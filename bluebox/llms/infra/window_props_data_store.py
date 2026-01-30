"""
bluebox/llms/infra/window_props_data_store.py

Data store for JavaScript window property snapshots captured via CDP.

Parses window properties event JSONL files and provides structured access
to JS runtime state at different points during page lifecycle.
"""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from bluebox.utils.logger import get_logger


logger = get_logger(name=__name__)


class ChangeType(StrEnum):
    """Types of property changes."""
    ADDED = "added"
    CHANGED = "changed"
    REMOVED = "removed"


@dataclass
class PropertyChange:
    """Represents a single property change."""
    path: str  # Dot-notation path (e.g., "___grecaptcha_cfg.clients.0.id")
    value: Any
    change_type: ChangeType


@dataclass
class WindowSnapshot:
    """Represents a snapshot of window properties at a point in time."""
    timestamp: float
    url: str
    changes: list[PropertyChange]
    total_keys: int

    def get_property(self, path: str) -> Any | None:
        """Get a property value by path from this snapshot's changes."""
        for change in self.changes:
            if change.path == path:
                return change.value
        return None

    def has_property(self, path: str) -> bool:
        """Check if a property exists in this snapshot's changes."""
        return any(c.path == path for c in self.changes)


@dataclass
class WindowPropsStats:
    """Summary statistics for window properties data."""
    total_snapshots: int = 0
    total_changes: int = 0
    unique_urls: int = 0
    unique_property_paths: int = 0

    # Top-level namespaces detected (e.g., "___grecaptcha_cfg", "chrome", etc.)
    top_level_namespaces: list[str] = field(default_factory=list)

    def to_summary(self) -> str:
        """Generate a human-readable summary."""
        namespaces_str = ", ".join(self.top_level_namespaces[:10])
        if len(self.top_level_namespaces) > 10:
            namespaces_str += f" ... (+{len(self.top_level_namespaces) - 10} more)"

        return (
            f"Window Properties Summary:\n"
            f"  Total Snapshots: {self.total_snapshots}\n"
            f"  Total Changes: {self.total_changes}\n"
            f"  Unique URLs: {self.unique_urls}\n"
            f"  Unique Property Paths: {self.unique_property_paths}\n"
            f"  Top-level Namespaces: {namespaces_str}"
        )


class WindowPropsDataStore:
    """
    Data store for JavaScript window property analysis.

    Parses window properties event JSONL files captured via CDP and provides
    structured access to JS runtime state captured at different page states.

    Usage:
        store = WindowPropsDataStore("/path/to/window_properties/events.jsonl")
        print(store.stats.to_summary())

        # Get current property values
        props = store.get_current_properties()
        print(props.get("___grecaptcha_cfg.pid"))

        # Search for values
        matches = store.search_for_value("sitekey")

        # Get snapshots for a specific URL
        snapshots = store.get_snapshots_by_url("https://example.com/page")
    """

    # Common browser/framework properties to filter out in searches
    NOISE_PREFIXES = (
        "on",  # Event handlers (onclick, onload, etc.)
        "GPU",  # GPU constants
        "Atomics",
        "CSS",
        "Temporal",
        "WebAssembly",
    )

    def __init__(self, jsonl_path: str | Path) -> None:
        """
        Initialize the window properties data store.

        Args:
            jsonl_path: Path to the window properties events JSONL file.
        """
        self._path = Path(jsonl_path)
        if not self._path.exists():
            raise FileNotFoundError(f"Window properties file not found: {jsonl_path}")

        # All snapshots
        self._snapshots: list[WindowSnapshot] = []

        # Current property state (latest values)
        self._current_properties: dict[str, Any] = {}

        # Tracking
        self._urls: set[str] = set()
        self._property_paths: set[str] = set()
        self._top_level_namespaces: set[str] = set()

        # Parse the file
        self._parse_jsonl()

        logger.debug(
            "Loaded WindowPropsDataStore: %d snapshots, %d unique paths, %d urls",
            len(self._snapshots),
            len(self._property_paths),
            len(self._urls),
        )

    def _parse_jsonl(self) -> None:
        """Parse the JSONL file and build property state."""
        with open(self._path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    self._process_event(event)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse window properties event line")
                    continue

    def _process_event(self, event: dict[str, Any]) -> None:
        """Process a single window properties snapshot event."""
        timestamp = event.get("timestamp", 0.0)
        url = event.get("url", "")
        changes_data = event.get("changes", [])
        total_keys = event.get("total_keys", 0)

        if url:
            self._urls.add(url)

        changes: list[PropertyChange] = []
        for change_data in changes_data:
            path = change_data.get("path", "")
            value = change_data.get("value")
            change_type_str = change_data.get("change_type", "added")

            try:
                change_type = ChangeType(change_type_str)
            except ValueError:
                change_type = ChangeType.ADDED

            change = PropertyChange(path=path, value=value, change_type=change_type)
            changes.append(change)

            # Track property paths and update current state
            if path:
                self._property_paths.add(path)

                # Extract top-level namespace
                top_level = path.split(".")[0]
                if top_level and not top_level.startswith("on"):  # Skip event handlers
                    self._top_level_namespaces.add(top_level)

                # Update current properties
                if change_type == ChangeType.REMOVED:
                    self._current_properties.pop(path, None)
                else:
                    self._current_properties[path] = value

        snapshot = WindowSnapshot(
            timestamp=timestamp,
            url=url,
            changes=changes,
            total_keys=total_keys,
        )
        self._snapshots.append(snapshot)

    @property
    def stats(self) -> WindowPropsStats:
        """Get summary statistics for the window properties data."""
        return WindowPropsStats(
            total_snapshots=len(self._snapshots),
            total_changes=sum(len(s.changes) for s in self._snapshots),
            unique_urls=len(self._urls),
            unique_property_paths=len(self._property_paths),
            top_level_namespaces=sorted(self._top_level_namespaces),
        )

    @property
    def snapshots(self) -> list[WindowSnapshot]:
        """Get all snapshots."""
        return self._snapshots.copy()

    @property
    def urls(self) -> list[str]:
        """Get all unique URLs."""
        return sorted(self._urls)

    @property
    def property_paths(self) -> list[str]:
        """Get all unique property paths."""
        return sorted(self._property_paths)

    def get_current_properties(self) -> dict[str, Any]:
        """
        Get the current (latest) state of all properties.

        Returns:
            Dict of property path -> value.
        """
        return self._current_properties.copy()

    def get_property(self, path: str) -> Any | None:
        """
        Get the current value of a specific property.

        Args:
            path: Dot-notation path (e.g., "___grecaptcha_cfg.pid").

        Returns:
            The property value, or None if not found.
        """
        return self._current_properties.get(path)

    def get_properties_by_prefix(self, prefix: str) -> dict[str, Any]:
        """
        Get all properties matching a prefix.

        Args:
            prefix: The path prefix to match (e.g., "___grecaptcha_cfg").

        Returns:
            Dict of matching property path -> value.
        """
        return {
            path: value
            for path, value in self._current_properties.items()
            if path.startswith(prefix)
        }

    def get_snapshots_by_url(self, url: str) -> list[WindowSnapshot]:
        """
        Get all snapshots for a specific URL.

        Args:
            url: The URL to filter by.

        Returns:
            List of snapshots for the URL.
        """
        return [s for s in self._snapshots if s.url == url]

    def get_snapshots_by_timestamp_range(
        self,
        start_ts: float | None = None,
        end_ts: float | None = None,
    ) -> list[WindowSnapshot]:
        """
        Get snapshots within a timestamp range.

        Args:
            start_ts: Optional start timestamp (inclusive).
            end_ts: Optional end timestamp (inclusive).

        Returns:
            List of snapshots within the range.
        """
        results = []
        for snapshot in self._snapshots:
            if start_ts is not None and snapshot.timestamp < start_ts:
                continue
            if end_ts is not None and snapshot.timestamp > end_ts:
                continue
            results.append(snapshot)
        return results

    def search_for_value(
        self,
        value: str,
        case_sensitive: bool = False,
        exclude_noise: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Search all properties for a specific value.

        Args:
            value: The value to search for.
            case_sensitive: Whether to do case-sensitive matching.
            exclude_noise: Whether to exclude common browser/framework noise.

        Returns:
            List of matches with path, value, and context.
        """
        results: list[dict[str, Any]] = []
        search_value = value if case_sensitive else value.lower()

        for path, prop_value in self._current_properties.items():
            # Skip noise if requested
            if exclude_noise:
                if any(path.startswith(prefix) for prefix in self.NOISE_PREFIXES):
                    continue

            # Convert value to string for searching
            str_value = str(prop_value) if prop_value is not None else ""
            compare_value = str_value if case_sensitive else str_value.lower()

            if search_value in compare_value:
                results.append({
                    "path": path,
                    "value": prop_value,
                    "value_type": type(prop_value).__name__,
                })

        return results

    def search_for_path(
        self,
        path_pattern: str,
        case_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Search for properties with paths matching a pattern.

        Args:
            path_pattern: The pattern to search for in paths.
            case_sensitive: Whether to do case-sensitive matching.

        Returns:
            List of matches with path and value.
        """
        results: list[dict[str, Any]] = []
        search_pattern = path_pattern if case_sensitive else path_pattern.lower()

        for path, value in self._current_properties.items():
            compare_path = path if case_sensitive else path.lower()
            if search_pattern in compare_path:
                results.append({
                    "path": path,
                    "value": value,
                    "value_type": type(value).__name__,
                })

        return results

    def get_property_history(self, path: str) -> list[dict[str, Any]]:
        """
        Get the history of changes for a specific property.

        Args:
            path: The property path to get history for.

        Returns:
            List of changes with timestamp, url, value, and change_type.
        """
        history: list[dict[str, Any]] = []

        for snapshot in self._snapshots:
            for change in snapshot.changes:
                if change.path == path:
                    history.append({
                        "timestamp": snapshot.timestamp,
                        "url": snapshot.url,
                        "value": change.value,
                        "change_type": change.change_type.value,
                    })

        return history

    def get_interesting_properties(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Get properties that are likely interesting (custom app data, config, etc.).

        Filters out common browser APIs, event handlers, and framework noise.

        Args:
            limit: Maximum number of properties to return.

        Returns:
            List of interesting properties with path and value.
        """
        # Skip these patterns
        skip_patterns = (
            "on",  # Event handlers
            "GPU",
            "Atomics",
            "CSS",
            "Temporal",
            "WebAssembly",
            "Symbol(",
            "chrome.",
            "Infinity",
            "NaN",
            "undefined",
            "isSecureContext",
            "crossOriginIsolated",
            "originAgentCluster",
            "credentialless",
            "fence",
            "offscreenBuffering",
        )

        interesting: list[dict[str, Any]] = []

        for path, value in self._current_properties.items():
            # Skip if starts with any skip pattern
            if any(path.startswith(p) for p in skip_patterns):
                continue

            # Skip null/None values
            if value is None:
                continue

            # Skip pure window dimension/position props
            if path in ("innerWidth", "innerHeight", "outerWidth", "outerHeight",
                       "screenX", "screenY", "screenLeft", "screenTop",
                       "scrollX", "scrollY", "pageXOffset", "pageYOffset",
                       "devicePixelRatio", "length", "name", "status", "closed"):
                continue

            interesting.append({
                "path": path,
                "value": value,
                "value_type": type(value).__name__,
            })

            if len(interesting) >= limit:
                break

        return interesting
