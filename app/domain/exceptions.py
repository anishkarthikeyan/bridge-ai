"""Domain-level exceptions."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every exception raised inside app/domain/."""


class PolicyValidationError(DomainError):
    """Raised by PolicyLoader when a policy pack file is missing, malformed, or fails schema
    validation. Never raised for a topic that is simply absent from the pack — see
    UnknownTopicError for that."""


class UnknownTopicError(DomainError):
    """Raised by TopicResolver.resolve() when a topic has no entry in the given policy pack.
    Callers that should degrade gracefully (e.g. a topic outside the current industry pack)
    use resolve_or_none() instead and never see this."""
