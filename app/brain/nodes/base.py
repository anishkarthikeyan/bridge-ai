"""BrainNode — the base class every brain node extends. Enforces the required lifecycle
(architecture doc, Phase 4 Change 3) structurally, not by convention:

    Read State -> Execute -> Persist Decision -> Persist Updated State -> Return Updated State

Subclasses implement only `execute()`, which receives the current AgentState and returns a
NodeResult describing what happened. `__call__` — the function LangGraph actually invokes as
the graph node — is not overridable; it always runs the four steps around `execute()` in
order, so there is no path through a node that skips persistence.

"No node mutates hidden state" is enforced the same way: a node instance holds only its
injected dependencies (a repository, and an LLMPort for the four LLM nodes) — never
per-call data. Everything a node needs comes in through `state`; everything it produces goes
out through the returned NodeResult. `state.conversation_graph` itself is never mutated in
place — `execute()` describes a partial update, and `__call__` applies it with
`dataclasses.replace()`, always producing a new object.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.brain.state import AgentState, ConversationGraphState
from app.domain.entities.case import Case
from app.domain.entities.decision import Decision
from app.domain.value_objects.decision_status import DecisionStatus


@dataclass
class NodeResult:
    """What `execute()` returns: enough to build this node's Decision record, plus the state
    changes to apply. Kept separate from AgentState so a node cannot hand back something that
    bypasses becoming a persisted Decision — `__call__` is the only thing that turns this
    into both a Decision and a state update, and it always does both.
    """

    reasoning_summary: str
    chosen_action: dict[str, Any] = field(default_factory=dict)
    input_snapshot: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    status: DecisionStatus = DecisionStatus.SUCCESS
    decision_id: UUID | None = None
    """Phase 6: lets a node (specifically create_decision) choose its own Decision's id
    instead of one being generated in __call__, so that id can be threaded forward through
    state to a later node (dispatch) that needs to look this exact Decision back up. None
    (the default) preserves every earlier node's behavior unchanged — a fresh uuid4()."""

    state_update: dict[str, Any] = field(default_factory=dict)
    """Partial update to top-level AgentState fields (current_message, extracted_intent,
    selected_channel, ...) — everything except conversation_graph, which has its own field
    below so it's never confused with a transient, per-pass field."""

    conversation_graph_update: dict[str, Any] = field(default_factory=dict)
    """Partial update to apply onto ConversationGraphState via dataclasses.replace() — e.g.
    {"missing_roles": [...], "communication_health": CommunicationHealth.AT_RISK}."""


class BrainNode(ABC):
    node_name: str

    def __init__(self, case_repository: CaseRepositoryPort) -> None:
        self._case_repository = case_repository

    def __call__(self, state: AgentState) -> dict[str, Any]:
        # Read State — `state` is the only input `execute()` receives.
        result = self.execute(state)

        case_id = state.conversation_graph.case_id

        # Create Decision Record
        decision = Decision(
            id=result.decision_id or uuid4(),
            case_id=case_id,
            node_name=self.node_name,
            reasoning_summary=result.reasoning_summary,
            input_snapshot=result.input_snapshot,
            chosen_action=result.chosen_action,
            confidence=result.confidence,
            status=result.status,
            created_at=datetime.now(UTC),
        )

        # Persist Decision
        self._case_repository.add_decision(case_id, decision)

        # Persist Updated State
        merged_graph = replace(state.conversation_graph, **result.conversation_graph_update)
        self._case_repository.save(_conversation_graph_to_case(merged_graph))

        # Return Updated State — LangGraph merges this dict into AgentState for the next node.
        update: dict[str, Any] = dict(result.state_update)
        update["conversation_graph"] = merged_graph
        update["node_log"] = [*state.node_log, self.node_name]
        return update

    @abstractmethod
    def execute(self, state: AgentState) -> NodeResult: ...


def _conversation_graph_to_case(graph: ConversationGraphState) -> Case:
    """Builds just enough of a Case to call CaseRepositoryPort.save(), which only ever reads
    a Case's own scalar/JSON fields (see that port's docstring) — participants/conversations/
    decisions are intentionally left at their dataclass defaults; save() never touches them.
    """
    return Case(
        id=graph.case_id,
        topic=graph.topic,
        required_roles=list(graph.required_roles),
        missing_roles=list(graph.missing_roles),
        channels_used=list(graph.channels_used),
        timeline=list(graph.timeline),
        communication_health=graph.communication_health,
        resolution_status=graph.resolution_status,
        priority=graph.priority,
        attempt_count=graph.attempt_count,
        next_check_at=graph.next_check_at,
    )
