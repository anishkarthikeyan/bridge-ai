"""SelectChannelNode in isolation — no graph, no database, no LLM. Proves the node is
independently testable and that it never returns a channel outside what's configured
available, even when the deterministically preferred one isn't.
"""

from uuid import uuid4

from app.brain.nodes.select_channel import SelectChannelNode
from app.brain.state import AgentState, ConversationGraphState
from app.domain.entities.case import Case
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.value_objects.channel import Channel
from app.domain.value_objects.priority import Priority
from tests.unit.brain.fakes import FakeCaseRepository


def _state_with_case(repo: FakeCaseRepository, priority: Priority) -> AgentState:
    case_id = uuid4()
    repo.add(Case(id=case_id))
    graph = ConversationGraphState(case_id=case_id, priority=priority)
    return AgentState(conversation_graph=graph)


def test_high_priority_prefers_telegram_when_available() -> None:
    repo = FakeCaseRepository()
    node = SelectChannelNode(
        repo,
        channel_registry=ChannelRegistry(available_channels={Channel.EMAIL, Channel.TELEGRAM}),
    )
    state = _state_with_case(repo, Priority.HIGH)

    update = node(state)

    assert update["selected_channel"] == Channel.TELEGRAM
    assert repo.decisions[-1].node_name == "select_channel"
    assert repo.decisions[-1].chosen_action["selected_channel"] == "telegram"


def test_falls_back_when_preferred_channel_unavailable() -> None:
    repo = FakeCaseRepository()
    # HIGH priority prefers Telegram (urgent), but only Email is configured available.
    node = SelectChannelNode(
        repo, channel_registry=ChannelRegistry(available_channels={Channel.EMAIL})
    )
    state = _state_with_case(repo, Priority.HIGH)

    update = node(state)

    assert update["selected_channel"] == Channel.EMAIL
    assert repo.decisions[-1].chosen_action["preferred_channel"] == "telegram"
    assert repo.decisions[-1].chosen_action["selected_channel"] == "email"


def test_never_returns_a_channel_when_nothing_is_available() -> None:
    repo = FakeCaseRepository()
    node = SelectChannelNode(repo, channel_registry=ChannelRegistry(available_channels=set()))
    state = _state_with_case(repo, Priority.LOW)

    update = node(state)  # must not raise

    assert update["selected_channel"] is None
