"""
web_hacker/llms/tools/guide_agent_tools.py

Tool functions for the guide agent.
"""

from typing import Any

from pydantic import ValidationError

from web_hacker.data_models.routine.routine import Routine


def validate_routine(routine_dict: dict) -> dict:
    """
    Validates a routine dictionary against the Routine schema.

    IMPORTANT: You MUST construct and pass the COMPLETE routine JSON object as the
    routine_dict argument. Do NOT call this with empty arguments {}.

    The routine_dict must be a JSON object containing:
    - "name" (string): The name of the routine
    - "description" (string): Description of what the routine does
    - "parameters" (array): Parameter definitions with name, description, type, required fields
    - "operations" (array): Operation definitions

    WORKFLOW:
    1. First construct the complete routine JSON in your response
    2. Then call this tool with that object
    3. If validation fails, read the error, fix the issues, and retry up to 3 times

    Args:
        routine_dict: The complete routine JSON object with name, description, parameters, and operations

    Returns:
        Dict with 'valid' bool and either 'message' (success) or 'error' (failure)
    """
    try:
        routine = Routine(**routine_dict)
        return {
            "valid": True,
            "message": f"Routine '{routine.name}' is valid with {len(routine.operations)} operations and {len(routine.parameters)} parameters.",
        }
    except ValidationError as e:
        return {
            "valid": False,
            "error": str(e),
        }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Unexpected error: {str(e)}",
        }


def start_routine_discovery_job_creation(
    task_description: str,
    expected_output_description: str,
    input_parameters: list[dict[str, str]] | None = None,
    filters_or_constraints: list[str] | None = None,
    target_website: str | None = None,
) -> dict[str, Any]:
    """
    Initiates the routine discovery process.

    Call this when you have gathered enough information about:
    1) What task the user wants to automate
    2) What data/output they expect
    3) What input parameters the routine should accept
    4) Any filters or constraints

    This tool requests user confirmation before executing.

    Args:
        task_description: Description of the task/routine the user wants to create
        expected_output_description: Description of what data the routine should return
        input_parameters: List of input parameters with 'name' and 'description' keys
        filters_or_constraints: Any filters or constraints the user mentioned
        target_website: Target website/URL if mentioned by user

    Returns:
        Result dict to be passed to routine discovery agent
    """
    # TODO: implement the actual handoff logic
    raise NotImplementedError("start_routine_discovery_job_creation not yet implemented")
