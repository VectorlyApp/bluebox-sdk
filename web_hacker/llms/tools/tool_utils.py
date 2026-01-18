"""
web_hacker/llms/tools/tool_utils.py

Utilities for converting Python functions to LLM tool definitions.
"""

import inspect
from typing import Any, Callable, get_type_hints

from pydantic import TypeAdapter


def extract_description_from_docstring(docstring: str | None) -> str:
    """
    Extract the first paragraph from a docstring as the description.

    Args:
        docstring: The function's docstring (func.__doc__)

    Returns:
        The first paragraph of the docstring, or empty string if none.
    """
    if not docstring:
        return ""

    # split on double newlines to get first paragraph
    paragraphs = docstring.strip().split("\n\n")
    if not paragraphs:
        return ""

    # clean up the first paragraph (remove leading/trailing whitespace from each line)
    first_para = paragraphs[0]
    lines = [line.strip() for line in first_para.split("\n")]
    return " ".join(lines)


def generate_parameters_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """
    Generate JSON Schema for function parameters using pydantic.

    Args:
        func: The function to generate schema for. Must have type hints.

    Returns:
        JSON Schema dict with 'type', 'properties', and 'required' keys.
    """
    sig = inspect.signature(obj=func)
    hints = get_type_hints(obj=func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        param_type = hints.get(param_name, Any)
        # use pydantic TypeAdapter to generate schema for this type
        schema = TypeAdapter(param_type).json_schema()

        # remove pydantic metadata that's not needed for tool schemas
        schema.pop("title", None)

        properties[param_name] = schema

        # parameter is required if it has no default value
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
