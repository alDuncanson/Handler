"""Configuration persistence for Handler.

Stores user preferences (theme, etc.) in a config file.
"""

import json
import logging
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(user_config_dir("handler"))
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_THEME = "gruvbox"


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


def get_theme() -> str:
    """Get the saved theme, or default if not set."""
    config = _load_config()
    return config.get("theme", DEFAULT_THEME)


def save_theme(theme: str) -> None:
    """Save the theme to config."""
    config = _load_config()
    config["theme"] = theme
    _save_config(config)
