"""Phase 1 triage pipeline — classify GitHub issues via Devin AI.

This module orchestrates the triage of open GitHub issues by dispatching
each one to a Devin session with a structured-output schema.  Devin
examines the codebase, evaluates severity / effort / category, and
returns a machine-readable ``TriageResult`` that is persisted in
``AppState`` and optionally posted back to the issue as a comment.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from orchestrator.config import get_config
from orchestrator.devin_client import DevinClient
from orchestrator.github_client import GitHubClient
from orchestrator.models import AppState, IssueState, TriageResult


# ---------------------------------------------------------------------------
# Logging helper (mirrors the style used in github_client / devin_client)
# ---------------------------------------------------------------------------

def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(message: str) -> None:
    print(f"[Triage {_timestamp()}] {message}")


# ---------------------------------------------------------------------------
# 1. Prompt builder
# ---------------------------------------------------------------------------

def build_triage_prompt(issue: dict) -> str:
    """Build the Devin prompt for triaging a single GitHub issue.

    The prompt gives Devin the repo context, the full issue text, and
    explicit instructions on what to analyse and return.
    """
    labels_str = ", ".join(issue.get("labels", [])) or "none"

    return f"""\
You are triaging a GitHub issue in a FinServ monorepo that contains:
- Python FastAPI micro-services
- Node.js Express micro-services
- Shared infrastructure and deployment configs

Please examine the codebase to understand the issue described below,
then produce a structured triage report.

--- ISSUE #{issue['number']} ---
Title: {issue['title']}
Labels: {labels_str}

Body:
{issue.get('body', '(no body)')}
--- END ISSUE ---

Instructions:
1. Read the relevant source files to understand the scope of the issue.
2. Determine the **severity** (critical / high / medium / low) based on
   user impact, data-integrity risk, and whether the issue blocks other
   work.
3. Estimate the **effort** required to fix (trivial / small / medium /
   large).
4. Classify the **category** (bug / feature / refactor / docs).
5. List every **affected file** (relative paths from the repo root).
6. Write a concise **summary** of your findings (2-4 sentences).
7. Decide whether this issue **can be auto-fixed** by an AI agent.
8. If it can be fixed, describe the **fix approach** at a high level;
   otherwise explain why manual intervention is needed.

Return your findings using the structured output schema provided.
"""


# ---------------------------------------------------------------------------
# 2. Structured-output JSON Schema
# ---------------------------------------------------------------------------

def get_triage_schema() -> dict:
    """Return the JSON Schema that Devin must conform to for triage output."""
    return {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["critical", "high", "medium", "low"],
            },
            "estimated_effort": {
                "type": "string",
                "enum": ["trivial", "small", "medium", "large"],
            },
            "category": {
                "type": "string",
                "enum": ["bug", "feature", "refactor", "docs"],
            },
            "affected_files": {
                "type": "array",
                "items": {"type": "string"},
            },
            "summary": {
                "type": "string",
            },
            "can_auto_fix": {
                "type": "boolean",
            },
            "fix_approach": {
                "type": "string",
            },
        },
        "required": [
            "severity",
            "estimated_effort",
            "category",
            "affected_files",
            "summary",
            "can_auto_fix",
            "fix_approach",
        ],
    }


# ---------------------------------------------------------------------------
# 3. Triage a single issue (kick-off only, does not wait)
# ---------------------------------------------------------------------------

def triage_issue(
    issue: dict,
    devin: DevinClient,
    state: AppState,
) -> IssueState:
    """Create a Devin triage session for *issue* and return an ``IssueState``.

    The session is started but **not** awaited here — call
    ``collect_triage_results`` later to poll for completion.
    """
    issue_number: int = issue["number"]
    _log(f"Creating triage session for issue #{issue_number}: {issue['title']}")

    prompt = build_triage_prompt(issue)
    schema = get_triage_schema()

    session_id, session_url = devin.create_session(
        prompt=prompt,
        structured_output_schema=schema,
        tags=["triage", f"issue-{issue_number}"],
        max_acu_limit=2,
    )

    _log(f"Issue #{issue_number} -> session {session_id} ({session_url})")

    issue_state = IssueState(
        issue_number=issue_number,
        title=issue["title"],
        labels=issue.get("labels", []),
        triage_session_id=session_id,
    )

    state.issues[issue_number] = issue_state
    return issue_state


# ---------------------------------------------------------------------------
# 4. Collect pending triage results
# ---------------------------------------------------------------------------

def collect_triage_results(
    state: AppState,
    devin: DevinClient,
) -> AppState:
    """Poll every issue that has a triage session but no result yet.

    Completed sessions with valid structured output are parsed into a
    ``TriageResult`` and attached to the corresponding ``IssueState``.
    """
    pending = [
        issue_state
        for issue_state in state.issues.values()
        if issue_state.triage_session_id and issue_state.triage_result is None
    ]

    if not pending:
        _log("No pending triage sessions to collect.")
        return state

    _log(f"Collecting results for {len(pending)} pending triage session(s)...")

    for issue_state in pending:
        session_id = issue_state.triage_session_id
        assert session_id is not None  # guarded above

        try:
            info = devin.get_session(session_id)
        except Exception as exc:
            _log(
                f"Error fetching session {session_id} for issue "
                f"#{issue_state.issue_number}: {exc}"
            )
            continue

        # Check for structured output first — Devin may be "blocked"
        # (waiting for user follow-up) but already have the triage result.
        if info.structured_output is not None:
            try:
                triage = TriageResult.model_validate(info.structured_output)
                issue_state.triage_result = triage
                _log(
                    f"Issue #{issue_state.issue_number}: severity="
                    f"{triage.severity}, effort={triage.estimated_effort}, "
                    f"can_auto_fix={triage.can_auto_fix}"
                )
            except Exception as exc:
                _log(
                    f"Failed to parse triage output for issue "
                    f"#{issue_state.issue_number}: {exc}"
                )
            continue

        # No output yet — check if still actively working.
        active_statuses = {"working", "blocked", "resumed", "resume_requested", "resume_requested_frontend"}
        if info.status.lower() in active_statuses:
            _log(
                f"Issue #{issue_state.issue_number} session {session_id} "
                f"still {info.status} (no output yet)"
            )
            continue

        _log(
            f"Issue #{issue_state.issue_number}: session {session_id} "
            f"ended ({info.status}) with no structured output."
        )

    return state


# ---------------------------------------------------------------------------
# 5. Main entry point
# ---------------------------------------------------------------------------

_POLL_INTERVAL = 30  # seconds between polling rounds
_POLL_TIMEOUT = 1800  # give up after 30 minutes


def run_triage(issue_numbers: list[int] | None = None) -> AppState:
    """Triage open issues end-to-end and return the updated ``AppState``.

    Parameters
    ----------
    issue_numbers:
        If given, only triage these issue numbers.  Otherwise triage
        every open issue.

    Steps
    -----
    1. Load (or create) persisted ``AppState``.
    2. Fetch open issues from GitHub.
    3. Filter to the requested subset and skip already-triaged issues.
    4. Fire off a Devin session for each issue.
    5. Poll until all sessions complete (or timeout).
    6. Post a triage summary comment on each issue.
    7. Save state and return it.
    """
    config = get_config()
    state = AppState.load(config.STATE_FILE)
    github = GitHubClient()
    devin = DevinClient()

    # -- Fetch issues -------------------------------------------------------
    open_issues = github.fetch_open_issues()
    _log(f"Found {len(open_issues)} open issue(s) on GitHub.")

    if issue_numbers is not None:
        requested = set(issue_numbers)
        open_issues = [i for i in open_issues if i["number"] in requested]
        _log(f"Filtered to {len(open_issues)} requested issue(s).")

    # -- Skip already-triaged -----------------------------------------------
    to_triage: list[dict] = []
    for issue in open_issues:
        existing = state.issues.get(issue["number"])
        if existing and existing.triage_result is not None:
            _log(f"Issue #{issue['number']} already triaged — skipping.")
            continue
        to_triage.append(issue)

    if not to_triage:
        _log("Nothing to triage.")
        state.last_updated = _timestamp()
        state.save(config.STATE_FILE)
        return state

    _log(f"Triaging {len(to_triage)} issue(s)...")

    # -- Create triage sessions (with delay to avoid rate limits) ------------
    for idx, issue in enumerate(to_triage):
        if idx > 0:
            time.sleep(5)  # space out session creation to avoid 429s
        try:
            triage_issue(issue, devin, state)
        except Exception as exc:
            _log(f"Failed to create session for issue #{issue['number']}: {exc}")

    # -- Poll for completion ------------------------------------------------
    deadline = time.monotonic() + _POLL_TIMEOUT

    while True:
        state = collect_triage_results(state, devin)

        # Check whether every dispatched session has a result now.
        still_pending = [
            s
            for s in state.issues.values()
            if s.triage_session_id and s.triage_result is None
        ]
        if not still_pending:
            _log("All triage sessions have completed.")
            break

        if time.monotonic() >= deadline:
            _log(
                f"Timeout reached with {len(still_pending)} session(s) still "
                "pending. Saving partial results."
            )
            break

        _log(
            f"{len(still_pending)} session(s) still running — "
            f"polling again in {_POLL_INTERVAL}s..."
        )
        time.sleep(_POLL_INTERVAL)

    # -- Post triage comments and apply severity labels ----------------------
    for issue in to_triage:
        issue_state = state.issues.get(issue["number"])
        if issue_state and issue_state.triage_result is not None:
            try:
                post_triage_comment(
                    issue_state.issue_number,
                    issue_state.triage_result,
                    github,
                )
                github.add_label(
                    issue_state.issue_number,
                    f"severity:{issue_state.triage_result.severity}",
                )
            except Exception as exc:
                _log(
                    f"Failed to post comment/label on issue "
                    f"#{issue_state.issue_number}: {exc}"
                )

    # -- Persist ------------------------------------------------------------
    state.last_updated = _timestamp()
    state.save(config.STATE_FILE)
    _log(f"State saved to {config.STATE_FILE}")

    return state


# ---------------------------------------------------------------------------
# 6. Post triage comment on GitHub
# ---------------------------------------------------------------------------

_SEVERITY_BADGES = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
}


def post_triage_comment(
    issue_number: int,
    triage_result: TriageResult,
    github: GitHubClient,
) -> None:
    """Post a Markdown-formatted triage summary as a comment on the issue."""
    badge = _SEVERITY_BADGES.get(triage_result.severity, triage_result.severity.upper())
    files_list = (
        "\n".join(f"- `{f}`" for f in triage_result.affected_files)
        if triage_result.affected_files
        else "_none identified_"
    )
    auto_fix_text = "Yes" if triage_result.can_auto_fix else "No"

    comment = f"""\
## Automated Triage Report (via Devin)

| Field | Value |
|-------|-------|
| **Severity** | `{badge}` |
| **Estimated effort** | `{triage_result.estimated_effort}` |
| **Category** | `{triage_result.category}` |
| **Auto-fixable** | {auto_fix_text} |

### Summary

{triage_result.summary}

### Affected files

{files_list}

### Fix approach

{triage_result.fix_approach}
"""

    _log(f"Posting triage comment on issue #{issue_number}...")
    github.add_comment(issue_number, comment)
    _log(f"Triage comment posted on issue #{issue_number}.")
