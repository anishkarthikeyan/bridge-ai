"""RoleResolver in isolation — pure domain logic, no brain, no repository, no I/O. Proves
Changes 1 and 2: deterministic multi-candidate selection, and the two explicit-failure paths
(unknown role, unreachable candidate) that replace what would otherwise be exceptions or an
ambiguous None.
"""

import random

from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.candidate_contact import CandidateContact
from app.domain.value_objects.channel import Channel

SECURITY_CANDIDATES = (
    CandidateContact(name="John Ortiz", role="Security", email="john@co.com", preference_rank=1),
    CandidateContact(name="Alice Chen", role="Security", email="alice@co.com", preference_rank=2),
    CandidateContact(
        name="Mike Reyes", role="Security", telegram_handle="@mike", preference_rank=3
    ),
)


def test_picks_lowest_preference_rank() -> None:
    resolver = RoleResolver(ChannelRegistry(available_channels={Channel.EMAIL}))
    result = resolver.resolve("Security", SECURITY_CANDIDATES)
    assert result.resolved
    assert result.participant.name == "John Ortiz"


def test_selection_is_independent_of_input_order() -> None:
    resolver = RoleResolver(ChannelRegistry(available_channels={Channel.EMAIL, Channel.TELEGRAM}))
    shuffled = list(SECURITY_CANDIDATES)
    for _ in range(5):
        random.shuffle(shuffled)
        result = resolver.resolve("Security", shuffled)
        assert result.participant.name == "John Ortiz"


def test_never_returns_a_candidate_not_in_the_input() -> None:
    resolver = RoleResolver(ChannelRegistry(available_channels={Channel.EMAIL}))
    result = resolver.resolve("Security", SECURITY_CANDIDATES)
    assert result.participant in SECURITY_CANDIDATES


def test_unknown_role_is_an_explicit_failure_not_an_exception() -> None:
    resolver = RoleResolver(ChannelRegistry(available_channels={Channel.EMAIL}))
    result = resolver.resolve("Legal", SECURITY_CANDIDATES)
    assert result.resolved is False
    assert result.participant is None
    assert "Legal" in result.failure_reason


def test_best_candidate_with_no_reachable_channel_falls_through_to_next() -> None:
    # Only Telegram is available; John (rank 1) has no telegram_handle, Alice (rank 2) has
    # no telegram_handle either, but Mike (rank 3) does — best REACHABLE, not best overall.
    resolver = RoleResolver(ChannelRegistry(available_channels={Channel.TELEGRAM}))
    result = resolver.resolve("Security", SECURITY_CANDIDATES)
    assert result.resolved
    assert result.participant.name == "Mike Reyes"
    assert result.preferred_channel == Channel.TELEGRAM
    assert result.address == "@mike"


def test_no_reachable_channel_at_all_is_an_explicit_failure() -> None:
    resolver = RoleResolver(ChannelRegistry(available_channels=set()))
    result = resolver.resolve("Security", SECURITY_CANDIDATES)
    assert result.resolved is False
    assert result.failure_reason is not None
