"""
web_hacker/data_models/production_routine.py

Production routine data models.
"""

import re
import time
import uuid
from abc import ABC
from datetime import datetime
from enum import StrEnum
from typing import Any, Annotated, ClassVar, Literal, Union, Callable

from pydantic import BaseModel, Field, field_validator, model_validator


class ResourceBase(BaseModel, ABC):
    """
    Base class for all resources that provides a standardized ID format.
    ID format: [resourceType]_[uuidv4]
    Examples: "Project_123e4567-e89b-12d3-a456-426614174000"
    """

    # standardized resource ID in format "[resourceType]_[uuid]"
    id: str = Field(
        default_factory=lambda: f"ResourceBase_{uuid.uuid4()}",
        description="Resource ID in format [resourceType]_[uuidv4]"
    )

    created_at: int = Field(
        default_factory=lambda: int(datetime.now().timestamp()),
        description="Unix timestamp (seconds) when resource was created"
    )
    updated_at: int = Field(
        default_factory=lambda: int(datetime.now().timestamp()),
        description="Unix timestamp (seconds) when resource was last updated"
    )

    @property
    def resource_type(self) -> str:
        """
        Return the resource type name (class name) for this class.
        """
        return self.__class__.__name__

    def __init_subclass__(cls, **kwargs) -> None:
        """
        Initialize subclass by setting up the correct default_factory for the id field.
        This method is called when a class inherits from ResourceBase. It ensures
        that each subclass gets an id field with a default_factory that generates
        IDs in the format "[ClassName]_[uuid4]".
        Args:
            cls: The subclass being initialized
            **kwargs: Additional keyword arguments passed to the subclass
        """
        super().__init_subclass__(**kwargs)
        # override the default_factory for the id field to use the actual class name
        if hasattr(cls, 'model_fields') and 'id' in cls.model_fields:
            cls.model_fields['id'].default_factory = lambda: f"{cls.__name__}_{uuid.uuid4()}"


class ParameterType(StrEnum):
    """Supported parameter types for MCP tools."""
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    EMAIL = "email"
    URL = "url"
    ENUM = "enum"


class BuiltinParameter(BaseModel):
    """
    Builtin parameter model.
    """
    name: str = Field(
        ...,
        description="Builtin parameter name"
    )
    description: str = Field(
        ...,
        description="Human-readable builtin parameter description"
    )
    value_generator: Callable[[], Any] = Field(
        ...,
        description="Function to generate the builtin parameter value"
    )


BUILTIN_PARAMETERS = [
    BuiltinParameter(
        name="uuid",
        description="UUID parameter",
        value_generator=lambda: str(uuid.uuid4())
    ),
    BuiltinParameter(
        name="epoch_milliseconds",
        description="Epoch milliseconds parameter",
        value_generator=lambda: str(int(time.time() * 1000))
    ),
]


class Parameter(BaseModel):
    """
    Parameter model with comprehensive validation and type information.
    Fields:
        name (str): Parameter name (must be valid Python identifier)
        type (ParameterType): Parameter data type
        required (bool): Whether parameter is required
        description (str): Human-readable parameter description
        default (Any | None): Default value if not provided
        examples (list[Any]): Example values
        min_length (int | None): Minimum length for strings
        max_length (int | None): Maximum length for strings
        min_value (int | float | None): Minimum value for numbers
        max_value (int | float | None): Maximum value for numbers
        pattern (str | None): Regex pattern for string validation
        enum_values (list[str] | None): Allowed values for enum type
        format (str | None): Format specification (e.g., 'YYYY-MM-DD')
    """

    # reserved prefixes: names that cannot be used at the beginning of a parameter name
    RESERVED_PREFIXES: ClassVar[list[str]] = [
        "sessionStorage",
        "localStorage",
        "cookie",
        "meta",
        "windowProperty",
        "uuid",
        "epoch_milliseconds",
    ]

    name: str = Field(..., description="Parameter name (must be valid Python identifier)")
    type: ParameterType = Field(
        default=ParameterType.STRING,
        description="Parameter data type"
    )
    required: bool = Field(
        default=True,
        description="Whether parameter is required"
    )
    description: str = Field(..., description="Human-readable parameter description")
    default: Any | None = Field(
        default=None,
        description="Default value if not provided"
    )
    examples: list[Any] = Field(
        default_factory=list,
        description="Example values"
    )

    # Type-specific validation
    min_length: int | None = Field(
        default=None,
        description="Minimum length for strings"
    )
    max_length: int | None = Field(
        default=None,
        description="Maximum length for strings"
    )
    min_value: int | float | None = Field(
        default=None,
        description="Minimum value for numbers")
    max_value: int | float | None = Field(
        default=None,
        description="Maximum value for numbers")
    pattern: str | None = Field(
        default=None,
        description="Regex pattern for string validation"
    )
    enum_values: list[str] | None = Field(
        default=None,
        description="Allowed values for enum type"
    )

    # Format specifications
    format: str | None = Field(
        default=None,
        description="Format specification (e.g., 'YYYY-MM-DD')"
    )

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        """Ensure parameter name is a valid Python identifier and not reserved."""
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', v):
            raise ValueError(f"Parameter name '{v}' is not a valid Python identifier")

        # Check for reserved prefixes
        for prefix in cls.RESERVED_PREFIXES:
            if v.startswith(prefix):
                raise ValueError(
                    f"Parameter name '{v}' cannot start with '{prefix}'. "
                    f"Reserved prefixes: {cls.RESERVED_PREFIXES}"
                )

        return v

    @model_validator(mode='after')
    def validate_type_consistency(self) -> 'Parameter':
        """Validate type-specific constraints are consistent."""
        if self.type == ParameterType.ENUM and not self.enum_values:
            raise ValueError("enum_values must be provided for enum type")
        return self

    @field_validator('default')
    @classmethod
    def validate_default_type(cls, v, info):
        """Ensure default value matches parameter type."""
        if v is None:
            return v

        param_type = info.data.get('type', ParameterType.STRING)
        if param_type == ParameterType.INTEGER and not isinstance(v, int):
            try:
                return int(v)
            except (ValueError, TypeError):
                raise ValueError(f"Default value {v} cannot be converted to integer")
        elif param_type == ParameterType.NUMBER and not isinstance(v, (int, float)):
            try:
                return float(v)
            except (ValueError, TypeError):
                raise ValueError(f"Default value {v} cannot be converted to number")
        elif param_type == ParameterType.BOOLEAN and not isinstance(v, bool):
            if isinstance(v, str):
                lower_v = v.lower()
                if lower_v in ('true', '1', 'yes', 'on'):
                    return True
                elif lower_v in ('false', '0', 'no', 'off'):
                    return False
                else:
                    raise ValueError(f"Default value {v} is not a valid boolean value")
            raise ValueError(f"Default value {v} cannot be converted to boolean")
        return v

    @field_validator('examples')
    @classmethod
    def validate_examples_type(cls, v, info):
        """Ensure examples match parameter type."""
        if not v:
            return v

        param_type = info.data.get('type', ParameterType.STRING)
        validated_examples = []

        for example in v:
            if param_type == ParameterType.INTEGER:
                try:
                    validated_examples.append(int(example))
                except (ValueError, TypeError):
                    raise ValueError(f"Example {example} cannot be converted to integer")
            elif param_type == ParameterType.NUMBER:
                try:
                    validated_examples.append(float(example))
                except (ValueError, TypeError):
                    raise ValueError(f"Example {example} cannot be converted to number")
            elif param_type == ParameterType.BOOLEAN:
                if isinstance(example, str):
                    lower_example = example.lower()
                    if lower_example in ('true', '1', 'yes', 'on'):
                        validated_examples.append(True)
                    elif lower_example in ('false', '0', 'no', 'off'):
                        validated_examples.append(False)
                    else:
                        raise ValueError(f"Example {example} is not a valid boolean value")
                else:
                    validated_examples.append(bool(example))
            else:
                validated_examples.append(str(example))

        return validated_examples


class HTTPMethod(StrEnum):
    """
    Supported HTTP methods for API endpoints.
    """
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class CREDENTIALS(StrEnum):
    """
    Supported credentials modes for API requests.
    """
    SAME_ORIGIN = "same-origin"
    INCLUDE = "include"
    OMIT = "omit"


class Endpoint(BaseModel):
    """
    Endpoint model with comprehensive parameter validation.
    """
    url: str = Field(..., description="Target API URL with parameter placeholders")
    description: str | None = Field(default=None, description="Human-readable description the fetch request")
    method: HTTPMethod = Field(..., description="HTTP method")
    headers: dict[str, Any] = Field(
        default={},
        description="Dictionary of headers, with parameter placeholders for later interpolation"
    )
    body: dict[str, Any] = Field(
        default={},
        description="Dictionary of request body, with parameter placeholders for later interpolation"
    )
    credentials: CREDENTIALS = Field(
        default=CREDENTIALS.SAME_ORIGIN,
        description="Credentials mode"
    )


class RoutineOperationTypes(StrEnum):
    """
    Browser operation types for running routines.
    """
    NAVIGATE = "navigate"
    SLEEP = "sleep"
    FETCH = "fetch"
    RETURN = "return"


class RoutineOperation(BaseModel):
    """
    Base class for routine operations.
    
    Args:
        type (RoutineOperationTypes): The type of operation.
    
    Returns:
        RoutineOperation: The interpolated operation.
    """
    type: RoutineOperationTypes


class RoutineNavigateOperation(RoutineOperation):
    """
    Navigate operation for routine.
    
    Args:
        type (Literal[RoutineOperationTypes.NAVIGATE]): The type of operation.
        url (str): The URL to navigate to.
    
    Returns:
        RoutineNavigateOperation: The interpolated operation.
    """
    type: Literal[RoutineOperationTypes.NAVIGATE] = RoutineOperationTypes.NAVIGATE
    url: str


class RoutineSleepOperation(RoutineOperation):
    """
    Sleep operation for routine.
    
    Args:
        type (Literal[RoutineOperationTypes.SLEEP]): The type of operation.
        timeout_seconds (float): The number of seconds to sleep.
    
    Returns:
        RoutineSleepOperation: The interpolated operation.
    """
    type: Literal[RoutineOperationTypes.SLEEP] = RoutineOperationTypes.SLEEP
    timeout_seconds: float


class RoutineFetchOperation(RoutineOperation):
    """
    Fetch operation for routine.
    
    Args:
        type (Literal[RoutineOperationTypes.FETCH]): The type of operation.
        endpoint (Endpoint): The endpoint to fetch.
        session_storage_key (str): The session storage key to save the fetch response to.
    
    Returns:
        RoutineFetchOperation: The interpolated operation.
    """
    type: Literal[RoutineOperationTypes.FETCH] = RoutineOperationTypes.FETCH
    endpoint: Endpoint
    session_storage_key: str


class RoutineReturnOperation(RoutineOperation):
    """
    Return operation for routine.
    
    Args:
        type (Literal[RoutineOperationTypes.RETURN]): The type of operation.
        session_storage_key (str): The session storage key to return.
    
    Returns:
        RoutineReturnOperation: The interpolated operation.
    """
    type: Literal[RoutineOperationTypes.RETURN] = RoutineOperationTypes.RETURN
    session_storage_key: str

    
# Routine operation union _________________________________________________________________________

RoutineOperationUnion = Annotated[
    Union[
        RoutineNavigateOperation,
        RoutineSleepOperation,
        RoutineFetchOperation,
        RoutineReturnOperation,
    ],
    Field(discriminator="type"),
]


# Routine models __________________________________________________________________________________

class RoutineStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"  # user wants to hide them
    DELETED = "deleted"    # soft deletes
    DRAFT = "draft"        # work in progress


class Routine(ResourceBase):
    """
    Routine model with comprehensive parameter validation.
    """
    # routine details
    name: str
    description: str
    operations: list[RoutineOperationUnion]
    incognito: bool = Field(
        default=True,
        description="Whether to use incognito mode when executing the routine"
    )
    parameters: list[Parameter] = Field(
        default_factory=list,
        description="List of parameters"
    )

    def fix_placeholders(self) -> None:
        """
        Fix placeholders in the routine operations.
        Ensures that string parameters are wrapped in escaped quotes and other parameters are not.
        """
        # Map parameter names to their types
        param_types = {param.name: param.type for param in self.parameters}
        
        # Define which types are considered "strings" that need quoting
        string_types = {
            ParameterType.STRING, 
            ParameterType.DATE, 
            ParameterType.DATETIME, 
            ParameterType.EMAIL, 
            ParameterType.URL, 
            ParameterType.ENUM
        }
        
        def should_be_quoted(param_name: str) -> bool:
            """Determine if a parameter should be quoted based on its type."""
            # Check builtins
            if param_name == "uuid":
                return True
            if param_name == "epoch_milliseconds":
                return False # treat as number
            
            # Check storage/application parameters (assume string)
            if ":" in param_name:
                return True
                
            # Check defined parameters
            if param_name in param_types:
                return param_types[param_name] in string_types
            
            # Default to string if unknown (safer for JSON usually)
            return True

        def fix_string(text: str) -> str:
            """
            Fix placeholders in a string.
            Finds {{param}} and ensures it is quoted if needed.
            """
            # Regex to find {{param}} placeholders
            # Capture the parameter name inside
            pattern = r'{{([^}]+)}}'
            
            def replacer(match):
                full_match = match.group(0)
                param_name = match.group(1).strip()
                
                # Check if it needs quoting
                if should_be_quoted(param_name):
                    # Check if already quoted with escaped quotes in the source text
                    # We look at the text around the match using the match object's indices
                    start, end = match.span()
                    
                    # check for preceding \"
                    preceded_by_quote = False
                    if start >= 2 and text[start-2:start] == '\\"':
                        preceded_by_quote = True
                    elif start >= 1 and text[start-1] == '"' and (start < 2 or text[start-2] != '\\'):
                         preceded_by_quote = True
                         
                    # check for following \"
                    followed_by_quote = False
                    if end <= len(text) - 2 and text[end:end+2] == '\\"':
                        followed_by_quote = True
                    elif end < len(text) and text[end] == '"':
                        followed_by_quote = True
                        
                    if preceded_by_quote and followed_by_quote:
                        return full_match # already quoted
                    
                    # It needs quotes and doesn't have them. Add quotes.
                    return f'"{full_match}"'
                else:
                    # It does NOT need quotes (e.g. integer).
                    # Return as is (or strip quotes if we wanted to be aggressive, but prompt only asked to force escaped quotes for strings)
                    return full_match

            return re.sub(pattern, replacer, text)

        def fix_value(value: Any) -> Any:
            """Recursively fix values in dicts/lists."""
            if isinstance(value, str):
                return fix_string(value)
            elif isinstance(value, dict):
                return {k: fix_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [fix_value(v) for v in value]
            return value

        # Iterate over operations and fix headers/body/url
        for op in self.operations:
            if op.type == RoutineOperationTypes.NAVIGATE:
                # Fix URL
                op.url = fix_string(op.url)
                
            elif op.type == RoutineOperationTypes.FETCH:
                # Fix URL
                op.endpoint.url = fix_string(op.endpoint.url)
                
                # Fix Headers
                if op.endpoint.headers:
                    op.endpoint.headers = fix_value(op.endpoint.headers)
                
                # Fix Body
                if op.endpoint.body:
                    op.endpoint.body = fix_value(op.endpoint.body)
                    
        return

    @model_validator(mode='after')
    def validate_parameter_usage(self) -> 'Routine':
        """
        Pydantic model validator to ensure all defined parameters are used in the routine
        and no undefined parameters are used.
        Raises ValueError if unused parameters are found or undefined parameters are used.
        """
        # Check 0: Ensure name and description fields don't contain parameter placeholders
        # These are metadata fields and should not have interpolation patterns
        param_pattern = r'\{\{([^}]*)\}\}'
        # check in Routine.name
        name_matches = re.findall(param_pattern, self.name)
        if name_matches:
            raise ValueError(
                f"Parameter placeholders found in routine name '{self.name}': {name_matches}. "
                "The 'name' field is a metadata field and should not contain parameter placeholders like {{param}}."
            )
        # check in Routine.description
        description_matches = re.findall(param_pattern, self.description)
        if description_matches:
            raise ValueError(
                f"Parameter placeholders found in routine description: {description_matches}. "
                "The 'description' field is a metadata field and should not contain parameter placeholders like {{param}}."
            )

        # list of builtin parameter names
        builtin_parameter_names = [builtin_parameter.name for builtin_parameter in BUILTIN_PARAMETERS]

        # Convert the entire routine to JSON string for searching
        routine_json = self.model_dump_json()

        # Extract all parameter names
        defined_parameters = {param.name for param in self.parameters}

        # Find all parameter usages in the JSON: {{*}}
        # Match placeholders anywhere: {{param}}
        # This matches parameters whether they're standalone quoted values or embedded in strings
        param_pattern = r'\{\{([^}]*)\}\}'
        matches = re.findall(param_pattern, routine_json)

        # track used parameters
        used_parameters = set()

        # iterate over all parameter usages
        for match in matches:
            # clean the match (already extracted the content between braces)
            match = match.strip()

            # if the parameter name contains a colon, it is an application parameter
            if ":" in match:
                kind, path = [p.strip() for p in match.split(":", 1)]
                assert kind in ["sessionStorage", "localStorage", "cookie", "meta", "windowProperty"], f"Invalid prefix in parameter name: {kind}"
                assert path, f"Path is required for sessionStorage, localStorage, cookie, meta, and windowProperty: {kind}:{path}"
                continue
            # if the parameter name is a builtin parameter, add it to the used parameters
            elif match in builtin_parameter_names:
                continue
            # if the parameter name is a regular parameter, add it to the used parameters
            else:
                used_parameters.add(match)

        # Check 1: All defined parameters must be used
        unused_parameters = defined_parameters - used_parameters
        if unused_parameters:
            raise ValueError(
                f"Unused parameters found in routine '{self.name}': {list(unused_parameters)}. "
                "All defined parameters must be used somewhere in the routine operations."
            )

        # Check 2: No undefined parameters should be used
        undefined_parameters = used_parameters - defined_parameters
        if undefined_parameters:
            raise ValueError(
                f"Undefined parameters found in routine '{self.name}': {list(undefined_parameters)}. "
                "All parameters used in the routine must be defined in parameters."
            )

        return self
