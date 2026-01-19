"""
web_hacker/sdk/monitor.py

Async browser monitoring SDK wrapper.

Contains:
- BrowserMonitor: Async wrapper for AsyncCDPSession for easy browser capture
- start(): Begin capturing network, storage, window properties
- stop(): End capture, save data to output directory
- Outputs: events.jsonl files, consolidated_transactions.json, network.har
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from web_hacker.cdp import AsyncCDPSession, FileEventWriter
from web_hacker.cdp.connection import cdp_new_tab, dispose_context
from web_hacker.utils.exceptions import BrowserConnectionError
from web_hacker.utils.logger import get_logger

logger = get_logger(__name__)


class BrowserMonitor:
    """
    Async high-level interface for monitoring browser activity.

    Example:
        >>> monitor = BrowserMonitor(output_dir="./captures")
        >>> async with monitor:
        ...     # User performs actions in browser
        ...     pass
        >>> summary = await monitor.get_summary()

    Or without context manager:
        >>> monitor = BrowserMonitor(output_dir="./captures")
        >>> await monitor.start()
        >>> # ... user performs actions ...
        >>> summary = await monitor.stop()
    """

    def __init__(
        self,
        remote_debugging_address: str = "http://127.0.0.1:9222",
        output_dir: str = "./cdp_captures",
        url: str = "about:blank",
        incognito: bool = True,
        create_tab: bool = True,
    ) -> None:
        """
        Initialize BrowserMonitor.

        Args:
            remote_debugging_address: Chrome DevTools remote debugging address.
            output_dir: Directory for output files.
            url: Initial URL for new tab (only if create_tab=True).
            incognito: Whether to create tab in incognito mode (only if create_tab=True).
            create_tab: Whether to create a new browser tab.
        """
        self.remote_debugging_address = remote_debugging_address
        self.output_dir = output_dir
        self.url = url
        self.incognito = incognito
        self.create_tab = create_tab

        # internal state
        self.session: AsyncCDPSession | None = None
        self.writer: FileEventWriter | None = None
        self.context_id: str | None = None
        self.created_tab = False
        self._run_task: asyncio.Task | None = None
        self._finalized = False

    def _setup_paths(self) -> dict[str, str]:
        """Setup output directory structure and return paths dict."""
        output_path = Path(self.output_dir)

        # create directories
        network_dir = output_path / "network"
        storage_dir = output_path / "storage"
        window_properties_dir = output_path / "window_properties"
        interaction_dir = output_path / "interaction"

        network_dir.mkdir(parents=True, exist_ok=True)
        storage_dir.mkdir(parents=True, exist_ok=True)
        window_properties_dir.mkdir(parents=True, exist_ok=True)
        interaction_dir.mkdir(parents=True, exist_ok=True)

        return {
            # Directories
            "output_dir": str(output_path),
            "network_dir": str(network_dir),
            "storage_dir": str(storage_dir),
            "window_properties_dir": str(window_properties_dir),
            "interaction_dir": str(interaction_dir),
            # Event JSONL paths
            "network_events_path": str(network_dir / "events.jsonl"),
            "storage_events_path": str(storage_dir / "events.jsonl"),
            "window_properties_path": str(window_properties_dir / "events.jsonl"),
            "interaction_events_path": str(interaction_dir / "events.jsonl"),
            # Consolidated output paths
            "consolidated_transactions_json_path": str(
                network_dir / "consolidated_transactions.json"
            ),
            "network_har_path": str(network_dir / "network.har"),
            "summary_path": str(output_path / "session_summary.json"),
        }

    def _is_browser_connected(self) -> bool:
        """Check if browser is still connected and responsive."""
        try:
            response = requests.get(
                url=f"{self.remote_debugging_address}/json/version",
                timeout=1,
            )
            return response.status_code == 200
        except Exception:
            return False

    async def start(self) -> None:
        """Start async monitoring session."""
        # Setup paths
        paths = self._setup_paths()

        # Get or create browser tab
        ws_url: str | None = None

        if self.create_tab:
            try:
                # Create new tab
                target_id, browser_context_id, browser_ws = cdp_new_tab(
                    remote_debugging_address=self.remote_debugging_address,
                    incognito=self.incognito,
                    url=self.url,
                )
                # Close browser WebSocket - we'll create a page-level one
                try:
                    browser_ws.close()
                except Exception:
                    pass
                self.context_id = browser_context_id
                self.created_tab = True
                # Build page-level WebSocket URL
                host_port = self.remote_debugging_address.replace("http://", "").replace("https://", "")
                ws_url = f"ws://{host_port}/devtools/page/{target_id}"
            except Exception as e:
                raise BrowserConnectionError(f"Failed to create browser tab: {e}") from e
        else:
            # connect to existing browser
            try:
                ver = requests.get(
                    url=f"{self.remote_debugging_address}/json/version",
                    timeout=5,
                )
                ver.raise_for_status()
                data = ver.json()
                ws_url = data.get("webSocketDebuggerUrl")
                if not ws_url:
                    raise BrowserConnectionError("Could not get WebSocket URL from browser")
            except requests.exceptions.RequestException as e:
                raise BrowserConnectionError(f"Failed to connect to browser: {e}") from e

        # Create file event writer
        self.writer = FileEventWriter(paths=paths)

        # Create async CDP session
        self.session = AsyncCDPSession(
            ws_url=ws_url,
            session_start_dtm=datetime.now().isoformat(),
            event_callback_fn=self.writer.write_event,
            paths=paths,
        )

        # Start monitoring in background task
        self._run_task = asyncio.create_task(
            coro=self._run_monitoring(),
        )

        logger.info("Browser monitoring started. Output directory: %s", self.output_dir)

    async def _run_monitoring(self) -> None:
        """Run the monitoring loop."""
        if not self.session:
            return

        try:
            await self.session.run()
        except asyncio.CancelledError:
            logger.info("Monitoring task cancelled")
        except Exception as e:
            logger.error("Error in monitoring loop: %s", e)

    async def _finalize_session(self) -> None:
        """Finalize session: consolidate data and cleanup."""
        if self._finalized:
            return
        self._finalized = True

        if not self.session:
            logger.warning("No session to finalize")
            return

        logger.info("Finalizing session...")

        # Check if browser is still connected
        browser_connected = self._is_browser_connected()

        if browser_connected:
            try:
                await self.session.finalize()
            except Exception as e:
                logger.warning("Error during finalization: %s", e)
        else:
            # Just do file consolidation without CDP calls
            logger.info("Browser disconnected, skipping CDP finalization")

    async def stop(self) -> dict[str, Any]:
        """Stop monitoring and return summary."""
        if not self.session:
            return {}

        # Cancel the monitoring task
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass

        # Finalize session
        await self._finalize_session()

        # Get summary before cleanup
        summary = self.get_summary()

        # Cleanup browser context if we created a tab
        if self.created_tab and self.context_id and self._is_browser_connected():
            try:
                dispose_context(self.remote_debugging_address, self.context_id)
                logger.info("Browser context disposed")
            except Exception as e:
                logger.debug("Could not dispose browser context: %s", e)

        logger.info("Browser monitoring stopped.")
        return summary

    def get_summary(self) -> dict[str, Any]:
        """Get current monitoring summary without stopping."""
        if not self.session:
            return {}
        return self.session.get_monitoring_summary()

    async def __aenter__(self) -> "BrowserMonitor":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.stop()
