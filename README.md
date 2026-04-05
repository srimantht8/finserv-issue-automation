# FinServ Issue Automation — Powered by Devin

Automated GitHub issue triage and resolution for FinServ monorepos using [Devin AI](https://devin.ai).

Built for **Client A (FinServ Co)**: _"We've got 300+ open issues across our monorepo. Most of them are small-to-medium bugs and feature requests that sit there for months because our senior engineers are heads-down on platform work."_

## Architecture

```
GitHub Issues (open backlog)
        │
        ▼
┌────────────────┐         ┌──────────────┐
│  Orchestrator   │────────▶│  Devin API   │
│  (Python CLI)   │◀────────│  (AI Agent)  │
└───────┬────────┘         └──────────────┘
        │
   ┌────┴────┐
   ▼         ▼
state.json   Streamlit Dashboard
```

**Phase 1 — Triage:** Each open issue is sent to Devin, which clones the repo, reads the
relevant source files, and returns a structured analysis (severity, effort, category,
affected files, auto-fixability, fix approach). Results are posted as GitHub comments.

**Phase 2 — Resolve:** Auto-fixable issues are dispatched to Devin with instructions to
create a branch, implement the fix, write tests, and open a pull request. ACU budgets
are mapped to estimated effort to control costs.

## Prerequisites

- Python 3.10+
- A [Devin](https://devin.ai) account with API access
- A GitHub personal access token (fine-grained, with Issues + PRs + Contents permissions)

## Setup

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r orchestrator/requirements.txt
```

### 2. Create the target repo

The orchestrator works against a **separate GitHub repo** that Devin can access.
The `demo-repo/` directory contains a simulated FinServ monorepo with intentional
bugs — push it to GitHub as the target:

```bash
cd demo-repo
git init
git add .
git commit -m "Initial commit: API Gateway + Trading Engine services"
git remote add origin https://github.com/<YOUR_USERNAME>/<YOUR_REPO>.git
git branch -M main
git push -u origin main
cd ..
```

The demo repo contains:
- **API Gateway** (Node.js/Express) — authentication, user management
- **Trading Engine** (Python/FastAPI) — transactions, accounts

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your API keys and the target repo you just created:

| Variable | Required | Description |
|----------|----------|-------------|
| `DEVIN_API_KEY` | Yes | Devin API key |
| `GITHUB_TOKEN` | Yes | GitHub PAT with Issues + PRs + Contents permissions |
| `REPO_OWNER` | Yes | GitHub username or org (from step 2) |
| `REPO_NAME` | Yes | Target repository name (from step 2) |
| `STATE_FILE` | No | Path to state file (default: `orchestrator/state.json`) |

### 4. Seed GitHub issues

```bash
python -m scripts.seed_issues
```

Creates 15 realistic issues (bugs, enhancements, refactoring, docs) on the target
repo. The script is idempotent — it skips issues that already exist.

## Usage

### Triage open issues
```bash
# Triage all open issues
python -m orchestrator triage

# Triage specific issues
python -m orchestrator triage --issues 1,2,3
```

### Resolve auto-fixable issues
```bash
# Resolve all issues marked as auto-fixable
python -m orchestrator resolve --auto

# Resolve specific issues
python -m orchestrator resolve --issues 1,2,3
```

### Check status
```bash
python -m orchestrator status
```

### Launch dashboard
```bash
python -m orchestrator dashboard
# Opens Streamlit at http://localhost:8501
```

## Project Structure

```
orchestrator/
  main.py           — CLI entry point (triage, resolve, status, dashboard)
  triage.py          — Phase 1: issue classification via Devin
  resolve.py         — Phase 2: automated fixes and PR creation
  devin_client.py    — Devin API v1 client with retry logic
  github_client.py   — GitHub API wrapper (PyGithub)
  models.py          — Pydantic v2 data models and state persistence
  dashboard.py       — Streamlit visualization and controls
  config.py          — Environment configuration
  tests/             — Unit tests
demo-repo/           — Simulated FinServ monorepo (pushed to GitHub)
scripts/
  seed_issues.py     — Populate GitHub repo with realistic issues
```

## Running Tests

```bash
python -m pytest orchestrator/tests/ -v
```
