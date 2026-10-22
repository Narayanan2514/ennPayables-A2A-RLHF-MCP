"""Discovers agents via their /.well-known/agent.json Agent Cards and keeps
an in-memory registry the orchestrator uses for routing decisions.

The client knows only the configured agent base URLs (env vars) -- it never
hardcodes what skills an agent has. Skills, tags and descriptions are all
read from each agent's Agent Card at discovery time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx

from shared.a2a_protocol.schemas import AgentCard
from shared.config.settings import AGENT_DISCOVERY_TIMEOUT_SECONDS, REGISTERED_AGENT_URLS
from shared.utilities.logging import get_logger

logger = get_logger("client.agent_registry")


@dataclass
class RegisteredAgent:
    card: AgentCard
    base_url: str
    status: str = "available"


@dataclass
class AgentRegistry:
    agents: dict[str, RegisteredAgent] = field(default_factory=dict)
    discovery_errors: dict[str, str] = field(default_factory=dict)

    async def discover(self, urls: Optional[list[str]] = None, client: httpx.AsyncClient | None = None) -> None:
        """Fetches each configured agent's Agent Card and (re)builds the
        registry. `client` can be injected for testing (e.g. an
        httpx.AsyncClient with ASGITransport mounts)."""
        urls = urls or REGISTERED_AGENT_URLS
        self.agents = {}
        self.discovery_errors = {}

        owns_client = client is None
        active_client = client or httpx.AsyncClient(timeout=AGENT_DISCOVERY_TIMEOUT_SECONDS)
        try:
            for url in urls:
                try:
                    response = await active_client.get(f"{url}/.well-known/agent.json")
                    response.raise_for_status()
                    card = AgentCard(**response.json())
                    self.agents[card.id] = RegisteredAgent(card=card, base_url=url, status="available")
                    logger.info("Discovered agent '%s' (%s skills) at %s", card.id, len(card.skills), url)
                except Exception as exc:
                    self.discovery_errors[url] = f"{type(exc).__name__}: {exc}"
                    logger.error("Failed to discover agent at %s: %s", url, exc)
        finally:
            if owns_client:
                await active_client.aclose()

    def list_agents(self) -> list[RegisteredAgent]:
        return list(self.agents.values())

    def get_agent(self, agent_id: str) -> Optional[RegisteredAgent]:
        return self.agents.get(agent_id)

    def all_skills(self) -> list[dict]:
        return [
            {"agentId": agent.card.id, "agentName": agent.card.name, "baseUrl": agent.base_url, "skill": skill.model_dump(mode="json")}
            for agent in self.agents.values()
            for skill in agent.card.skills
        ]


registry = AgentRegistry()
