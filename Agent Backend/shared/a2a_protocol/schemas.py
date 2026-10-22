"""A2A protocol data models shared by the orchestrator and every agent.

This is a self-contained, from-scratch implementation of the subset of the
Agent-to-Agent (A2A) protocol used by this project: Agent Cards, JSON-RPC 2.0
message/task envelopes, and structured request/response payloads. Nothing in
this module is imported from, or depends on, the reference ERP project.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "0.3.0-ennvault"


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class PartKind(str, Enum):
    TEXT = "text"
    DATA = "data"


class Part(BaseModel):
    kind: PartKind
    text: Optional[str] = None
    data: Optional[dict[str, Any]] = None


class Role(str, Enum):
    USER = "user"
    AGENT = "agent"


class Message(BaseModel):
    role: Role
    parts: list[Part]
    messageId: str = Field(default_factory=lambda: new_id("msg"))
    taskId: Optional[str] = None
    contextId: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class TaskStatus(BaseModel):
    state: TaskState
    message: Optional[Message] = None
    timestamp: Optional[str] = None


class Artifact(BaseModel):
    artifactId: str = Field(default_factory=lambda: new_id("artifact"))
    name: str
    parts: list[Part]


class Task(BaseModel):
    id: str = Field(default_factory=lambda: new_id("task"))
    contextId: str = Field(default_factory=lambda: new_id("ctx"))
    status: TaskStatus
    artifacts: list[Artifact] = Field(default_factory=list)
    history: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    inputModes: list[str] = Field(default_factory=lambda: ["application/json"])
    outputModes: list[str] = Field(default_factory=lambda: ["application/json"])


class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = True


class AgentAuthentication(BaseModel):
    required: bool = False
    schemes: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    id: str
    name: str
    description: str
    version: str
    url: str
    protocolVersion: str = PROTOCOL_VERSION
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill]
    defaultInputModes: list[str] = Field(default_factory=lambda: ["application/json", "text/plain"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["application/json", "text/plain"])
    authentication: AgentAuthentication = Field(default_factory=AgentAuthentication)
    metadata: dict[str, Any] = Field(default_factory=dict)


class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: new_id("rpc"))
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Optional[dict[str, Any]] = None


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: Optional[dict[str, Any]] = None
    error: Optional[JSONRPCError] = None


class ErrorCode:
    """A2A / JSON-RPC error codes. Negative range below -32000 is reserved
    for A2A/application errors, matching JSON-RPC 2.0 conventions."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    SKILL_NOT_SUPPORTED = -32001
    ERP_OPERATION_FAILED = -32002
    VALIDATION_FAILED = -32003
    AGENT_UNAVAILABLE = -32004
