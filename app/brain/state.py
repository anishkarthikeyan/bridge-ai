"""The AI Brain's state schema — three layers, all in this one file because they're one
artifact viewed from three angles, not three separate types:

  1. LangGraph state — LangGraph checkpoints whatever type is passed to `StateGraph(...)`.
     That type is `AgentState`, below. There is no separate "LangGraph state" class distinct
     from AgentState — LangGraph's checkpointing mechanism operates directly on it. See the
     Phase 4 architectural observations for why introducing a redundant wrapper type here
     would be a distinction without a difference.

  2. ConversationGraphState — the durable, business-meaning part of state: participants,
     channels used, topic, required/missing stakeholder roles, communication health,
     priority, resolution status. Field-for-field, this mirrors the reasoning-relevant shape
     of the domain `Case` entity (app/domain/entities/case.py) — because it *is* that case's
     Conversation Graph, just carried across a graph run rather than freshly loaded each
     node. `evaluate_case` (still a stub) is responsible for hydrating one of these from a
     `Case` at the start of a run and reconciling it back at the end.

  3. AgentState — the full state LangGraph checkpoints for one case's run. It wraps a
     ConversationGraphState plus transient, per-pass working fields: the message currently
     being processed, and each LLM/deterministic node's not-yet-merged output. Only
     `conversation_graph` is business data in its own right; everything else exists to pass
     one node's result to the next within a single pass and is not meaningful once persisted.

Dataclasses throughout, not TypedDict: LangGraph 1.x supports both, and dataclasses match
every other state shape already in this codebase (Case, Conversation, ... in
app/domain/entities/). Node return values are partial dicts (LangGraph's standard
last-write-wins merge into the dataclass), which is what keeps state mutation visible and
auditable — see brain/nodes/base.py for why "no node mutates hidden state" is enforced
structurally, not just documented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.application.dto.inbound_message import InboundMessage
from app.application.ports.llm_port import EntitiesResult, IntentResult, TopicClassification
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.communication_health import CommunicationHealth
from app.domain.value_objects.decision_status import DecisionStatus
from app.domain.value_objects.policy_pack import PolicyTopic
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.resolution_outcome import ResolutionOutcome
from app.domain.value_objects.resolution_state import ResolutionState
from app.domain.value_objects.role_resolution import RoleResolution


@dataclass
class ParticipantState:
    """A participant as carried in graph state — the subset of app/domain/entities/participant.py
    that reasoning nodes actually need. id is None for a participant merged into the graph
    this pass but not yet persisted (assigned once IngestInboundMessageUseCase saves it).
    """

    name: str
    role: str | None = None
    email: str | None = None
    telegram_handle: str | None = None
    id: UUID | None = None


@dataclass
class ConversationGraphState:
    """The persisted Conversation Graph, in the shape brain nodes read and write. Mirrors
    app/domain/entities/case.py's reasoning-relevant fields; see this module's docstring for
    why it isn't the same class as Case (Case also carries persistence metadata — id,
    timestamps, full Conversation/Decision collections — that no node needs mid-pass).
    """

    case_id: UUID
    topic: str | None = None
    participants: list[ParticipantState] = field(default_factory=list)
    channels_used: list[Channel] = field(default_factory=list)
    required_roles: list[str] = field(default_factory=list)
    missing_roles: list[str] = field(default_factory=list)
    communication_health: CommunicationHealth = CommunicationHealth.HEALTHY
    priority: Priority = Priority.MEDIUM
    resolution_status: ResolutionState = ResolutionState.OPEN
    attempt_count: int = 0
    next_check_at: datetime | None = None
    timeline: list[dict[str, Any]] = field(default_factory=list)
    """Carried through unchanged by nodes that don't append to it — present here so that
    every node's persistence step (CaseRepositoryPort.save(), which writes every scalar/JSON
    field on Case) has the real value to write back rather than silently overwriting it with
    an empty list. See brain/nodes/base.py."""


@dataclass
class AgentState:
    """The full state LangGraph checkpoints for one case's reasoning graph. See this
    module's docstring for the three-layer explanation — this is layers 1 and 3 combined;
    `conversation_graph` (layer 2) is its only field that is business data in its own right.
    """

    conversation_graph: ConversationGraphState

    # Transient, per-pass working fields — populated by one node, consumed by a later one in
    # the same pass. None of these are read back after the pass merges into
    # conversation_graph and persists; they exist only to move data forward through the
    # sequence without a node reaching into another node's internals.
    current_message: InboundMessage | None = None
    extracted_intent: IntentResult | None = None
    extracted_entities: EntitiesResult | None = None
    topic_classification: TopicClassification | None = None
    policy_topic: PolicyTopic | None = None
    """The resolved policy entry for the current topic (None if the topic has no entry in
    the pack) — LoadPolicyNode's output, read by DetectMissingStakeholdersNode and
    CalculatePriorityNode. Not part of conversation_graph: it's policy *reference* data, not
    part of the case's own persisted shape (required_roles, which IS part of the case, is
    derived from it and written there directly)."""
    communication_health_score: int | None = None
    """The raw 0-100 score from CalculateCommunicationHealthNode — conversation_graph only
    carries the banded CommunicationHealth enum; CalculatePriorityNode needs the finer-grained
    number, so it travels here rather than being recomputed."""
    selected_channel: Channel | None = None
    role_resolution: RoleResolution | None = None
    """select_channel's RoleResolver result when missing_roles is non-empty — the specific
    person and address generate_message/create_decision address, in place of the Phase 4
    default of replying to the original sender. None when there's no missing role to target
    (the Phase 4 sender-reply path) or when resolution failed (see role_resolution.resolved)."""
    generated_message: str | None = None
    pending_decision_id: UUID | None = None
    """The id create_decision assigned its own (not-yet-dispatched) Decision — Phase 6.
    dispatch reads this to look the exact Decision back up via the case repository; nothing
    else consumes it."""
    last_dispatch_status: DecisionStatus | None = None
    """dispatch's outcome (SUCCESS/FAILED) — Phase 6. ResolutionEvaluator reads this as one
    of its six inputs ("Decision Status"); nothing upstream of dispatch sets it."""
    resolution_outcome: ResolutionOutcome | None = None
    """ResolutionEvaluator's own output — Phase 6. Read only by the conditional-edge routing
    function in graph.py, never by another node's business logic."""

    # Node bookkeeping — observability only, never read by business logic. Each node appends
    # its own name; a test can assert on this without touching the database.
    node_log: list[str] = field(default_factory=list)
