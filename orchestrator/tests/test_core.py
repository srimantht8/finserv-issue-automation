"""Unit tests for the FinServ Issue Automation orchestrator."""

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.models import AppState, IssueState, TriageResult
from orchestrator.triage import build_triage_prompt, get_triage_schema
from orchestrator.resolve import build_resolve_prompt, get_acu_limit
from orchestrator.main import _parse_issues


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestTriageResult:
    def test_valid_result(self):
        result = TriageResult(
            severity="high",
            estimated_effort="small",
            category="bug",
            affected_files=["src/main.py"],
            summary="A bug in the main module.",
            can_auto_fix=True,
            fix_approach="Add input validation.",
        )
        assert result.severity == "high"
        assert result.can_auto_fix is True

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            TriageResult(
                severity="urgent",  # not in enum
                estimated_effort="small",
                category="bug",
                affected_files=[],
                summary="test",
                can_auto_fix=False,
                fix_approach="n/a",
            )

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            TriageResult(
                severity="low",
                estimated_effort="small",
                category="improvement",  # not in enum
                affected_files=[],
                summary="test",
                can_auto_fix=False,
                fix_approach="n/a",
            )


class TestAppState:
    def test_save_and_load_round_trip(self, tmp_path):
        state = AppState()
        state.issues[1] = IssueState(
            issue_number=1,
            title="Test issue",
            labels=["bug"],
            triage_result=TriageResult(
                severity="critical",
                estimated_effort="trivial",
                category="bug",
                affected_files=["a.py"],
                summary="summary",
                can_auto_fix=True,
                fix_approach="fix it",
            ),
        )
        state.last_updated = "2026-01-01T00:00:00Z"

        path = str(tmp_path / "state.json")
        state.save(path)

        loaded = AppState.load(path)
        assert len(loaded.issues) == 1
        assert loaded.issues[1].title == "Test issue"
        assert loaded.issues[1].triage_result.severity == "critical"
        assert loaded.last_updated == "2026-01-01T00:00:00Z"

    def test_load_nonexistent_returns_empty(self, tmp_path):
        state = AppState.load(str(tmp_path / "missing.json"))
        assert len(state.issues) == 0


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------


class TestTriagePrompt:
    def test_contains_issue_details(self):
        issue = {
            "number": 42,
            "title": "Login broken",
            "labels": ["bug", "high-priority"],
            "body": "Users can't log in.",
        }
        prompt = build_triage_prompt(issue)
        assert "ISSUE #42" in prompt
        assert "Login broken" in prompt
        assert "bug, high-priority" in prompt
        assert "Users can't log in." in prompt

    def test_schema_has_required_fields(self):
        schema = get_triage_schema()
        required = schema["required"]
        assert "severity" in required
        assert "can_auto_fix" in required
        assert "affected_files" in required


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------


class TestResolve:
    def test_acu_limit_mapping(self):
        assert get_acu_limit("trivial") == 3
        assert get_acu_limit("small") == 5
        assert get_acu_limit("medium") == 8
        assert get_acu_limit("large") == 10
        assert get_acu_limit("unknown") == 5  # default

    def test_acu_limit_returns_int(self):
        for effort in ["trivial", "small", "medium", "large"]:
            assert isinstance(get_acu_limit(effort), int)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestParseIssues:
    def test_comma_separated(self):
        assert _parse_issues("1,2,3") == [1, 2, 3]

    def test_single_issue(self):
        assert _parse_issues("42") == [42]

    def test_whitespace_handling(self):
        assert _parse_issues(" 1 , 2 , 3 ") == [1, 2, 3]
