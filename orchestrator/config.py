"""Configuration module for the Cognition orchestrator."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    DEVIN_API_KEY: str
    DEVIN_BASE_URL: str
    GITHUB_TOKEN: str
    REPO_OWNER: str
    REPO_NAME: str
    STATE_FILE: str


_config: Config | None = None


def get_config() -> Config:
    """Return the singleton Config instance, creating it on first call.

    Raises ``ValueError`` if any required environment variable is missing.
    """
    global _config
    if _config is not None:
        return _config

    required_vars = [
        "DEVIN_API_KEY",
        "GITHUB_TOKEN",
        "REPO_OWNER",
        "REPO_NAME",
    ]

    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Please set them in your .env file or shell environment."
        )

    _config = Config(
        DEVIN_API_KEY=os.environ["DEVIN_API_KEY"],
        DEVIN_BASE_URL=os.getenv("DEVIN_BASE_URL", "https://api.devin.ai/v1"),
        GITHUB_TOKEN=os.environ["GITHUB_TOKEN"],
        REPO_OWNER=os.environ["REPO_OWNER"],
        REPO_NAME=os.environ["REPO_NAME"],
        STATE_FILE=os.getenv("STATE_FILE", "orchestrator/state.json"),
    )
    return _config
