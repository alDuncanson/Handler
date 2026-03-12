"""Common utilities for the Handler package.

Provides logging and output utilities shared across modules.
"""

from .config import (
    clear_agent_bearer_command,
    get_agent_bearer_command,
    get_default_bearer_command,
    get_theme,
    save_agent_bearer_command,
    save_default_bearer_command,
    save_theme,
)
from .logging import (
    LogLevel,
    LogRecord,
    TUILogHandler,
    get_logger,
    get_tui_log_handler,
    install_tui_log_handler,
    setup_logging,
)
from .output import Output
from .output import configure_output

__all__ = [
    "LogLevel",
    "LogRecord",
    "Output",
    "configure_output",
    "clear_agent_bearer_command",
    "get_agent_bearer_command",
    "get_default_bearer_command",
    "TUILogHandler",
    "get_logger",
    "get_theme",
    "get_tui_log_handler",
    "install_tui_log_handler",
    "save_agent_bearer_command",
    "save_default_bearer_command",
    "save_theme",
    "setup_logging",
]
