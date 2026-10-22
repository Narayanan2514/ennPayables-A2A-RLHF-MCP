"""Validates and dispatches inbound JSON-RPC A2A requests for Agent 4."""
from __future__ import annotations

from shared.a2a_protocol.schemas import ErrorCode, JSONRPCError, JSONRPCRequest, JSONRPCResponse, Message

from ..executor.executor import Agent4Executor

executor = Agent4Executor()


async def handle_jsonrpc(request: JSONRPCRequest) -> JSONRPCResponse:
    if request.method != "message/send":
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(code=ErrorCode.METHOD_NOT_FOUND, message=f"Unsupported method '{request.method}'. Expected 'message/send'."),
        )

    message_payload = request.params.get("message")
    if not message_payload:
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(code=ErrorCode.INVALID_PARAMS, message="Missing required 'message' param."),
        )

    try:
        message = Message(**message_payload)
    except Exception as exc:
        return JSONRPCResponse(
            id=request.id,
            error=JSONRPCError(code=ErrorCode.INVALID_REQUEST, message=f"Malformed A2A message: {exc}"),
        )

    task = await executor.execute(message)
    return JSONRPCResponse(id=request.id, result=task.model_dump(mode="json"))
