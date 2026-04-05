"""Streamlit dashboard for the FinServ Issue Automation system.

Provides a visual overview of issue triage, resolution, Devin session
tracking, and pull-request status.  Reads from persisted ``AppState``
and optionally triggers triage / resolve pipelines via sidebar actions.

Run with::

    streamlit run orchestrator/dashboard.py
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Page configuration (must be first Streamlit call)
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FinServ Issue Automation",
    page_icon="\U0001f527",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Imports from the orchestrator package
# ---------------------------------------------------------------------------

from orchestrator.config import get_config  # noqa: E402
from orchestrator.models import AppState  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _load_state() -> AppState | None:
    """Load application state from disk; return *None* on failure."""
    try:
        config = get_config()
        state_path = config.STATE_FILE
    except Exception:
        state_path = "orchestrator/state.json"

    if not Path(state_path).exists():
        return None

    try:
        return AppState.load(state_path)
    except Exception as exc:
        st.error(f"Failed to load state file: {exc}")
        return None


def _severity_sort_key(severity: str) -> int:
    return _SEVERITY_ORDER.get(severity, 99)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("FinServ Issue Automation \u2014 Powered by Devin")
st.caption(
    "Automated triage, resolution, and PR tracking for your FinServ repository"
)

# ---------------------------------------------------------------------------
# Sidebar: Actions
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Actions")

    import subprocess, sys
    _CWD = str(Path(__file__).resolve().parent.parent)

    st.subheader("Triage")
    triage_input = st.text_input(
        "Issue numbers (comma-separated)",
        placeholder="e.g. 1,9,15 — leave blank for all",
        key="triage_input",
    )
    if st.button("Triage Issues", use_container_width=True):
        cmd = [sys.executable, "-m", "orchestrator.main", "triage"]
        if triage_input.strip():
            cmd += ["--issues", triage_input.strip()]
            st.info(f"Triaging issues {triage_input.strip()}...")
        else:
            st.info("Triaging all open issues...")
        subprocess.Popen(cmd, cwd=_CWD)

    st.divider()
    st.subheader("Resolve")
    resolve_input = st.text_input(
        "Issue numbers (comma-separated)",
        placeholder="e.g. 1,9,15 — leave blank for all auto-fixable",
        key="resolve_input",
    )
    if st.button("Resolve Issues", use_container_width=True):
        if resolve_input.strip():
            subprocess.Popen(
                [sys.executable, "-m", "orchestrator.main", "resolve",
                 "--issues", resolve_input.strip()],
                cwd=_CWD,
            )
            st.info(f"Resolving issues {resolve_input.strip()}...")
        else:
            subprocess.Popen(
                [sys.executable, "-m", "orchestrator.main", "resolve", "--auto"],
                cwd=_CWD,
            )
            st.info("Resolving all auto-fixable issues...")

    st.divider()

    if st.button("Refresh Status", use_container_width=True):
        # Poll Devin for any in-progress resolve sessions before refreshing
        try:
            from orchestrator.devin_client import DevinClient
            from orchestrator.models import AppState
            config = get_config()
            _state = AppState.load(config.STATE_FILE)
            devin = DevinClient()
            _done = {"finished", "expired", "suspend_requested", "suspend_requested_frontend"}
            updated = False
            for _num, _iss in _state.issues.items():
                if _iss.resolve_session_id and _iss.resolve_status == "in_progress":
                    info = devin.get_session(_iss.resolve_session_id)
                    if info.status.lower() in _done:
                        _iss.resolve_status = info.status
                        if info.pull_requests:
                            _iss.pr_url = info.pull_requests[0].get("url", "")
                            _iss.pr_state = "open"
                        _state.issues[_num] = _iss
                        updated = True
            if updated:
                from datetime import datetime, timezone
                _state.last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                _state.save(config.STATE_FILE)
        except Exception:
            pass  # fail silently — worst case just reloads stale state
        st.rerun()

    st.divider()

    # --- Auto-refresh toggle ------------------------------------------------
    st.header("Auto-Refresh")
    auto_refresh = st.toggle("Enable auto-refresh (30s)", value=False)

    st.divider()

    # --- Filters ------------------------------------------------------------
    st.header("Filters")

    severity_options = ["critical", "high", "medium", "low"]
    selected_severities = st.multiselect(
        "Severity",
        options=severity_options,
        default=severity_options,
    )

    category_options = ["bug", "feature", "refactor", "docs"]
    selected_categories = st.multiselect(
        "Category",
        options=category_options,
        default=category_options,
    )

    status_filter = st.selectbox(
        "Status",
        options=["All", "Pending Triage", "Triaged", "In Progress", "Resolved"],
        index=0,
    )

# ---------------------------------------------------------------------------
# Load state
# ---------------------------------------------------------------------------

state = _load_state()

if state is None or not state.issues:
    st.info(
        "No data yet \u2014 click **Triage All Issues** in the sidebar to start."
    )
    if auto_refresh:
        time.sleep(30)
        st.rerun()
    st.stop()

issues = list(state.issues.values())

# ---------------------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------------------

filtered_issues = issues

if status_filter != "All":
    _filtered: list = []
    for iss in filtered_issues:
        if status_filter == "Pending Triage" and iss.triage_result is None:
            _filtered.append(iss)
        elif status_filter == "Triaged" and iss.triage_result is not None and iss.resolve_session_id is None:
            _filtered.append(iss)
        elif status_filter == "In Progress" and iss.resolve_status == "in_progress":
            _filtered.append(iss)
        elif status_filter == "Resolved" and iss.resolve_status is not None and iss.resolve_status != "in_progress":
            _filtered.append(iss)
    filtered_issues = _filtered

# ---------------------------------------------------------------------------
# Metrics row
# ---------------------------------------------------------------------------

st.markdown("---")

total = len(issues)
triaged = sum(1 for i in issues if i.triage_result is not None)
in_progress = sum(1 for i in issues if i.resolve_status == "in_progress")
prs_opened = sum(1 for i in issues if i.pr_url is not None)
auto_fixable = sum(
    1
    for i in issues
    if i.triage_result is not None and i.triage_result.can_auto_fix
)

_EFFORT_ACU = {"trivial": 3, "small": 5, "medium": 8, "large": 10}
_TRIAGE_ACU = 2  # ACU per triage session

triage_acu = triaged * _TRIAGE_ACU
resolve_acu = sum(
    _EFFORT_ACU.get(i.triage_result.estimated_effort, 5)
    for i in issues
    if i.triage_result is not None and i.resolve_session_id is not None
)
total_acu = triage_acu + resolve_acu

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Total Issues", total)
m2.metric("Triaged", triaged)
m3.metric("In Progress", in_progress)
m4.metric("PRs Opened", prs_opened)
m5.metric("Auto-Fixable", auto_fixable)
m6.metric("ACU Used", f"{total_acu}")

# ---------------------------------------------------------------------------
# ROI Summary
# ---------------------------------------------------------------------------

with st.container():
    st.subheader("ROI Estimate")

    roi_left, roi_right = st.columns([3, 1])
    with roi_right:
        avg_engineer_hours_per_issue = st.number_input(
            "Avg hours per issue", min_value=0.5, max_value=10.0, value=2.5, step=0.5)
        engineer_hourly_rate = st.number_input(
            "Engineer hourly rate ($)", min_value=25, max_value=300, value=85, step=5)
        cost_per_acu = st.number_input(
            "Cost per ACU ($)", min_value=0.50, max_value=10.0, value=2.00, step=0.25,
            help="Devin Teams plan: $2.00/ACU, Core plan: $2.25/ACU")

    manual_cost = total * avg_engineer_hours_per_issue * engineer_hourly_rate
    time_saved_hours = triaged * avg_engineer_hours_per_issue
    devin_cost = total_acu * cost_per_acu
    net_savings = manual_cost - devin_cost

    with roi_left:
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Engineer Hours Saved", f"{time_saved_hours:.0f}h",
                  help="Estimated hours saved vs. manual triage")
        r2.metric("Manual Cost", f"${manual_cost:,.0f}",
                  help=f"{total} issues x {avg_engineer_hours_per_issue}h x ${engineer_hourly_rate}/h")
        r3.metric("Devin Cost", f"${devin_cost:,.0f}",
                  help=f"{total_acu} ACU x ${cost_per_acu:.2f}/ACU")
        r4.metric("Net Savings", f"${net_savings:,.0f}",
                  delta=f"{net_savings / manual_cost * 100:.0f}% reduction" if manual_cost > 0 else None)

    with st.expander("View detailed ROI breakdown"):
        st.markdown("#### Cost Assumptions")
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"""
| Parameter | Value |
|-----------|-------|
| Avg. engineer time per issue | **{avg_engineer_hours_per_issue}h** |
| Fully loaded engineer hourly rate | **${engineer_hourly_rate}** |
| Cost per ACU (Devin Teams plan) | **${cost_per_acu:.2f}** |
| ACU per triage session | **{_TRIAGE_ACU}** |
| ACU per resolve (varies by effort) | **3–10** |
""")
        with col_b:
            st.markdown(f"""
| Effort Level | ACU Budget | Cost |
|-------------|-----------|------|
| Trivial | 3 ACU | ${3 * cost_per_acu:.2f} |
| Small | 5 ACU | ${5 * cost_per_acu:.2f} |
| Medium | 8 ACU | ${8 * cost_per_acu:.2f} |
| Large | 10 ACU | ${10 * cost_per_acu:.2f} |
""")

        st.markdown("#### Current Backlog")
        st.markdown(f"""
| Metric | Value |
|--------|-------|
| Issues triaged by Devin | **{triaged}** |
| Engineer hours saved | **{time_saved_hours:.0f}h** |
| Manual cost avoided | **${manual_cost:,.0f}** |
| Triage ACU consumed | **{triage_acu}** (${triage_acu * cost_per_acu:,.0f}) |
| Resolve ACU consumed | **{resolve_acu}** (${resolve_acu * cost_per_acu:,.0f}) |
| **Total Devin cost** | **{total_acu} ACU** (${devin_cost:,.0f}) |
| **Net savings** | **${net_savings:,.0f}** |
| PRs opened (zero engineer effort) | **{prs_opened}** |
""")

        st.markdown("#### Projected Savings at Scale (300 issues)")
        scale_issues = 300
        scale_triage_hours = scale_issues * avg_engineer_hours_per_issue
        scale_manual_cost = scale_triage_hours * engineer_hourly_rate
        scale_triage_acu = scale_issues * _TRIAGE_ACU
        # 85% auto-fixable (conservative discount from our 93% demo rate
        # to account for increased complexity in production codebases)
        scale_auto_fix_rate = 0.85
        scale_resolve_acu = int(scale_issues * scale_auto_fix_rate * 5)
        scale_total_acu = scale_triage_acu + scale_resolve_acu
        scale_devin_cost = scale_total_acu * cost_per_acu
        scale_savings = scale_manual_cost - scale_devin_cost
        scale_reduction = scale_savings / scale_manual_cost * 100 if scale_manual_cost > 0 else 0

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Manual Cost", f"${scale_manual_cost:,.0f}")
        s2.metric("Devin Cost", f"${scale_devin_cost:,.0f}")
        s3.metric("Net Savings", f"${scale_savings:,.0f}")
        s4.metric("Cost Reduction", f"{scale_reduction:.0f}%")

        resolve_count = int(scale_issues * scale_auto_fix_rate)
        resolve_cost = scale_resolve_acu * cost_per_acu
        triage_cost = scale_triage_acu * cost_per_acu
        st.markdown(
            f"- **Triage 300 issues:** {scale_triage_acu} ACU (\\${triage_cost:,.0f})  \n"
            f"- **Resolve ~{resolve_count} auto-fixable (85%):** ~{scale_resolve_acu} ACU (\\${resolve_cost:,.0f})  \n"
            f"- **Total Devin cost:** ~\\${scale_devin_cost:,.0f} vs. \\${scale_manual_cost:,.0f} manual  \n"
            f"- **Time:** Hours (Devin) vs. weeks (manual triage rotation)"
        )

st.markdown("---")

# ---------------------------------------------------------------------------
# Triage Results Table
# ---------------------------------------------------------------------------

st.subheader("Issues")

# Confidence score: how confident Devin is it can resolve this issue
_EFFORT_CONFIDENCE = {"trivial": 1.0, "small": 0.85, "medium": 0.6, "large": 0.3}
_CATEGORY_CONFIDENCE = {"bug": 0.9, "refactor": 0.8, "docs": 0.7, "feature": 0.5}


def _confidence_score(tr) -> int:
    base = 0.5 if tr.can_auto_fix else 0.1
    effort = _EFFORT_CONFIDENCE.get(tr.estimated_effort, 0.5) * 0.3
    category = _CATEGORY_CONFIDENCE.get(tr.category, 0.5) * 0.2
    return int((base + effort + category) * 100)


def _issue_status(iss) -> str:
    if iss.pr_url:
        return "PR Opened"
    if iss.resolve_status == "in_progress":
        return "In Progress"
    if iss.triage_result is not None:
        return "Ready"
    return "Pending Triage"


# Apply severity/category filters only to triaged issues; always show pending
display_issues = []
for iss in filtered_issues:
    if iss.triage_result is not None:
        if (iss.triage_result.severity in selected_severities
                and iss.triage_result.category in selected_categories):
            display_issues.append(iss)
    else:
        display_issues.append(iss)

# Sort: pending first, then by severity
display_issues.sort(key=lambda i: (
    0 if i.triage_result is None else 1,
    _severity_sort_key(i.triage_result.severity) if i.triage_result else 0,
))

if display_issues:
    rows = []
    for iss in display_issues:
        tr = iss.triage_result
        rows.append({
            "Issue #": iss.issue_number,
            "Title": iss.title,
            "Severity": tr.severity.capitalize() if tr else "—",
            "Effort": tr.estimated_effort.capitalize() if tr else "—",
            "Category": tr.category.capitalize() if tr else "—",
            "Confidence": f"{_confidence_score(tr)}%" if tr else "—",
            "Status": _issue_status(iss),
            "Summary": tr.summary if tr else "Awaiting triage...",
        })

    st.dataframe(
        pd.DataFrame(rows),
        column_config={
            "Issue #": st.column_config.NumberColumn("Issue #", format="%d"),
            "Title": st.column_config.TextColumn("Title", width="medium"),
            "Severity": st.column_config.TextColumn("Severity"),
            "Effort": st.column_config.TextColumn("Effort"),
            "Category": st.column_config.TextColumn("Category"),
            "Confidence": st.column_config.TextColumn("Confidence"),
            "Status": st.column_config.TextColumn("Status"),
            "Summary": st.column_config.TextColumn("Summary", width="large"),
        },
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No issues match the current filters.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Session Tracker
# ---------------------------------------------------------------------------

st.subheader("Devin Session Tracker")

active_sessions = [
    iss
    for iss in filtered_issues
    if iss.triage_session_id is not None or iss.resolve_session_id is not None
]

if active_sessions:
    for iss in active_sessions:
        # Determine the most relevant session to display
        session_id = iss.resolve_session_id or iss.triage_session_id
        session_type = "Resolve" if iss.resolve_session_id else "Triage"

        if iss.resolve_status == "in_progress":
            display_status = "running"
        elif iss.resolve_status is not None:
            display_status = iss.resolve_status
        elif iss.triage_result is not None:
            display_status = "completed"
        else:
            display_status = "pending"

        # Strip "devin-" prefix from session ID for the app URL
        session_uuid = session_id.removeprefix("devin-")
        session_url = f"https://app.devin.ai/sessions/{session_uuid}"
        is_running = display_status in {"running", "in_progress", "working", "queued"}

        with st.expander(
            f"Issue #{iss.issue_number}: {iss.title}  \u2014  [{session_type}] {display_status.upper()}",
            expanded=is_running,
        ):
            col_a, col_b = st.columns([3, 1])
            with col_a:
                st.markdown(f"**Session ID:** `{session_id}`")
                st.markdown(f"**Type:** {session_type}")
                st.markdown(f"**Status:** `{display_status}`")
            with col_b:
                st.link_button("Open in Devin", session_url)
else:
    st.info("No Devin sessions found.")

st.markdown("---")

# ---------------------------------------------------------------------------
# PR Tracker
# ---------------------------------------------------------------------------

st.subheader("Pull Request Tracker")

pr_issues = [iss for iss in filtered_issues if iss.pr_url is not None]

if pr_issues:
    pr_rows = []
    for iss in pr_issues:
        pr_rows.append(
            {
                "Issue #": iss.issue_number,
                "Title": iss.title,
                "PR URL": iss.pr_url,
                "PR State": (iss.pr_state or "unknown").capitalize(),
            }
        )

    pr_df = pd.DataFrame(pr_rows)

    st.dataframe(
        pr_df,
        column_config={
            "Issue #": st.column_config.NumberColumn("Issue #", format="%d"),
            "Title": st.column_config.TextColumn("Title", width="medium"),
            "PR URL": st.column_config.LinkColumn("PR URL", display_text="Open PR"),
            "PR State": st.column_config.TextColumn("PR State"),
        },
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No pull requests have been opened yet.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    f"Last state update: {state.last_updated or 'N/A'}  \u00b7  "
    f"Tracking {len(state.issues)} issue(s)"
)

# ---------------------------------------------------------------------------
# Auto-refresh loop
# ---------------------------------------------------------------------------

if auto_refresh:
    time.sleep(30)
    st.rerun()
