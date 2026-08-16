"""DispatchMessageUseCase — Outbound Routing + Dispatch Service (architecture doc, Phase 5
items 4 and 10). The sole call site for ChannelPort.send() — everywhere else in the codebase
that wants a message sent goes through this, never an adapter directly.

Implements the full dispatch lifecycle (Change 1's Decision.status, exercised end to end for
the first time):

    PENDING --[dispatch() called]--> EXECUTING --[adapter.send() result]--> SUCCESS or FAILED

Dispatch only ever receives an OutboundAction once it's built one (Phase 5 rule: "Dispatch
only receives OutboundAction") — everything above that line in this class exists to build
that object from a PENDING Decision; the send() call itself never sees the Decision or the
Case.

`Case.attempt_count` and `next_check_at` are updated only on SUCCESS (architecture doc:
"Update attempt_count, next_check_at when dispatch succeeds") — a failed send should not
schedule a future follow-up on the assumption the message went out.

Cross-channel/cross-recipient continuity (Phase 6.6.6): a successful send's `SendResult`
carries `conversation_ref` — the gateway's own thread identifier for wherever this message
just went (see app/integrations/real_caspian_client.py's docstring for how the real Caspian
adapter obtains it). Whenever a dispatch's recipient wasn't already known to the Case's
existing Conversation rows (a resolved missing-role recipient, an escalation target, or a
channel switch — not just cross-channel: even a same-channel send to a NEW recipient gets its
own Caspian conversation), this registers a new `Conversation` for it on the SAME Case, via
the existing `CaseRepositoryPort.add_conversation` — the same mechanism
`ReceiveMessageNode._ensure_conversation` already uses for inbound. That's what lets a later
reply on that recipient's own thread resolve back to this case
(`CaseRepositoryPort.find_by_conversation_ref`, consumed by `IngestInboundMessageUseCase`)
instead of opening a new one. Never a duplicate: skipped if this exact (channel,
conversation_ref) pair is already registered — to this case (the common case: a reply-to-sender
follow-up reuses the conversation `ReceiveMessageNode` already registered on receipt) or,
defensively, logged and left alone if somehow already owned by a different one.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.domain.entities.case import Case
from app.domain.entities.conversation import Conversation
from app.domain.entities.decision import Decision
from app.domain.entities.outbound_action import OutboundAction, Recipient
from app.domain.services.followup_policy import FollowUpPolicy
from app.domain.services.policy_loader import PolicyLoader
from app.domain.services.topic_resolver import TopicResolver
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.policy_pack import CommunicationRules
from app.domain.value_objects.priority import Priority
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry

logger = logging.getLogger(__name__)

_DEFAULT_COMMUNICATION_RULES = CommunicationRules(
    cooldown_hours=24, max_attempts=3, escalation_delay_hours=24
)
"""Used when a case's topic has no policy pack entry — the same "degrade, don't fail"
behavior LoadPolicyNode applies during reasoning, applied here during dispatch too."""


class DispatchMessageUseCase:
    def __init__(
        self,
        case_repository: CaseRepositoryPort,
        channel_adapter_registry: ChannelAdapterRegistry,
        policy_loader: PolicyLoader | None = None,
        policy_pack_path: str = "policies/software.yaml",
        followup_policy: FollowUpPolicy | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._case_repository = case_repository
        self._channel_adapter_registry = channel_adapter_registry
        self._policy_loader = policy_loader or PolicyLoader()
        self._policy_pack_path = policy_pack_path
        self._followup_policy = followup_policy or FollowUpPolicy()
        self._clock = clock

    def dispatch(self, decision: Decision) -> Decision:
        if decision.status != DecisionStatus.PENDING:
            raise ValueError(
                f"Decision {decision.id} is {decision.status.value}, not pending — "
                "only a pending decision can be dispatched."
            )

        case = self._case_repository.get_by_id(decision.case_id)
        if case is None:
            raise ValueError(f"Case {decision.case_id} does not exist")

        action = self._build_outbound_action(decision)
        if action is None:
            self._case_repository.update_decision_status(decision.id, DecisionStatus.FAILED)
            return replace(decision, status=DecisionStatus.FAILED)

        self._case_repository.update_decision_status(decision.id, DecisionStatus.EXECUTING)

        adapter = self._channel_adapter_registry.get(action.channel)
        result = adapter.send(action)

        if result.success:
            self._case_repository.update_decision_status(decision.id, DecisionStatus.SUCCESS)
            case.attempt_count += 1
            case.next_check_at = action.follow_up_at
            self._case_repository.save(case)
            if result.conversation_ref:
                self._register_conversation_if_needed(case, action.channel, result.conversation_ref)
            else:
                # Part E: a successful send must not silently pretend continuity exists when
                # it doesn't — logged plainly rather than left invisible.
                logger.warning(
                    "Dispatch for decision %s (case %s) succeeded but no Caspian conversation "
                    "reference was available — a later reply on this channel to %s may not "
                    "resume this case automatically.",
                    decision.id,
                    case.id,
                    action.recipient.address,
                )
            return replace(decision, status=DecisionStatus.SUCCESS)

        self._case_repository.update_decision_status(decision.id, DecisionStatus.FAILED)
        return replace(decision, status=DecisionStatus.FAILED)

    def _register_conversation_if_needed(
        self, case: Case, channel: Channel, conversation_ref: str
    ) -> None:
        existing_owner = self._case_repository.find_by_conversation_ref(
            channel.value, conversation_ref
        )
        if existing_owner is not None:
            if existing_owner.id != case.id:
                # Extremely unlikely (Caspian's own conversation ids are effectively unique
                # per project) but never silently reassign someone else's registered thread.
                logger.warning(
                    "Caspian conversation %s (%s) is already registered to case %s, not %s — "
                    "not reassigning it.",
                    conversation_ref,
                    channel.value,
                    existing_owner.id,
                    case.id,
                )
            return  # already registered — to this case (the common case) or another
        self._case_repository.add_conversation(
            case.id,
            Conversation(
                id=uuid.uuid4(),
                case_id=case.id,
                channel=channel,
                external_thread_ref=conversation_ref,
            ),
        )

    def _build_outbound_action(self, decision: Decision) -> OutboundAction | None:
        chosen = decision.chosen_action
        address = chosen.get("recipient_address")
        if not address:
            return None

        rules = self._communication_rules_for(chosen.get("topic"))
        now = self._clock()

        return OutboundAction(
            recipient=Recipient(name=chosen.get("recipient_name") or "recipient", address=address),
            channel=Channel(chosen["channel"]),
            message=chosen["message"],
            priority=Priority(chosen["priority"]),
            follow_up_at=self._followup_policy.compute_next_check_at(now, rules),
            decision_id=decision.id,
            case_id=decision.case_id,
        )

    def _communication_rules_for(self, topic: str | None) -> CommunicationRules:
        if topic is None:
            return _DEFAULT_COMMUNICATION_RULES
        pack = self._policy_loader.load(self._policy_pack_path)
        policy_topic = TopicResolver(pack).resolve_or_none(topic)
        return policy_topic.communication_rules if policy_topic else _DEFAULT_COMMUNICATION_RULES
