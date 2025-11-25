
"""
web_hacker/data_models/ui_elements.py

UI element data models for robust element identification and replay.
"""

from enum import StrEnum
from typing import Dict, List
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


class IdentifierType(StrEnum):
    CSS = "css"
    XPATH = "xpath"
    TEXT = "text"          # e.g. "button with label X"
    ROLE = "role"          # e.g. role+name/aria-label
    NAME = "name"          # input[name="..."]
    ID = "id"              # #id


# Default priority mapping for selector types (lower = higher priority)
DEFAULT_IDENTIFIER_PRIORITIES: Dict[IdentifierType, int] = {
    IdentifierType.ID: 10,           # Highest priority - IDs are unique
    IdentifierType.NAME: 20,         # Form controls by name are very stable
    IdentifierType.CSS: 30,          # CSS Identifiers (with stable attributes)
    IdentifierType.ROLE: 40,         # ARIA roles + labels
    IdentifierType.TEXT: 50,         # Text-based matching
    IdentifierType.XPATH: 80,        # XPath (often brittle, last resort)
}


class Identifier(BaseModel):
    """
    A single way to locate an element.
    `value` is the raw string (CSS, XPath, etc.)
    `type` tells the executor how to interpret it.
    `priority` controls which selector to try first (lower = higher priority).
    If not specified, uses the default priority for the selector type.
    """
    type: IdentifierType
    value: str
    priority: int | None = Field(
        default=None,
        description="Priority for this selector (lower = higher priority). If None, uses default for selector type.",
    )

    description: str | None = Field(
        default=None,
        description="Human readable note (e.g. 'primary stable selector').",
    )
    
    def get_priority(self) -> int:
        """Get the effective priority, using default if not set."""
        if self.priority is not None:
            return self.priority
        return DEFAULT_IDENTIFIER_PRIORITIES.get(self.type, 100)


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class UiElement(BaseModel):
    """
    Unified description of a UI element sufficient for robust replay.

    - Raw DOM data (tag, attributes, text)
    - Multiple Identifiers (CSS, XPath, text-based, etc.)
    - Context (URL, frame)
    """
    # Context
    url: str | None = Field(
        default=None,
        description="Page URL where this element was observed.",
    )

    # Core DOM identity
    tag_name: str
    id: str | None = None
    name: str | None = None
    class_names: List[str] | None = Field(default=None, description="List of CSS class names.")

    # Common attributes
    type_attr: str | None = Field(default=None, description="Input type, button type, etc.")
    role: str | None = None
    aria_label: str | None = None
    placeholder: str | None = None
    title: str | None = None
    href: str | None = None
    src: str | None = None
    value: str | None = None

    # Full attribute map for anything else (data-*, etc.)
    attributes: Dict[str, str] | None = Field(
        default=None,
        description="All raw attributes from the DOM element.",
    )

    # Content
    text: str | None = Field(
        default=None,
        description="Trimmed inner text (useful for text-based Identifiers).",
    )

    # Geometry
    bounding_box: BoundingBox | None = None

    # Locators (multiple ways to find it again)
    Identifiers: List[Identifier] | None = Field(
        default=None,
        description="Ordered list of Identifiers to try when locating this element.",
    )

    # Convenience accessors for most common Identifiers
    css_path: str | None = None    # from getElementPath
    xpath: str | None = None       # full xpath

    def build_default_Identifiers(self) -> None:
        """
        Populate `Identifiers` from known fields if empty.
        Call this once after constructing from raw DOM.
        """
        if self.Identifiers is None:
            self.Identifiers = []
        elif self.Identifiers:
            return
        
        # Ensure attributes is a dict for easier access
        if self.attributes is None:
            self.attributes = {}
        
        # Ensure class_names is a list
        if self.class_names is None:
            self.class_names = []

        # Highest priority: ID (uses default priority from DEFAULT_IDENTIFIER_PRIORITIES)
        if self.id:
            self.Identifiers.append(
                Identifier(
                    type=IdentifierType.ID,
                    value=self.id,
                    priority=DEFAULT_IDENTIFIER_PRIORITIES[IdentifierType.ID],
                    description="Locate by DOM id",
                )
            )

        # Name attribute - if it exists, use it
        if self.name:
            self.Identifiers.append(
                Identifier(
                    type=IdentifierType.NAME,
                    value=self.name,
                    priority=DEFAULT_IDENTIFIER_PRIORITIES[IdentifierType.NAME],
                    description="Locate by name attribute",
                )
            )

        # Placeholder attribute - if it exists, use it
        if self.placeholder:
            self.Identifiers.append(
                Identifier(
                    type=IdentifierType.CSS,
                    value=f'{self.tag_name.lower()}[placeholder="{self.placeholder}"]',
                    priority=DEFAULT_IDENTIFIER_PRIORITIES[IdentifierType.CSS],
                    description="Locate by placeholder",
                )
            )

        # Role - if it exists, use it
        if self.role:
            self.Identifiers.append(
                Identifier(
                    type=IdentifierType.ROLE,
                    value=self.role,
                    priority=DEFAULT_IDENTIFIER_PRIORITIES[IdentifierType.ROLE],
                    description=f"Locate by role={self.role}",
                )
            )

        # Text - if it exists, use it
        if self.text:
            snippet = self.text.strip()
            if snippet:
                self.Identifiers.append(
                    Identifier(
                        type=IdentifierType.TEXT,
                        value=snippet,
                        priority=DEFAULT_IDENTIFIER_PRIORITIES[IdentifierType.TEXT],
                        description="Locate by text content",
                    )
                )

        # Direct CSS and XPath if we have them
        if self.css_path:
            self.Identifiers.append(
                Identifier(
                    type=IdentifierType.CSS,
                    value=self.css_path,
                    priority=DEFAULT_IDENTIFIER_PRIORITIES[IdentifierType.CSS],
                    description="Recorded CSS path",
                )
            )
        if self.xpath:
            self.Identifiers.append(
                Identifier(
                    type=IdentifierType.XPATH,
                    value=self.xpath,
                    priority=DEFAULT_IDENTIFIER_PRIORITIES[IdentifierType.XPATH],
                    description="Full XPath (last resort)",
                )
            )

        # Fallback: first stable-looking class
        if not self.Identifiers and self.class_names:
            
            # Filter out classes that are likely to be unstable
            stable_classes = [
                c for c in self.class_names
                if not c.startswith("sc-")
                and not c.startswith("css-")
                and (not c.isalnum() or len(c) < 10)
            ]
            
            # If there are stable classes, use the first one
            if stable_classes:
                cls = stable_classes[0]
                self.Identifiers.append(
                    Identifier(
                        type=IdentifierType.CSS,
                        value=f".{cls}",
                        priority=DEFAULT_IDENTIFIER_PRIORITIES[IdentifierType.CSS],
                        description="Fallback by single stable-looking class",
                    )
                )
                
        if not self.Identifiers: 
            logger.warning("No Identifiers found for element %s", self.model_dump_json())
                