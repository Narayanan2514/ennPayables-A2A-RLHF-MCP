import httpx
import pytest

from agents.agent_1.main.main import app as agent1_app
from agents.agent_2.main.main import app as agent2_app
from agents.agent_3.main.main import app as agent3_app
from agents.agent_4.main.main import app as agent4_app
from client.agent_registry.registry import registry
from client.orchestrator import orchestrator
from shared.config.settings import AGENT_1_URL, AGENT_2_URL, AGENT_3_URL, AGENT_4_URL

MOUNTS = {
    AGENT_1_URL: httpx.ASGITransport(app=agent1_app),
    AGENT_2_URL: httpx.ASGITransport(app=agent2_app),
    AGENT_3_URL: httpx.ASGITransport(app=agent3_app),
    AGENT_4_URL: httpx.ASGITransport(app=agent4_app),
}


@pytest.fixture(autouse=True)
def reset_client_state():
    """Every test gets a clean agent registry and workflow history, since
    both are process-wide singletons in the real app."""
    registry.agents = {}
    registry.discovery_errors = {}
    orchestrator._history.clear()
    yield
    registry.agents = {}
    registry.discovery_errors = {}
    orchestrator._history.clear()


@pytest.fixture
def in_process_httpx(monkeypatch):
    """Patches httpx.AsyncClient so any orchestrator/registry code that
    creates its own client (the production code path, client=None) is
    transparently routed to the in-process agent apps via ASGITransport
    instead of hitting real sockets."""

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("mounts", MOUNTS)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedAsyncClient)
    return MOUNTS
