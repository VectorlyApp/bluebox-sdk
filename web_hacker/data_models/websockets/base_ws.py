"""
web_hacker/data_models/websockets/base_ws.py

Base data models for WebSocket communication shared across agents.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


# Base response type enums _________________________________________________________________________________________________

class WebSocketBaseCommandResponseType(StrEnum):
    """
    Common response types shared across all WebSocket endpoints.
    Subapps can extend with their own specific response types.
    """

    PONG = "pong"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class WebSocketBaseStreamResponseType(StrEnum):
    """
    Common stream response types shared across all WebSocket endpoints.
    Subapps can extend with their own specific stream types.
    """

    SESSION_ENDED = "session_ended"
    TOOL_INVOCATION_REQUEST = "tool_invocation_request"


# Base response classes ____________________________________________________________________________________________________

class WebSocketResponseBase(BaseModel):
    """
    Base shape for all websocket response messages.
    All agent-specific responses should inherit from this.
    """

    type: str  # generic string type for base, subclasses narrow to specific literals
    timestamp: float = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc).timestamp(),
        description="UTC unix timestamp",
    )


# Common command responses _________________________________________________________________________________________________

class WebSocketPongResponse(WebSocketResponseBase):
    """Response to the ping command."""

    type: Literal[WebSocketBaseCommandResponseType.PONG] = (
        WebSocketBaseCommandResponseType.PONG
    )


class WebSocketSuccessResponse(WebSocketResponseBase):
    """Generic success response for commands that complete successfully."""

    type: Literal[WebSocketBaseCommandResponseType.SUCCESS] = (
        WebSocketBaseCommandResponseType.SUCCESS
    )
    message: str = Field(
        description="Human-readable success message",
    )


class WebSocketWarningResponse(WebSocketResponseBase):
    """Warning response used for non-fatal cases where the command could not be completed."""

    type: Literal[WebSocketBaseCommandResponseType.WARNING] = (
        WebSocketBaseCommandResponseType.WARNING
    )
    message: str = Field(
        description="Human-readable warning message",
    )


class WebSocketErrorResponse(WebSocketResponseBase):
    """Error envelope used when a command is invalid or fails."""

    type: Literal[WebSocketBaseCommandResponseType.ERROR] = (
        WebSocketBaseCommandResponseType.ERROR
    )
    message: str = Field(
        description="Human-readable error message",
    )


# Common stream responses __________________________________________________________________________________________________

class WebSocketSessionEndedResponse(WebSocketResponseBase):
    """
    Notification sent to clients when the session is ending.
    Sent before the WebSocket connection is closed.
    """

    type: Literal[WebSocketBaseStreamResponseType.SESSION_ENDED] = (
        WebSocketBaseStreamResponseType.SESSION_ENDED
    )
    reason: str = Field(
        description="Reason for session end (e.g., 'Session ended manually', 'Timeout reached', 'Error occurred')",
    )
    error_message: str | None = Field(
        default=None,
        description="Optional error message if the session ended due to an error",
    )


class WebSocketToolInvocationRequestResponse(WebSocketResponseBase):
    """
    Generic tool invocation request requiring user confirmation.

    Sent when an agent wants to execute a tool but needs user approval first.
    The client should respond with a confirm or deny command.
    """

    type: Literal[WebSocketBaseStreamResponseType.TOOL_INVOCATION_REQUEST] = (
        WebSocketBaseStreamResponseType.TOOL_INVOCATION_REQUEST
    )
    invocation_id: str = Field(
        description="Unique ID for this invocation (UUIDv4)",
    )
    tool_name: str = Field(
        description="Name of the tool to invoke",
    )
    tool_arguments: dict[str, Any] = Field(
        description="Arguments to pass to the tool",
    )
    explanation: str = Field(
        description="Human-readable explanation of what the tool will do",
    )
