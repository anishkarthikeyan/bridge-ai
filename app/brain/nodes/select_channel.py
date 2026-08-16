"""SelectChannelNode — node 9. Deterministic. Two paths, chosen by whether the case has a
missing stakeholder to reach:

  - **Missing role present** (Phase 5): RoleResolver (app/domain/services/role_resolver.py)
    resolves the case's first missing role — required_roles order is preserved by
    DetectMissingStakeholdersNode, so this is deterministic, not arbitrary — against the role
    directory, choosing both the person and the channel in one step. This is the actual
    point of the mission: reaching the person who *should* be in the conversation.
  - **No missing role, or resolution failed** (Phase 4, unchanged): falls back to
    Priority -> CommunicationStyle -> ChannelSelectionRules -> ChannelRegistry, addressing
    whoever sent the current message. A role directory miss (nobody known for the role, or
    no reachable channel) degrades to this path rather than stalling the case — the same
    "degrade, don't fail" behavior as LoadPolicyNode for an out-of-pack topic.

_PRIORITY_TO_STYLE is the deterministic bridge between Priority and CommunicationStyle that
neither Phase 3's ChannelSelectionRules nor Change 2's ChannelRegistry defines on its own;
kept here, colocated with its only consumer.
"""

from __future__ import annotations

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState, ConversationGraphState
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.channel_selection_rules import ChannelSelectionRules
from app.domain.services.role_directory_loader import RoleDirectory
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.communication_style import CommunicationStyle
from app.domain.value_objects.priority import Priority
from app.domain.value_objects.role_resolution import RoleResolution

_PRIORITY_TO_STYLE: dict[Priority, CommunicationStyle] = {
    Priority.HIGH: CommunicationStyle.URGENT,
    Priority.MEDIUM: CommunicationStyle.FORMAL,
    Priority.LOW: CommunicationStyle.DISCUSSION,
}


class SelectChannelNode(BrainNode):
    node_name = "select_channel"

    def __init__(
        self,
        case_repository: CaseRepositoryPort,
        channel_selection_rules: ChannelSelectionRules | None = None,
        channel_registry: ChannelRegistry | None = None,
        role_resolver: RoleResolver | None = None,
        role_directory: RoleDirectory | None = None,
    ) -> None:
        super().__init__(case_repository)
        self._channel_selection_rules = channel_selection_rules or ChannelSelectionRules()
        self._channel_registry = channel_registry or ChannelRegistry()
        self._role_resolver = role_resolver or RoleResolver(self._channel_registry)
        self._role_directory: RoleDirectory = role_directory or {}

    def execute(self, state: AgentState) -> NodeResult:
        graph = state.conversation_graph

        if graph.missing_roles:
            role = graph.missing_roles[0]
            resolution = self._role_resolver.resolve(role, self._role_directory.get(role, ()))
            if resolution.resolved:
                return self._result_for_role_resolution(graph, resolution)
            # Falls through to the priority-based path below on failure — logged either way.
            fallback_note = f" (role resolution for '{role}' failed: {resolution.failure_reason})"
        else:
            fallback_note = ""

        return self._result_for_priority_fallback(graph, fallback_note)

    def _result_for_role_resolution(
        self, graph: ConversationGraphState, resolution: RoleResolution
    ) -> NodeResult:
        channel = resolution.preferred_channel
        assert (
            channel is not None and resolution.participant is not None
        )  # guaranteed by resolved=True

        channels_used = (
            graph.channels_used
            if channel in graph.channels_used
            else [
                *graph.channels_used,
                channel,
            ]
        )
        return NodeResult(
            reasoning_summary=(
                f"Missing role '{resolution.role}' resolved to {resolution.participant.name} "
                f"via {channel.value}."
            ),
            chosen_action={
                "path": "role_resolution",
                "role": resolution.role,
                "participant": resolution.participant.name,
                "selected_channel": channel.value,
            },
            input_snapshot={"missing_roles": list(graph.missing_roles)},
            state_update={"selected_channel": channel, "role_resolution": resolution},
            conversation_graph_update={"channels_used": channels_used},
        )

    def _result_for_priority_fallback(
        self, graph: ConversationGraphState, fallback_note: str
    ) -> NodeResult:
        style = _PRIORITY_TO_STYLE[graph.priority]
        preferred = Channel(self._channel_selection_rules.select(style))
        selected = self._channel_registry.preferred_channel(preferred)

        if selected is not None:
            summary = (
                f"Priority {graph.priority.value} -> {style.value} -> preferred "
                f"{preferred.value}; selected {selected.value}.{fallback_note}"
            )
            channels_used = (
                graph.channels_used
                if selected in graph.channels_used
                else [
                    *graph.channels_used,
                    selected,
                ]
            )
        else:
            summary = (
                f"Priority {graph.priority.value} -> {style.value} -> preferred "
                f"{preferred.value}; no configured channel is available.{fallback_note}"
            )
            channels_used = graph.channels_used

        return NodeResult(
            reasoning_summary=summary,
            chosen_action={
                "path": "priority_fallback",
                "style": style.value,
                "preferred_channel": preferred.value,
                "selected_channel": selected.value if selected else None,
                "available_channels": [
                    c.value for c in self._channel_registry.available_channels()
                ],
            },
            input_snapshot={"priority": graph.priority.value},
            state_update={"selected_channel": selected, "role_resolution": None},
            conversation_graph_update={"channels_used": channels_used},
        )
