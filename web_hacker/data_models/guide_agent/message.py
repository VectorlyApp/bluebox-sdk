"""
web_hacker/data_models/guide_agent/message.py

Guide agent message data models for internal communication via callbacks.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from data_models.guide_agent.conversation import PendingToolInvocation


class GuideAgentMessageType(StrEnum):
    """Types of messages the guide agent can emit via callback."""

    CHAT_RESPONSE = "chat_response"
    TOOL_INVOCATION_REQUEST = "tool_invocation_request"
    TOOL_INVOCATION_RESULT = "tool_invocation_result"
    ERROR = "error"


class GuideAgentMessage(BaseModel):
    """
    Message emitted by the guide agent via callback.

    This is the internal message format used by GuideAgent to communicate
    with its host (e.g., CLI, WebSocket handler in servers repo).
    """

    type: GuideAgentMessageType = Field(
        ...,
        description="The type of message being emitted",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the message was created",
    )
    content: str | None = Field(
        default=None,
        description="Text content for chat responses or error messages",
    )
    tool_invocation: PendingToolInvocation | None = Field(
        default=None,
        description="Tool invocation details for request/result messages",
    )
    tool_result: dict[str, Any] | None = Field(
        default=None,
        description="Result data from tool execution",
    )
    error: str | None = Field(
        default=None,
        description="Error message if type is ERROR",
    )
