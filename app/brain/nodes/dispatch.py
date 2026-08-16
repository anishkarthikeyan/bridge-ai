"""DispatchNode — node 12 (Phase 6: Dispatch joins the graph directly, replacing the
Phase 4 persist_state node — every node already persists via the shared BrainNode lifecycle,
so a dedicated no-op checkpoint node added nothing dispatch doesn't already provide).

Wraps DispatchMessageUseCase (application layer, Phase 5) rather than re-implementing the
dispatch lifecycle here — the node's own job is purely to bridge graph state to that use
case: find the Decision create_decision just made (via `state.pending_decision_id`), hand it
to Dispatch, and reflect the attempt_count/next_check_at Dispatch just persisted back into
conversation_graph so this node's own (required) persistence step doesn't overwrite them
with the stale pre-dispatch values still sitting in `state.conversation_graph`.
"""

from __future__ import annotations

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.use_cases.dispatch_message import DispatchMessageUseCase
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState


class DispatchNode(BrainNode):
    node_name = "dispatch"

    def __init__(
        self, case_repository: CaseRepositoryPort, dispatch_use_case: DispatchMessageUseCase
    ) -> None:
        super().__init__(case_repository)
        self._dispatch_use_case = dispatch_use_case

    def execute(self, state: AgentState) -> NodeResult:
        decision_id = state.pending_decision_id
        if decision_id is None:
            raise ValueError(
                "dispatch requires state.pending_decision_id to be set (run create_decision first)"
            )

        case_id = state.conversation_graph.case_id
        case = self._case_repository.get_by_id(case_id)
        if case is None:
            raise ValueError(f"Case {case_id} does not exist")

        decision = next((d for d in case.decisions if d.id == decision_id), None)
        if decision is None:
            raise ValueError(f"Decision {decision_id} not found on case {case_id}")

        dispatched = self._dispatch_use_case.dispatch(decision)

        # DispatchMessageUseCase already persisted attempt_count/next_check_at on the Case —
        # fetch the fresh values so this node's own conversation_graph_update carries them
        # forward instead of the base class's save() clobbering them back to the pre-dispatch
        # snapshot still held in state.conversation_graph.
        refreshed_case = self._case_repository.get_by_id(case_id)

        return NodeResult(
            reasoning_summary=f"Dispatch {dispatched.status.value} for decision {decision_id}.",
            chosen_action={
                "decision_id": str(decision_id),
                "status": dispatched.status.value,
                "channel": decision.chosen_action.get("channel"),
            },
            input_snapshot={"recipient_address": decision.chosen_action.get("recipient_address")},
            state_update={"last_dispatch_status": dispatched.status},
            conversation_graph_update={
                "attempt_count": refreshed_case.attempt_count,
                "next_check_at": refreshed_case.next_check_at,
            },
        )
