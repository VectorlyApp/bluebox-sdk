# Plan: JSDataStore, JS Formatting, and Browser Test Tool

## Overview

Three changes:
1. Create `bluebox/llms/infra/js_data_store.py` — dedicated data store for JavaScript files
2. Update `JSSpecialist` — enforce readable JS formatting in system prompts and validation
3. Add browser test tool to `JSSpecialist` — navigate to URL and execute JS via CDP

---

## File 1: `bluebox/llms/infra/js_data_store.py` (new)

A thin wrapper around `NetworkDataStore` specialized for JavaScript files. The JS events JSONL (`network/javascript_events.jsonl`) already exists via `FileEventWriter`, and JS entries are `NetworkTransactionEvent` with JS MIME types. The current approach passes a raw `NetworkDataStore` — this new class adds JS-specific query methods.

**Class**: `JSDataStore`

**Constructor**: `__init__(self, jsonl_path: str)` — loads from `javascript_events.jsonl`. Uses `NetworkDataStore` internally but **skips the `_is_relevant_entry` filter** (since all entries in the JS file are already JS). Approach: parse JSONL directly (same pattern as `NetworkDataStore.__init__` but without MIME filtering).

**Stats model** (`JSFileStats` dataclass):
- `total_files: int`
- `unique_urls: int`
- `total_bytes: int`
- `hosts: dict[str, int]` — count of JS files per host

**Query methods** (delegate to internal data where possible):
- `search_by_terms(terms: list[str], top_n: int = 20)` → ranked results (reuse `NetworkDataStore.search_entries_by_terms` logic)
- `get_file(request_id: str) -> NetworkTransactionEvent | None`
- `get_file_content(request_id: str, max_chars: int = 10_000) -> str | None` — truncated response body
- `search_by_url(pattern: str) -> list[NetworkTransactionEvent]` — glob match on URL
- `list_files() -> list[dict]` — summary of all JS files (request_id, url, size)

**Why not just subclass NetworkDataStore?** NetworkDataStore's `__init__` applies `_is_relevant_entry` which *excludes* JS files. We need the opposite filter. Composition or a standalone class with shared utility methods is cleaner. We can expect the JS files to be put in a separate file (per the file_event_writer.py).

---

## File 2: `bluebox/agents/specialists/js_specialist.py` (modify)

### 2a. Change `js_data_store` type from `NetworkDataStore | None` to `JSDataStore | None`

Update constructor, imports, and all tool handlers that reference `self._js_data_store`.

### 2b. JS formatting enforcement

**System prompt additions** (both conversational and autonomous):
- Add a "## Code Formatting" section:
  - "Write readable, well-formatted JavaScript. Never write extremely long single-line IIFEs."
  - "Use proper indentation (2 spaces), line breaks between statements, and descriptive variable names."
  - "Each statement should be on its own line. Complex expressions should be broken across lines."

**Validation addition** in `_validate_js()`:
- After IIFE/pattern checks, add a readability check: if the code body (between outer `{` and `}`) contains any line > 200 chars, return a warning (not error) suggesting the LLM reformat. This is soft — the LLM sees the warning in the tool result and can rewrite.

### 2c. New tool: `execute_js_in_browser`

**Purpose**: Navigate to a target URL and execute JS code via CDP `Runtime.evaluate`, returning the result. This lets the specialist test its code against the real site.

**Constructor change**: Add `remote_debugging_address: str | None = None` parameter. When provided, browser tools become available.

**Tool registration** (in `_register_tools`, gated on `self._remote_debugging_address`):

```
execute_js_in_browser:
  params:
    url: str          — URL to navigate to first (or empty to skip navigation)
    js_code: str      — IIFE JavaScript to execute
    timeout_seconds: float (default 5.0)
  returns:
    result: Any       — the JS return value
    console_logs: list — captured console.log calls
    error: str | None — execution error if any
```

**Implementation** (`_tool_execute_js_in_browser`):

1. Validate JS code using `_validate_js()` — fail fast on blocked patterns
2. Open CDP connection:
   - `cdp_new_tab(self._remote_debugging_address, incognito=True, url="about:blank")`
   - `create_cdp_helpers(browser_ws)`
   - `Target.attachToTarget` with `flatten: True` → get `session_id`
   - Enable `Page`, `Runtime` domains
3. If `url` provided:
   - `Page.navigate` to the URL
   - Wait for `Page.loadEventFired` (with timeout)
4. Wrap JS in `generate_js_evaluate_wrapper_js()` (from `bluebox/utils/js_utils.py`)
5. `Runtime.evaluate` with `returnByValue: True`, `awaitPromise: True`
6. Parse reply: extract result value, console logs, errors
7. **Cleanup**: `Target.closeTarget`, dispose browser context, close WebSocket
8. Return structured result dict

**Important**: All of steps 2-7 wrapped in try/finally for cleanup. Use a timeout of `timeout_seconds + 5` for the overall operation.

**System prompt update**: Add tool description:
- "**execute_js_in_browser**: Test your JavaScript code against the live website. Navigates to the URL and executes your IIFE, returning the result and any console output. Use this to verify your code works before submitting."

---

## Implementation Order

1. `js_data_store.py` — standalone, no dependencies on other changes
2. JS formatting changes in `js_specialist.py` — prompts + validation tweak
3. Browser test tool in `js_specialist.py` — new constructor arg + tool + handler
4. Update imports in js_specialist.py (`JSDataStore` instead of `NetworkDataStore`)

## Key Files

- **New**: `bluebox/llms/infra/js_data_store.py`
- **Modify**: `bluebox/agents/specialists/js_specialist.py`
- **Read-only references**:
  - `bluebox/cdp/connection.py` — `cdp_new_tab`, `create_cdp_helpers`, `dispose_context`
  - `bluebox/utils/js_utils.py` — `generate_js_evaluate_wrapper_js`
  - `bluebox/llms/infra/network_data_store.py` — pattern reference
  - `bluebox/data_models/routine/operation.py` — `RoutineJsEvaluateOperation._execute_operation` pattern

## Verification

```bash
# Import checks
python -c "from bluebox.llms.infra.js_data_store import JSDataStore; print('OK')"
python -c "from bluebox.agents.specialists.js_specialist import JSSpecialist; print('OK')"

# Existing tests still pass
pytest tests/ -v
```
