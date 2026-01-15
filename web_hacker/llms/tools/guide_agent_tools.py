"""
web_hacker/llms/tools/guide_agent_tools.py

Tools and tool parameter models for the guide agent.
"""

from pydantic import BaseModel, Field


class StartRoutineDiscoveryJobCreationParams(BaseModel):
    """
    Parameters for the start_routine_discovery_job_creation tool.

    This model defines what information the LLM should extract from
    the conversation before handing off to routine discovery.
    """

    task_description: str = Field(
        ...,
        description="Description of the task/routine the user wants to create",
    )
    expected_output_description: str = Field(
        ...,
        description="Description of what data the routine should return",
    )
    input_parameters: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of input parameters with 'name' and 'description' keys",
    )
    filters_or_constraints: list[str] = Field(
        default_factory=list,
        description="Any filters or constraints the user mentioned",
    )
    target_website: str | None = Field(
        default=None,
        description="Target website/URL if mentioned by user",
    )


# Tool metadata constants
START_ROUTINE_DISCOVERY_TOOL_NAME = "start_routine_discovery_job_creation"
START_ROUTINE_DISCOVERY_TOOL_DESCRIPTION = """
Initiates the routine discovery process by passing control to the routine discovery agent.

Call this tool when you have gathered enough information about:
1. What task the user wants to automate
2. What data/output they expect from the routine
3. What input parameters the routine should accept
4. Any filters or constraints on the data

This tool does NOT execute immediately - it will request user confirmation first.
""".strip()
