"""Helpers for loading workspace-local environment files."""

from __future__ import annotations

from dotenv import find_dotenv, load_dotenv


def load_runtime_dotenv() -> bool:
    """Load a .env file by searching upward from the current working directory.

    This keeps `uvx` and other installed entrypoints aligned with how server
    config is discovered from the user's workspace instead of from site-packages.
    """

    dotenv_path = find_dotenv(usecwd=True)
    if not dotenv_path:
        return False
    return load_dotenv(dotenv_path=dotenv_path)
