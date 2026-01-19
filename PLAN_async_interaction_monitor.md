# Plan: Implement AsyncInteractionMonitor

## Background

The `AsyncInteractionMonitor` class exists as a stub at `web_hacker/cdp/async_cdp/monitors/async_interaction_monitor.py` but has no implementation:

```python
class AsyncInteractionMonitor(AbstractAsyncMonitor):
    """
    Async interaction monitor for CDP.
    """
    pass
```

There is a sync version of this monitor at `web_hacker/cdp/interaction_monitor.py` (currently only in the installed package, not in the repo source). This sync version needs to be ported to async.

### What InteractionMonitor Does

The `InteractionMonitor` tracks user interactions with the browser:
- **Mouse events**: click, mousedown, mouseup, dblclick, contextmenu, mouseover
- **Keyboard events**: keydown, keyup, keypress
- **Form events**: input, change
- **Focus events**: focus, blur

It works by:
1. Injecting JavaScript into the page via `Runtime.addBinding` and `Page.addScriptToEvaluateOnNewDocument`
2. The injected JS listens for DOM events and calls a CDP binding (`__webHackerInteractionLog`)
3. When the binding is called, CDP sends a `Runtime.bindingCalled` event
4. The monitor parses the event data and converts it to `UiInteractionEvent` models
5. Events are logged to a JSONL file

### Data Models Used

The monitor uses these existing Pydantic models from `web_hacker/data_models/`:

- `UiInteractionEvent` — Complete interaction event record
- `InteractionType` — Enum (click, keydown, input, etc.)
- `Interaction` — Event details (mouse coords, key pressed, modifiers)
- `UiElement` — DOM element with selectors, attributes, bounding box
- `Identifier`, `IdentifierType`, `BoundingBox` — Supporting types

### Async Monitor Pattern

All async monitors follow this pattern (see `AsyncStorageMonitor` for reference):

```python
class AsyncSomethingMonitor(AbstractAsyncMonitor):
    def __init__(self, event_callback_fn: Callable[[str, dict], Awaitable[None]]) -> None:
        self.event_callback_fn = event_callback_fn
        # ... state tracking ...

    @classmethod
    def get_ws_event_summary(cls, detail: dict[str, Any]) -> dict[str, Any]:
        # Extract lightweight summary for WebSocket streaming
        ...

    async def setup_something_monitoring(self, cdp_session: AsyncCDPSession) -> None:
        # Enable CDP domains, inject scripts, etc.
        ...

    async def handle_something_message(self, msg: dict, cdp_session: AsyncCDPSession) -> bool:
        # Handle CDP events, return True if handled
        ...

    async def handle_something_command_reply(self, msg: dict) -> bool:
        # Handle CDP command replies, return True if handled
        ...
```

## Goals

1. Implement `AsyncInteractionMonitor` following the async monitor pattern
2. Port all functionality from the sync `InteractionMonitor`
3. Use callback pattern (`event_callback_fn`) instead of direct file writes
4. Add `get_interaction_summary()` method for session summaries
5. Add `consolidate_interactions()` method for post-session consolidation

## Files to Modify

| File | Action |
|------|--------|
| `web_hacker/cdp/async_cdp/monitors/async_interaction_monitor.py` | Implement full monitor |
| `web_hacker/cdp/async_cdp/async_cdp_session.py` | Add interaction monitor integration |
| `web_hacker/cdp/async_cdp/data_models.py` | Add `InteractionEvent` model (optional, can reuse existing) |

## Implementation Steps

### Step 1: Implement `AsyncInteractionMonitor` class

Port from sync `InteractionMonitor`. Key changes:
- Constructor takes `event_callback_fn` instead of `output_dir`, `paths`
- All CDP sends use `await cdp_session.send()` instead of `cdp_session.send()`
- Event logging calls `await self.event_callback_fn(category, event)` instead of `write_jsonl()`
- All handler methods are `async def`

```python
"""
web_hacker/cdp/async_cdp/monitors/async_interaction_monitor.py

Async interaction monitor for CDP.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from web_hacker.cdp.async_cdp.monitors.abstract_async_monitor import AbstractAsyncMonitor
from web_hacker.data_models.ui_elements import UiElement, BoundingBox
from web_hacker.data_models.ui_interaction import UiInteractionEvent, InteractionType, Interaction
from web_hacker.utils.logger import get_logger

if TYPE_CHECKING:
    from web_hacker.cdp.async_cdp.async_cdp_session import AsyncCDPSession

logger = get_logger(name=__name__)


class AsyncInteractionMonitor(AbstractAsyncMonitor):
    """
    Async interaction monitor for CDP.
    Tracks mouse clicks, keyboard events, and element details via JavaScript injection.
    """

    # Class constant
    BINDING_NAME = "__webHackerInteractionLog"

    # Abstract method implementation
    @classmethod
    def get_ws_event_summary(cls, detail: dict[str, Any]) -> dict[str, Any]:
        """Extract lightweight summary for WebSocket streaming."""
        return {
            "type": cls.get_monitor_category(),
            "interaction_type": detail.get("type"),
            "element_tag": detail.get("element", {}).get("tag_name"),
            "url": detail.get("url"),
        }

    def __init__(self, event_callback_fn: Callable[[str, dict], Awaitable[None]]) -> None:
        """
        Initialize AsyncInteractionMonitor.
        Args:
            event_callback_fn: Async callback for emitting events.
        """
        self.event_callback_fn = event_callback_fn

        # Statistics tracking
        self.interaction_count: int = 0
        self.interaction_types: dict[str, int] = defaultdict(int)
        self.interactions_by_url: dict[str, int] = defaultdict(int)

        # Pending DOM commands (for element enrichment if needed)
        self.pending_dom_commands: dict[int, dict[str, Any]] = {}

    # ... rest of implementation follows sync version pattern ...
```

### Step 2: Implement `setup_interaction_monitoring()`

```python
async def setup_interaction_monitoring(self, cdp_session: AsyncCDPSession) -> None:
    """Setup interaction monitoring via CDP session."""
    logger.info("Setting up interaction monitoring...")

    # Enable required domains
    await cdp_session.enable_domain("Runtime")
    await cdp_session.enable_domain("DOM")
    await cdp_session.enable_domain("Page")

    # Create binding for JavaScript to call
    await cdp_session.send("Runtime.addBinding", {"name": self.BINDING_NAME})

    # Inject interaction listeners
    await self._inject_interaction_listeners(cdp_session)

    logger.info("Interaction monitoring setup complete")
```

### Step 3: Implement `_inject_interaction_listeners()`

Port the JavaScript injection code from sync version. The JS code itself doesn't change — only the CDP send calls become async:

```python
async def _inject_interaction_listeners(self, cdp_session: AsyncCDPSession) -> None:
    """Inject JavaScript listeners for mouse and keyboard events."""
    interaction_script = f"""
    (function() {{
        'use strict';
        const bindingName = '{self.BINDING_NAME}';
        // ... rest of JS code from sync version ...
    }})();
    """

    try:
        # Inject for all future documents
        await cdp_session.send("Page.addScriptToEvaluateOnNewDocument", {
            "source": interaction_script
        })

        # Inject for current page
        await cdp_session.send("Runtime.evaluate", {
            "expression": interaction_script,
            "includeCommandLineAPI": False
        })

        logger.info("Interaction monitoring script injected")
    except Exception as e:
        logger.warning("Failed to inject interaction script: %s", e)
```

### Step 4: Implement `handle_interaction_message()`

```python
async def handle_interaction_message(self, msg: dict, cdp_session: AsyncCDPSession) -> bool:
    """Handle interaction-related CDP messages."""
    method = msg.get("method")

    if method == "Runtime.bindingCalled":
        return await self._on_binding_called(msg)

    if method == "Page.frameNavigated":
        # Script auto-injected via addScriptToEvaluateOnNewDocument
        return False  # Don't swallow

    if method == "DOM.documentUpdated":
        return False  # Don't swallow

    return False
```

### Step 5: Implement `_on_binding_called()`

This is the main event handler. Port from sync version, but call callback instead of writing to file:

```python
async def _on_binding_called(self, msg: dict) -> bool:
    """Handle Runtime.bindingCalled event from JavaScript."""
    try:
        params = msg.get("params", {})
        name = params.get("name")
        payload = params.get("payload", "")

        if name != self.BINDING_NAME:
            return False

        # Parse interaction data
        raw_data = json.loads(payload)

        # Convert to UiInteractionEvent (same logic as sync version)
        ui_interaction_event = self._parse_interaction_event(raw_data)
        if ui_interaction_event is None:
            return False

        # Update statistics
        self.interaction_count += 1
        interaction_type_str = ui_interaction_event.type.value
        self.interaction_types[interaction_type_str] += 1
        self.interactions_by_url[ui_interaction_event.url] += 1

        # Emit event via callback
        try:
            await self.event_callback_fn(
                self.get_monitor_category(),
                ui_interaction_event.model_dump()
            )
        except Exception as e:
            logger.error("Error in event callback: %s", e, exc_info=True)

        return True

    except Exception as e:
        logger.warning("Error handling binding call: %s", e)
        return False
```

### Step 6: Implement `_parse_interaction_event()` helper

Extract the parsing logic into a helper method (same logic as sync version):

```python
def _parse_interaction_event(self, raw_data: dict) -> UiInteractionEvent | None:
    """Parse raw JS data into UiInteractionEvent model."""
    try:
        element_data = raw_data.get("element")
        if not element_data:
            logger.warning("Missing element data for interaction")
            return None

        # Build BoundingBox
        bounding_box = None
        if element_data.get("bounding_box"):
            bb = element_data["bounding_box"]
            bounding_box = BoundingBox(
                x=bb.get("x", 0),
                y=bb.get("y", 0),
                width=bb.get("width", 0),
                height=bb.get("height", 0)
            )

        # Build UiElement
        ui_element = UiElement(
            tag_name=element_data.get("tag_name", ""),
            id=element_data.get("id"),
            name=element_data.get("name"),
            class_names=element_data.get("class_names"),
            type_attr=element_data.get("type_attr"),
            role=element_data.get("role"),
            aria_label=element_data.get("aria_label"),
            placeholder=element_data.get("placeholder"),
            title=element_data.get("title"),
            href=element_data.get("href"),
            src=element_data.get("src"),
            value=element_data.get("value"),
            text=element_data.get("text"),
            attributes=element_data.get("attributes"),
            bounding_box=bounding_box,
            css_path=element_data.get("css_path"),
            xpath=element_data.get("xpath"),
            url=element_data.get("url") or raw_data.get("url"),
        )
        ui_element.build_default_Identifiers()

        # Build Interaction details
        event_raw = raw_data.get("event", {})
        interaction = Interaction(
            mouse_button=event_raw.get("mouse_button"),
            key_value=event_raw.get("key_value"),
            key_code=event_raw.get("key_code"),
            key_code_deprecated=event_raw.get("key_code_deprecated"),
            key_which_deprecated=event_raw.get("key_which_deprecated"),
            ctrl_pressed=event_raw.get("ctrl_pressed", False),
            shift_pressed=event_raw.get("shift_pressed", False),
            alt_pressed=event_raw.get("alt_pressed", False),
            meta_pressed=event_raw.get("meta_pressed", False),
            mouse_x_viewport=event_raw.get("mouse_x_viewport"),
            mouse_y_viewport=event_raw.get("mouse_y_viewport"),
            mouse_x_page=event_raw.get("mouse_x_page"),
            mouse_y_page=event_raw.get("mouse_y_page"),
        )

        # Get interaction type
        interaction_type_str = raw_data.get("type", "unknown")
        try:
            interaction_type = InteractionType(interaction_type_str)
        except ValueError:
            logger.warning("Unknown interaction type: %s", interaction_type_str)
            return None

        return UiInteractionEvent(
            type=interaction_type,
            timestamp=raw_data.get("timestamp", 0),
            interaction=interaction,
            element=ui_element,
            url=raw_data.get("url", ""),
        )

    except Exception as e:
        logger.warning("Failed to parse interaction event: %s", e)
        return None
```

### Step 7: Implement `handle_interaction_command_reply()`

```python
async def handle_interaction_command_reply(self, msg: dict) -> bool:
    """Handle CDP command replies."""
    cmd_id = msg.get("id")
    if cmd_id is None:
        return False

    if cmd_id in self.pending_dom_commands:
        self.pending_dom_commands.pop(cmd_id)
        return True

    return False
```

### Step 8: Implement `get_interaction_summary()`

```python
def get_interaction_summary(self) -> dict[str, Any]:
    """Get summary of interaction monitoring."""
    return {
        "interactions_logged": self.interaction_count,
        "interactions_by_type": dict(self.interaction_types),
        "interactions_by_url": dict(self.interactions_by_url),
    }
```

### Step 9: Integrate into `AsyncCDPSession`

Update `web_hacker/cdp/async_cdp/async_cdp_session.py`:

```python
# In __init__:
from web_hacker.cdp.async_cdp.monitors.async_interaction_monitor import AsyncInteractionMonitor

self.interaction_monitor = AsyncInteractionMonitor(event_callback_fn=self.event_callback_fn)

# In setup_cdp():
await self.interaction_monitor.setup_interaction_monitoring(self)

# In handle_message():
handled_interaction = await self.interaction_monitor.handle_interaction_message(msg, self)
if handled_interaction:
    return
```

## Verification

### Test 1: Manual browser test

```bash
# Start Chrome in debug mode
# Run a test script that creates AsyncCDPSession with a logging callback
# Perform clicks and keyboard input in the browser
# Verify interaction events are captured
```

### Test 2: Check event structure

Verify emitted events match `UiInteractionEvent` schema:
- Has `type` (InteractionType enum value)
- Has `timestamp` (milliseconds)
- Has `element` with `tag_name`, selectors, etc.
- Has `interaction` with mouse/keyboard details
- Has `url`

## Notes

- The JavaScript injection code is ~260 lines and should be copied verbatim from the sync version
- The sync version is at `/home/ec2-user/servers/.venv/lib/python3.12/site-packages/web_hacker/cdp/interaction_monitor.py`
- The async monitor uses existing data models from `web_hacker/data_models/ui_interaction.py` and `web_hacker/data_models/ui_elements.py` — no new models needed
- `consolidate_interactions()` can be added later if needed for file-based output (same pattern as other monitors)
