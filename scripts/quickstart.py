#!/usr/bin/env python3
"""
Quickstart script: Full workflow for web-hacker
This script guides you through: Launch Chrome → Monitor → Discover → Execute
"""

import os
import sys
import time
import platform
import subprocess
import shutil
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("Error: 'requests' package is required. Install it with: pip install requests")
    sys.exit(1)

# Colors for output (ANSI codes work on modern Windows 10+ terminals)
GREEN = '\033[0;32m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'  # No Color

# Configuration
PORT = 9222
OUTPUT_DIR = Path("./cdp_captures")
ROUTINE_OUTPUT = Path("./routine_discovery_output")


def print_colored(text: str, color: str = NC) -> None:
    """Print colored text."""
    print(f"{color}{text}{NC}")


def check_chrome_running(port: int) -> bool:
    """Check if Chrome is already running in debug mode."""
    try:
        response = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=1)
        return response.status_code == 200
    except (requests.RequestException, requests.Timeout):
        return False


def find_chrome_path() -> Optional[str]:
    """Find Chrome executable path based on OS."""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.isfile(chrome_path):
            return chrome_path
    elif system == "Linux":
        # Try common Linux Chrome/Chromium names
        for name in ["google-chrome", "chromium-browser", "chromium", "chrome"]:
            chrome_path = shutil.which(name)
            if chrome_path:
                return chrome_path
    elif system == "Windows":
        # Common Windows Chrome locations
        possible_paths = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in possible_paths:
            if os.path.isfile(path):
                return path
        # Try to find in PATH
        chrome_path = shutil.which("chrome") or shutil.which("google-chrome")
        if chrome_path:
            return chrome_path
    
    return None


def launch_chrome(port: int) -> Optional[subprocess.Popen]:
    """Launch Chrome in debug mode."""
    chrome_path = find_chrome_path()
    
    if not chrome_path:
        print_colored("⚠️  Chrome not found automatically.", YELLOW)
        print("   Please launch Chrome manually with:")
        print(f"   --remote-debugging-port={port}")
        print()
        input("Press Enter when Chrome is running in debug mode...")
        return None
    
    # Create user data directory
    if platform.system() == "Windows":
        chrome_user_dir = os.path.expandvars(r"%USERPROFILE%\tmp\chrome")
    else:
        chrome_user_dir = os.path.expanduser("~/tmp/chrome")
    
    os.makedirs(chrome_user_dir, exist_ok=True)
    
    # Build Chrome arguments
    chrome_args = [
        chrome_path,
        f"--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={chrome_user_dir}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    
    # Launch Chrome
    print("🚀 Launching Chrome...")
    try:
        # On Windows, use CREATE_NEW_PROCESS_GROUP to detach
        creation_flags = 0
        if platform.system() == "Windows":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        
        process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        
        # Wait for Chrome to be ready
        print("⏳ Waiting for Chrome to start...")
        for _ in range(10):
            if check_chrome_running(port):
                print_colored("✅ Chrome is ready!", GREEN)
                return process
            time.sleep(1)
        
        # Chrome didn't start in time
        print_colored("⚠️  Chrome failed to start automatically.", YELLOW)
        try:
            process.terminate()
            time.sleep(0.5)
            process.kill()
        except Exception:
            pass
        
        print("   Please launch Chrome manually with:")
        print(f"   --remote-debugging-port={port}")
        print()
        input("Press Enter when Chrome is running in debug mode...")
        return None
        
    except Exception as e:
        print_colored(f"⚠️  Error launching Chrome: {e}", YELLOW)
        print("   Please launch Chrome manually with:")
        print(f"   --remote-debugging-port={port}")
        print()
        input("Press Enter when Chrome is running in debug mode...")
        return None


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return True if successful."""
    try:
        result = subprocess.run(cmd, check=True)
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False
    except KeyboardInterrupt:
        print()
        print_colored("⚠️  Command interrupted.", YELLOW)
        return False
    except FileNotFoundError:
        print_colored(f"⚠️  Command not found: {cmd[0]}", YELLOW)
        print("   Make sure web-hacker is installed: pip install -e .")
        return False


def main():
    """Main workflow."""
    print_colored("╔════════════════════════════════════════════════════════════╗", BLUE)
    print_colored("║          Web Hacker - Quickstart Workflow                ║", BLUE)
    print_colored("╚════════════════════════════════════════════════════════════╝", BLUE)
    print()
    
    # Step 1: Launch Chrome
    print_colored("Step 1: Launching Chrome in debug mode...", GREEN)
    
    chrome_process = None
    if check_chrome_running(PORT):
        print_colored(f"✅ Chrome is already running in debug mode on port {PORT}", GREEN)
    else:
        chrome_process = launch_chrome(PORT)
    
    print()
    
    # Step 2: Monitor
    print_colored("Step 2: Starting browser monitoring...", GREEN)
    print_colored("📋 Instructions:", YELLOW)
    print("   1. A new Chrome tab will open")
    print("   2. Navigate to your target website")
    print("   3. Perform the actions you want to automate (search, login, etc.)")
    print("   4. Press Ctrl+C when you're done")
    print()
    input("Press Enter to start monitoring...")
    
    print()
    print("🚀 Starting monitor (press Ctrl+C when done)...")
    
    monitor_cmd = [
        "web-hacker-monitor",
        "--host", "127.0.0.1",
        "--port", str(PORT),
        "--output-dir", str(OUTPUT_DIR),
        "--url", "about:blank",
        "--incognito",
    ]
    
    run_command(monitor_cmd, "monitoring")
    print()
    
    # Step 3: Discover
    transactions_dir = OUTPUT_DIR / "network" / "transactions"
    if not OUTPUT_DIR.exists() or not transactions_dir.exists() or not any(transactions_dir.iterdir()):
        print_colored("⚠️  No capture data found. Skipping discovery step.", YELLOW)
        print("   Make sure you performed actions during monitoring.")
        return
    
    print_colored("Step 3: Discovering routine from captured data...", GREEN)
    print_colored("📋 Enter a description of what you want to automate:", YELLOW)
    print("   Example: 'Search for flights and get prices'")
    task = input("   Task: ").strip()
    
    if not task:
        print_colored("⚠️  No task provided. Skipping discovery.", YELLOW)
        return
    
    print()
    print("🤖 Running routine discovery agent...")
    
    discover_cmd = [
        "web-hacker-discover",
        "--task", task,
        "--cdp-captures-dir", str(OUTPUT_DIR),
        "--output-dir", str(ROUTINE_OUTPUT),
        "--llm-model", "gpt-5",
    ]
    
    run_command(discover_cmd, "discovery")
    print()
    
    # Step 4: Execute (optional)
    routine_file = ROUTINE_OUTPUT / "routine.json"
    if not routine_file.exists():
        print_colored(f"⚠️  Routine not found at {routine_file}", YELLOW)
        return
    
    print_colored("Step 4: Ready to execute routine!", GREEN)
    print()
    print("✅ Routine discovered successfully!")
    print(f"   Location: {routine_file}")
    print()
    print_colored("To execute the routine, run:", YELLOW)
    print("   web-hacker-execute \\")
    print(f"     --routine-path {routine_file} \\")
    
    test_params_file = ROUTINE_OUTPUT / "test_parameters.json"
    if test_params_file.exists():
        print(f"     --parameters-path {test_params_file}")
    else:
        print("     --parameters-dict '{\"param1\": \"value1\", \"param2\": \"value2\"}'")
    
    print()
    print_colored(f"💡 Tip: Review {routine_file} before executing", BLUE)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print_colored("⚠️  Interrupted by user.", YELLOW)
        sys.exit(0)

