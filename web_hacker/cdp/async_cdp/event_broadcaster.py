"""
web_hacker/cdp/async_cdp/event_broadcaster.py

Central hub for event distribution from CDP monitors.
Uses callback pattern for event handling - no AWS dependencies.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from web_hacker.cdp.async_cdp.data_models import BaseCDPEvent
from web_hacker.cdp.async_cdp.monitors.abstract_async_monitor import AbstractAsyncMonitor
from web_hacker.utils.logger import get_logger

logger = get_logger(name=__name__)


class EventBroadcaster:
    """
    Central hub for event distribution from CDP monitors.
    Uses callbacks to emit events - the caller can inject their own handlers
    for storage (S3, local files, etc.) and streaming (WebSocket, etc.).
    """

    # Magic methods ________________________________________________________________________________________________________

    def __init__(
        self,
        session_id: str,
        session_start_dtm: str,
        on_event_callback: Callable[[str, str, str, BaseCDPEvent], Awaitable[None]] | None = None,
    ) -> None:
        """
        Initialize EventBroadcaster.
        Args:
            session_id: Unique session identifier for this CDP capture session.
            session_start_dtm: Session start datetime in format YYYY-MM-DDTHH-MM-SSZ.
            on_event_callback: Optional async callback function that receives:
                - session_id: str
                - session_start_dtm: str
                - category: str (class name of the monitor, e.g., "AsyncNetworkMonitor")
                - detail: BaseCDPEvent (the event model)
                This allows the caller to handle events however they want (S3, local files, etc.).
        """
        self.session_id = session_id
        self.session_start_dtm = session_start_dtm
        self.on_event_callback = on_event_callback

        # generic category-based accumulators: category -> count
        self._event_counts: dict[str, int] = {}

        # shutdown flag
        self._shutdown = False


    # Private methods ______________________________________________________________________________________________________

    async def _handle_event(
        self,
        category: str,
        detail: BaseCDPEvent
    ) -> None:
        """
        Main event handler called by CDP monitors.
        Args:
            category: Event category (class name of the monitor, e.g., "AsyncNetworkMonitor").
            detail: CDP event model (NetworkTransactionEvent, StorageEvent, or WindowPropertyEvent).
        """
        if self._shutdown:
            return

        # 1. update generic accumulator
        self._event_counts[category] = self._event_counts.get(category, 0) + 1

        # 2. call the external callback if provided
        if self.on_event_callback:
            try:
                await self.on_event_callback(
                    self.session_id,
                    self.session_start_dtm,
                    category,
                    detail,
                )
            except Exception as e:
                logger.error("❌ Error in on_event_callback: %s", e)


    # Public methods _______________________________________________________________________________________________________

    def get_event_callback(self) -> Callable[[str, BaseCDPEvent], Awaitable[None]]:
        """Return the callback function to pass to AsyncCDPSession."""
        return self._handle_event

    def get_current_stats(self) -> dict[str, Any]:
        """Return current accumulator stats."""
        return {
            "total_events": sum(self._event_counts.values()),
            "event_counts": dict(self._event_counts),
        }

    def get_ws_event_summary(self, category: str, detail: dict) -> dict[str, Any]:
        """
        Get a lightweight summary of an event for WebSocket streaming.
        Delegates to the monitor's get_ws_event_summary method if found.
        Args:
            category: Event category (class name of the monitor, e.g., "AsyncNetworkMonitor").
            detail: Event detail dict.
        Returns:
            A simplified dict with only the fields relevant for WebSocket streaming.
        """
        # find monitor class by matching class name
        for monitor_class in AbstractAsyncMonitor.get_all_subclasses():
            if monitor_class.get_monitor_category() == category:
                return monitor_class.get_ws_event_summary(detail)

        # fallback: return a minimal summary
        logger.warning(
            "❌ No monitor class found for category: \"%s\" (options: %s)",
            category,
            [mc.get_monitor_category() for mc in AbstractAsyncMonitor.get_all_subclasses()],
        )
        return {"type": detail.get("type", "unknown")}

    async def shutdown(self, reason: str = "Session ended") -> None:
        """
        Shutdown the broadcaster.
        Args:
            reason: Human-readable reason for session end.
        """
        self._shutdown = True
        logger.info("📡 Shutting down EventBroadcaster: %s", reason)
