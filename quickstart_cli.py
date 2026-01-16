#!/usr/bin/env python3
"""
Web Hacker - Interactive Quickstart CLI

A beautiful terminal interface for the web-hacker workflow:
  Monitor → Discover → Execute

Commands:
  /status    - Show current pipeline status
  /chrome    - Launch/check Chrome debug mode
  /monitor   - Start browser monitoring
  /discover  - Run routine discovery
  /execute   - Execute the discovered routine
  /routine   - Show current routine details
  /params    - Show/edit execution parameters
  /captures  - Show captured data summary
  /clear     - Clear screen
  /help      - Show this help
  /quit      - Exit
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from enum import StrEnum

import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich import box
from rich.prompt import Prompt, Confirm

from web_hacker.sdk import WebHacker, BrowserMonitor
from web_hacker.data_models.routine.routine import Routine
from web_hacker.cdp.connection import get_existing_tabs
from web_hacker.utils.infra_utils import clear_directory

console = Console()

# Configuration
PORT = 9222
REMOTE_DEBUGGING_ADDRESS = f"http://127.0.0.1:{PORT}"
CDP_CAPTURES_DIR = Path("./cdp_captures")
DISCOVERY_OUTPUT_DIR = Path("./routine_discovery_output")


class PipelineStage(StrEnum):
    NOT_STARTED = "not_started"
    CHROME_READY = "chrome_ready"
    MONITORING = "monitoring"
    CAPTURED = "captured"
    DISCOVERING = "discovering"
    DISCOVERED = "discovered"
    EXECUTING = "executing"
    COMPLETED = "completed"


class QuickstartState:
    """Holds the state of the quickstart workflow."""

    def __init__(self):
        self.stage: PipelineStage = PipelineStage.NOT_STARTED
        self.chrome_process: Optional[subprocess.Popen] = None
        self.monitor: Optional[BrowserMonitor] = None
        self.hacker: Optional[WebHacker] = None
        self.routine: Optional[Routine] = None
        self.parameters: dict[str, str] = {}
        self.last_result: Optional[dict] = None
        self.capture_summary: Optional[dict] = None
        self.cdp_captures_dir: Path = CDP_CAPTURES_DIR
        self.discovery_output_dir: Path = DISCOVERY_OUTPUT_DIR


state = QuickstartState()


def check_chrome_running() -> bool:
    """Check if Chrome is running in debug mode."""
    try:
        response = requests.get(f"http://127.0.0.1:{PORT}/json/version", timeout=1)
        return response.status_code == 200
    except (requests.RequestException, requests.Timeout):
        return False


def find_chrome_path() -> Optional[str]:
    """Find Chrome executable path based on OS."""
    system = platform.system()

    if system == "Darwin":
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.isfile(chrome_path):
            return chrome_path
    elif system == "Linux":
        for name in ["google-chrome", "chromium-browser", "chromium", "chrome"]:
            chrome_path = shutil.which(name)
            if chrome_path:
                return chrome_path
    elif system == "Windows":
        possible_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in possible_paths:
            if os.path.isfile(path):
                return path

    return None


def get_capture_stats() -> dict:
    """Get statistics about captured data."""
    stats = {
        "transactions": 0,
        "storage_entries": 0,
        "has_data": False,
    }

    transactions_dir = state.cdp_captures_dir / "network" / "transactions"
    if transactions_dir.exists():
        stats["transactions"] = len(list(transactions_dir.iterdir()))

    storage_file = state.cdp_captures_dir / "storage" / "storage.jsonl"
    if storage_file.exists():
        with open(storage_file) as f:
            stats["storage_entries"] = sum(1 for _ in f)

    stats["has_data"] = stats["transactions"] > 0
    return stats


def print_header() -> None:
    """Print the main header."""
    console.print()
    console.print(Panel(
        "[bold cyan]🕷️  Web Hacker - Interactive Quickstart[/bold cyan]\n\n"
        "[dim]Transform browser interactions into reusable automation routines[/dim]",
        box=box.DOUBLE,
        border_style="cyan"
    ))
    console.print()


def print_status() -> None:
    """Print current pipeline status."""
    console.print()

    # Pipeline stages
    stages = [
        ("Chrome", PipelineStage.CHROME_READY, "🌐"),
        ("Monitor", PipelineStage.CAPTURED, "📡"),
        ("Discover", PipelineStage.DISCOVERED, "🔍"),
        ("Execute", PipelineStage.COMPLETED, "🚀"),
    ]

    stage_order = [
        PipelineStage.NOT_STARTED,
        PipelineStage.CHROME_READY,
        PipelineStage.MONITORING,
        PipelineStage.CAPTURED,
        PipelineStage.DISCOVERING,
        PipelineStage.DISCOVERED,
        PipelineStage.EXECUTING,
        PipelineStage.COMPLETED,
    ]
    current_idx = stage_order.index(state.stage)

    # Build pipeline visualization
    pipeline_parts = []
    for name, complete_stage, icon in stages:
        complete_idx = stage_order.index(complete_stage)
        if current_idx >= complete_idx:
            pipeline_parts.append(f"[green]{icon} {name} ✓[/green]")
        elif current_idx == complete_idx - 1:
            pipeline_parts.append(f"[yellow]{icon} {name} ◀[/yellow]")
        else:
            pipeline_parts.append(f"[dim]{icon} {name}[/dim]")

    pipeline_str = " → ".join(pipeline_parts)

    # Status table
    table = Table(title="Pipeline Status", box=box.ROUNDED, title_style="bold")
    table.add_column("Component", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    # Chrome
    chrome_running = check_chrome_running()
    if chrome_running:
        table.add_row("Chrome", "[green]● Running[/green]", f"Port {PORT}")
        if state.stage == PipelineStage.NOT_STARTED:
            state.stage = PipelineStage.CHROME_READY
    else:
        table.add_row("Chrome", "[red]● Stopped[/red]", "[dim]Run /chrome to launch[/dim]")

    # Captures
    capture_stats = get_capture_stats()
    if capture_stats["has_data"]:
        table.add_row(
            "Captures",
            "[green]● Ready[/green]",
            f"{capture_stats['transactions']} transactions"
        )
    else:
        table.add_row("Captures", "[dim]● Empty[/dim]", "[dim]Run /monitor to capture[/dim]")

    # Routine
    if state.routine:
        table.add_row(
            "Routine",
            "[green]● Loaded[/green]",
            f"{state.routine.name} ({len(state.routine.operations)} ops)"
        )
    else:
        routine_file = state.discovery_output_dir / "routine.json"
        if routine_file.exists():
            table.add_row("Routine", "[yellow]● Available[/yellow]", "[dim]Run /discover to load[/dim]")
        else:
            table.add_row("Routine", "[dim]● None[/dim]", "[dim]Run /discover first[/dim]")

    # Parameters
    if state.parameters:
        table.add_row("Parameters", "[green]● Set[/green]", f"{len(state.parameters)} values")
    else:
        table.add_row("Parameters", "[dim]● Empty[/dim]", "[dim]Run /params to configure[/dim]")

    # Last Result
    if state.last_result:
        if state.last_result.get("ok"):
            table.add_row("Last Run", "[green]● Success[/green]", "[dim]View with /result[/dim]")
        else:
            table.add_row("Last Run", "[red]● Failed[/red]", str(state.last_result.get("error", ""))[:30])

    console.print(Panel(pipeline_str, title="Progress", box=box.ROUNDED))
    console.print()
    console.print(table)
    console.print()


def cmd_chrome() -> None:
    """Launch or check Chrome status."""
    console.print()

    if check_chrome_running():
        console.print("[green]✓ Chrome is already running in debug mode[/green]")
        console.print(f"[dim]  Port: {PORT}[/dim]")

        # Show tabs
        try:
            tabs = get_existing_tabs(REMOTE_DEBUGGING_ADDRESS)
            page_tabs = [t for t in tabs if t.get("type") == "page"]
            console.print(f"[dim]  Open tabs: {len(page_tabs)}[/dim]")
            for tab in page_tabs[:3]:
                url = tab.get("url", "")[:50]
                console.print(f"[dim]    • {url}...[/dim]")
        except Exception:
            pass

        state.stage = max(state.stage, PipelineStage.CHROME_READY, key=lambda x: list(PipelineStage).index(x))
        return

    chrome_path = find_chrome_path()
    if not chrome_path:
        console.print("[yellow]⚠️  Chrome not found automatically[/yellow]")
        console.print(f"[dim]Please launch Chrome manually with:[/dim]")
        console.print(f"[cyan]--remote-debugging-port={PORT}[/cyan]")
        return

    # Launch Chrome
    console.print("[dim]Launching Chrome...[/dim]")

    if platform.system() == "Windows":
        chrome_user_dir = os.path.expandvars(r"%USERPROFILE%\tmp\chrome")
    else:
        chrome_user_dir = os.path.expanduser("~/tmp/chrome")

    os.makedirs(chrome_user_dir, exist_ok=True)

    chrome_args = [
        chrome_path,
        f"--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={chrome_user_dir}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("Starting Chrome...", total=None)

        try:
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0
            state.chrome_process = subprocess.Popen(
                chrome_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )

            for _ in range(10):
                if check_chrome_running():
                    break
                time.sleep(0.5)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return

    if check_chrome_running():
        console.print("[green]✓ Chrome launched successfully![/green]")
        state.stage = PipelineStage.CHROME_READY
    else:
        console.print("[red]✗ Chrome failed to start[/red]")


def cmd_monitor() -> None:
    """Start browser monitoring."""
    console.print()

    if not check_chrome_running():
        console.print("[yellow]⚠️  Chrome not running. Launch with /chrome first[/yellow]")
        return

    # Check existing data
    if state.cdp_captures_dir.exists() and any(state.cdp_captures_dir.iterdir()):
        console.print(f"[yellow]⚠️  {state.cdp_captures_dir} contains existing data[/yellow]")
        if Confirm.ask("Clear existing data?", default=True):
            clear_directory(state.cdp_captures_dir)
            console.print("[green]✓ Cleared[/green]")

    console.print()
    console.print(Panel(
        "[bold]Instructions:[/bold]\n\n"
        "1. A new incognito tab will open\n"
        "2. Navigate to your target website\n"
        "3. Perform the actions you want to automate\n"
        "4. Press [cyan]Ctrl+C[/cyan] when done",
        title="📡 Browser Monitoring",
        border_style="cyan"
    ))
    console.print()

    if not Confirm.ask("Start monitoring?", default=True):
        return

    console.print()
    state.stage = PipelineStage.MONITORING

    monitor = BrowserMonitor(
        remote_debugging_address=REMOTE_DEBUGGING_ADDRESS,
        output_dir=str(state.cdp_captures_dir),
        url="about:blank",
        incognito=True,
    )
    state.monitor = monitor

    try:
        monitor.start()
        console.print("[green]✓ Monitoring started![/green]")
        console.print("[dim]Perform your actions in the browser...[/dim]")
        console.print("[yellow]Press Ctrl+C when done[/yellow]")
        console.print()

        # Show live stats
        with Live(console=console, refresh_per_second=1) as live:
            start_time = time.time()
            while True:
                elapsed = time.time() - start_time
                stats = get_capture_stats()

                status_text = Text()
                status_text.append("⏱️  ", style="cyan")
                status_text.append(f"{elapsed:.0f}s", style="bold")
                status_text.append("  │  📦 ", style="dim")
                status_text.append(f"{stats['transactions']} transactions", style="green" if stats['transactions'] > 0 else "dim")

                live.update(Panel(status_text, box=box.ROUNDED))
                time.sleep(1)

    except KeyboardInterrupt:
        console.print()
        console.print("[dim]Stopping monitor...[/dim]")
    finally:
        summary = monitor.stop()
        state.capture_summary = summary
        state.monitor = None

    stats = get_capture_stats()
    console.print()
    console.print(Panel(
        f"[bold green]✓ Monitoring Complete![/bold green]\n\n"
        f"Duration: {summary.get('duration', 0):.1f}s\n"
        f"Transactions: {stats['transactions']}\n"
        f"Storage entries: {stats['storage_entries']}",
        border_style="green"
    ))

    if stats["has_data"]:
        state.stage = PipelineStage.CAPTURED


def cmd_discover() -> None:
    """Run routine discovery."""
    console.print()

    # Check prerequisites
    stats = get_capture_stats()
    if not stats["has_data"]:
        console.print("[yellow]⚠️  No capture data found. Run /monitor first[/yellow]")
        return

    # Check for existing routine
    routine_file = state.discovery_output_dir / "routine.json"
    if routine_file.exists():
        console.print(f"[yellow]Found existing routine at {routine_file}[/yellow]")
        choice = Prompt.ask(
            "What would you like to do?",
            choices=["load", "overwrite", "cancel"],
            default="load"
        )

        if choice == "load":
            try:
                state.routine = Routine.model_validate_json(routine_file.read_text())
                state.stage = PipelineStage.DISCOVERED
                console.print(f"[green]✓ Loaded routine: {state.routine.name}[/green]")
                return
            except Exception as e:
                console.print(f"[red]Error loading routine: {e}[/red]")
                return
        elif choice == "cancel":
            return
        # else overwrite - continue

    # Collect task description
    console.print()
    console.print(Panel(
        "[bold]Define Your Routine[/bold]\n\n"
        "We'll analyze your recorded session and create a reusable automation routine.",
        border_style="cyan"
    ))
    console.print()

    console.print("[cyan]What data should this routine return?[/cyan]")
    console.print("[dim](e.g., flight prices, product details, search results)[/dim]")
    data_output = Prompt.ask("→")
    if not data_output:
        console.print("[yellow]Cancelled[/yellow]")
        return

    console.print()
    console.print("[cyan]What inputs or filters does it need?[/cyan]")
    console.print("[dim](e.g., search query, date range, location)[/dim]")
    inputs_needed = Prompt.ask("→", default="")

    console.print()
    console.print("[cyan]Any additional context?[/cyan]")
    console.print("[dim](optional - notes, special handling, edge cases)[/dim]")
    extra_context = Prompt.ask("→", default="")

    # Build task description
    task_parts = [f"Create a web routine that returns {data_output}"]
    if inputs_needed:
        task_parts.append(f"given {inputs_needed}")
    if extra_context:
        task_parts.append(f"({extra_context})")
    task = " ".join(task_parts) + "."

    console.print()
    console.print(Panel(f"[bold]Task:[/bold] {task}", border_style="yellow"))
    console.print()

    if not Confirm.ask("Start discovery?", default=True):
        return

    # Initialize hacker if needed
    if not state.hacker:
        console.print("[dim]Initializing WebHacker...[/dim]")
        try:
            state.hacker = WebHacker(
                remote_debugging_address=REMOTE_DEBUGGING_ADDRESS,
                llm_model="gpt-4.1",
            )
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            console.print("[dim]Make sure OPENAI_API_KEY is set[/dim]")
            return

    # Run discovery
    state.stage = PipelineStage.DISCOVERING
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task_id = progress.add_task("Running AI discovery agent...", total=None)

        try:
            result = state.hacker.discover_routine(
                task=task,
                cdp_captures_dir=str(state.cdp_captures_dir),
                output_dir=str(state.discovery_output_dir),
            )
            state.routine = result.routine
            state.stage = PipelineStage.DISCOVERED

        except Exception as e:
            console.print(f"[red]Discovery failed: {e}[/red]")
            state.stage = PipelineStage.CAPTURED
            return

    console.print()
    console.print(Panel(
        f"[bold green]✓ Routine Discovered![/bold green]\n\n"
        f"[bold]Name:[/bold] {state.routine.name}\n"
        f"[bold]Operations:[/bold] {len(state.routine.operations)}\n"
        f"[bold]Parameters:[/bold] {len(state.routine.parameters)}",
        border_style="green"
    ))

    # Auto-load test parameters if available
    test_params_file = state.discovery_output_dir / "test_parameters.json"
    if test_params_file.exists():
        try:
            state.parameters = json.loads(test_params_file.read_text())
            console.print(f"[dim]Loaded test parameters from {test_params_file}[/dim]")
        except Exception:
            pass


def cmd_routine() -> None:
    """Show current routine details."""
    console.print()

    if not state.routine:
        console.print("[yellow]No routine loaded. Run /discover first[/yellow]")
        return

    r = state.routine

    # Basic info
    console.print(Panel(
        f"[bold]{r.name}[/bold]\n\n"
        f"{r.description or '[dim]No description[/dim]'}",
        title="📋 Routine Details",
        border_style="cyan"
    ))

    # Parameters
    if r.parameters:
        console.print()
        param_table = Table(title="Parameters", box=box.ROUNDED)
        param_table.add_column("Name", style="cyan")
        param_table.add_column("Type")
        param_table.add_column("Required")
        param_table.add_column("Default")
        param_table.add_column("Description")

        for p in r.parameters:
            param_table.add_row(
                p.name,
                p.type,
                "✓" if p.required else "",
                str(p.default) if p.default else "",
                (p.description or "")[:40]
            )

        console.print(param_table)

    # Operations
    console.print()
    op_table = Table(title="Operations", box=box.ROUNDED)
    op_table.add_column("#", style="dim")
    op_table.add_column("Type", style="cyan")
    op_table.add_column("Details")

    for i, op in enumerate(r.operations):
        details = ""
        if op.type == "fetch":
            method = op.endpoint.method if hasattr(op, 'endpoint') else "?"
            url = (op.endpoint.url if hasattr(op, 'endpoint') else "")[:40]
            details = f"{method} {url}..."
        elif op.type == "navigate":
            details = (op.url or "")[:50]
        elif op.type == "extract":
            details = f"→ {op.session_storage_key or 'output'}"

        op_table.add_row(str(i + 1), op.type, details)

    console.print(op_table)


def cmd_params() -> None:
    """Show and edit execution parameters."""
    console.print()

    if not state.routine:
        console.print("[yellow]No routine loaded. Run /discover first[/yellow]")
        return

    # Show current parameters
    if state.parameters:
        console.print("[bold]Current Parameters:[/bold]")
        for key, value in state.parameters.items():
            display_val = value if len(str(value)) < 50 else str(value)[:50] + "..."
            console.print(f"  [cyan]{key}[/cyan]: {display_val}")
        console.print()

    if not Confirm.ask("Edit parameters?", default=not bool(state.parameters)):
        return

    console.print()
    console.print("[dim]Enter new values (press Enter to keep current)[/dim]")
    console.print()

    new_params = {}
    for param in state.routine.parameters:
        current = state.parameters.get(param.name, param.default or "")
        hint = f" [current: {str(current)[:30]}]" if current else ""

        console.print(f"[cyan]{param.name}[/cyan]{hint}")
        if param.description:
            console.print(f"[dim]  {param.description}[/dim]")

        value = Prompt.ask("  →", default=str(current) if current else "")
        if value:
            new_params[param.name] = value
        elif param.required and not current:
            console.print(f"[red]  ⚠️  {param.name} is required![/red]")
            return
        elif current:
            new_params[param.name] = current

        console.print()

    state.parameters = new_params
    console.print("[green]✓ Parameters updated[/green]")


def cmd_execute() -> None:
    """Execute the routine."""
    console.print()

    if not state.routine:
        console.print("[yellow]No routine loaded. Run /discover first[/yellow]")
        return

    if not check_chrome_running():
        console.print("[yellow]Chrome not running. Launching...[/yellow]")
        cmd_chrome()
        if not check_chrome_running():
            return

    # Check parameters
    missing = []
    for param in state.routine.parameters:
        if param.required and param.name not in state.parameters:
            missing.append(param.name)

    if missing:
        console.print(f"[yellow]Missing required parameters: {', '.join(missing)}[/yellow]")
        console.print("[dim]Run /params to configure[/dim]")
        return

    # Show execution preview
    console.print(Panel(
        f"[bold]Routine:[/bold] {state.routine.name}\n"
        f"[bold]Operations:[/bold] {len(state.routine.operations)}\n"
        f"[bold]Parameters:[/bold] {json.dumps(state.parameters, indent=2)}",
        title="🚀 Execution Preview",
        border_style="yellow"
    ))
    console.print()

    if not Confirm.ask("Execute routine?", default=True):
        return

    # Initialize hacker if needed
    if not state.hacker:
        state.hacker = WebHacker(
            remote_debugging_address=REMOTE_DEBUGGING_ADDRESS,
            llm_model="gpt-4.1",
        )

    # Get tab to reuse
    try:
        tabs = get_existing_tabs(REMOTE_DEBUGGING_ADDRESS)
        page_tabs = [t for t in tabs if t.get("type") == "page"]
        tab_id = page_tabs[0]["id"] if page_tabs else None
    except Exception:
        tab_id = None

    state.stage = PipelineStage.EXECUTING
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task_id = progress.add_task("Executing routine...", total=None)

        try:
            result = state.hacker.execute_routine(
                routine=state.routine,
                parameters=state.parameters,
                timeout=60.0,
                close_tab_when_done=False,
                tab_id=tab_id,
            )

            state.last_result = {
                "ok": result.ok,
                "data": result.data,
                "error": result.error,
                "placeholder_resolution": result.placeholder_resolution,
                "warnings": result.warnings,
            }

        except Exception as e:
            state.last_result = {"ok": False, "error": str(e)}
            console.print(f"[red]Execution error: {e}[/red]")
            return

    console.print()

    if state.last_result["ok"]:
        state.stage = PipelineStage.COMPLETED

        # Save result
        output_file = state.discovery_output_dir / "execution_result.json"
        output_file.write_text(json.dumps(state.last_result, indent=2))

        console.print(Panel(
            f"[bold green]✓ Execution Successful![/bold green]\n\n"
            f"Result saved to: {output_file}",
            border_style="green"
        ))

        # Preview data
        if state.last_result.get("data"):
            console.print()
            data_str = json.dumps(state.last_result["data"], indent=2)
            preview = data_str[:1000] + "..." if len(data_str) > 1000 else data_str
            console.print(Panel(
                Syntax(preview, "json", theme="monokai"),
                title="📄 Result Preview",
                border_style="cyan"
            ))
    else:
        console.print(Panel(
            f"[bold red]✗ Execution Failed[/bold red]\n\n"
            f"Error: {state.last_result.get('error', 'Unknown error')}",
            border_style="red"
        ))


def cmd_captures() -> None:
    """Show captured data summary."""
    console.print()

    stats = get_capture_stats()

    if not stats["has_data"]:
        console.print("[yellow]No capture data found. Run /monitor first[/yellow]")
        return

    console.print(Panel(
        f"[bold]Capture Directory:[/bold] {state.cdp_captures_dir}\n\n"
        f"[cyan]Network Transactions:[/cyan] {stats['transactions']}\n"
        f"[cyan]Storage Entries:[/cyan] {stats['storage_entries']}",
        title="📦 Captured Data",
        border_style="cyan"
    ))

    # Show some transaction URLs
    transactions_dir = state.cdp_captures_dir / "network" / "transactions"
    if transactions_dir.exists():
        console.print()
        console.print("[bold]Recent Transactions:[/bold]")

        for i, tx_dir in enumerate(sorted(transactions_dir.iterdir(), reverse=True)[:5]):
            request_file = tx_dir / "request.json"
            if request_file.exists():
                try:
                    req = json.loads(request_file.read_text())
                    method = req.get("method", "?")
                    url = req.get("url", "?")[:60]
                    console.print(f"  [dim]{method}[/dim] {url}...")
                except Exception:
                    pass


def print_help() -> None:
    """Print help."""
    console.print()
    console.print(Panel(
        """[bold]Pipeline Commands:[/bold]
  [cyan]/chrome[/cyan]    - Launch Chrome in debug mode
  [cyan]/monitor[/cyan]   - Start capturing browser activity
  [cyan]/discover[/cyan]  - Run AI to create routine from captures
  [cyan]/execute[/cyan]   - Run the discovered routine

[bold]Inspection Commands:[/bold]
  [cyan]/status[/cyan]    - Show current pipeline status
  [cyan]/routine[/cyan]   - Show routine details
  [cyan]/params[/cyan]    - View/edit execution parameters
  [cyan]/captures[/cyan]  - Show captured data summary

[bold]General:[/bold]
  [cyan]/clear[/cyan]     - Clear screen
  [cyan]/help[/cyan]      - Show this help
  [cyan]/quit[/cyan]      - Exit

[bold]Quick Workflow:[/bold]
  1. /chrome   → Launch browser
  2. /monitor  → Record your actions
  3. /discover → AI creates routine
  4. /execute  → Run it!""",
        title="🕷️ Web Hacker CLI",
        border_style="blue"
    ))
    console.print()


def main():
    print_header()

    # Check initial state
    if check_chrome_running():
        state.stage = PipelineStage.CHROME_READY

    stats = get_capture_stats()
    if stats["has_data"]:
        state.stage = max(state.stage, PipelineStage.CAPTURED, key=lambda x: list(PipelineStage).index(x))

    routine_file = state.discovery_output_dir / "routine.json"
    if routine_file.exists():
        try:
            state.routine = Routine.model_validate_json(routine_file.read_text())
            state.stage = max(state.stage, PipelineStage.DISCOVERED, key=lambda x: list(PipelineStage).index(x))

            # Load test params too
            test_params = state.discovery_output_dir / "test_parameters.json"
            if test_params.exists():
                state.parameters = json.loads(test_params.read_text())
        except Exception:
            pass

    print_status()
    print_help()

    while True:
        try:
            # Mini status prompt
            stage_icons = {
                PipelineStage.NOT_STARTED: "⚪",
                PipelineStage.CHROME_READY: "🌐",
                PipelineStage.MONITORING: "📡",
                PipelineStage.CAPTURED: "📦",
                PipelineStage.DISCOVERING: "🔍",
                PipelineStage.DISCOVERED: "✨",
                PipelineStage.EXECUTING: "🚀",
                PipelineStage.COMPLETED: "✅",
            }
            icon = stage_icons.get(state.stage, "⚪")

            user_input = console.input(f"[dim]{icon}[/dim] [bold green]web-hacker>[/bold green] ").strip()

            if not user_input:
                continue

            if user_input.startswith("/"):
                cmd = user_input.lower()

                if cmd in ["/quit", "/exit", "/q"]:
                    console.print("[yellow]Goodbye![/yellow]")
                    break
                elif cmd == "/status":
                    print_status()
                elif cmd == "/chrome":
                    cmd_chrome()
                elif cmd == "/monitor":
                    cmd_monitor()
                elif cmd == "/discover":
                    cmd_discover()
                elif cmd == "/execute":
                    cmd_execute()
                elif cmd == "/routine":
                    cmd_routine()
                elif cmd == "/params":
                    cmd_params()
                elif cmd == "/captures":
                    cmd_captures()
                elif cmd == "/clear":
                    console.clear()
                    print_header()
                elif cmd == "/help":
                    print_help()
                else:
                    console.print(f"[red]Unknown command: {cmd}[/red]")
                    console.print("[dim]Type /help for available commands[/dim]")
            else:
                console.print("[dim]Type /help for commands, or start with /chrome[/dim]")

        except KeyboardInterrupt:
            console.print("\n[yellow]Use /quit to exit[/yellow]")
        except EOFError:
            break


if __name__ == "__main__":
    main()
