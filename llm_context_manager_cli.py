#!/usr/bin/env python3
"""
Interactive CLI for testing LLMContextManager.

Commands:
  /stats     - Show current context stats (T_current, T_drain, T_max, etc.)
  /messages  - Show all messages in context
  /active    - Show what would be sent to LLM right now
  /summary   - Show the last summary if present
  /summaries - Show all summaries
  /logs      - Show summary logs
  /drain     - Force context drain (summarize and truncate)
  /paste     - Send clipboard contents as message
  /clear     - Clear screen
  /help      - Show this help
  /quit      - Exit

Otherwise, type your message to chat with the LLM.
"""

import logging
import os
import subprocess
import sys
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown
from rich.logging import RichHandler
from rich import box

from llm_context_manager import LLMContextManager, MessageRole
from llm_context_manager import summary_logger  # renamed to llm_context_manager logger

# setup summary logger with in-memory handler to capture logs
class LogCapture(logging.Handler):
    """Handler that captures log records in memory."""
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def clear(self) -> None:
        self.records.clear()

log_capture = LogCapture()
log_capture.setLevel(logging.DEBUG)
log_capture.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
summary_logger.addHandler(log_capture)

console = Console()


def print_stats(manager: LLMContextManager) -> None:
    """Print current context manager stats."""
    stats = manager.get_stats()

    # create a visual progress bar for context usage
    t_current = stats["T_current"]
    t_drain = stats["T_drain"]
    t_max = stats["T_max"]
    t_target = stats["T_target"]

    # determine color based on thresholds
    if t_current > t_max:
        color = "red bold"
        status = "OVER MAX - WILL DRAIN"
    elif t_current > t_drain:
        color = "yellow"
        status = "ABOVE DRAIN - SUMMARIZING"
    elif t_current > t_target:
        color = "cyan"
        status = "NORMAL"
    else:
        color = "green"
        status = "LOW"

    table = Table(title="Context Manager Stats", box=box.ROUNDED)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_column("Status", justify="center")

    # context size row with bar
    pct_of_max = min(t_current / t_max * 100, 100)
    bar_width = 30
    filled = int(pct_of_max / 100 * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)

    table.add_row(
        "T_current",
        f"[{color}]{t_current:,}[/{color}]",
        f"[{color}]{bar} {pct_of_max:.1f}%[/{color}]"
    )
    table.add_row("T_target", f"{t_target:,}", "[dim]after drain target[/dim]")
    table.add_row("T_drain", f"{t_drain:,}", "[dim]async summary threshold[/dim]")
    table.add_row("T_max", f"{t_max:,}", "[dim]forced drain threshold[/dim]")
    table.add_row("T_summary_max", f"{stats['T_summary_max']:,}", "[dim]max summary size[/dim]")
    table.add_row("", "", "")
    table.add_row("Messages", str(stats["message_count"]), "")
    table.add_row("Summaries", str(stats["summary_count"]), "")
    table.add_row("Anchor Index", str(stats["current_anchor_idx"] or "None"), "")
    table.add_row("Has Response ID", "✓" if stats["has_response_id"] else "✗",
                  "[green]continuation mode[/green]" if stats["has_response_id"] else "[yellow]fresh context[/yellow]")
    table.add_row("Summarizing", "⏳" if stats["summarization_in_progress"] else "✗", "")

    console.print()
    console.print(table)
    console.print(f"\n[bold]Status:[/bold] [{color}]{status}[/{color}]")
    console.print()


def print_messages(manager: LLMContextManager) -> None:
    """Print all messages in the conversation."""
    console.print()
    console.print(Panel("[bold]All Messages in History[/bold]", style="blue"))

    if not manager.messages:
        console.print("[dim]No messages yet[/dim]")
        return

    for i, msg in enumerate(manager.messages):
        # highlight anchor
        anchor_marker = ""
        if manager.current_anchor_idx is not None and i == manager.current_anchor_idx:
            anchor_marker = " [red bold]◀ ANCHOR[/red bold]"

        role_colors = {
            MessageRole.SYSTEM: "magenta",
            MessageRole.USER: "green",
            MessageRole.ASSISTANT: "cyan"
        }
        color = role_colors.get(msg.role, "white")

        # truncate long messages for display
        content = msg.content
        if len(content) > 200:
            content = content[:200] + "..."

        console.print(f"[dim][{i}][/dim] [{color} bold]{msg.role.value.upper()}[/{color} bold]{anchor_marker}")
        console.print(f"    [dim]({len(msg.content):,} chars)[/dim] {content}")
        console.print()


def print_active_context(manager: LLMContextManager) -> None:
    """Print what would be sent to the LLM right now."""
    console.print()
    console.print(Panel("[bold]Active Context (what would be sent to LLM)[/bold]", style="yellow"))

    # simulate building input
    llm_input = manager._build_llm_input()

    total_chars = 0
    for i, msg in enumerate(llm_input):
        role = msg["role"]
        content = msg["content"]
        total_chars += len(content)

        role_colors = {
            "system": "magenta",
            "user": "green",
            "assistant": "cyan"
        }
        color = role_colors.get(role, "white")

        # truncate for display
        display_content = content if len(content) <= 300 else content[:300] + "..."

        console.print(f"[dim][{i}][/dim] [{color} bold]{role.upper()}[/{color} bold]")
        console.print(f"    [dim]({len(content):,} chars)[/dim]")

        # check if this is a summary injection
        if "<conversation_summary>" in content:
            console.print("    [yellow]📝 SUMMARY CONTEXT INJECTED[/yellow]")
        else:
            console.print(f"    {display_content}")
        console.print()

    console.print(f"[bold]Total active context: {total_chars:,} chars[/bold]")
    console.print()


def print_summary(manager: LLMContextManager) -> None:
    """Print the last summary."""
    console.print()

    if not manager.summaries:
        console.print(Panel("[dim]No summaries yet[/dim]", title="Last Summary", style="yellow"))
        return

    last_summary = manager.summaries[-1]
    # escape summary content to prevent Rich from interpreting brackets as markup
    escaped_summary = escape(last_summary.summary)
    console.print(Panel(
        f"[bold]Anchor Index:[/bold] {last_summary.anchor_message_idx}\n\n{escaped_summary}",
        title="Last Summary",
        style="yellow"
    ))
    console.print()


def print_all_summaries(manager: LLMContextManager) -> None:
    """Print all summaries."""
    console.print()
    console.print(Panel("[bold]All Summaries[/bold]", style="yellow"))

    if not manager.summaries:
        console.print("[dim]No summaries yet[/dim]")
        return

    for i, summary in enumerate(manager.summaries):
        console.print(f"[bold]Summary #{i + 1}[/bold] (anchor @ message {summary.anchor_message_idx})")
        truncated = summary.summary[:500] + ('...' if len(summary.summary) > 500 else '')
        console.print(f"[dim]{escape(truncated)}[/dim]")
        console.print()


def print_logs() -> None:
    """Print captured summary logs."""
    console.print()
    console.print(Panel("[bold]Summary Logs[/bold]", style="red"))

    if not log_capture.records:
        console.print("[dim]No logs yet[/dim]")
        return

    for record in log_capture.records:
        level_colors = {
            "DEBUG": "dim",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red bold",
        }
        color = level_colors.get(record.levelname, "white")
        timestamp = log_capture.formatter.formatTime(record, datefmt="%H:%M:%S")
        console.print(f"[dim]{timestamp}[/dim] [{color}][{record.levelname}][/{color}] {record.getMessage()}")

    console.print()


def get_clipboard() -> str | None:
    """Get clipboard contents. Works on macOS."""
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def print_help() -> None:
    """Print help."""
    console.print()
    console.print(Panel(
        """[bold]Commands:[/bold]
  [cyan]/stats[/cyan]     - Show current context stats (T_current, T_drain, T_max, etc.)
  [cyan]/messages[/cyan]  - Show all messages in context
  [cyan]/active[/cyan]    - Show what would be sent to LLM right now
  [cyan]/summary[/cyan]   - Show the last summary if present
  [cyan]/summaries[/cyan] - Show all summaries
  [cyan]/logs[/cyan]      - Show summary logs (debug info)
  [cyan]/drain[/cyan]     - Force context drain (summarize and truncate)
  [cyan]/paste[/cyan]     - Send clipboard contents as message
  [cyan]/clear[/cyan]     - Clear screen
  [cyan]/help[/cyan]      - Show this help
  [cyan]/quit[/cyan]      - Exit

[bold]Just type to chat![/bold] The context manager handles everything automatically.""",
        title="LLM Context Manager CLI",
        style="blue"
    ))
    console.print()


def main():
    console.print()
    console.print("[bold blue]═══════════════════════════════════════════════════════════════[/bold blue]")
    console.print("[bold blue]          LLM Context Manager - Interactive CLI                [/bold blue]")
    console.print("[bold blue]═══════════════════════════════════════════════════════════════[/bold blue]")
    console.print()

    # create manager with lower thresholds for easier testing
    # (summaries start generating after ~5k chars instead of 80k)
    manager = LLMContextManager(
        T_max=20_000,        # 20k chars max (force drain)
        T_drain=5_000,       # 5k start async summarization
        T_target=8_000,      # 8k target after drain
        T_summary_max=4_000  # 4k max summary size
    )

    # start session
    system_prompt = """You are a helpful AI assistant. Be concise but thorough in your responses.
You are being used to test a context management system, so feel free to generate longer responses
when asked to help test the context limits."""

    manager.start_session(system_prompt)

    console.print("[green]✓ Session started![/green]")
    console.print(f"[dim]System prompt: {len(system_prompt)} chars[/dim]")
    console.print()
    print_stats(manager)
    print_help()

    while True:
        try:
            # show mini status in prompt
            stats = manager.get_stats()
            t_pct = stats["T_current"] / stats["T_max"] * 100

            if t_pct > 100:
                status_color = "red"
            elif stats["T_current"] > stats["T_drain"]:
                status_color = "yellow"
            else:
                status_color = "green"

            console.print(f"[dim][{status_color}]{stats['T_current']:,}/{stats['T_max']:,} ({t_pct:.0f}%)[/{status_color}][/dim]", end=" ")
            user_input = console.input("[bold green]You>[/bold green] ").strip()

            if not user_input:
                continue

            # handle commands
            if user_input.startswith("/"):
                cmd = user_input.lower()

                if cmd == "/quit" or cmd == "/exit" or cmd == "/q":
                    console.print("[yellow]Goodbye![/yellow]")
                    break
                elif cmd == "/stats":
                    print_stats(manager)
                elif cmd == "/messages":
                    print_messages(manager)
                elif cmd == "/active":
                    print_active_context(manager)
                elif cmd == "/summary":
                    print_summary(manager)
                elif cmd == "/summaries":
                    print_all_summaries(manager)
                elif cmd == "/logs":
                    print_logs()
                elif cmd == "/drain":
                    console.print("[yellow]⏳ Forcing context drain...[/yellow]")
                    pre_stats = manager.get_stats()
                    manager.force_drain()
                    post_stats = manager.get_stats()
                    console.print(f"[green]✓ Context drained: {pre_stats['T_current']:,} → {post_stats['T_current']:,} chars[/green]")
                    console.print(f"[dim]Anchor moved to message {post_stats['current_anchor_idx']}[/dim]")
                    print_stats(manager)
                elif cmd == "/paste":
                    clipboard_content = get_clipboard()
                    if not clipboard_content:
                        console.print("[red]Failed to read clipboard (is it empty?)[/red]")
                        continue
                    console.print(f"[dim]📋 Clipboard: {len(clipboard_content):,} chars[/dim]")
                    # preview first 200 chars
                    preview = clipboard_content[:200] + "..." if len(clipboard_content) > 200 else clipboard_content
                    console.print(f"[dim]{preview}[/dim]")
                    user_input = clipboard_content  # fall through to send as message
                elif cmd == "/clear":
                    console.clear()
                elif cmd == "/help":
                    print_help()
                else:
                    console.print(f"[red]Unknown command: {cmd}[/red]")
                    console.print("[dim]Type /help for available commands[/dim]")
                    continue

                # commands that don't set user_input should continue
                if cmd != "/paste":
                    continue

            # regular message - send to LLM
            console.print()
            console.print("[dim]Sending to LLM...[/dim]")

            # show pre-call stats
            pre_stats = manager.get_stats()

            try:
                response = manager.get_response(user_input)
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
                continue

            # show response
            console.print()
            console.print("[bold cyan]Assistant>[/bold cyan]")
            console.print(Markdown(response))
            console.print()

            # show post-call stats delta
            post_stats = manager.get_stats()
            delta = post_stats["T_current"] - pre_stats["T_current"]

            console.print(f"[dim]─────────────────────────────────────────────────────[/dim]")
            console.print(f"[dim]Context: {pre_stats['T_current']:,} → {post_stats['T_current']:,} (+{delta:,} chars)[/dim]")

            if post_stats["summarization_in_progress"]:
                console.print("[yellow]⏳ Async summarization in progress...[/yellow]")

            if pre_stats["has_response_id"] != post_stats["has_response_id"]:
                if post_stats["has_response_id"]:
                    console.print("[green]🔗 Now in continuation mode[/green]")
                else:
                    console.print("[yellow]⚠️ Context was drained - fresh start[/yellow]")

            if pre_stats["current_anchor_idx"] != post_stats["current_anchor_idx"]:
                console.print(f"[yellow]📍 Anchor moved: {pre_stats['current_anchor_idx']} → {post_stats['current_anchor_idx']}[/yellow]")

            if pre_stats["summary_count"] != post_stats["summary_count"]:
                console.print(f"[green]📝 New summary generated! (total: {post_stats['summary_count']})[/green]")

            console.print()

        except KeyboardInterrupt:
            console.print("\n[yellow]Use /quit to exit[/yellow]")
        except EOFError:
            break


if __name__ == "__main__":
    main()
