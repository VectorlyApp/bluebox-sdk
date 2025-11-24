"""
web_hacker/data_models/ui_interactions.py

UI interaction data models for tracking user interactions with web elements.
"""

from enum import StrEnum
from typing import Optional
from pydantic import BaseModel, Field

from web_hacker.data_models.ui_elements import UiElement


class InteractionType(StrEnum):
    """Types of UI interactions that can be recorded."""
    # Mouse interactions
    MOUSE_CLICK = "mouse_click"
    MOUSE_DOWN = "mouse_down"
    MOUSE_UP = "mouse_up"
    MOUSE_DOUBLE_CLICK = "mouse_double_click"
    MOUSE_CONTEXT_MENU = "mouse_context_menu"
    MOUSE_OVER = "mouse_over"
    
    # Keyboard interactions
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    KEY_PRESS = "key_press"
    
    # Form interactions
    INPUT = "input"
    CHANGE = "change"
    
    # Focus interactions
    FOCUS = "focus"
    BLUR = "blur"


class EventData(BaseModel):
    """
    Raw event data from the browser event object.
    Contains all the details about the specific event that occurred.
    """
    # Event type (e.g., "click", "keydown", "input")
    type: str
    
    # Mouse button (0=left, 1=middle, 2=right, null for non-mouse events)
    button: Optional[int] = None
    
    # Keyboard key information
    key: Optional[str] = Field(
        default=None,
        description="The key value of the key pressed (e.g., 'a', 'Enter', 'Shift')."
    )
    code: Optional[str] = Field(
        default=None,
        description="The physical key code (e.g., 'KeyA', 'Enter', 'ShiftLeft')."
    )
    keyCode: Optional[int] = Field(
        default=None,
        description="Deprecated key code (numeric)."
    )
    which: Optional[int] = Field(
        default=None,
        description="Deprecated key code (numeric)."
    )
    
    # Modifier keys
    ctrlKey: bool = False
    shiftKey: bool = False
    altKey: bool = False
    metaKey: bool = False
    
    # Mouse coordinates (null for non-mouse events)
    clientX: Optional[int] = Field(
        default=None,
        description="X coordinate relative to viewport."
    )
    clientY: Optional[int] = Field(
        default=None,
        description="Y coordinate relative to viewport."
    )
    pageX: Optional[int] = Field(
        default=None,
        description="X coordinate relative to page (includes scroll)."
    )
    pageY: Optional[int] = Field(
        default=None,
        description="Y coordinate relative to page (includes scroll)."
    )


class UiInteraction(BaseModel):
    """
    Complete UI interaction record.
    
    Represents a single user interaction with a web element, including:
    - What type of interaction occurred
    - When it occurred (client and server timestamps)
    - What element was interacted with (UiElement)
    - Raw event details (EventData)
    - Page context (URL)
    """
    # Interaction type
    type: InteractionType
    
    # Timestamp
    timestamp: int = Field(
        description="Client-side timestamp (milliseconds since epoch) when the interaction occurred."
    )
    
    # Event details
    event: EventData | None = Field(
        default=None,
        description="Raw event details from the browser event object."
    )
    
    # Element that was interacted with
    element: UiElement
    
    # Page context
    url: str = Field(
        description="URL of the page where the interaction occurred."
    )

