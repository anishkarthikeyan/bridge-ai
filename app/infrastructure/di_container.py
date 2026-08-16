"""Composition root.

This is the one place in the whole codebase allowed to know about a concrete adapter and
wire it to the port it implements. Nothing in domain/ or application/ may import from here —
the dependency only ever flows inward (see architecture doc §2, clean architecture).

Two kinds of things get wired here, deliberately kept apart:
  - `Container` holds process-wide singletons — everything stateless enough to share across
    requests (the Caspian client/gateway, channel adapters, the channel registry, the role
    directory and resolver, the policy loader).
  - `build_case_repository()` / `build_compiled_graph()` are factories, not Container
    fields, because a SQLAlchemy Session (which a case repository needs) and a checkpointer
    connection (which a compiled graph needs) are each scoped to one unit of work, not the
    whole process — storing either on Container would mean sharing a single DB connection
    across every concurrent case, which is wrong. `build_compiled_graph` takes an
    already-open checkpointer rather than opening one itself and closing it on return, which
    would silently hand back a graph whose checkpointer connection is already dead.

`llm_client: LLMPort` (Phase 6.5) is bound here to the real `FeatherlessClient`, built from
`Settings` — the same "compose the concrete adapter once, hand out the interface" pattern as
everything else in this container. Every brain node was already written against `LLMPort`
(Phase 4), so this wiring is purely additive: nothing above the container changed. Tests keep
using `FakeLLMPort` directly (they build their own stack — see tests/unit/brain/fakes.py and
the integration tests under tests/integration/) rather than going through `build_container()`;
`llm_client` accepts an override for the same reason `settings` does, so a test that *does*
want a container-built stack isn't forced to hit a real Featherless endpoint.

`caspian_client: CaspianClientProtocol` (Phase 6.6) is `RealCaspianClient` when
`Settings.caspian_api_key` is configured, `LocalCaspianClient` otherwise — the same
config-driven "degrade, don't fail" pattern used everywhere else in this container, not a
special case. Constructing `RealCaspianClient` does no I/O (see its docstring); connecting
channels for real is `RealCaspianClient.provision()`, called once from app/main.py's lifespan,
same reasoning as `build_compiled_graph` staying I/O-free until a checkpointer is actually open.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from app.application.ports.case_repository_port import CaseRepositoryPort
from app.application.ports.llm_port import LLMPort
from app.application.use_cases.dispatch_message import DispatchMessageUseCase
from app.brain.graph import build_graph
from app.domain.services.channel_registry import ChannelRegistry
from app.domain.services.policy_loader import PolicyLoader
from app.domain.services.role_directory_loader import RoleDirectory, RoleDirectoryLoader
from app.domain.services.role_resolver import RoleResolver
from app.domain.value_objects.channel import Channel
from app.infrastructure.config import Settings, get_settings
from app.integrations.caspian_client import CaspianClientProtocol, LocalCaspianClient
from app.integrations.inbound.channel_adapter_registry import ChannelAdapterRegistry
from app.integrations.inbound.channels.email_adapter import EmailAdapter
from app.integrations.inbound.channels.telegram_adapter import TelegramAdapter
from app.integrations.llm.featherless_client import FeatherlessClient
from app.integrations.outbound.caspian_gateway import CaspianGateway
from app.integrations.persistence.sqlalchemy.repositories.case_repository import (
    SqlAlchemyCaseRepository,
)
from app.integrations.real_caspian_client import RealCaspianClient

DEFAULT_POLICY_PACK_PATH = "policies/software.yaml"
DEFAULT_ROLE_DIRECTORY_PATH = "policies/role_directory.yaml"


@dataclass
class Container:
    settings: Settings
    caspian_client: CaspianClientProtocol
    caspian_gateway: CaspianGateway
    channel_adapter_registry: ChannelAdapterRegistry
    channel_registry: ChannelRegistry
    policy_loader: PolicyLoader
    role_directory: RoleDirectory
    role_resolver: RoleResolver
    llm_client: LLMPort


def build_container(
    settings: Settings | None = None,
    llm_client: LLMPort | None = None,
    caspian_client: CaspianClientProtocol | None = None,
) -> Container:
    """Constructs the composition root. Called once at process startup.

    `llm_client` defaults to a real `FeatherlessClient` built from `settings` (Part 7:
    "Production: LLMPort -> FeatherlessClient") — pass an override (e.g. FakeLLMPort) for a
    test that wants a container-built stack without hitting a real Featherless endpoint.

    `caspian_client` defaults to `RealCaspianClient` when `settings.caspian_api_key` is set,
    `LocalCaspianClient` otherwise (Phase 6.6 Part 7's "Environment" section: production uses
    the real SDK, tests keep using `LocalCaspianClient`) — pass an override for a test that
    wants a container-built stack without either.
    """
    settings = settings or get_settings()

    caspian_client = caspian_client or _build_caspian_client(settings)
    caspian_gateway = CaspianGateway(caspian_client)

    channel_adapter_registry = ChannelAdapterRegistry(
        {
            Channel.EMAIL: EmailAdapter(caspian_gateway),
            Channel.TELEGRAM: TelegramAdapter(caspian_gateway),
        }
    )
    # Availability mirrors exactly which adapters are configured above (Channel Registry
    # Integration, architecture doc item 7) — slack/discord have no adapter yet, so they are
    # never "available" here regardless of the Channel enum including them.
    channel_registry = ChannelRegistry(
        available_channels=set(channel_adapter_registry.configured_channels())
    )

    role_directory = RoleDirectoryLoader().load(DEFAULT_ROLE_DIRECTORY_PATH)

    return Container(
        settings=settings,
        caspian_client=caspian_client,
        caspian_gateway=caspian_gateway,
        channel_adapter_registry=channel_adapter_registry,
        channel_registry=channel_registry,
        policy_loader=PolicyLoader(),
        role_directory=role_directory,
        role_resolver=RoleResolver(channel_registry),
        llm_client=llm_client or FeatherlessClient(settings),
    )


def _build_caspian_client(settings: Settings) -> CaspianClientProtocol:
    if not settings.caspian_api_key:
        return LocalCaspianClient()

    from caspian_sdk import CommClient  # only constructed on this branch — never touches I/O

    comm_client = CommClient(
        api_key=settings.caspian_api_key,
        base_url=settings.caspian_base_url or None,
    )
    return RealCaspianClient(comm_client)


def build_case_repository(session: Session) -> CaseRepositoryPort:
    """One per unit of work — a Session isn't safe to share across concurrent requests."""
    return SqlAlchemyCaseRepository(session)


def build_dispatch_use_case(
    container: Container, case_repository: CaseRepositoryPort
) -> DispatchMessageUseCase:
    """Same one-per-unit-of-work reasoning as `build_case_repository` — a DispatchMessageUseCase
    is bound to a specific case repository (and therefore a specific Session), so it's a
    factory, not a Container field. Used directly by `build_compiled_graph` below, and by the
    scheduler (app/infrastructure/scheduler.py), which needs its own instance per sweep tick
    bound to that tick's own case repository.
    """
    return DispatchMessageUseCase(
        case_repository, container.channel_adapter_registry, policy_loader=container.policy_loader
    )


def build_compiled_graph(
    container: Container,
    case_repository: CaseRepositoryPort,
    llm_port: LLMPort,
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    """Wires a fresh brain graph for one case repository + LLM client + checkpointer.
    `checkpointer` must stay open for as long as the returned graph is used — callers own
    that lifecycle (e.g. `with postgres_checkpointer() as cp: ...`), it is not managed here.
    """
    graph = build_graph(
        case_repository,
        llm_port,
        container.channel_adapter_registry,
        policy_loader=container.policy_loader,
        channel_registry=container.channel_registry,
        role_resolver=container.role_resolver,
        role_directory=container.role_directory,
        dispatch_use_case=build_dispatch_use_case(container, case_repository),
    )
    return graph.compile(checkpointer=checkpointer)
