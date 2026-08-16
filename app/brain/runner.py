"""Resume Support — the thin, explicit contract for invoking the compiled brain graph, so
"how do I resume a case" is one obvious function call rather than something every future
caller has to rediscover from LangGraph's Command/thread_id primitives.

Both functions key on the case's id as LangGraph's thread_id. That id, plus a checkpointer
pointed at the same database, is *all* that's needed to resume a case — nothing else is
expected to survive in memory between calls, which is the whole point: the process that
started a case and the process that resumes it days later can be different processes on
different machines.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.application.dto.inbound_message import InboundMessage
from app.brain.state import AgentState


def _config_for(case_id: UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(case_id)}}


def start_case(compiled_graph: CompiledStateGraph, initial_state: AgentState) -> dict[str, Any]:
    """First invocation for a case. Runs the pipeline through to wait_for_reply, where it
    pauses; the return value is LangGraph's state dict at that pause point (it carries a
    `__interrupt__` key describing why)."""
    case_id = initial_state.conversation_graph.case_id
    return compiled_graph.invoke(initial_state, config=_config_for(case_id))


def resume_case(
    compiled_graph: CompiledStateGraph, case_id: UUID, reply: InboundMessage
) -> dict[str, Any]:
    """Resumes a paused case with a new reply. The checkpointer restores everything the case
    had accumulated, however long ago it paused and regardless of which process paused it —
    this call needs nothing but the id and the reply.
    """
    return compiled_graph.invoke(Command(resume=reply), config=_config_for(case_id))
