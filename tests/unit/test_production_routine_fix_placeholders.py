"""
tests/unit/test_production_routine_fix_placeholders.py

Unit tests for fix_placeholders method in Routine class.
"""

from pathlib import Path

import pytest

from web_hacker.utils.data_utils import load_data
from web_hacker.data_models.production_routine import (
    Routine,
    Parameter,
    ParameterType,
    RoutineNavigateOperation,
    RoutineFetchOperation,
    Endpoint,
    HTTPMethod,
    CREDENTIALS,
)


def _make_basic_routine(
    parameters: list[Parameter],
    operations: list,
    name: str = "test_routine",
    description: str = "Test routine",
) -> Routine:
    """Helper to create a basic routine for testing."""
    return Routine(
        name=name,
        description=description,
        parameters=parameters,
        operations=operations,
    )


def _make_fetch_operation(
    url: str = "https://api.example.com/endpoint",
    headers: dict | None = None,
    body: dict | None = None,
    session_storage_key: str = "result",
) -> RoutineFetchOperation:
    """Helper to create a fetch operation."""
    return RoutineFetchOperation(
        endpoint=Endpoint(
            url=url,
            method=HTTPMethod.POST,
            headers=headers or {},
            body=body or {},
            credentials=CREDENTIALS.INCLUDE,
        ),
        session_storage_key=session_storage_key,
    )


class TestFixPlaceholders:
    """Tests for Routine.fix_placeholders method."""
    
    def test_fix_placeholders_from_json(self, input_data_dir: Path) -> None:
        """
        Test that fix_placeholders correctly adds escaped quotes to string parameters
        and leaves other parameters as is.
        """
        # Load input routine
        input_path = input_data_dir / "production_routine" / "fix_placeholders_test.json"
        expected_path = input_data_dir.parent / "expected_output" / "production_routine" / "fix_placeholders_result.json"
        
        # Ensure output dir exists
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load input routine
        routine_data = load_data(input_path)
        
        # Create Routine object
        routine = Routine(**routine_data)
        
        # Apply fix
        routine.fix_placeholders()
        
        # Load expected output
        expected_data = load_data(expected_path)
        
        # Convert fixed routine to dict using JSON mode (serializes enums to strings)
        result_data = routine.model_dump(mode='json', exclude={"id", "created_at", "updated_at"})
        
        # Compare operations (the main thing we're testing)
        assert result_data["operations"] == expected_data["operations"], \
            f"Operations mismatch. Got: {result_data['operations']}, Expected: {expected_data['operations']}"
        
        # Parameters should be unchanged (normalize by removing None/empty values and default required=True)
        result_params = []
        for param in result_data["parameters"]:
            normalized = {k: v for k, v in param.items() 
                         if v is not None and v != [] and not (k == "required" and v is True)}
            result_params.append(normalized)
        
        expected_params = []
        for param in expected_data["parameters"]:
            normalized = {k: v for k, v in param.items() 
                         if v is not None and v != [] and not (k == "required" and v is True)}
            expected_params.append(normalized)
        
        assert result_params == expected_params
    
    def test_fix_placeholders_string_params_in_url(self) -> None:
        """String parameters in URLs should get escaped quotes."""
        params = [
            Parameter(name="user_id", type=ParameterType.STRING, description="User ID")
        ]
        ops = [
            RoutineNavigateOperation(url="https://example.com/users/{{user_id}}/profile")
        ]
        routine = _make_basic_routine(parameters=params, operations=ops)
        
        routine.fix_placeholders()
        
        # URL should have escaped quotes around the placeholder
        assert routine.operations[0].url == 'https://example.com/users/"{{user_id}}"/profile'
    
    def test_fix_placeholders_string_params_in_headers(self) -> None:
        """String parameters in headers should get escaped quotes."""
        params = [
            Parameter(name="api_key", type=ParameterType.STRING, description="API key")
        ]
        ops = [
            _make_fetch_operation(
                headers={"Authorization": "{{api_key}}"}
            )
        ]
        routine = _make_basic_routine(parameters=params, operations=ops)
        
        routine.fix_placeholders()
        
        # Header value should have escaped quotes
        assert routine.operations[0].endpoint.headers["Authorization"] == '"{{api_key}}"'
    
    def test_fix_placeholders_integer_params_not_quoted(self) -> None:
        """Integer parameters should NOT get escaped quotes."""
        params = [
            Parameter(name="user_age", type=ParameterType.INTEGER, description="User age")
        ]
        ops = [
            _make_fetch_operation(
                headers={"X-Age": "{{user_age}}"}
            )
        ]
        routine = _make_basic_routine(parameters=params, operations=ops)
        
        routine.fix_placeholders()
        
        # Integer parameter should remain unquoted
        assert routine.operations[0].endpoint.headers["X-Age"] == "{{user_age}}"
    
    def test_fix_placeholders_already_quoted_preserved(self) -> None:
        """Already quoted placeholders should be preserved."""
        params = [
            Parameter(name="user_name", type=ParameterType.STRING, description="User name")
        ]
        ops = [
            _make_fetch_operation(
                headers={"X-Name": '"{{user_name}}"'}
            )
        ]
        routine = _make_basic_routine(parameters=params, operations=ops)
        
        routine.fix_placeholders()
        
        # Already quoted placeholder should remain unchanged
        assert routine.operations[0].endpoint.headers["X-Name"] == '"{{user_name}}"'
    
    def test_fix_placeholders_session_storage_quoted(self) -> None:
        """sessionStorage parameters should get escaped quotes."""
        ops = [
            _make_fetch_operation(
                headers={"X-Session": "{{sessionStorage:session.id}}"}
            )
        ]
        routine = _make_basic_routine(parameters=[], operations=ops)
        
        routine.fix_placeholders()
        
        # sessionStorage parameter should be quoted
        assert routine.operations[0].endpoint.headers["X-Session"] == '"{{sessionStorage:session.id}}"'
    
    def test_fix_placeholders_nested_body(self) -> None:
        """Placeholders in nested body structures should be fixed."""
        params = [
            Parameter(name="user_name", type=ParameterType.STRING, description="User name"),
            Parameter(name="user_age", type=ParameterType.INTEGER, description="User age")
        ]
        ops = [
            _make_fetch_operation(
                body={
                    "user": {
                        "name": "{{user_name}}",
                        "age": "{{user_age}}",
                        "meta": {
                            "role": "{{sessionStorage:user.role}}"
                        }
                    }
                }
            )
        ]
        routine = _make_basic_routine(parameters=params, operations=ops)
        
        routine.fix_placeholders()
        
        # String parameter should be quoted
        assert routine.operations[0].endpoint.body["user"]["name"] == '"{{user_name}}"'
        
        # Integer parameter should remain unquoted
        assert routine.operations[0].endpoint.body["user"]["age"] == "{{user_age}}"
        
        # sessionStorage should be quoted
        assert routine.operations[0].endpoint.body["user"]["meta"]["role"] == '"{{sessionStorage:user.role}}"'
    
    def test_fix_placeholders_enum_type_quoted(self) -> None:
        """Enum type parameters should be treated as strings and quoted."""
        params = [
            Parameter(
                name="status",
                type=ParameterType.ENUM,
                enum_values=["active", "inactive"],
                description="Status"
            )
        ]
        ops = [
            _make_fetch_operation(
                body={"status": "{{status}}"}
            )
        ]
        routine = _make_basic_routine(parameters=params, operations=ops)
        
        routine.fix_placeholders()
        
        # Enum parameter should be quoted (treated as string)
        assert routine.operations[0].endpoint.body["status"] == '"{{status}}"'
