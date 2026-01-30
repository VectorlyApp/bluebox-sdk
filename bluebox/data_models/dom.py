"""
bluebox/data_models/dom.py

Data models for DOM snapshot events.
"""

from typing import Any

from pydantic import Field

from bluebox.data_models.cdp import BaseCDPEvent


class DOMSnapshotEvent(BaseCDPEvent):
    """
    Model for DOM snapshot events.
    Captures the full DOM tree structure using CDP DOMSnapshot.captureSnapshot.
    """
    url: str = Field(
        ...,
        description="The URL of the page when the snapshot was captured",
    )
    title: str | None = Field(
        default=None,
        description="The page title when the snapshot was captured",
    )
    documents: list[dict[str, Any]] = Field(
        ...,
        description="Array of document snapshots (main frame + iframes). "
                    "Each contains nodes, layout, textBoxes arrays with indices into strings.",
    )
    strings: list[str] = Field(
        ...,
        description="String table - node names, values, and attributes are indices into this array.",
    )
    computed_styles: list[str] = Field(
        default_factory=list,
        description="List of CSS property names that were captured for computed styles.",
    )
