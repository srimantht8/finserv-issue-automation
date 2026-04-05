"""GitHub API client for the Cognition orchestrator."""

from datetime import datetime, timezone

from github import Github, GithubException

from orchestrator.config import get_config


def _timestamp() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(message: str) -> None:
    """Print a timestamped log message to stdout."""
    print(f"[{_timestamp()}] {message}")


def _issue_to_dict(issue) -> dict:
    """Convert a PyGithub Issue object to a plain dictionary."""
    return {
        "number": issue.number,
        "title": issue.title,
        "body": issue.body or "",
        "labels": [label.name for label in issue.labels],
        "created_at": issue.created_at.isoformat(),
        "url": issue.html_url,
    }


class GitHubClient:
    """Thin wrapper around the GitHub API using PyGithub."""

    def __init__(self) -> None:
        config = get_config()
        self._gh = Github(config.GITHUB_TOKEN)
        self._repo = self._gh.get_repo(f"{config.REPO_OWNER}/{config.REPO_NAME}")
        _log(f"GitHubClient initialised for {config.REPO_OWNER}/{config.REPO_NAME}")

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def fetch_open_issues(self) -> list[dict]:
        """Return every open issue (excluding pull requests) as a dict.

        PyGithub's ``get_issues`` returns both issues and PRs.  We filter
        out PRs by checking the ``pull_request`` attribute.
        """
        _log("Fetching open issues...")
        try:
            issues = self._repo.get_issues(state="open")
            result: list[dict] = []
            for issue in issues:
                if issue.pull_request is not None:
                    continue
                result.append(_issue_to_dict(issue))
            _log(f"Fetched {len(result)} open issues")
            return result
        except GithubException as exc:
            _log(f"Error fetching open issues: {exc}")
            raise

    def get_issue(self, issue_number: int) -> dict:
        """Return a single issue as a dict.

        Raises ``GithubException`` if the issue does not exist.
        """
        _log(f"Fetching issue #{issue_number}...")
        try:
            issue = self._repo.get_issue(number=issue_number)
            return _issue_to_dict(issue)
        except GithubException as exc:
            _log(f"Error fetching issue #{issue_number}: {exc}")
            raise

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def add_label(self, issue_number: int, label: str) -> None:
        """Add *label* to the given issue, creating it first if necessary."""
        _log(f"Adding label '{label}' to issue #{issue_number}...")
        try:
            # Ensure the label exists on the repo.
            try:
                self._repo.get_label(label)
            except GithubException:
                _log(f"Label '{label}' does not exist — creating it")
                self._repo.create_label(name=label, color="ededed")

            issue = self._repo.get_issue(number=issue_number)
            issue.add_to_labels(label)
            _log(f"Label '{label}' added to issue #{issue_number}")
        except GithubException as exc:
            _log(f"Error adding label '{label}' to issue #{issue_number}: {exc}")
            raise

    def add_comment(self, issue_number: int, comment: str) -> None:
        """Post a comment on the given issue."""
        _log(f"Adding comment to issue #{issue_number}...")
        try:
            issue = self._repo.get_issue(number=issue_number)
            issue.create_comment(comment)
            _log(f"Comment added to issue #{issue_number}")
        except GithubException as exc:
            _log(f"Error adding comment to issue #{issue_number}: {exc}")
            raise

    def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> int:
        """Create a new issue and return its number."""
        _log(f"Creating issue: {title!r}...")
        try:
            issue = self._repo.create_issue(
                title=title,
                body=body,
                labels=labels or [],
            )
            _log(f"Created issue #{issue.number}: {title!r}")
            return issue.number
        except GithubException as exc:
            _log(f"Error creating issue: {exc}")
            raise
