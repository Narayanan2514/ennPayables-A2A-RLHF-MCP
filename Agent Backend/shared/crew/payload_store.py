"""Per-agent in-memory store for large structured payloads that ride along
with an A2A message as a DataPart.

CrewAI's tool-call argument parser is a ReAct-style text parser (not native
OpenAI function calling) -- it's unreliable at reproducing large or nested
JSON as an "Action Input" value (it has to emit valid, correctly-escaped
JSON as free text, which smaller/faster models frequently get wrong on
anything non-trivial). So instead of asking the LLM to copy a big JSON blob
into a tool argument, the executor extracts the message's DataPart directly
(no LLM involved), stashes it here under a short key, and only that key
travels through the LLM's tool call -- which it can copy verbatim.

Each agent owns its own `PayloadStore` instance (constructed once alongside
its tools); nothing here is shared across agents.
"""
from __future__ import annotations

import uuid
from typing import Any


class PayloadStore:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def put(self, payload: Any) -> str:
        key = uuid.uuid4().hex[:12]
        self._data[key] = payload
        return key

    def pop(self, key: str) -> Any | None:
        return self._data.pop(key, None)

    def discard(self, key: str) -> None:
        self._data.pop(key, None)
