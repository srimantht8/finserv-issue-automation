"""CLI entry point for the FinServ Issue Automation system.

Usage examples::

    python -m orchestrator.main triage --issues 1,2,3
    python -m orchestrator.main resolve --auto
    python -m orchestrator.main status
    python -m orchestrator.main dashboard
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from orchestrator.models import AppState


BANNER = r"""
 _____ _       ____                      ___                         _         _   _
|  ___(_)_ __ / ___|  ___ _ ____   __   |_ _|___ ___ _   _  ___    / \  _   _| |_(_) ___  _ __ ___   __ _| |_(_) ___  _ __
| |_  | | '_ \\___ \ / _ \ '__\ \ / /    | |/ __/ __| | | |/ _ \  / _ \| | | | __| |/ _ \| '_ ` _ \ / _` | __| |/ _ \| '_ \
|  _| | | | | |___) |  __/ |   \ V /     | |\__ \__ \ |_| |  __/ / ___ \ |_| | |_| | (_) | | | | | | (_| | |_| | (_) | | | |
|_|   |_|_| |_|____/ \___|_|    \_/     |___|___/___/\__,_|\___/_/___ \_\__,_|\__|_|\___/|_| |_| |_|\__,_|\__|_|\___/|_| |_|
                                                    Powered by Devin
"""


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------

def _parse_issues(raw: str) -> list[int]:
    """Parse a comma-separated string of issue numbers into a list of ints."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        return [int(p) for p in parts]
    except ValueError:
        print(f"Error: invalid issue numbers '{raw}'. Expected comma-separated integers (e.g. 1,2,3).")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _handle_triage(args: argparse.Namespace) -> None:
    """Run the triage pipeline on the specified (or all open) issues."""
    from orchestrator.triage import run_triage

    issue_numbers = _parse_issues(args.issues) if args.issues else None

    if issue_numbers:
        print(f"Triaging issues: {issue_numbers}")
    else:
        print("Triaging all open issues...")

    try:
        state = run_triage(issue_numbers=issue_numbers)
        triaged = sum(1 for s in state.issues.values() if s.triage_result is not None)
        print(f"\nTriage complete. {triaged}/{len(state.issues)} issue(s) triaged successfully.")
    except Exception as exc:
        print(f"\nTriage failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _handle_resolve(args: argparse.Namespace) -> None:
    """Run the resolve pipeline on the specified issues or all auto-fixable ones."""
    from orchestrator.resolve import run_resolve

    issue_numbers = _parse_issues(args.issues) if args.issues else None
    auto: bool = args.auto

    if not issue_numbers and not auto:
        print("Error: specify --issues or --auto to select issues for resolution.")
        sys.exit(1)

    if auto:
        print("Resolving all auto-fixable issues...")
    else:
        print(f"Resolving issues: {issue_numbers}")

    try:
        state = run_resolve(issue_numbers=issue_numbers, auto=auto)
        resolved = sum(
            1
            for s in state.issues.values()
            if s.resolve_session_id is not None
            and s.resolve_status not in (None, "in_progress")
        )
        with_prs = sum(1 for s in state.issues.values() if s.pr_url)
        print(f"\nResolve complete. {resolved} issue(s) resolved, {with_prs} PR(s) opened.")
    except FileNotFoundError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        print("Hint: run 'triage' first to create the state file.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\nResolve failed: {exc}", file=sys.stderr)
        sys.exit(1)


def _handle_status(args: argparse.Namespace) -> None:
    """Print a formatted status table from state.json (no API keys required).

    Intentionally reads STATE_FILE via os.getenv instead of get_config()
    so this command works without DEVIN_API_KEY or GITHUB_TOKEN set.
    """
    import os
    state_path = os.getenv("STATE_FILE", "orchestrator/state.json")

    if not Path(state_path).exists():
        print(f"No state file found at '{state_path}'.")
        print("Run the triage pipeline first to generate issue data.")
        return

    state = AppState.load(state_path)

    if not state.issues:
        print("State file exists but contains no tracked issues.")
        return

    # ----- Build table -----
    headers = ["Issue #", "Title", "Triage", "Severity", "Effort", "Auto-Fix", "Resolve", "PR"]

    rows: list[list[str]] = []
    for issue_number in sorted(state.issues):
        issue = state.issues[issue_number]
        tr = issue.triage_result

        triage_status = "Done" if tr is not None else "Pending"
        severity = tr.severity if tr else "-"
        effort = tr.estimated_effort if tr else "-"
        auto_fix = ("Yes" if tr.can_auto_fix else "No") if tr else "-"
        resolve_status = issue.resolve_status or "-"
        pr = issue.pr_url or "-"
        title = issue.title if len(issue.title) <= 40 else issue.title[:37] + "..."

        rows.append([
            str(issue_number),
            title,
            triage_status,
            severity,
            effort,
            auto_fix,
            resolve_status,
            pr,
        ])

    # ----- Compute column widths -----
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(cell))

    def _fmt_row(cells: list[str]) -> str:
        parts = []
        for cell, width in zip(cells, col_widths):
            parts.append(cell.ljust(width))
        return " | ".join(parts)

    separator = "-+-".join("-" * w for w in col_widths)

    print()
    print(_fmt_row(headers))
    print(separator)
    for row in rows:
        print(_fmt_row(row))

    # ----- Summary counts -----
    total = len(state.issues)
    triaged = sum(1 for s in state.issues.values() if s.triage_result is not None)
    auto_fixable = sum(
        1
        for s in state.issues.values()
        if s.triage_result is not None and s.triage_result.can_auto_fix
    )
    resolved = sum(
        1
        for s in state.issues.values()
        if s.resolve_status is not None and s.resolve_status != "in_progress"
    )
    prs_opened = sum(1 for s in state.issues.values() if s.pr_url)

    print()
    print(f"Total: {total} | Triaged: {triaged} | Auto-fixable: {auto_fixable} | Resolved: {resolved} | PRs: {prs_opened}")
    if state.last_updated:
        print(f"Last updated: {state.last_updated}")
    print()


def _handle_dashboard(args: argparse.Namespace) -> None:
    """Launch the Streamlit dashboard via subprocess."""
    dashboard_path = Path(__file__).resolve().parent / "dashboard.py"

    if not dashboard_path.exists():
        print(f"Dashboard file not found at '{dashboard_path}'.")
        sys.exit(1)

    print(f"Launching Streamlit dashboard ({dashboard_path})...")

    try:
        subprocess.run(
            [sys.executable, "-m", "streamlit", "run", str(dashboard_path)],
            check=True,
        )
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    except FileNotFoundError:
        print("Error: 'streamlit' is not installed. Install it with: pip install streamlit", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(f"Dashboard exited with code {exc.returncode}.", file=sys.stderr)
        sys.exit(exc.returncode)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="FinServ Issue Automation — triage, resolve, and track GitHub issues with Devin AI.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # -- triage --
    triage_parser = subparsers.add_parser(
        "triage",
        help="Run triage on open GitHub issues",
        description="Dispatch Devin sessions to triage open GitHub issues.",
    )
    triage_parser.add_argument(
        "--issues",
        type=str,
        default=None,
        help="Comma-separated issue numbers to triage (e.g. --issues 1,2,3). Omit to triage all open issues.",
    )

    # -- resolve --
    resolve_parser = subparsers.add_parser(
        "resolve",
        help="Resolve triaged issues via Devin",
        description="Create Devin sessions to fix triaged issues and open pull requests.",
    )
    resolve_parser.add_argument(
        "--issues",
        type=str,
        default=None,
        help="Comma-separated issue numbers to resolve (e.g. --issues 1,2,3).",
    )
    resolve_parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Automatically resolve all issues marked as auto-fixable.",
    )

    # -- status --
    subparsers.add_parser(
        "status",
        help="Print current status of all tracked issues",
        description="Read state.json and display a formatted status table. No API keys required.",
    )

    # -- dashboard --
    subparsers.add_parser(
        "dashboard",
        help="Launch the Streamlit dashboard",
        description="Start the interactive Streamlit dashboard for monitoring issues.",
    )

    return parser


def main() -> None:
    """Parse arguments, print the banner, and dispatch the chosen subcommand."""
    parser = build_parser()
    args = parser.parse_args()

    print(BANNER)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "triage": _handle_triage,
        "resolve": _handle_resolve,
        "status": _handle_status,
        "dashboard": _handle_dashboard,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
