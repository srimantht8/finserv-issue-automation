"""Pydantic v2 models for issue triage, session tracking, and application state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class TriageResult(BaseModel):
    """Result of triaging a single GitHub issue."""

    model_config = ConfigDict(strict=True)

    severity: Literal["critical", "high", "medium", "low"]
    estimated_effort: Literal["trivial", "small", "medium", "large"]
    category: Literal["bug", "feature", "refactor", "docs"]
    affected_files: list[str]
    summary: str
    can_auto_fix: bool
    fix_approach: str


class IssueState(BaseModel):
    """Tracks the lifecycle of a single issue through triage and resolution."""

    model_config = ConfigDict(strict=True)

    issue_number: int
    title: str
    labels: list[str]
    triage_session_id: Optional[str] = None
    triage_result: Optional[TriageResult] = None
    resolve_session_id: Optional[str] = None
    resolve_status: Optional[str] = None
    pr_url: Optional[str] = None
    pr_state: Optional[str] = None


class SessionInfo(BaseModel):
    """Snapshot of a Devin session."""

    model_config = ConfigDict(strict=True)

    session_id: str
    status: str
    pull_requests: list[dict]
    structured_output: Optional[dict] = None
    created_at: str
    updated_at: str


class AppState(BaseModel):
    """Top-level application state persisted to disk."""

    issues: dict[int, IssueState] = {}
    last_updated: str = ""

    def save(self, path: str) -> None:
        """Serialize the state to a JSON file at *path*."""
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str) -> AppState:
        """Deserialize an ``AppState`` from the JSON file at *path*.

        Returns a fresh ``AppState`` if the file does not exist.
        """
        filepath = Path(path)
        if not filepath.exists():
            return cls()
        data = json.loads(filepath.read_text())
        return cls.model_validate(data)
