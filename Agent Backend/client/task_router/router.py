"""Client-side task routing.

Turns a free-text user request into one or more (agentId, taskText)
invocations by matching tokens in the request against the tags/name/
description of every skill each agent advertises on its Agent Card. Each
matched agent then receives the *full* natural-language request and its own
CrewAI crew decides which of its tools to call and how to fill its
arguments -- so this router only ever decides WHICH agent(s) apply, never
which tool or what parameters. That keeps skill-level reasoning inside each
agent, where it belongs, while agent selection stays a client concern.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..agent_registry.registry import AgentRegistry

_STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "to", "and", "or", "for", "in", "on", "at", "by", "with",
    "from", "this", "that", "what", "when", "where", "how", "me", "give", "please", "tell", "today",
    "like", "you", "your", "i", "it", "be", "do", "does", "did", "can", "could", "would", "should",
}


@dataclass
class RoutedCall:
    agent_id: str
    base_url: str
    task_text: str
    reason: str


def _tokenize(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9_]+", text.lower()))
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 1}


def route(registry: AgentRegistry, user_text: str) -> list[RoutedCall]:
    """Scores every discovered agent (via the union of its skills' tags/
    name/description) against the request text -- the score is the fraction
    of the request's meaningful tokens the agent's vocabulary covers -- and
    returns the agents close to the best match. Multiple agents can be
    returned for one request, enabling multi-agent workflows."""
    tokens = _tokenize(user_text)
    if not tokens:
        return []

    scored: list[tuple[float, str, str]] = []
    for agent in registry.list_agents():
        agent_tokens: set[str] = set()
        for skill in agent.card.skills:
            agent_tokens |= _tokenize(" ".join([skill.id, skill.name, skill.description, " ".join(skill.tags)]))
        overlap = tokens & agent_tokens
        if overlap:
            score = len(overlap) / len(tokens)
            scored.append((score, agent.card.id, agent.base_url))

    if not scored:
        return []

    scored.sort(key=lambda item: item[0], reverse=True)
    top_score = scored[0][0]
    threshold = top_score * 0.6

    calls: list[RoutedCall] = []
    seen_agents: set[str] = set()
    for score, agent_id, base_url in scored:
        if score < threshold or agent_id in seen_agents:
            continue
        seen_agents.add(agent_id)
        calls.append(RoutedCall(agent_id, base_url, user_text, reason=f"matched agent '{agent_id}' with score {round(score, 2)}"))
    return calls
