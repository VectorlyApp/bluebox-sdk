# Plan: CLI Scripts for JS Specialist and Interaction Specialist

## Overview

Create two CLI scripts following the `run_network_spy.py` pattern:
1. `scripts/run_js_specialist.py` — CLI for `JSSpecialist`
2. `scripts/run_interaction_specialist.py` — CLI for `InteractionSpecialist`

Both scripts will support **conversational** and **autonomous** modes, with Rich-formatted output.

## Files to Create

### 1. `scripts/run_js_specialist.py`

**CLI args:**
- `--jsonl-path` (required): Path to `javascript_events.jsonl`
- `--model` (default `gpt-5.1`): LLM model
- `--remote-debugging-address` (optional): Chrome debug address for `execute_js_in_browser` tool
- `--dom-snapshots-dir` (optional): Directory containing DOM snapshot JSON files

**Structure** (mirroring `run_network_spy.py`):
- ASCII banner (JS-themed)
- `print_welcome()` — show `JSFileStats` (total files, unique URLs, total size, top hosts)
- `TerminalJSSpecialistChat` class:
  - `_handle_stream_chunk()` / `_handle_message()` — same pattern as network spy
  - `/autonomous <task>` command — runs `JSSpecialist.run_autonomous(task)`, displays `JSCodeResult` or `JSCodeFailureResult`
  - `/reset`, `/help`, `/quit` commands
  - Regular chat via `process_new_message()`

**Data loading:**
- `JSDataStore(jsonl_path)` — loads JS network events
- Optionally load DOM snapshots from `--dom-snapshots-dir` (glob `*.json`, parse as `DOMSnapshotEvent`)

### 2. `scripts/run_interaction_specialist.py`

**CLI args:**
- `--jsonl-path` (required): Path to `interaction_events.jsonl`
- `--model` (default `gpt-5.1`): LLM model

**Structure:**
- ASCII banner (interaction-themed)
- `print_welcome()` — show `InteractionStats` (total events, unique URLs, unique elements, events by type)
- `TerminalInteractionSpecialistChat` class:
  - Same streaming/message pattern
  - `/autonomous <task>` — runs `InteractionSpecialist.run_autonomous(task)`, displays `ParameterDiscoveryResult` or `ParameterDiscoveryFailureResult`
  - `/reset`, `/help`, `/quit`
  - Regular chat via `process_new_message()`

**Data loading:**
- `InteractionsDataStore.from_jsonl(jsonl_path)` — loads interaction events

## Key Patterns from `run_network_spy.py` to Replicate

1. Rich `Console` + `Panel` + `Table` for formatted output
2. `print_welcome()` with stats panel
3. Chat class with `_handle_stream_chunk` and `_handle_message` callbacks
4. `/autonomous <task>` dispatching to `run_autonomous()`
5. Result display: success panel (green), failure panel (red), incomplete panel (yellow)
6. Timing display (`time.perf_counter()` around autonomous runs)

## Verification

- Run each script with `--help` to confirm args parse
- Run with sample JSONL files from `cdp_samples/`:
  - `python scripts/run_js_specialist.py --jsonl-path cdp_samples/network_events.jsonl`
  - `python scripts/run_interaction_specialist.py --jsonl-path cdp_samples/interaction_events.jsonl`
- Verify welcome stats display correctly
- Verify `/help`, `/reset`, `/quit` commands work
