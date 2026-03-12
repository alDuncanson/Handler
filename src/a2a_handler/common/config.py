"""Configuration persistence for Handler.

Stores user preferences (theme, etc.) in a config file.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".handler"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_THEME = "gruvbox"
AUTH_CONFIG_KEY = "auth"
DEFAULT_BEARER_COMMAND_KEY = "default_bearer_command"
AGENT_BEARER_COMMANDS_KEY = "agent_bearer_commands"


def _ensure_config_dir() -> None:
    """Ensure the config directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict[str, Any]:
    """Load the config file, returning empty dict if not found."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load config: %s", e)
        return {}


def _save_config(config: dict[str, Any]) -> None:
    """Save config to file."""
    _ensure_config_dir()
    try:
        CONFIG_FILE.write_text(json.dumps(config, indent=2))
    except OSError as e:
        logger.warning("Failed to save config: %s", e)


def _get_auth_config(config: dict[str, Any]) -> dict[str, Any]:
    """Ensure auth config object exists and return it."""
    auth_config = config.get(AUTH_CONFIG_KEY)
    if not isinstance(auth_config, dict):
        auth_config = {}
        config[AUTH_CONFIG_KEY] = auth_config
    return auth_config


def get_theme() -> str:
    """Get the saved theme, or default if not set."""
    config = _load_config()
    return config.get("theme", DEFAULT_THEME)


def save_theme(theme: str) -> None:
    """Save the theme to config."""
    config = _load_config()
    config["theme"] = theme
    _save_config(config)


def get_default_bearer_command() -> str | None:
    """Get the configured default bearer token command, if present."""
    config = _load_config()
    auth_config = config.get(AUTH_CONFIG_KEY)
    if not isinstance(auth_config, dict):
        return None

    command = auth_config.get(DEFAULT_BEARER_COMMAND_KEY)
    if isinstance(command, str) and command.strip():
        return command
    return None


def save_default_bearer_command(command: str | None) -> None:
    """Set or clear the global default bearer token command."""
    config = _load_config()
    auth_config = _get_auth_config(config)

    if command is None:
        auth_config.pop(DEFAULT_BEARER_COMMAND_KEY, None)
    else:
        auth_config[DEFAULT_BEARER_COMMAND_KEY] = command

    _save_config(config)


def get_agent_bearer_command(agent_url: str) -> str | None:
    """Get a per-agent bearer token command, if configured."""
    config = _load_config()
    auth_config = config.get(AUTH_CONFIG_KEY)
    if not isinstance(auth_config, dict):
        return None

    by_agent = auth_config.get(AGENT_BEARER_COMMANDS_KEY)
    if not isinstance(by_agent, dict):
        return None

    command = by_agent.get(agent_url)
    if isinstance(command, str) and command.strip():
        return command
    return None


def save_agent_bearer_command(agent_url: str, command: str) -> None:
    """Persist a per-agent bearer token command."""
    config = _load_config()
    auth_config = _get_auth_config(config)
    by_agent = auth_config.get(AGENT_BEARER_COMMANDS_KEY)
    if not isinstance(by_agent, dict):
        by_agent = {}
        auth_config[AGENT_BEARER_COMMANDS_KEY] = by_agent

    by_agent[agent_url] = command
    _save_config(config)


def clear_agent_bearer_command(agent_url: str) -> None:
    """Remove a configured per-agent bearer token command."""
    config = _load_config()
    auth_config = _get_auth_config(config)
    by_agent = auth_config.get(AGENT_BEARER_COMMANDS_KEY)
    if isinstance(by_agent, dict):
        by_agent.pop(agent_url, None)
    _save_config(config)
