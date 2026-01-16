"""
web_hacker/llms/abstract_llm_vendor_client.py

Abstract base class for LLM vendor clients.
"""

from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel

from web_hacker.data_models.chat import LLMChatResponse
from web_hacker.data_models.llms import LLMModel


T = TypeVar("T", bound=BaseModel)


class AbstractLLMVendorClient(ABC):
    """
    Abstract base class defining the interface for LLM vendor clients.

    All vendor-specific clients (OpenAI, Anthropic, etc.) must implement
    this interface to ensure consistent behavior across the LLMClient.
    """

    # Class attributes ____________________________________________________________________________________________________

    DEFAULT_MAX_TOKENS: ClassVar[int] = 4_096
    DEFAULT_TEMPERATURE: ClassVar[float] = 0.7
    DEFAULT_STRUCTURED_TEMPERATURE: ClassVar[float] = 0.0  # deterministic for structured outputs


    # Magic methods ________________________________________________________________________________________________________

    def __init__(self, model: LLMModel) -> None:
        """
        Initialize the vendor client.

        Args:
            model: The LLM model to use.
        """
        self.model = model
        self._tools: list[dict[str, Any]] = []


    # Private methods ______________________________________________________________________________________________________

    def _resolve_max_tokens(self, max_tokens: int | None) -> int:
        """Resolve max_tokens, using default if None."""
        return max_tokens if max_tokens is not None else self.DEFAULT_MAX_TOKENS

    def _resolve_temperature(
        self,
        temperature: float | None,
        structured: bool = False,
    ) -> float:
        """Resolve temperature, using appropriate default if None."""
        if temperature is not None:
            return temperature
        return self.DEFAULT_STRUCTURED_TEMPERATURE if structured else self.DEFAULT_TEMPERATURE


    # Public methods _______________________________________________________________________________________________________

    ### Tool management

    @abstractmethod
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
        pass

    def clear_tools(self) -> None:
        """Clear all registered tools."""
        self._tools = []

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Return the list of registered tools."""
        return self._tools

    ## Text generation

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    ## Structured responses

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    ## Chat with tools

    @abstractmethod
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
        pass

    @abstractmethod
    def chat_stream_sync(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Generator[str | LLMChatResponse, None, None]:
        """
        Chat with streaming, yielding text chunks and final LLMChatResponse.

        Yields text chunks as they arrive, then yields the final LLMChatResponse
        with the complete content and any tool call.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            system_prompt: Optional system prompt for context.
            max_tokens: Maximum tokens in the response. Defaults to DEFAULT_MAX_TOKENS.
            temperature: Sampling temperature (0.0-1.0). Defaults to DEFAULT_TEMPERATURE.

        Yields:
            str: Text chunks as they arrive.
            LLMChatResponse: Final response with complete content and optional tool call.
        """
        pass
