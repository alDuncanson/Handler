"""Tests for Handler logging helpers."""

from __future__ import annotations

import logging
import threading

from a2a_handler.common.logging import TUILogHandler


def _record(name: str, message: str = "hello") -> logging.LogRecord:
    """Build a log record for direct handler tests."""
    return logging.LogRecord(
        name=name,
        level=logging.DEBUG,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_tui_log_handler_notifies_after_releasing_handler_lock() -> None:
    """Callbacks may touch the TUI without blocking unrelated logging calls."""
    handler = TUILogHandler()
    lock = threading.Lock()
    handler.lock = lock
    callback_saw_unlocked_handler = False

    def callback(line: str) -> None:
        nonlocal callback_saw_unlocked_handler
        callback_saw_unlocked_handler = lock.acquire(blocking=False)
        if callback_saw_unlocked_handler:
            lock.release()

    handler.set_callback(callback)

    assert handler.handle(_record("a2a_handler.test", "stored")) is True
    assert callback_saw_unlocked_handler is True
    assert any("stored" in line for line in handler.get_lines())


def test_tui_log_handler_ignores_markdown_parser_debug_noise() -> None:
    """Textual Markdown parsing should not flood or re-enter the TUI log panel."""
    handler = TUILogHandler()
    callback_lines: list[str] = []
    handler.set_callback(callback_lines.append)

    assert (
        handler.handle(_record("markdown_it.rules_block.fence", "entering fence"))
        is False
    )
    assert handler.get_lines() == []
    assert callback_lines == []
