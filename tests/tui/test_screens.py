"""Tests for the command palette prompt screens."""

from __future__ import annotations

from textual.app import App
from textual.widgets import Input

from a2a_handler.tui.commands.screens import ConfirmScreen, TextPromptScreen


class _Harness(App[None]):
    pass


async def test_text_prompt_returns_the_trimmed_value() -> None:
    results: list[str | None] = []
    app = _Harness()
    async with app.run_test() as pilot:
        app.push_screen(
            TextPromptScreen("Rename", "Pick a name", value="old"),
            callback=results.append,
        )
        await pilot.pause()
        app.screen.query_one("#command-dialog-input", Input).value = "  new-name  "
        await pilot.click("#command-dialog-confirm")
        await pilot.pause()
    assert results == ["new-name"]


async def test_text_prompt_returns_none_for_blank_or_cancel() -> None:
    results: list[str | None] = []
    app = _Harness()
    async with app.run_test() as pilot:
        app.push_screen(
            TextPromptScreen("Rename", "Pick a name"), callback=results.append
        )
        await pilot.pause()
        app.screen.query_one("#command-dialog-input", Input).value = "   "
        await pilot.click("#command-dialog-confirm")
        await pilot.pause()

        app.push_screen(
            TextPromptScreen("Rename", "Pick a name"), callback=results.append
        )
        await pilot.pause()
        await pilot.click("#command-dialog-cancel")
        await pilot.pause()
    assert results == [None, None]


async def test_text_prompt_submits_on_enter() -> None:
    results: list[str | None] = []
    app = _Harness()
    async with app.run_test() as pilot:
        app.push_screen(
            TextPromptScreen("Rename", "Pick a name", value="typed"),
            callback=results.append,
        )
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert results == ["typed"]


async def test_confirm_screen_reports_the_choice() -> None:
    results: list[bool] = []
    app = _Harness()
    async with app.run_test() as pilot:
        app.push_screen(
            ConfirmScreen("Remove", "Really?", confirm_label="Remove"),
            callback=results.append,
        )
        await pilot.pause()
        await pilot.click("#command-dialog-confirm")
        await pilot.pause()

        app.push_screen(ConfirmScreen("Remove", "Really?"), callback=results.append)
        await pilot.pause()
        await pilot.click("#command-dialog-cancel")
        await pilot.pause()
    assert results == [True, False]
