#!/usr/bin/env python3
"""
Browser Agent - Root Entry Point
Delegates CLI execution to browser_agent.agent or starts the Web UI if invoked interactively.
"""
import sys


def main():
    if len(sys.argv) == 1:
        # If run directly with no CLI arguments, launch the Web Control Center
        from web_server import main as launch_web_ui
        launch_web_ui()
    elif len(sys.argv) == 2 and sys.argv[1] in ("--check", "-c", "check", "--diagnostics"):
        from browser_agent.diagnostics import run_all_checks
        sys.exit(0 if run_all_checks() else 1)
    else:
        # If task is provided on CLI, run the agent CLI
        from browser_agent.agent import main as run_agent_cli
        sys.exit(run_agent_cli())


if __name__ == "__main__":
    main()
