"""
web_hacker/llms/anthropic_client.py

Anthropic-specific LLM client implementation.
"""

from collections.abc import Generator
from typing import Any, TypeVar

from anthropic import Anthropic, AsyncAnthropic
from pydantic import BaseModel

from web_hacker.data_models.chat import LLMChatResponse, LLMToolCall
from web_hacker.data_models.llms import LLMModel
from web_hacker.llms.abstract_llm_vendor_client import AbstractLLMVendorClient
from web_hacker.config import Config
from web_hacker.utils.logger import get_logger

logger = get_logger(name=__name__)


T = TypeVar("T", bound=BaseModel)


class AnthropicClient(AbstractLLMVendorClient):
    """
    Anthropic-specific implementation of the LLM vendor client.

    Uses the Anthropic Python SDK for message completions, structured outputs
    via tool use, and function calling.
    """

    # Magic methods ________________________________________________________________________________________________________

    def __init__(self, model: LLMModel) -> None:
        super().__init__(model)
        self._client = Anthropic(api_key=Config.ANTHROPIC_API_KEY)
        self._async_client = AsyncAnthropic(api_key=Config.ANTHROPIC_API_KEY)
        logger.debug("Initialized AnthropicClient with model: %s", model)


    # Private methods ______________________________________________________________________________________________________

    def _extract_text_content(self, content: list[Any]) -> str:
        """Extract text from Anthropic content blocks."""
        text_parts = [block.text for block in content if hasattr(block, "text")]
        return "".join(text_parts)

    def _build_extraction_tool(
        self,
        response_model: type[T],
    ) -> dict[str, Any]:
        """Build the extraction tool for structured responses."""
        tool_schema = response_model.model_json_schema()
        return {
            "name": "extract_data",
            "description": f"Extract data matching the {response_model.__name__} schema.",
            "input_schema": tool_schema,
        }

    def _append_extraction_instruction(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Append extraction instruction to the last user message."""
        if not messages:
            return messages

        # Copy messages to avoid mutating the original
        messages = [dict(m) for m in messages]

        # Find the last user message and append instruction
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                messages[i]["content"] = (
                    f"{messages[i]['content']}\n\nUse the 'extract_data' tool to provide your response "
                    f"in the exact schema specified."
                )
                break

        return messages

    def _extract_tool_result(
        self,
        content: list[Any],
        response_model: type[T],
    ) -> T:
        """Extract and validate the tool use result from Anthropic response."""
        for block in content:
            if hasattr(block, "input") and hasattr(block, "name") and block.name == "extract_data":
                return response_model.model_validate(block.input)
        raise ValueError("Failed to extract structured response from Anthropic")


    # Public methods _______________________________________________________________________________________________________

    ## Tool management

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> None:
        """Register a tool in Anthropic's tool format."""
        logger.debug("Registering Anthropic tool: %s", name)
        self._tools.append({
            "name": name,
            "description": description,
            "input_schema": parameters,
        })

    ## Text generation

    def get_text_sync(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Get a text response synchronously using Anthropic messages API."""
        kwargs: dict[str, Any] = {
            "model": self.model.value,
            "messages": messages,
            "max_tokens": self._resolve_max_tokens(max_tokens),
            "temperature": self._resolve_temperature(temperature),
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if self._tools:
            kwargs["tools"] = self._tools

        response = self._client.messages.create(**kwargs)
        return self._extract_text_content(response.content)

    async def get_text_async(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Get a text response asynchronously using Anthropic messages API."""
        kwargs: dict[str, Any] = {
            "model": self.model.value,
            "messages": messages,
            "max_tokens": self._resolve_max_tokens(max_tokens),
            "temperature": self._resolve_temperature(temperature),
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if self._tools:
            kwargs["tools"] = self._tools

        response = await self._async_client.messages.create(**kwargs)
        return self._extract_text_content(response.content)

    ## Structured responses

    def get_structured_response_sync(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> T:
        """Get a structured response using Anthropic's tool_use with forced tool choice."""
        tool = self._build_extraction_tool(response_model)
        structured_messages = self._append_extraction_instruction(messages)

        kwargs: dict[str, Any] = {
            "model": self.model.value,
            "messages": structured_messages,
            "max_tokens": self._resolve_max_tokens(max_tokens),
            "temperature": self._resolve_temperature(temperature, structured=True),
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "extract_data"},
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self._client.messages.create(**kwargs)
        return self._extract_tool_result(response.content, response_model)

    async def get_structured_response_async(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> T:
        """Get a structured response asynchronously using Anthropic's tool_use."""
        tool = self._build_extraction_tool(response_model)
        structured_messages = self._append_extraction_instruction(messages)

        kwargs: dict[str, Any] = {
            "model": self.model.value,
            "messages": structured_messages,
            "max_tokens": self._resolve_max_tokens(max_tokens),
            "temperature": self._resolve_temperature(temperature, structured=True),
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "extract_data"},
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._async_client.messages.create(**kwargs)
        return self._extract_tool_result(response.content, response_model)

    ## Chat with tools

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMChatResponse:
        """Chat with Anthropic using message history and tool calling support."""
        kwargs: dict[str, Any] = {
            "model": self.model.value,
            "messages": messages,
            "max_tokens": self._resolve_max_tokens(max_tokens),
            "temperature": self._resolve_temperature(temperature),
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if self._tools:
            kwargs["tools"] = self._tools

        response = self._client.messages.create(**kwargs)

        # Extract text content
        text_content = self._extract_text_content(response.content)

        # Extract tool call if present
        tool_call: LLMToolCall | None = None
        for block in response.content:
            if hasattr(block, "input") and hasattr(block, "name"):
                tool_call = LLMToolCall(
                    tool_name=block.name,
                    tool_arguments=block.input,
                )
                break

        return LLMChatResponse(
            content=text_content if text_content else None,
            tool_call=tool_call,
        )

    def chat_stream_sync(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Generator[str | LLMChatResponse, None, None]:
        """Chat with streaming, yielding text chunks and final LLMChatResponse."""
        kwargs: dict[str, Any] = {
            "model": self.model.value,
            "messages": messages,
            "max_tokens": self._resolve_max_tokens(max_tokens),
            "temperature": self._resolve_temperature(temperature),
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if self._tools:
            kwargs["tools"] = self._tools

        full_content: list[str] = []
        tool_name: str | None = None
        tool_input: dict[str, Any] = {}

        with self._client.messages.stream(**kwargs) as stream:
            for event in stream:
                # Handle text delta events
                if hasattr(event, "type"):
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            full_content.append(event.delta.text)
                            yield event.delta.text
                        elif hasattr(event.delta, "partial_json"):
                            # Tool input being streamed
                            pass
                    elif event.type == "content_block_start":
                        if hasattr(event.content_block, "name"):
                            tool_name = event.content_block.name

            # Get final message for tool input
            final_message = stream.get_final_message()
            for block in final_message.content:
                if hasattr(block, "input") and hasattr(block, "name"):
                    tool_name = block.name
                    tool_input = block.input
                    break

        # Build final response
        tool_call: LLMToolCall | None = None
        if tool_name:
            tool_call = LLMToolCall(
                tool_name=tool_name,
                tool_arguments=tool_input,
            )

        yield LLMChatResponse(
            content="".join(full_content) if full_content else None,
            tool_call=tool_call,
        )
