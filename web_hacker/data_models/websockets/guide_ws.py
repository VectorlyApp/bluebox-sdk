"""
web_hacker/data_models/websockets/guide_ws.py

Data models for Guide Agent WebSocket communication.
"""

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, Field

from data_models.websockets.base_ws import (
    WebSocketBaseCommandResponseType,
    WebSocketBaseStreamResponseType,
    WebSocketErrorResponse,
    WebSocketPongResponse,
    WebSocketResponseBase,
    WebSocketSessionEndedResponse,
    WebSocketSuccessResponse,
    WebSocketToolInvocationRequestResponse,
    WebSocketWarningResponse,
)


__all__ = [
    # Re-exported from base_ws
    "WebSocketResponseBase",
    "WebSocketPongResponse",
    "WebSocketSuccessResponse",
    "WebSocketWarningResponse",
    "WebSocketErrorResponse",
    "WebSocketSessionEndedResponse",
    "WebSocketToolInvocationRequestResponse",
    # Guide-specific
    "GuideWebSocketClientCommandType",
    "ParsedGuideWebSocketClientCommand",
    "GuideWebSocketCommandResponseType",
    "GuideWebSocketStreamResponseType",
    "GuideWebSocketMessageResponse",
    "GuideWebSocketStateResponse",
    "GuideWebSocketToolInvocationResultResponse",
    "GuideWebSocketServerResponse",
]


# Commands from client _____________________________________________________________________________________________________

class GuideWebSocketClientCommandType(StrEnum):
    """Commands that can be sent from the client to the guide agent."""

    # simple commands
    PING = "ping"
    GET_STATE = "get_state"
    RESET = "reset"

    # commands that expect arguments in the message payload
    SEND_MESSAGE = "send_message"  # client sends "send_message:<content>"
    CONFIRM_TOOL = "confirm_tool"  # client sends "confirm_tool:<invocation_id>"
    DENY_TOOL = "deny_tool"  # client sends "deny_tool:<invocation_id>" or "deny_tool:<invocation_id>:<reason>"


class ParsedGuideWebSocketClientCommand(BaseModel):
    """Parsed websocket command with normalized command type and extracted arguments."""

    command: GuideWebSocketClientCommandType | None = Field(
        description="The parsed command type, or None if the command was invalid",
    )
    args: str | None = Field(
        default=None,
        description="Raw argument string extracted from the command",
    )
    error: str | None = Field(
        default=None,
        description="Error message if the command could not be parsed, or None if parsing succeeded",
    )

    @property
    def is_valid(self) -> bool:
        """Whether the command was successfully parsed."""
        return self.command is not None and self.error is None

    @property
    def message_content(self) -> str | None:
        """
        Extract message content from send_message command.

        Returns:
            - None if not a send_message command
            - Empty string if send_message with no content
            - Content string if send_message with content
        """
        if self.command != GuideWebSocketClientCommandType.SEND_MESSAGE:
            return None
        return self.args or ""

    @property
    def invocation_id(self) -> str | None:
        """
        Extract invocation ID from confirm_tool or deny_tool command.

        Returns:
            - None if not a confirm/deny command
            - Invocation ID string if confirm/deny command
        """
        if self.command not in (
            GuideWebSocketClientCommandType.CONFIRM_TOOL,
            GuideWebSocketClientCommandType.DENY_TOOL,
        ):
            return None
        if not self.args:
            return None
        # For deny_tool, args could be "invocation_id:reason"
        return self.args.split(":")[0]

    @property
    def deny_reason(self) -> str | None:
        """
        Extract denial reason from deny_tool command.

        Returns:
            - None if not a deny_tool command or no reason provided
            - Reason string if deny_tool with reason
        """
        if self.command != GuideWebSocketClientCommandType.DENY_TOOL:
            return None
        if not self.args or ":" not in self.args:
            return None
        parts = self.args.split(":", 1)
        return parts[1] if len(parts) > 1 else None

    @classmethod
    def parse_raw_websocket_command(cls, raw_message: str) -> Self:
        """
        Parse a raw websocket message into a structured command with arguments.

        Args:
            raw_message: The raw message string from the client

        Returns:
            ParsedGuideWebSocketClientCommand with normalized command type and extracted arguments

        Examples:
            >>> ParsedGuideWebSocketClientCommand.parse_raw_websocket_command("ping")
            ParsedGuideWebSocketClientCommand(command="ping", args=None, error=None)

            >>> ParsedGuideWebSocketClientCommand.parse_raw_websocket_command("send_message:Hello")
            ParsedGuideWebSocketClientCommand(command="send_message", args="Hello", error=None)

            >>> ParsedGuideWebSocketClientCommand.parse_raw_websocket_command("confirm_tool:abc-123")
            ParsedGuideWebSocketClientCommand(command="confirm_tool", args="abc-123", error=None)
        """
        message = raw_message.strip().lower()

        # simple commands (no arguments)
        if message == GuideWebSocketClientCommandType.PING:
            return cls(command=GuideWebSocketClientCommandType.PING)

        if message == GuideWebSocketClientCommandType.GET_STATE:
            return cls(command=GuideWebSocketClientCommandType.GET_STATE)

        if message == GuideWebSocketClientCommandType.RESET:
            return cls(command=GuideWebSocketClientCommandType.RESET)

        # send_message command (preserve original case for content)
        if message.startswith(GuideWebSocketClientCommandType.SEND_MESSAGE):
            remainder = message[len(GuideWebSocketClientCommandType.SEND_MESSAGE):]

            if remainder == "":
                return cls(command=GuideWebSocketClientCommandType.SEND_MESSAGE, args=None)

            if remainder.startswith(":"):
                # preserve original case for message content
                original_remainder = raw_message.strip()[
                    len(GuideWebSocketClientCommandType.SEND_MESSAGE) + 1:
                ]
                return cls(
                    command=GuideWebSocketClientCommandType.SEND_MESSAGE,
                    args=original_remainder.strip() if original_remainder.strip() else None,
                )

            return cls(
                command=None,
                error=f'Invalid send_message command: "{raw_message}" (must be "send_message" or "send_message:<content>")',
            )

        # confirm_tool command
        if message.startswith(GuideWebSocketClientCommandType.CONFIRM_TOOL):
            remainder = message[len(GuideWebSocketClientCommandType.CONFIRM_TOOL):]

            if remainder == "":
                return cls(
                    command=None,
                    error='confirm_tool requires an invocation_id (e.g., "confirm_tool:<invocation_id>")',
                )

            if remainder.startswith(":"):
                original_remainder = raw_message.strip()[
                    len(GuideWebSocketClientCommandType.CONFIRM_TOOL) + 1:
                ]
                invocation_id = original_remainder.strip()
                if not invocation_id:
                    return cls(
                        command=None,
                        error='confirm_tool requires an invocation_id',
                    )
                return cls(
                    command=GuideWebSocketClientCommandType.CONFIRM_TOOL,
                    args=invocation_id,
                )

            return cls(
                command=None,
                error=f'Invalid confirm_tool command: "{raw_message}"',
            )

        # deny_tool command
        if message.startswith(GuideWebSocketClientCommandType.DENY_TOOL):
            remainder = message[len(GuideWebSocketClientCommandType.DENY_TOOL):]

            if remainder == "":
                return cls(
                    command=None,
                    error='deny_tool requires an invocation_id (e.g., "deny_tool:<invocation_id>" or "deny_tool:<invocation_id>:<reason>")',
                )

            if remainder.startswith(":"):
                original_remainder = raw_message.strip()[
                    len(GuideWebSocketClientCommandType.DENY_TOOL) + 1:
                ]
                args = original_remainder.strip()
                if not args:
                    return cls(
                        command=None,
                        error='deny_tool requires an invocation_id',
                    )
                return cls(
                    command=GuideWebSocketClientCommandType.DENY_TOOL,
                    args=args,
                )

            return cls(
                command=None,
                error=f'Invalid deny_tool command: "{raw_message}"',
            )

        # unknown command
        return cls(
            command=None,
            error=f'Unknown command: "{raw_message}"',
        )


# Responses to client _____________________________________________________________________________________________________

## Response type enums

class GuideWebSocketCommandResponseType(StrEnum):
    """
    Response envelope types the server sends back to the client for direct commands.
    Extends base types with guide-specific response types.
    """

    # inherited from base
    PONG = WebSocketBaseCommandResponseType.PONG
    SUCCESS = WebSocketBaseCommandResponseType.SUCCESS
    WARNING = WebSocketBaseCommandResponseType.WARNING
    ERROR = WebSocketBaseCommandResponseType.ERROR
    # guide-specific
    MESSAGE = "message"
    STATE = "state"


class GuideWebSocketStreamResponseType(StrEnum):
    """
    Message types used when the server streams guide agent updates.
    Extends base types with guide-specific stream types.
    """

    # inherited from base
    SESSION_ENDED = WebSocketBaseStreamResponseType.SESSION_ENDED
    TOOL_INVOCATION_REQUEST = WebSocketBaseStreamResponseType.TOOL_INVOCATION_REQUEST
    # guide-specific
    TOOL_INVOCATION_RESULT = "tool_invocation_result"


## Guide-specific command responses

class GuideWebSocketMessageResponse(WebSocketResponseBase):
    """Agent chat message response."""

    type: Literal[GuideWebSocketCommandResponseType.MESSAGE] = (
        GuideWebSocketCommandResponseType.MESSAGE
    )
    content: str = Field(
        description="The agent's message content",
    )


class GuideWebSocketStateResponse(WebSocketResponseBase):
    """Response to the get_state command with current conversation state."""

    type: Literal[GuideWebSocketCommandResponseType.STATE] = (
        GuideWebSocketCommandResponseType.STATE
    )
    guide_chat_id: str = Field(
        description="Current session ID",
    )
    message_count: int = Field(
        description="Number of messages in conversation history",
    )
    has_pending_tool_invocation: bool = Field(
        description="Whether there's a pending tool invocation awaiting confirmation",
    )
    pending_tool_invocation_id: str | None = Field(
        default=None,
        description="ID of the pending tool invocation, if any",
    )


## Guide-specific streamed responses

class GuideWebSocketToolInvocationResultResponse(WebSocketResponseBase):
    """Result after tool confirmation/denial/execution."""

    type: Literal[GuideWebSocketStreamResponseType.TOOL_INVOCATION_RESULT] = (
        GuideWebSocketStreamResponseType.TOOL_INVOCATION_RESULT
    )
    invocation_id: str = Field(
        description="ID of the tool invocation",
    )
    status: str = Field(
        description="Status of the invocation (confirmed, denied, executed, failed)",
    )
    result: dict[str, Any] | None = Field(
        default=None,
        description="Result data from tool execution, if successful",
    )
    error: str | None = Field(
        default=None,
        description="Error message if execution failed",
    )


# Type unions for working with all possible response types _________________________________________________________________

GuideWebSocketServerResponse = (
    # command responses (from base)
    WebSocketPongResponse
    | WebSocketSuccessResponse
    | WebSocketWarningResponse
    | WebSocketErrorResponse
    # command responses (guide-specific)
    | GuideWebSocketMessageResponse
    | GuideWebSocketStateResponse
    # streamed responses (from base)
    | WebSocketSessionEndedResponse
    | WebSocketToolInvocationRequestResponse
    # streamed responses (guide-specific)
    | GuideWebSocketToolInvocationResultResponse
)
