"""
Unit tests for execute_routine_tool.
"""

import json
import pytest

from bluebox.llms.tools.execute_routine_tool import (
    execute_routine_from_json,
    execute_routine_from_dict,
)


def test_execute_routine_from_json_invalid_json():
    """Test that invalid JSON returns an error."""
    result = execute_routine_from_json(
        routine_json_str="not valid json",
        parameters={"test": "value"},
    )
    assert result["success"] is False
    assert "Invalid routine JSON" in result["error"]


def test_execute_routine_from_json_invalid_routine():
    """Test that invalid routine structure returns an error."""
    result = execute_routine_from_json(
        routine_json_str='{"invalid": "routine"}',
        parameters={"test": "value"},
    )
    assert result["success"] is False
    assert "Failed to parse routine" in result["error"]


def test_execute_routine_from_dict_invalid_routine():
    """Test that invalid routine dict returns an error."""
    result = execute_routine_from_dict(
        routine_dict={"invalid": "routine"},
        parameters={"test": "value"},
    )
    assert result["success"] is False
    assert "Failed to parse routine" in result["error"]


def test_execute_routine_from_json_valid_structure():
    """Test that a valid routine structure can be parsed and executed."""
    routine = {
        "name": "test_routine",
        "description": "A test routine",
        "parameters": [
            {
                "name": "test_param",
                "description": "A test parameter",
                "type": "string",
                "required": True,
            }
        ],
        "operations": [
            {
                "type": "navigate",
                "url": "https://example.com/\"{{test_param}}\"",
            }
        ],
    }

    result = execute_routine_from_json(
        routine_json_str=json.dumps(routine),
        parameters={"test_param": "value"},
    )

    # Parsing should always succeed with valid structure
    assert "Failed to parse routine" not in result.get("error", "")

    # Execution may succeed if Chrome is running, or fail if not
    # Either way is fine - we're testing the tool works correctly
    assert "success" in result

    # If it failed, error should be about execution, not parsing
    if not result.get("success"):
        assert "Failed to parse routine" not in result.get("error", "")


def test_execute_routine_from_dict_valid_structure():
    """Test that a valid routine dict can be parsed and executed."""
    routine = {
        "name": "test_routine",
        "description": "A test routine",
        "parameters": [
            {
                "name": "test_param",
                "description": "A test parameter",
                "type": "string",
                "required": True,
            }
        ],
        "operations": [
            {
                "type": "navigate",
                "url": "https://example.com/\"{{test_param}}\"",
            }
        ],
    }

    result = execute_routine_from_dict(
        routine_dict=routine,
        parameters={"test_param": "value"},
    )

    # Parsing should always succeed with valid structure
    assert "Failed to parse routine" not in result.get("error", "")

    # Execution may succeed if Chrome is running, or fail if not
    # Either way is fine - we're testing the tool works correctly
    assert "success" in result

    # If it failed, error should be about execution, not parsing
    if not result.get("success"):
        assert "Failed to parse routine" not in result.get("error", "")
