"""
web_hacker/cdp/__init__.py

CDP (Chrome DevTools Protocol) monitoring package.
Provides async CDP session management and event monitoring.

The primary classes are in the async_cdp subpackage:
- AsyncCDPSession: Async CDP session for browser monitoring
- FileEventWriter: Callback adapter for writing events to files
"""

from web_hacker.cdp.async_cdp import (
    AsyncCDPSession,
    FileEventWriter,
    BaseCDPEvent,
    NetworkTransactionEvent,
    StorageEvent,
    WindowPropertyChange,
    WindowPropertyEvent,
)

__all__ = [
    "AsyncCDPSession",
    "FileEventWriter",
    "BaseCDPEvent",
    "NetworkTransactionEvent",
    "StorageEvent",
    "WindowPropertyChange",
    "WindowPropertyEvent",
]
