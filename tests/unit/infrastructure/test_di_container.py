"""DI wiring tests (Phase 6.5 Part 7 / Phase 6.6 Part 7): production wires
LLMPort -> FeatherlessClient and CaspianClientProtocol -> RealCaspianClient; a test (or the
scheduler, or the compiled graph) can override either without a second composition-root
implementation — one container, one place either binding is made.
"""

from __future__ import annotations

from app.application.ports.llm_port import LLMPort
from app.application.use_cases.dispatch_message import DispatchMessageUseCase
from app.infrastructure.config import Settings
from app.infrastructure.di_container import build_container, build_dispatch_use_case
from app.integrations.caspian_client import LocalCaspianClient
from app.integrations.llm.featherless_client import FeatherlessClient
from app.integrations.real_caspian_client import RealCaspianClient
from tests.unit.brain.fakes import FakeCaseRepository, FakeLLMPort


def test_build_container_wires_featherless_client_by_default() -> None:
    container = build_container()
    assert isinstance(container.llm_client, FeatherlessClient)
    assert isinstance(container.llm_client, LLMPort)


def test_build_container_accepts_an_llm_client_override_for_tests() -> None:
    fake = FakeLLMPort()
    container = build_container(llm_client=fake)
    assert container.llm_client is fake


def test_build_dispatch_use_case_is_bound_to_the_given_case_repository() -> None:
    container = build_container(llm_client=FakeLLMPort())
    repo = FakeCaseRepository()
    dispatch_use_case = build_dispatch_use_case(container, repo)
    assert isinstance(dispatch_use_case, DispatchMessageUseCase)
    assert dispatch_use_case._case_repository is repo


# --- Caspian client wiring (Phase 6.6) ------------------------------------------------------


def test_build_container_wires_local_caspian_client_when_no_api_key_configured() -> None:
    container = build_container(settings=Settings(caspian_api_key=""), llm_client=FakeLLMPort())
    assert isinstance(container.caspian_client, LocalCaspianClient)


def test_build_container_wires_real_caspian_client_when_api_key_configured() -> None:
    # Constructing CommClient does no I/O (see RealCaspianClient's docstring) — this proves
    # the *wiring*, not connectivity, without touching the network.
    settings = Settings(
        caspian_api_key="test-key-not-real", caspian_base_url="https://example.invalid"
    )
    container = build_container(settings=settings, llm_client=FakeLLMPort())
    assert isinstance(container.caspian_client, RealCaspianClient)


def test_build_container_accepts_a_caspian_client_override_for_tests() -> None:
    local = LocalCaspianClient()
    container = build_container(llm_client=FakeLLMPort(), caspian_client=local)
    assert container.caspian_client is local
