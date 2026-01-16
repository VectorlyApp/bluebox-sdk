"""
web_hacker/llms/llm_client.py

Unified LLM client supporting OpenAI and Anthropic models.
"""

from collections.abc import Generator
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from web_hacker.data_models.chat import LLMChatResponse
from web_hacker.data_models.llms import (
    LLMModel,
    LLMVendor,
    OpenAIModel,
    get_model_vendor,
)
from web_hacker.llms.tools.tool_utils import extract_description_from_docstring, generate_parameters_schema
from web_hacker.llms.abstract_llm_vendor_client import AbstractLLMVendorClient
from web_hacker.llms.anthropic_client import AnthropicClient
from web_hacker.llms.openai_client import OpenAIClient
from web_hacker.utils.logger import get_logger

logger = get_logger(name=__name__)


T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """
    Unified LLM client class for interacting with OpenAI and Anthropic APIs.

    This is a facade that delegates to vendor-specific clients (OpenAIClient,
    AnthropicClient) based on the selected model.

    Supports:
    - Sync and async text generation
    - Structured responses using Pydantic models
    - Tool/function registration
    """

    # Magic methods ________________________________________________________________________________________________________

    def __init__(
        self,
        llm_model: LLMModel = OpenAIModel.GPT_5_MINI,
    ) -> None:
        self.llm_model = llm_model
        self.vendor = get_model_vendor(llm_model)

        # initialize the appropriate vendor client
        self._vendor_client: AbstractLLMVendorClient
        if self.vendor == LLMVendor.OPENAI:
            self._vendor_client = OpenAIClient(model=llm_model)
        elif self.vendor == LLMVendor.ANTHROPIC:
            self._vendor_client = AnthropicClient(model=llm_model)
        else:
            raise ValueError(f"Unsupported vendor: {self.vendor}")

        logger.info("Instantiated LLMClient with model: %s (vendor: %s)", llm_model, self.vendor)

    # Public methods _______________________________________________________________________________________________________

    ## Tools

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> None:
        """
        Register a tool for function calling.

        Args:
            name: The name of the tool/function.
            description: Description of what the tool does.
            parameters: JSON Schema describing the tool's parameters.
        """
        logger.debug("Registering tool %s (description: %s) with parameters: %s", name, description, parameters)
        self._vendor_client.register_tool(name, description, parameters)

    def register_tool_from_function(self, func: Callable[..., Any]) -> None:
        """
        Register a tool from a Python function, extracting metadata automatically.

        Extracts:
        - name: from func.__name__
        - description: from the docstring (first paragraph)
        - parameters: JSON Schema generated from type hints via pydantic

        Args:
            func: The function to register as a tool. Must have type hints.
        """
        name = func.__name__
        description = extract_description_from_docstring(func.__doc__)
        parameters = generate_parameters_schema(func)
        self.register_tool(name, description, parameters)

    def clear_tools(self) -> None:
        """Clear all registered tools."""
        self._vendor_client.clear_tools()
        logger.debug("Cleared all registered tools")

    ## Text generation

    def get_text_sync(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """
        Get a text response synchronously.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            system_prompt: Optional system prompt for context.
            max_tokens: Maximum tokens in the response. Defaults to DEFAULT_MAX_TOKENS.
            temperature: Sampling temperature (0.0-1.0). Defaults to DEFAULT_TEMPERATURE.

        Returns:
            The generated text response.
        """
        return self._vendor_client.get_text_sync(
            messages,
            system_prompt,
            max_tokens,
            temperature,
        )

    async def get_text_async(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """
        Get a text response asynchronously.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            system_prompt: Optional system prompt for context.
            max_tokens: Maximum tokens in the response. Defaults to DEFAULT_MAX_TOKENS.
            temperature: Sampling temperature (0.0-1.0). Defaults to DEFAULT_TEMPERATURE.

        Returns:
            The generated text response.
        """
        return await self._vendor_client.get_text_async(
            messages,
            system_prompt,
            max_tokens,
            temperature,
        )

    ## Structured responses

    def get_structured_response_sync(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> T:
        """
        Get a structured response as a Pydantic model synchronously.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            response_model: Pydantic model class for the response structure.
            system_prompt: Optional system prompt for context.
            max_tokens: Maximum tokens in the response. Defaults to DEFAULT_MAX_TOKENS.
            temperature: Sampling temperature. Defaults to DEFAULT_STRUCTURED_TEMPERATURE.

        Returns:
            Parsed response as the specified Pydantic model.
        """
        return self._vendor_client.get_structured_response_sync(
            messages,
            response_model,
            system_prompt,
            max_tokens,
            temperature,
        )

    async def get_structured_response_async(
        self,
        messages: list[dict[str, str]],
        response_model: type[T],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> T:
        """
        Get a structured response as a Pydantic model asynchronously.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            response_model: Pydantic model class for the response structure.
            system_prompt: Optional system prompt for context.
            max_tokens: Maximum tokens in the response. Defaults to DEFAULT_MAX_TOKENS.
            temperature: Sampling temperature. Defaults to DEFAULT_STRUCTURED_TEMPERATURE.

        Returns:
            Parsed response as the specified Pydantic model.
        """
        return await self._vendor_client.get_structured_response_async(
            messages,
            response_model,
            system_prompt,
            max_tokens,
            temperature,
        )

    ## Chat with tools

    def chat_sync(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMChatResponse:
        """
        Chat with the LLM using a message history, with tool calling support.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            system_prompt: Optional system prompt for context.
            max_tokens: Maximum tokens in the response. Defaults to DEFAULT_MAX_TOKENS.
            temperature: Sampling temperature (0.0-1.0). Defaults to DEFAULT_TEMPERATURE.

        Returns:
            LLMChatResponse with text content and optional tool call.
        """
        return self._vendor_client.chat_sync(
            messages,
            system_prompt,
            max_tokens,
            temperature,
        )

    def chat_stream_sync(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Generator[str | LLMChatResponse, None, None]:
        """
        Chat with streaming, yielding text chunks and final LLMChatResponse.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            system_prompt: Optional system prompt for context.
            max_tokens: Maximum tokens in the response. Defaults to DEFAULT_MAX_TOKENS.
            temperature: Sampling temperature (0.0-1.0). Defaults to DEFAULT_TEMPERATURE.

        Yields:
            str: Text chunks as they arrive.
            LLMChatResponse: Final response with complete content and optional tool call.
        """
        yield from self._vendor_client.chat_stream_sync(
            messages,
            system_prompt,
            max_tokens,
            temperature,
        )
