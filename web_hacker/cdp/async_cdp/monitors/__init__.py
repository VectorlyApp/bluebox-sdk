"""
web_hacker/cdp/async_cdp/monitors/__init__.py

cdp.async.monitors package
NOTE: This file is actually necessary, because it triggers the AbstractAsyncMonitor.__init_subclass__
method for all monitor classes, so that the AbstractAsyncMonitor._subclasses list is populated.
That is important because EventBroadcaster uses AbstractAsyncMonitor.get_all_subclasses() to find
the right monitor class by class name, so it can call get_ws_event_summary() to create
lightweight summaries for WebSocket streaming.
"""

from web_hacker.cdp.async_cdp.monitors.abstract_async_monitor import AbstractAsyncMonitor

# import all monitor classes to trigger AbstractAsyncMonitor.__init_subclass__
from web_hacker.cdp.async_cdp.monitors.async_network_monitor import AsyncNetworkMonitor
from web_hacker.cdp.async_cdp.monitors.async_storage_monitor import AsyncStorageMonitor
from web_hacker.cdp.async_cdp.monitors.async_window_property_monitor import AsyncWindowPropertyMonitor

__all__ = [
    "AbstractAsyncMonitor",
    "AsyncNetworkMonitor",
    "AsyncStorageMonitor",
    "AsyncWindowPropertyMonitor",
]
