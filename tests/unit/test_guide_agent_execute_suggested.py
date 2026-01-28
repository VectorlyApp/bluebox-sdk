"""
Unit tests for execute_suggested_routine tool in GuideAgent.
"""

import json
from unittest.mock import Mock

from bluebox.agents.guide_agent import GuideAgent
from bluebox.data_models.llms.interaction import ChatRole
from bluebox.data_models.routine import Routine


def test_execute_suggested_routine_not_found():
    """Test that executing non-existent suggestion returns error."""
    emitted_messages = []

    def emit_callback(msg):
        emitted_messages.append(msg)

    agent = GuideAgent(
        emit_message_callable=emit_callback,
    )

    # Try to execute a suggestion that doesn't exist
    result = agent._tool_execute_suggested_routine({
        "suggested_edit_id": "nonexistent-id",
        "parameters": {"test": "value"},
    })

    assert "error" in result
    assert "not found" in result["error"]


def test_execute_suggested_routine_requires_parameters():
    """Test that parameters are required."""
    emitted_messages = []

    def emit_callback(msg):
        emitted_messages.append(msg)

    agent = GuideAgent(
        emit_message_callable=emit_callback,
    )

    # Create a valid suggestion first
    routine = Routine(
        name="test_routine",
        description="A test routine",
        parameters=[
            {
                "name": "test_param",
                "description": "A test parameter",
                "type": "string",
                "required": True,
            }
        ],
        operations=[
            {
                "type": "navigate",
                "url": "https://example.com/\"{{test_param}}\"",
            }
        ],
    )
    suggest_result = agent._tool_suggest_routine_edit({
        "routine": routine.model_dump()
    })
    edit_id = suggest_result["edit_id"]

    # Try without parameters
    try:
        agent._tool_execute_suggested_routine({
            "suggested_edit_id": edit_id,
        })
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "parameters is required" in str(e)


def test_execute_suggested_routine_valid_suggestion():
    """Test executing a valid suggested routine."""
    emitted_messages = []

    def emit_callback(msg):
        emitted_messages.append(msg)

    agent = GuideAgent(
        emit_message_callable=emit_callback,
    )

    # Create a routine
    routine = Routine(
        name="test_routine",
        description="A test routine",
        parameters=[
            {
                "name": "test_param",
                "description": "A test parameter",
                "type": "string",
                "required": True,
            }
        ],
        operations=[
            {
                "type": "navigate",
                "url": "https://example.com/\"{{test_param}}\"",
            }
        ],
    )

    # First, let's call suggest_routine_edit to create a suggestion
    suggest_result = agent._tool_suggest_routine_edit({
        "routine": routine.model_dump()
    })

    assert suggest_result["success"] is True
    edit_id = suggest_result["edit_id"]

    # Now execute the suggested routine
    exec_result = agent._tool_execute_suggested_routine({
        "suggested_edit_id": edit_id,
        "parameters": {"test_param": "value"},
    })

    # Should have success key (may be True or False depending on Chrome)
    assert "success" in exec_result

    # If it failed, should not be a parsing error
    if not exec_result.get("success"):
        assert "Failed to parse" not in exec_result.get("error", "")


def test_execute_suggested_routine_does_not_update_current():
    """Test that executing suggested routine doesn't update current routine state."""
    emitted_messages = []

    def emit_callback(msg):
        emitted_messages.append(msg)

    agent = GuideAgent(
        emit_message_callable=emit_callback,
    )

    # Set current routine
    original_routine = {
        "name": "original_routine",
        "description": "Original routine",
        "parameters": [
            {
                "name": "param1",
                "description": "Param 1",
                "type": "string",
                "required": True,
            }
        ],
        "operations": [
            {
                "type": "navigate",
                "url": "https://example.com/\"{{param1}}\"",
            }
        ],
    }

    agent.routine_state.update_current_routine(json.dumps(original_routine))

    # Create a different suggested routine
    suggested_routine = Routine(
        name="suggested_routine",
        description="Suggested routine",
        parameters=[
            {
                "name": "param2",
                "description": "Param 2",
                "type": "string",
                "required": True,
            }
        ],
        operations=[
            {
                "type": "navigate",
                "url": "https://example.com/\"{{param2}}\"",
            }
        ],
    )

    # Suggest the edit
    suggest_result = agent._tool_suggest_routine_edit({
        "routine": suggested_routine.model_dump()
    })
    edit_id = suggest_result["edit_id"]

    # Execute the suggested routine
    agent._tool_execute_suggested_routine({
        "suggested_edit_id": edit_id,
        "parameters": {"param2": "value"},
    })

    # Verify current routine is still the original
    current = json.loads(agent.routine_state.current_routine_str)
    assert current["name"] == "original_routine"
    assert current["name"] != "suggested_routine"
