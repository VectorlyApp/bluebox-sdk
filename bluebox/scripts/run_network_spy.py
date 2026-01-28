#!/usr/bin/env python3
"""
bluebox/scripts/run_network_spy.py

Interactive CLI for the Network Spy agent.

Usage:
    python bluebox/scripts/run_network_spy.py --har-path ./cdp_captures/network/network.har
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from bluebox.agents.network_spy import NetworkSpyAgent
from bluebox.llms.infra.har_data_store import HarDataStore
from bluebox.data_models.llms.interaction import (
    ChatRole,
    EmittedMessage,
    ChatResponseEmittedMessage,
    ErrorEmittedMessage,
    ToolInvocationResultEmittedMessage,
    PendingToolInvocation,
    ToolInvocationStatus,
)
from bluebox.data_models.llms.vendors import OpenAIModel
from bluebox.utils.logger import get_logger


logger = get_logger(name=__name__)
console = Console()


BANNER = """\
[bold cyan]╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                                              ║
║ ▄▄▄   ▄▄                                                    ▄▄                    ▄▄▄▄                       ║
║ ███   ██              ██                                    ██                  ▄█▀▀▀▀█                      ║
║ ██▀█  ██   ▄████▄   ███████  ██      ██  ▄████▄    ██▄████  ██ ▄██▀             ██▄       ██▄███▄   ▀██  ███ ║
║ ██ ██ ██  ██▄▄▄▄██    ██     ▀█  ██  █▀ ██▀  ▀██   ██▀      ██▄██                ▀████▄   ██▀  ▀██   ██▄ ██  ║
║ ██  █▄██  ██▀▀▀▀▀▀    ██      ██▄██▄██  ██    ██   ██       ██▀██▄                   ▀██  ██    ██    ████▀  ║
║ ██   ███  ▀██▄▄▄▄█    ██▄▄▄   ▀██  ██▀  ▀██▄▄██▀   ██       ██  ▀█▄             █▄▄▄▄▄█▀  ███▄▄██▀     ███   ║
║ ▀▀   ▀▀▀    ▀▀▀▀▀      ▀▀▀▀    ▀▀  ▀▀     ▀▀▀▀     ▀▀       ▀▀   ▀▀▀             ▀▀▀▀▀    ██ ▀▀▀       ██    ║
║                                                                                           ██         ███     ║
║                                                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════╝[/bold cyan]
"""


def print_welcome(model: str, har_path: str, har_store: HarDataStore) -> None:
    """Print welcome message with HAR stats."""
    console.print(BANNER)
    console.print()

    stats = har_store.stats

    # Build stats table
    stats_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    stats_table.add_column("Label", style="dim")
    stats_table.add_column("Value", style="white")

    stats_table.add_row("Total Requests", str(stats.total_requests))
    stats_table.add_row("Unique URLs", str(stats.unique_urls))
    stats_table.add_row("Unique Hosts", str(stats.unique_hosts))

    # Methods breakdown
    methods_str = ", ".join(f"{m}: {c}" for m, c in sorted(stats.methods.items(), key=lambda x: -x[1]))
    stats_table.add_row("Methods", methods_str)

    # Status codes breakdown
    status_str = ", ".join(f"{s}: {c}" for s, c in sorted(stats.status_codes.items()))
    stats_table.add_row("Status Codes", status_str)

    # Features
    features = []
    if stats.has_cookies:
        features.append("🍪 Cookies")
    if stats.has_auth_headers:
        features.append("🔐 Auth Headers")
    if stats.has_json_requests:
        features.append("📦 JSON")
    if stats.has_form_data:
        features.append("📝 Form Data")
    if features:
        stats_table.add_row("Features", " ".join(features))

    # Top hosts
    top_hosts = sorted(stats.hosts.items(), key=lambda x: -x[1])[:5]
    if top_hosts:
        hosts_str = ", ".join(f"{h} ({c})" for h, c in top_hosts)
        stats_table.add_row("Top Hosts", hosts_str)

    console.print(Panel(
        stats_table,
        title=f"[bold cyan]HAR Stats[/bold cyan] [dim]({har_path})[/dim]",
        border_style="cyan",
        box=box.ROUNDED,
    ))
    console.print()

    console.print(Panel(
        """[bold]Commands:[/bold]
  [cyan]/reset[/cyan]    Start a new conversation
  [cyan]/help[/cyan]     Show help
  [cyan]/quit[/cyan]     Exit

Just ask questions about the network traffic!""",
        title="[bold cyan]Network Spy[/bold cyan]",
        subtitle=f"[dim]Model: {model}[/dim]",
        border_style="cyan",
        box=box.ROUNDED,
    ))
    console.print()


def print_assistant_message(content: str) -> None:
    """Print an assistant response using markdown rendering."""
    console.print()
    console.print("[bold cyan]Assistant[/bold cyan]")
    console.print()
    console.print(Markdown(content))
    console.print()


def print_error(error: str) -> None:
    """Print an error message."""
    console.print()
    console.print(f"[bold red]⚠ Error:[/bold red] [red]{escape(error)}[/red]")
    console.print()


def print_tool_call(invocation: PendingToolInvocation) -> None:
    """Print a tool call with formatted arguments."""
    args_formatted = json.dumps(invocation.tool_arguments, indent=2)

    content = Text()
    content.append("Tool: ", style="dim")
    content.append(invocation.tool_name, style="bold white")
    content.append("\n\n")
    content.append("Arguments:\n", style="dim")
    content.append(args_formatted, style="white")

    console.print()
    console.print(Panel(
        content,
        title="[bold yellow]⚙ TOOL CALL[/bold yellow]",
        style="yellow",
        box=box.ROUNDED,
    ))


def print_tool_result(
    invocation: PendingToolInvocation,
    result: dict[str, Any] | None,
) -> None:
    """Print a tool invocation result."""
    if invocation.status == ToolInvocationStatus.EXECUTED:
        console.print("[bold green]✓ Tool executed[/bold green]")
        if result:
            result_json = json.dumps(result, indent=2)
            # Limit display to 150 lines
            lines = result_json.split("\n")
            if len(lines) > 150:
                display = "\n".join(lines[:150]) + f"\n... ({len(lines) - 150} more lines)"
            else:
                display = result_json
            console.print(Panel(display, title="Result", style="green", box=box.ROUNDED))

    elif invocation.status == ToolInvocationStatus.FAILED:
        console.print("[bold red]✗ Tool execution failed[/bold red]")
        error = result.get("error") if result else None
        if error:
            console.print(Panel(str(error), title="Error", style="red", box=box.ROUNDED))

    console.print()


class TerminalNetworkSpyChat:
    """Interactive terminal chat interface for the Network Spy Agent."""

    def __init__(
        self,
        har_store: HarDataStore,
        llm_model: OpenAIModel = OpenAIModel.GPT_5_1,
    ) -> None:
        """Initialize the terminal chat interface."""
        self._streaming_started: bool = False
        self._agent = NetworkSpyAgent(
            emit_message_callable=self._handle_message,
            har_data_store=har_store,
            stream_chunk_callable=self._handle_stream_chunk,
            llm_model=llm_model,
        )

    def _handle_stream_chunk(self, chunk: str) -> None:
        """Handle a streaming text chunk from the LLM."""
        if not self._streaming_started:
            console.print()
            console.print("[bold cyan]Assistant[/bold cyan]")
            console.print()
            self._streaming_started = True

        print(chunk, end="", flush=True)

    def _handle_message(self, message: EmittedMessage) -> None:
        """Handle messages emitted by the Network Spy Agent."""
        if isinstance(message, ChatResponseEmittedMessage):
            if self._streaming_started:
                print()
                print()
                self._streaming_started = False
            else:
                print_assistant_message(message.content)

        elif isinstance(message, ToolInvocationResultEmittedMessage):
            # Show tool call and result
            print_tool_call(message.tool_invocation)
            print_tool_result(message.tool_invocation, message.tool_result)

        elif isinstance(message, ErrorEmittedMessage):
            print_error(message.error)

    def run(self) -> None:
        """Run the interactive chat loop."""
        while True:
            try:
                user_input = console.input("[bold green]You>[/bold green] ")

                if not user_input.strip():
                    continue

                cmd = user_input.strip().lower()

                if cmd in ("/quit", "/exit", "/q"):
                    console.print()
                    console.print("[bold cyan]Goodbye![/bold cyan]")
                    console.print()
                    break

                if cmd == "/reset":
                    self._agent.reset()
                    console.print()
                    console.print("[yellow]↺ Conversation reset[/yellow]")
                    console.print()
                    continue

                if cmd in ("/help", "/h", "/?"):
                    console.print()
                    console.print(Panel(
                        """[bold]Commands:[/bold]
  [cyan]/reset[/cyan]    Start a new conversation
  [cyan]/help[/cyan]     Show this help message
  [cyan]/quit[/cyan]     Exit

[bold]Tips:[/bold]
  - Ask about specific endpoints, headers, or cookies
  - Request a summary of API calls
  - Ask about authentication patterns""",
                        title="[bold cyan]Help[/bold cyan]",
                        border_style="cyan",
                        box=box.ROUNDED,
                    ))
                    console.print()
                    continue

                self._agent.process_new_message(user_input, ChatRole.USER)

            except KeyboardInterrupt:
                console.print()
                console.print("[cyan]Interrupted. Goodbye![/cyan]")
                console.print()
                break

            except EOFError:
                console.print()
                console.print("[cyan]Goodbye![/cyan]")
                console.print()
                break


def main() -> None:
    """Run the Network Spy agent interactively."""
    parser = argparse.ArgumentParser(
        description="Network Spy - Interactive HAR file analyzer"
    )
    parser.add_argument(
        "--har-path",
        type=str,
        required=True,
        help="Path to the HAR file to analyze",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-5.1",
        help="LLM model to use (default: gpt-5.1)",
    )
    args = parser.parse_args()

    # Load HAR file
    har_path = Path(args.har_path)
    if not har_path.exists():
        console.print(f"[bold red]Error: HAR file not found: {har_path}[/bold red]")
        sys.exit(1)

    console.print(f"[dim]Loading HAR file: {har_path}[/dim]")
    har_content = har_path.read_text()

    # Parse HAR into data store
    try:
        har_store = HarDataStore(har_content)
    except ValueError as e:
        console.print(f"[bold red]Error parsing HAR file: {e}[/bold red]")
        sys.exit(1)

    # Map model string to enum
    model_map = {
        "gpt-5.1": OpenAIModel.GPT_5_1,
    }
    llm_model = model_map.get(args.model, OpenAIModel.GPT_5_1)

    print_welcome(args.model, str(har_path), har_store)

    chat = TerminalNetworkSpyChat(
        har_store=har_store,
        llm_model=llm_model,
    )
    chat.run()


if __name__ == "__main__":
    main()
