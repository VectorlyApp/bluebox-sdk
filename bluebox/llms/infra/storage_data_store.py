"""
bluebox/llms/infra/storage_data_store.py

Data store for browser storage events (cookies, sessionStorage, localStorage).

Parses storage event JSONL files captured via CDP and provides structured access
to storage data with search capabilities.
"""

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from bluebox.utils.logger import get_logger


logger = get_logger(name=__name__)


class StorageType(StrEnum):
    """Types of browser storage."""
    COOKIE = "cookie"
    SESSION_STORAGE = "sessionStorage"
    LOCAL_STORAGE = "localStorage"


class StorageEventType(StrEnum):
    """Types of storage events."""
    COOKIE_CHANGE = "cookieChange"
    SESSION_STORAGE_ADDED = "sessionStorageItemAdded"
    SESSION_STORAGE_MODIFIED = "sessionStorageItemModified"
    SESSION_STORAGE_REMOVED = "sessionStorageItemRemoved"
    LOCAL_STORAGE_ADDED = "localStorageItemAdded"
    LOCAL_STORAGE_MODIFIED = "localStorageItemModified"
    LOCAL_STORAGE_REMOVED = "localStorageItemRemoved"


@dataclass
class Cookie:
    """Represents a browser cookie."""
    name: str
    value: str
    domain: str
    path: str
    expires: float | None
    http_only: bool
    secure: bool
    same_site: str | None
    timestamp: float  # When this cookie state was captured

    @classmethod
    def from_cdp(cls, data: dict[str, Any], timestamp: float) -> "Cookie":
        """Create Cookie from CDP cookie data."""
        return cls(
            name=data.get("name", ""),
            value=data.get("value", ""),
            domain=data.get("domain", ""),
            path=data.get("path", "/"),
            expires=data.get("expires"),
            http_only=data.get("httpOnly", False),
            secure=data.get("secure", False),
            same_site=data.get("sameSite"),
            timestamp=timestamp,
        )


@dataclass
class StorageItem:
    """Represents a sessionStorage or localStorage item."""
    storage_type: StorageType
    key: str
    value: str
    origin: str
    timestamp: float
    old_value: str | None = None  # For modified events


@dataclass
class StorageStats:
    """Summary statistics for storage data."""
    total_events: int = 0
    cookie_events: int = 0
    session_storage_events: int = 0
    local_storage_events: int = 0

    unique_cookie_names: int = 0
    unique_cookie_domains: int = 0
    unique_session_keys: int = 0
    unique_local_keys: int = 0
    unique_origins: int = 0

    def to_summary(self) -> str:
        """Generate a human-readable summary."""
        return (
            f"Storage Events Summary:\n"
            f"  Total Events: {self.total_events}\n"
            f"  Cookie Events: {self.cookie_events} ({self.unique_cookie_names} unique names, {self.unique_cookie_domains} domains)\n"
            f"  Session Storage Events: {self.session_storage_events} ({self.unique_session_keys} unique keys)\n"
            f"  Local Storage Events: {self.local_storage_events} ({self.unique_local_keys} unique keys)\n"
            f"  Unique Origins: {self.unique_origins}"
        )


class StorageDataStore:
    """
    Data store for browser storage event analysis.

    Parses storage event JSONL files captured via CDP and provides structured
    access to cookies, sessionStorage, and localStorage data.

    Usage:
        store = StorageDataStore("/path/to/storage/events.jsonl")
        print(store.stats.to_summary())

        # Get current cookie state
        cookies = store.get_cookies_by_domain(".google.com")

        # Search for values
        matches = store.search_for_value("auth_token")

        # Get storage state at a point in time
        session_data = store.get_session_storage(origin="https://example.com")
    """

    def __init__(self, jsonl_path: str | Path) -> None:
        """
        Initialize the storage data store.

        Args:
            jsonl_path: Path to the storage events JSONL file.
        """
        self._path = Path(jsonl_path)
        if not self._path.exists():
            raise FileNotFoundError(f"Storage events file not found: {jsonl_path}")

        # Storage state (latest values)
        self._cookies: dict[tuple[str, str, str], Cookie] = {}  # (name, domain, path) -> Cookie
        self._session_storage: dict[tuple[str, str], StorageItem] = {}  # (origin, key) -> StorageItem
        self._local_storage: dict[tuple[str, str], StorageItem] = {}  # (origin, key) -> StorageItem

        # All events for historical queries
        self._events: list[dict[str, Any]] = []

        # Stats tracking
        self._cookie_names: set[str] = set()
        self._cookie_domains: set[str] = set()
        self._session_keys: set[str] = set()
        self._local_keys: set[str] = set()
        self._origins: set[str] = set()

        # Parse the file
        self._parse_jsonl()

        logger.debug(
            "Loaded StorageDataStore: %d events, %d cookies, %d session items, %d local items",
            len(self._events),
            len(self._cookies),
            len(self._session_storage),
            len(self._local_storage),
        )

    def _parse_jsonl(self) -> None:
        """Parse the JSONL file and build storage state."""
        with open(self._path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    self._events.append(event)
                    self._process_event(event)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse storage event line")
                    continue

    def _process_event(self, event: dict[str, Any]) -> None:
        """Process a single storage event."""
        event_type = event.get("type", "")
        timestamp = event.get("timestamp", 0.0)

        if event_type == StorageEventType.COOKIE_CHANGE:
            self._process_cookie_event(event, timestamp)

        elif event_type in (StorageEventType.SESSION_STORAGE_ADDED, StorageEventType.SESSION_STORAGE_MODIFIED):
            self._process_session_storage_event(event, timestamp, is_removed=False)

        elif event_type == StorageEventType.SESSION_STORAGE_REMOVED:
            self._process_session_storage_event(event, timestamp, is_removed=True)

        elif event_type in (StorageEventType.LOCAL_STORAGE_ADDED, StorageEventType.LOCAL_STORAGE_MODIFIED):
            self._process_local_storage_event(event, timestamp, is_removed=False)

        elif event_type == StorageEventType.LOCAL_STORAGE_REMOVED:
            self._process_local_storage_event(event, timestamp, is_removed=True)

    def _process_cookie_event(self, event: dict[str, Any], timestamp: float) -> None:
        """Process a cookie change event."""
        # Handle added cookies
        for cookie_data in event.get("added") or []:
            cookie = Cookie.from_cdp(cookie_data, timestamp)
            key = (cookie.name, cookie.domain, cookie.path)
            self._cookies[key] = cookie
            self._cookie_names.add(cookie.name)
            self._cookie_domains.add(cookie.domain)

        # Handle modified cookies
        for mod in event.get("modified") or []:
            new_data = mod.get("new", {})
            cookie = Cookie.from_cdp(new_data, timestamp)
            key = (cookie.name, cookie.domain, cookie.path)
            self._cookies[key] = cookie
            self._cookie_names.add(cookie.name)
            self._cookie_domains.add(cookie.domain)

        # Handle removed cookies
        for cookie_data in event.get("removed") or []:
            name = cookie_data.get("name", "")
            domain = cookie_data.get("domain", "")
            path = cookie_data.get("path", "/")
            key = (name, domain, path)
            self._cookies.pop(key, None)

    def _process_session_storage_event(
        self,
        event: dict[str, Any],
        timestamp: float,
        is_removed: bool,
    ) -> None:
        """Process a sessionStorage event."""
        origin = event.get("origin", "")
        key = event.get("key", "")

        if not origin or not key:
            return

        self._origins.add(origin)

        if is_removed:
            self._session_storage.pop((origin, key), None)
        else:
            value = event.get("value", "")
            old_value = event.get("old_value")
            item = StorageItem(
                storage_type=StorageType.SESSION_STORAGE,
                key=key,
                value=value,
                origin=origin,
                timestamp=timestamp,
                old_value=old_value,
            )
            self._session_storage[(origin, key)] = item
            self._session_keys.add(key)

    def _process_local_storage_event(
        self,
        event: dict[str, Any],
        timestamp: float,
        is_removed: bool,
    ) -> None:
        """Process a localStorage event."""
        origin = event.get("origin", "")
        key = event.get("key", "")

        if not origin or not key:
            return

        self._origins.add(origin)

        if is_removed:
            self._local_storage.pop((origin, key), None)
        else:
            value = event.get("value", "")
            old_value = event.get("old_value")
            item = StorageItem(
                storage_type=StorageType.LOCAL_STORAGE,
                key=key,
                value=value,
                origin=origin,
                timestamp=timestamp,
                old_value=old_value,
            )
            self._local_storage[(origin, key)] = item
            self._local_keys.add(key)

    @property
    def stats(self) -> StorageStats:
        """Get summary statistics for the storage data."""
        cookie_events = sum(
            1 for e in self._events
            if e.get("type") == StorageEventType.COOKIE_CHANGE
        )
        session_events = sum(
            1 for e in self._events
            if e.get("type", "").startswith("sessionStorage")
        )
        local_events = sum(
            1 for e in self._events
            if e.get("type", "").startswith("localStorage")
        )

        return StorageStats(
            total_events=len(self._events),
            cookie_events=cookie_events,
            session_storage_events=session_events,
            local_storage_events=local_events,
            unique_cookie_names=len(self._cookie_names),
            unique_cookie_domains=len(self._cookie_domains),
            unique_session_keys=len(self._session_keys),
            unique_local_keys=len(self._local_keys),
            unique_origins=len(self._origins),
        )

    @property
    def cookies(self) -> list[Cookie]:
        """Get all current cookies."""
        return list(self._cookies.values())

    @property
    def session_storage_items(self) -> list[StorageItem]:
        """Get all current sessionStorage items."""
        return list(self._session_storage.values())

    @property
    def local_storage_items(self) -> list[StorageItem]:
        """Get all current localStorage items."""
        return list(self._local_storage.values())

    @property
    def origins(self) -> list[str]:
        """Get all unique origins."""
        return sorted(self._origins)

    def get_cookies_by_domain(self, domain: str) -> list[Cookie]:
        """
        Get all cookies for a specific domain.

        Args:
            domain: The domain to filter by (e.g., ".google.com").

        Returns:
            List of cookies matching the domain.
        """
        return [c for c in self._cookies.values() if domain in c.domain]

    def get_cookie_by_name(self, name: str) -> list[Cookie]:
        """
        Get all cookies with a specific name.

        Args:
            name: The cookie name to search for.

        Returns:
            List of cookies with the given name (may be multiple domains).
        """
        return [c for c in self._cookies.values() if c.name == name]

    def get_session_storage(self, origin: str | None = None) -> dict[str, str]:
        """
        Get sessionStorage items, optionally filtered by origin.

        Args:
            origin: Optional origin to filter by.

        Returns:
            Dict of key -> value for sessionStorage items.
        """
        if origin:
            return {
                item.key: item.value
                for (o, _), item in self._session_storage.items()
                if o == origin
            }
        return {item.key: item.value for item in self._session_storage.values()}

    def get_local_storage(self, origin: str | None = None) -> dict[str, str]:
        """
        Get localStorage items, optionally filtered by origin.

        Args:
            origin: Optional origin to filter by.

        Returns:
            Dict of key -> value for localStorage items.
        """
        if origin:
            return {
                item.key: item.value
                for (o, _), item in self._local_storage.items()
                if o == origin
            }
        return {item.key: item.value for item in self._local_storage.values()}

    def search_for_value(self, value: str, case_sensitive: bool = False) -> list[dict[str, Any]]:
        """
        Search all storage for a specific value.

        Args:
            value: The value to search for.
            case_sensitive: Whether to do case-sensitive matching.

        Returns:
            List of matches with storage type, key, value, and context.
        """
        results: list[dict[str, Any]] = []
        search_value = value if case_sensitive else value.lower()

        # Search cookies
        for cookie in self._cookies.values():
            cookie_value = cookie.value if case_sensitive else cookie.value.lower()
            if search_value in cookie_value:
                results.append({
                    "storage_type": StorageType.COOKIE,
                    "key": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "timestamp": cookie.timestamp,
                })

        # Search sessionStorage
        for item in self._session_storage.values():
            item_value = item.value if case_sensitive else item.value.lower()
            if search_value in item_value:
                results.append({
                    "storage_type": StorageType.SESSION_STORAGE,
                    "key": item.key,
                    "value": item.value,
                    "origin": item.origin,
                    "timestamp": item.timestamp,
                })

        # Search localStorage
        for item in self._local_storage.values():
            item_value = item.value if case_sensitive else item.value.lower()
            if search_value in item_value:
                results.append({
                    "storage_type": StorageType.LOCAL_STORAGE,
                    "key": item.key,
                    "value": item.value,
                    "origin": item.origin,
                    "timestamp": item.timestamp,
                })

        return results

    def search_for_key(self, key_pattern: str, case_sensitive: bool = False) -> list[dict[str, Any]]:
        """
        Search all storage for keys matching a pattern.

        Args:
            key_pattern: The pattern to search for in keys.
            case_sensitive: Whether to do case-sensitive matching.

        Returns:
            List of matches with storage type, key, value, and context.
        """
        results: list[dict[str, Any]] = []
        search_pattern = key_pattern if case_sensitive else key_pattern.lower()

        # Search cookies
        for cookie in self._cookies.values():
            cookie_name = cookie.name if case_sensitive else cookie.name.lower()
            if search_pattern in cookie_name:
                results.append({
                    "storage_type": StorageType.COOKIE,
                    "key": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "timestamp": cookie.timestamp,
                })

        # Search sessionStorage
        for item in self._session_storage.values():
            item_key = item.key if case_sensitive else item.key.lower()
            if search_pattern in item_key:
                results.append({
                    "storage_type": StorageType.SESSION_STORAGE,
                    "key": item.key,
                    "value": item.value,
                    "origin": item.origin,
                    "timestamp": item.timestamp,
                })

        # Search localStorage
        for item in self._local_storage.values():
            item_key = item.key if case_sensitive else item.key.lower()
            if search_pattern in item_key:
                results.append({
                    "storage_type": StorageType.LOCAL_STORAGE,
                    "key": item.key,
                    "value": item.value,
                    "origin": item.origin,
                    "timestamp": item.timestamp,
                })

        return results

    def get_events_by_timestamp_range(
        self,
        start_ts: float | None = None,
        end_ts: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all events within a timestamp range.

        Args:
            start_ts: Optional start timestamp (inclusive).
            end_ts: Optional end timestamp (inclusive).

        Returns:
            List of events within the range.
        """
        results = []
        for event in self._events:
            ts = event.get("timestamp", 0.0)
            if start_ts is not None and ts < start_ts:
                continue
            if end_ts is not None and ts > end_ts:
                continue
            results.append(event)
        return results

    def get_raw_events(self) -> list[dict[str, Any]]:
        """Get all raw events."""
        return self._events.copy()
