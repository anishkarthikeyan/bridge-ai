"""WaitForReplyNode — the checkpoint pause, reached from two places (see graph.py): after
`dispatch` sends a message, and directly from `resolution_evaluator` on a WAIT outcome (no
message needed — just keep waiting). `execute()` calls LangGraph's `interrupt()` as close to
its first line as possible and does nothing else beforehand — that matters mechanically, not
just stylistically: on resume, LangGraph re-runs this node's function from the top, and
`interrupt()` returns the resume value instead of pausing again. Anything placed before it
would re-run a second time; there is nothing here to re-run.

On the pausing call, `interrupt()` never returns — the whole graph invocation unwinds and the
BrainNode base class's post-execute persistence steps simply do not run (correctly: nothing
happened yet to persist). On the resuming call — a fresh `invoke(Command(resume=...))`,
possibly from a different process on a different day — `interrupt()` returns the new
InboundMessage, `execute()` returns normally, and the base class persists a Decision plus the
updated state exactly as any other node would. This is what "every state transition must
survive process restart, machine restart, and delayed replies" actually means in code: the
PostgresSaver checkpointer, not this node, is what makes the pause durable.

Also resets every transient, per-pass AgentState field on resume (absorbing the job the
Phase 4/5 `resume_case` node used to do — that node no longer exists; ResolutionEvaluator
replaced its routing role, and this is the natural place for its state-hygiene role, since
this is where a resume actually happens). A fresh pass over a new reply must not see the
prior pass's extracted intent, entities, topic, channel, role resolution, dispatch status,
resolution outcome, or generated message.
"""

from __future__ import annotations

from langgraph.types import interrupt

from app.application.dto.inbound_message import InboundMessage
from app.brain.nodes.base import BrainNode, NodeResult
from app.brain.state import AgentState


class WaitForReplyNode(BrainNode):
    node_name = "wait_for_reply"

    def execute(self, state: AgentState) -> NodeResult:
        reply: InboundMessage = interrupt(
            {
                "case_id": str(state.conversation_graph.case_id),
                "reason": "awaiting_reply",
                "priority": state.conversation_graph.priority.value,
            }
        )

        return NodeResult(
            reasoning_summary=f"Reply received on {reply.channel.value} from {reply.sender.name}.",
            chosen_action={"channel": reply.channel.value, "sender": reply.sender.name},
            state_update={
                "current_message": reply,
                "extracted_intent": None,
                "extracted_entities": None,
                "topic_classification": None,
                "policy_topic": None,
                "communication_health_score": None,
                "selected_channel": None,
                "role_resolution": None,
                "generated_message": None,
                "pending_decision_id": None,
                "last_dispatch_status": None,
                "resolution_outcome": None,
            },
        )
