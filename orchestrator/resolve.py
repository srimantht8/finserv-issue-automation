"""Phase 2 resolution pipeline: resolve triaged GitHub issues using Devin AI.

This module orchestrates the creation of Devin sessions that fix triaged issues
and open pull requests.  It manages the full lifecycle from prompt construction
through polling for completion to posting results back on GitHub.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.config import get_config
from orchestrator.devin_client import DevinClient
from orchestrator.github_client import GitHubClient
from orchestrator.models import AppState, IssueState


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(message: str) -> None:
    print(f"[resolve {_timestamp()}] {message}")


# ------------------------------------------------------------------
# Prompt construction
# ------------------------------------------------------------------

def build_resolve_prompt(issue: IssueState) -> str:
    """Build a detailed prompt instructing Devin to fix *issue*.

    The prompt includes the repo context, triage analysis, and clear
    instructions for branching, fixing, testing, and opening a PR.
    """
    config = get_config()
    repo = f"{config.REPO_OWNER}/{config.REPO_NAME}"
    tr = issue.triage_result

    affected = "\n".join(f"  - {f}" for f in tr.affected_files) if tr.affected_files else "  (none identified)"

    return (
        f"You are working on the repository {repo}.\n"
        f"\n"
        f"## Issue #{issue.issue_number}: {issue.title}\n"
        f"\n"
        f"### Triage Analysis\n"
        f"- **Category:** {tr.category}\n"
        f"- **Severity:** {tr.severity}\n"
        f"- **Estimated effort:** {tr.estimated_effort}\n"
        f"- **Summary:** {tr.summary}\n"
        f"\n"
        f"### Affected Files\n"
        f"{affected}\n"
        f"\n"
        f"### Recommended Fix Approach\n"
        f"{tr.fix_approach}\n"
        f"\n"
        f"## Instructions\n"
        f"1. Create a new branch from the default branch with a descriptive name "
        f"(e.g., `fix/issue-{issue.issue_number}`).\n"
        f"2. Implement the fix following the approach described above.\n"
        f"3. Follow the existing code style and conventions in the repository.\n"
        f"4. Write or update tests where appropriate to cover the changes.\n"
        f"5. Open a pull request against the default branch.\n"
        f"   - The PR title should clearly describe the change.\n"
        f"   - The PR body must include `Fixes #{issue.issue_number}` so the "
        f"issue is closed automatically when the PR is merged.\n"
    )


# ------------------------------------------------------------------
# ACU budget
# ------------------------------------------------------------------

_EFFORT_ACU_MAP: dict[str, int] = {
    "trivial": 3,
    "small": 5,
    "medium": 8,
    "large": 10,
}


def get_acu_limit(effort: str) -> int:
    """Map an estimated effort level to the corresponding ACU limit."""
    return _EFFORT_ACU_MAP.get(effort, 5)


# ------------------------------------------------------------------
# Single-issue resolution
# ------------------------------------------------------------------

def resolve_issue(
    issue_state: IssueState,
    devin: DevinClient,
    state: AppState,
) -> IssueState:
    """Create a Devin session to resolve *issue_state* and return the updated state.

    The caller must ensure that ``issue_state.triage_result`` is populated
    before invoking this function.
    """
    if issue_state.triage_result is None:
        raise ValueError(
            f"Issue #{issue_state.issue_number} has no triage result; "
            "cannot build a resolution prompt."
        )

    prompt = build_resolve_prompt(issue_state)
    tags = [
        "resolve",
        f"issue-{issue_state.issue_number}",
        issue_state.triage_result.severity,
    ]
    acu_limit = get_acu_limit(issue_state.triage_result.estimated_effort)

    _log(
        f"Creating Devin session for issue #{issue_state.issue_number} "
        f"(effort={issue_state.triage_result.estimated_effort}, acu_limit={acu_limit})"
    )

    session_id, session_url = devin.create_session(
        prompt=prompt,
        tags=tags,
        max_acu_limit=acu_limit,
    )

    _log(
        f"Session created for issue #{issue_state.issue_number}: "
        f"id={session_id}, url={session_url}"
    )

    issue_state = issue_state.model_copy(
        update={
            "resolve_session_id": session_id,
            "resolve_status": "in_progress",
        }
    )

    state.issues[issue_state.issue_number] = issue_state
    return issue_state


# ------------------------------------------------------------------
# Result collection
# ------------------------------------------------------------------

_DONE_STATUSES = {"finished", "expired", "suspend_requested", "suspend_requested_frontend"}


def collect_resolve_results(state: AppState, devin: DevinClient) -> AppState:
    """Poll all in-progress resolution sessions and update *state* accordingly.

    For each issue whose ``resolve_status`` is ``"in_progress"``, this function
    queries the Devin API.  If the session has finished, it records the outcome
    and any PR information on the ``IssueState``.
    """
    for issue_number, issue_state in state.issues.items():
        if issue_state.resolve_session_id is None:
            continue
        if issue_state.resolve_status != "in_progress":
            continue

        _log(f"Polling session for issue #{issue_number}...")
        session_info = devin.get_session(issue_state.resolve_session_id)
        status_lower = session_info.status.lower()

        if status_lower == "blocked":
            _log(
                f"WARNING: Issue #{issue_number} session is blocked — "
                f"Devin may need manual input at "
                f"https://app.devin.ai/sessions/{issue_state.resolve_session_id}"
            )

        if status_lower in _DONE_STATUSES:
            _log(
                f"Issue #{issue_number} session finished with status "
                f"'{session_info.status}'"
            )

            updates: dict = {"resolve_status": session_info.status}

            if session_info.pull_requests:
                pr = session_info.pull_requests[0]
                updates["pr_url"] = pr.get("url", "")
                updates["pr_state"] = "open"  # v1 API doesn't return state
                _log(
                    f"Issue #{issue_number} PR: {updates['pr_url']} "
                    f"(state={updates['pr_state']})"
                )

            state.issues[issue_number] = issue_state.model_copy(update=updates)
        else:
            _log(
                f"Issue #{issue_number} still in progress "
                f"(status={session_info.status})"
            )

    return state


# ------------------------------------------------------------------
# GitHub comment posting
# ------------------------------------------------------------------

def post_resolve_comment(issue_state: IssueState, github: GitHubClient) -> None:
    """Post a comment on GitHub summarising the resolution outcome."""
    session_url = ""
    if issue_state.resolve_session_id:
        session_url = (
            f"https://app.devin.ai/sessions/{issue_state.resolve_session_id}"
        )

    if issue_state.pr_url:
        comment = (
            "\U0001f527 **Automated Fix Submitted**\n\n"
            f"A pull request has been opened to resolve this issue: "
            f"{issue_state.pr_url}\n\n"
            f"Devin session: {session_url}"
        )
    else:
        comment = (
            "\u274c **Automated fix attempted but encountered issues**\n\n"
            f"Devin was unable to produce a pull request for this issue.\n\n"
            f"Devin session: {session_url}"
        )

    _log(f"Posting resolve comment on issue #{issue_state.issue_number}")
    github.add_comment(issue_state.issue_number, comment)


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

def run_resolve(
    issue_numbers: list[int] | None = None,
    auto: bool = False,
) -> AppState:
    """Resolve triaged issues by dispatching Devin sessions.

    Parameters
    ----------
    issue_numbers:
        Explicit list of issue numbers to resolve.  Each must already
        have a ``triage_result`` in the persisted state.
    auto:
        When ``True``, automatically select every issue whose triage
        result has ``can_auto_fix == True``.

    Returns the updated ``AppState`` after all sessions have completed.
    """
    config = get_config()
    state_path = config.STATE_FILE

    if not Path(state_path).exists():
        _log(f"State file not found at {state_path}. Run triage first.")
        raise FileNotFoundError(
            f"State file '{state_path}' does not exist. "
            "Run the triage pipeline before resolving issues."
        )

    state = AppState.load(state_path)
    _log(f"Loaded state with {len(state.issues)} tracked issues")

    # ---- Determine which issues to resolve --------------------------

    selected: list[IssueState] = []

    if auto:
        for issue_state in state.issues.values():
            if (
                issue_state.triage_result is not None
                and issue_state.triage_result.can_auto_fix
                and issue_state.resolve_session_id is None
            ):
                selected.append(issue_state)
        _log(f"Auto mode: selected {len(selected)} auto-fixable issues")

    elif issue_numbers is not None:
        for num in issue_numbers:
            if num not in state.issues:
                _log(f"Warning: issue #{num} not found in state, skipping")
                continue
            issue_state = state.issues[num]
            if issue_state.triage_result is None:
                _log(
                    f"Warning: issue #{num} has no triage result, skipping"
                )
                continue
            if issue_state.resolve_session_id is not None:
                _log(
                    f"Issue #{num} already has a resolve session, skipping"
                )
                continue
            selected.append(issue_state)
        _log(f"Selected {len(selected)} issues from provided list")

    else:
        _log("No issues selected (pass issue_numbers or use auto=True)")
        return state

    if not selected:
        _log("No eligible issues to resolve")
        state.last_updated = _timestamp()
        state.save(state_path)
        return state

    # ---- Dispatch Devin sessions ------------------------------------

    devin = DevinClient()

    for idx, issue_state in enumerate(selected):
        if idx > 0:
            time.sleep(5)  # space out session creation to avoid 429s
        resolve_issue(issue_state, devin, state)

    state.last_updated = _timestamp()
    state.save(state_path)
    _log("All resolution sessions dispatched; beginning to poll for results")

    # ---- Poll until all sessions complete ---------------------------

    _POLL_TIMEOUT = 1800  # 30 minutes
    deadline = time.monotonic() + _POLL_TIMEOUT
    pending = True
    while pending:
        state = collect_resolve_results(state, devin)
        state.last_updated = _timestamp()
        state.save(state_path)

        pending = any(
            s.resolve_status == "in_progress"
            for s in state.issues.values()
            if s.resolve_session_id is not None
        )

        if pending:
            if time.monotonic() > deadline:
                _log("Timeout reached — some sessions may still be in progress")
                break
            _log("Some sessions still in progress, waiting 30s before next poll")
            time.sleep(30)

    _log("All resolution sessions have completed")

    # ---- Post GitHub comments ---------------------------------------

    github = GitHubClient()

    for issue_state in selected:
        final_state = state.issues[issue_state.issue_number]
        try:
            post_resolve_comment(final_state, github)
        except Exception as exc:
            _log(
                f"Failed to post comment on issue "
                f"#{issue_state.issue_number}: {exc}"
            )

    # ---- Final save and summary -------------------------------------

    state.last_updated = _timestamp()
    state.save(state_path)

    resolved = sum(
        1
        for s in state.issues.values()
        if s.resolve_session_id is not None
        and s.resolve_status not in (None, "in_progress")
    )
    with_prs = sum(1 for s in state.issues.values() if s.pr_url)
    _log(f"Resolution complete: {resolved} sessions finished, {with_prs} PRs opened")

    return state
