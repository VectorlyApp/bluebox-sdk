"""
web_hacker/scripts/browser_monitor.py

CDP-based web scraper that blocks trackers and captures network requests.
Uses async CDP monitoring with callback-based event handling.
"""

import argparse
import asyncio
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from web_hacker.cdp.async_cdp import AsyncCDPSession, FileEventWriter
from web_hacker.cdp.connection import cdp_new_tab, dispose_context
from web_hacker.data_models.routine.endpoint import ResourceType
from web_hacker.utils.logger import get_logger

logger = get_logger(__name__)

# ---- Configuration ----

BLOCK_PATTERNS = [
    "*://*.doubleclick.net/*",
    "*://*.googletagmanager.com/*",
    "*://*.google-analytics.com/*",
    "*://*.g.doubleclick.net/*",
    "*://*.facebook.com/tr/*",
    "*://connect.facebook.net/*",
    "*://tr.snapchat.com/*",
    "*://sc-static.net/*",
    "*://*.scorecardresearch.com/*",
    "*://*.quantserve.com/*",
    "*://*.krxd.net/*",
    "*://*.adobedtm.com/*",
    "*://*.omtrdc.net/*",
    "*://*.demdex.net/*",
    "*://*.optimizely.com/*",
    "*://cdn.cookielaw.org/*",
    "*://*.segment.io/*",
    "*://*.mixpanel.com/*",
    "*://*.hotjar.com/*",
    "*://*.clarity.ms/*",
    "*://*.taboola.com/*",
    "*://*.outbrain.com/*",
]

# Default values - can be overridden by command line args
DEFAULT_CAPTURE_RESOURCE_TYPES = {
    ResourceType.XHR,
    ResourceType.FETCH,
    ResourceType.DOCUMENT,
    ResourceType.SCRIPT,
    ResourceType.IMAGE,
    ResourceType.MEDIA
}


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="CDP-based web scraper that blocks trackers and captures network requests. By default, clears all cookies and storage before monitoring.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_cdp.py <TAB_ID>                    # Use existing tab
  python run_cdp.py                             # Create new tab automatically
  python run_cdp.py --incognito                 # Create new incognito tab
  python run_cdp.py --tab-id <TAB_ID> --url https://example.com
  python run_cdp.py -t <TAB_ID> --output-dir ./captures --no-navigate
  python run_cdp.py -t <TAB_ID> --capture-resources XHR Fetch --block-resources Image Font
  python run_cdp.py -t <TAB_ID> --no-clear-all --url https://example.com
  python run_cdp.py -t <TAB_ID> --no-clear-cookies --no-clear-storage

Get TAB_ID from chrome://inspect/#devices or http://127.0.0.1:9222/json
If no TAB_ID is provided, a new tab will be created automatically.
        """
    )

    parser.add_argument(
        "tab_id",
        nargs="?",
        help="Chrome DevTools tab ID (optional - will create new tab if not provided)"
    )

    parser.add_argument(
        "-t", "--tab-id",
        dest="tab_id_alt",
        help="Chrome DevTools tab ID (alternative to positional argument)"
    )

    parser.add_argument(
        "--incognito",
        action="store_true",
        help="Create new tab in incognito mode (only used when no tab_id provided)"
    )

    parser.add_argument(
        "-u", "--url",
        default="about:blank",
        help="URL to navigate to (default: about:blank)"
    )

    parser.add_argument(
        "-o", "--output-dir",
        default="./cdp_captures",
        help="Output directory for captures (default: ./cdp_captures)"
    )

    parser.add_argument(
        "--no-navigate",
        action="store_true",
        help="Don't navigate to URL, just attach to existing tab"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=9222,
        help="Chrome DevTools port (default: 9222)"
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Chrome DevTools host (default: 127.0.0.1)"
    )

    parser.add_argument(
        "--clear-output",
        action="store_true",
        help="Clear output directory before starting (default behavior)"
    )

    parser.add_argument(
        "--keep-output",
        action="store_true",
        help="Keep existing files in output directory"
    )


    parser.add_argument(
        "--capture-resources",
        nargs="*",
        default=list(DEFAULT_CAPTURE_RESOURCE_TYPES),
        help="Resource types to capture and save (default: XHR Fetch)"
    )

    parser.add_argument(
        "--no-clear-cookies",
        action="store_true",
        help="Don't clear browser cookies before starting monitoring (cookies are cleared by default)"
    )

    parser.add_argument(
        "--no-clear-storage",
        action="store_true",
        help="Don't clear localStorage and sessionStorage before starting monitoring (storage is cleared by default)"
    )

    parser.add_argument(
        "--no-clear-all",
        action="store_true",
        help="Don't clear cookies or storage before starting monitoring (disables default clearing)"
    )

    args = parser.parse_args()

    # Determine tab_id from positional or named argument
    tab_id = args.tab_id or args.tab_id_alt
    # tab_id is now optional - will create new tab if not provided

    # Validate conflicting options
    if args.clear_output and args.keep_output:
        parser.error("--clear-output and --keep-output are mutually exclusive")

    # Convert resource lists to sets
    args.capture_resources = set(args.capture_resources)

    # Set clearing defaults (enabled by default)
    args.clear_cookies = True
    args.clear_storage = True

    # Handle no-clear options (disable clearing)
    if args.no_clear_all:
        args.clear_cookies = False
        args.clear_storage = False
    else:
        if args.no_clear_cookies:
            args.clear_cookies = False
        if args.no_clear_storage:
            args.clear_storage = False

    return args, tab_id


def setup_output_directory(output_dir: str, keep_output: bool) -> dict[str, str]:
    """Setup the output directory structure and return paths for log files."""
    output_path = Path(output_dir)

    # Handle main output directory
    if output_path.exists() and not keep_output:
        shutil.rmtree(output_path)

    output_path.mkdir(parents=True, exist_ok=True)

    # Create organized subdirectories
    network_dir = output_path / "network"
    storage_dir = output_path / "storage"
    window_properties_dir = output_path / "window_properties"
    interaction_dir = output_path / "interaction"

    network_dir.mkdir(exist_ok=True)
    storage_dir.mkdir(exist_ok=True)
    window_properties_dir.mkdir(exist_ok=True)
    interaction_dir.mkdir(exist_ok=True)

    return {
        # Main directories
        "output_dir": str(output_path),
        "network_dir": str(network_dir),
        "storage_dir": str(storage_dir),
        "window_properties_dir": str(window_properties_dir),
        "interaction_dir": str(interaction_dir),
        # Event JSONL paths (written by FileEventWriter)
        "network_events_path": str(network_dir / "events.jsonl"),
        "storage_events_path": str(storage_dir / "events.jsonl"),
        "window_properties_path": str(window_properties_dir / "events.jsonl"),
        "interaction_events_path": str(interaction_dir / "events.jsonl"),
        # Consolidated output paths (written by finalize())
        "consolidated_transactions_json_path": str(network_dir / "consolidated_transactions.json"),
        "network_har_path": str(network_dir / "network.har"),
        "summary_path": str(output_path / "session_summary.json"),
    }


def save_session_summary(
    paths: dict[str, str],
    summary: dict,
    args,
    start_time: float,
    end_time: float,
    created_tab: bool = False,
    context_id: str | None = None,
) -> dict:
    """Save detailed session summary to JSON file."""
    session_summary = {
        "session_info": {
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": end_time - start_time,
            "tab_id": args.tab_id or args.tab_id_alt,
            "url": args.url,
            "output_dir": args.output_dir,
            "tab_created": created_tab,
            "context_id": context_id,
        },
        "configuration": {
            "capture_resources": list(args.capture_resources),
            "block_patterns_count": len(BLOCK_PATTERNS),
            "navigated": not args.no_navigate,
            "cleared_cookies": args.clear_cookies,
            "cleared_storage": args.clear_storage,
        },
        "monitoring_summary": summary,
        "output_files": {
            "network": {
                "events": paths["network_events_path"],
                "consolidated": paths["consolidated_transactions_json_path"],
                "har": paths["network_har_path"],
            },
            "storage": {
                "events": paths["storage_events_path"],
            },
            "window_properties": {
                "events": paths["window_properties_path"],
            },
            "interactions": {
                "events": paths["interaction_events_path"],
            },
        },
    }

    with open(paths["summary_path"], mode="w", encoding="utf-8") as f:
        json.dump(session_summary, f, indent=2, ensure_ascii=False)

    return session_summary


async def run_session(ws_url: str, paths: dict[str, str]) -> dict:
    """
    Run async CDP monitoring session.

    Args:
        ws_url: WebSocket URL for CDP connection.
        paths: Dict of file paths for output.

    Returns:
        Monitoring summary dict.
    """
    # Create file event writer
    writer = FileEventWriter(paths=paths)

    # Create async CDP session
    session = AsyncCDPSession(
        ws_url=ws_url,
        session_start_dtm=datetime.now().isoformat(),
        event_callback_fn=writer.write_event,
        paths=paths,
    )

    try:
        # Run the monitoring session (blocks until connection closes or cancelled)
        await session.run()
    except asyncio.CancelledError:
        logger.info("Session cancelled")
    finally:
        # Finalize session (consolidate transactions, generate HAR, etc.)
        await session.finalize()

    return session.get_monitoring_summary()


def main():
    """Main function."""
    start_time = time.time()

    # Parse arguments
    args, tab_id = parse_arguments()

    # Setup output directory and paths
    paths = setup_output_directory(args.output_dir, args.keep_output)

    # Handle tab creation if no tab_id provided
    created_tab = False
    context_id = None
    remote_debugging_address = f"http://{args.host}:{args.port}"

    if not tab_id:
        logger.info("No tab ID provided, creating new tab...")
        try:
            # cdp_new_tab returns browser-level WebSocket (for tab management)
            # We need page-level WebSocket for AsyncCDPSession, so close the browser WS
            tab_id, context_id, browser_ws = cdp_new_tab(
                remote_debugging_address=remote_debugging_address,
                incognito=args.incognito,
                url=args.url if not args.no_navigate else "about:blank",
            )
            # Close browser WebSocket - we'll create a page-level one for AsyncCDPSession
            try:
                browser_ws.close()
            except Exception:
                pass
            created_tab = True
            logger.info(f"Created new tab: {tab_id}")
            if context_id:
                logger.info(f"Browser context: {context_id}")
        except Exception as e:
            logger.info(f"Error creating new tab: {e}")
            sys.exit(1)

    # Build page-level WebSocket URL for monitoring
    ws_url = f"ws://{args.host}:{args.port}/devtools/page/{tab_id}"

    logger.info("Starting async CDP monitoring session...")
    logger.info(f"Output directory: {args.output_dir}")
    logger.info(f"Target URL: {args.url if not args.no_navigate else 'No navigation (attach only)'}")
    logger.info(f"Tab ID: {tab_id}")

    # Run async session
    summary = {}
    try:
        summary = asyncio.run(run_session(ws_url, paths))
    except KeyboardInterrupt:
        logger.info("\nSession stopped by user")
    except Exception as e:
        logger.error("Session crashed!", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Running cleanup...")
        # Cleanup: dispose context if we created a tab
        if created_tab and context_id:
            try:
                logger.info(f"Disposing browser context {context_id}...")
                dispose_context(remote_debugging_address, context_id)
                logger.info("✓ Browser context disposed - tab should close")
            except Exception as e:
                logger.error(f"✗ Failed to dispose browser context: {e}", exc_info=True)
        else:
            logger.info("No browser context to dispose (tab was not created by this script)")

        end_time = time.time()

        # Get final summary and save it
        try:
            save_session_summary(paths, summary, args, start_time, end_time, created_tab, context_id)

            # Print organized summary
            logger.info("\n" + "=" * 60)
            logger.info("SESSION SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Duration: {end_time - start_time:.1f} seconds")
            logger.info(f"Tab created: {'Yes' if created_tab else 'No'}")
            if created_tab and context_id:
                logger.info(f"Browser context: {context_id}")

            if summary:
                network = summary.get("network", {})
                storage = summary.get("storage", {})
                window_props = summary.get("window_properties", {})
                interactions = summary.get("interactions", {})

                logger.info(f"Network requests tracked: {network.get('requests_tracked', 0)}")
                logger.info(f"Cookies tracked: {storage.get('cookies_count', 0)}")
                logger.info(f"LocalStorage origins: {len(storage.get('local_storage_origins', []))}")
                logger.info(f"SessionStorage origins: {len(storage.get('session_storage_origins', []))}")
                logger.info(f"Window properties tracked: {window_props.get('total_keys', 0)}")
                logger.info(f"Interactions logged: {interactions.get('interactions_logged', 0)}")

            logger.info("OUTPUT STRUCTURE:")
            logger.info("├── session_summary.json")
            logger.info("├── network/")
            logger.info("│   ├── events.jsonl")
            logger.info("│   ├── consolidated_transactions.json")
            logger.info("│   └── network.har")
            logger.info("├── storage/")
            logger.info("│   └── events.jsonl")
            logger.info("├── window_properties/")
            logger.info("│   └── events.jsonl")
            logger.info("└── interaction/")
            logger.info("    └── events.jsonl")

            logger.info("\n")
            logger.info(f"Session complete! Check {args.output_dir} for all outputs.")

        except Exception as e:
            logger.info("Warning: Could not generate summary: %s", e)


if __name__ == "__main__":
    main()
