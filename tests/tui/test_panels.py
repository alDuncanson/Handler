"""Behavioral tests for the main TUI activity panels."""

from __future__ import annotations

from unittest.mock import Mock, call

import pytest
from a2a.types import (
    Artifact,
    DataPart,
    FilePart,
    FileWithUri,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
    TextPart,
)
from textual.app import App, ComposeResult
from textual.widgets import Button, Markdown, TabbedContent

from a2a_handler.auth import AuthType, create_oauth2_auth
from a2a_handler.tui.components.logs import LogsPanel
from a2a_handler.tui.components import ArtifactsPanel, TabbedMessagesPanel, TasksPanel


def _rendered_texts(widget) -> list[str]:
    return [str(child.render()) for child in widget.query("Label, Static")]


def _chat_texts(panel: TabbedMessagesPanel) -> list[str]:
    chat = panel.query_one("#chat")
    return [str(getattr(widget, "content", "")) for widget in chat.children]


def _log_lines(panel: TabbedMessagesPanel) -> list[str]:
    logs_panel = panel.query_one("#logs-panel", LogsPanel)
    return [str(line) for line in logs_panel.lines]


def _make_artifact(
    artifact_id: str = "artifact-123",
    *,
    name: str = "Release Notes",
    description: str = "Rendered markdown output",
    text: str = "Artifact body text",
) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        name=name,
        description=description,
        parts=[Part(root=TextPart(text=text))],
    )


def _make_task(
    task_id: str = "task-123",
    context_id: str = "ctx-123",
    *,
    state: TaskState = TaskState.completed,
    history_text: str = "Agent response body",
) -> Task:
    return Task(
        id=task_id,
        context_id=context_id,
        status=TaskStatus(state=state),
        history=[
            Message(
                message_id="msg-user-1",
                role=Role.user,
                parts=[Part(root=TextPart(text="User prompt"))],
                context_id=context_id,
                task_id=task_id,
            ),
            Message(
                message_id="msg-agent-1",
                role=Role.agent,
                parts=[Part(root=TextPart(text=history_text))],
                context_id=context_id,
                task_id=task_id,
            ),
        ],
        artifacts=[
            Artifact(
                artifact_id="artifact-123",
                name="Spec",
                description="Structured result",
                parts=[Part(root=TextPart(text="Artifact preview text"))],
            )
        ],
    )


class _TasksPanelHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield TasksPanel()


class _ArtifactsPanelHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield ArtifactsPanel()


class _MessagesPanelHarness(App[None]):
    def compose(self) -> ComposeResult:
        yield TabbedMessagesPanel()


@pytest.mark.asyncio
async def test_tasks_panel_updates_detail_view_and_copies_ids() -> None:
    """Selecting a task should expose its details and keep copy actions wired to the selection."""
    app = _TasksPanelHarness()
    copy_mock = Mock()
    setattr(app, "copy_to_clipboard", copy_mock)
    task = _make_task()

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TasksPanel)
        panel.add_task(task)
        await pilot.pause()

        detail_texts = _rendered_texts(panel.query_one("#task-detail"))
        assert any("task-123" in text for text in detail_texts)
        assert any("ctx-123" in text for text in detail_texts)
        assert any("Agent response body" in text for text in detail_texts)
        assert any("Artifact preview text" in text for text in detail_texts)

        updated_task = _make_task(history_text="Updated agent response")
        panel.update_task(updated_task)
        await pilot.pause()

        updated_texts = _rendered_texts(panel.query_one("#task-detail"))
        assert any("Updated agent response" in text for text in updated_texts)

        panel.action_copy_task_id()
        panel.action_copy_context_id()

        assert copy_mock.call_args_list == [
            call("task-123"),
            call("ctx-123"),
        ]


@pytest.mark.asyncio
async def test_tasks_panel_labels_protocol_history_parts() -> None:
    """Task history should show A2A message part kinds, not just chat text."""
    app = _TasksPanelHarness()
    task = Task(
        id="task-structured",
        context_id="ctx-structured",
        status=TaskStatus(state=TaskState.working),
        history=[
            Message(
                message_id="msg-user-structured",
                role=Role.user,
                parts=[Part(root=TextPart(text="Summarize this file"))],
                context_id="ctx-structured",
                task_id="task-structured",
            ),
            Message(
                message_id="msg-agent-data",
                role=Role.agent,
                parts=[
                    Part(
                        root=DataPart(
                            data={
                                "toolCall": {
                                    "name": "search_handler",
                                    "query": "handler mcp",
                                }
                            }
                        )
                    )
                ],
                context_id="ctx-structured",
                task_id="task-structured",
            ),
            Message(
                message_id="msg-agent-file",
                role=Role.agent,
                parts=[
                    Part(
                        root=FilePart(
                            file=FileWithUri(
                                uri="https://example.com/report.md",
                                name="report.md",
                                mime_type="text/markdown",
                            )
                        )
                    )
                ],
                context_id="ctx-structured",
                task_id="task-structured",
            ),
        ],
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TasksPanel)
        panel.add_task(task)
        await pilot.pause()

        detail_texts = _rendered_texts(panel.query_one("#task-detail"))
        assert any("Task History" in text for text in detail_texts)
        assert any("parts: text" in text for text in detail_texts)
        assert any("Summarize this file" in text for text in detail_texts)
        assert any("parts: data" in text for text in detail_texts)
        assert any(
            "toolCall" in text and "search_handler" in text for text in detail_texts
        )
        assert any("parts: file" in text for text in detail_texts)
        assert any("report.md (text/markdown)" in text for text in detail_texts)


@pytest.mark.asyncio
async def test_artifacts_panel_updates_detail_view_and_copies_ids() -> None:
    """Artifact details and copy actions should follow the selected artifact entry."""
    app = _ArtifactsPanelHarness()
    copy_mock = Mock()
    setattr(app, "copy_to_clipboard", copy_mock)
    artifact = _make_artifact()

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(ArtifactsPanel)
        panel.add_artifact(artifact, "task-123", "ctx-123")
        await pilot.pause()

        detail_texts = _rendered_texts(panel.query_one("#artifact-detail"))
        assert any("artifact-123" in text for text in detail_texts)
        assert any("Release Notes" in text for text in detail_texts)
        assert any("Artifact body text" in text for text in detail_texts)

        updated_artifact = _make_artifact(
            name="Updated Release Notes",
            description="New description",
            text="Updated artifact body",
        )
        panel.update_artifact(updated_artifact, "task-123", "ctx-123")
        await pilot.pause()

        updated_texts = _rendered_texts(panel.query_one("#artifact-detail"))
        assert any("Updated Release Notes" in text for text in updated_texts)
        assert any("Updated artifact body" in text for text in updated_texts)

        panel.action_copy_artifact_id()
        panel.action_copy_task_id()

        assert copy_mock.call_args_list == [
            call("artifact-123"),
            call("task-123"),
        ]


@pytest.mark.asyncio
async def test_messages_panel_clear_replaces_chat_with_system_notice() -> None:
    """Clearing chat should remove old entries and leave a single system message behind."""
    app = _MessagesPanelHarness()
    response = Message(
        message_id="msg-1",
        role=Role.agent,
        parts=[Part(root=TextPart(text="Agent reply"))],
        context_id="ctx-123",
        task_id="task-123",
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.add_message("user", "Hello there")
        panel.add_agent_message(response)
        await pilot.pause()

        await panel.clear()
        await pilot.pause()

        chat_texts = _chat_texts(panel)
        assert len(chat_texts) == 1
        assert "Chat cleared" in chat_texts[0]


@pytest.mark.asyncio
async def test_messages_panel_renders_completed_tasks_and_empty_agent_responses() -> (
    None
):
    """Completed resumed tasks should render their text, while empty responses stay visible."""
    app = _MessagesPanelHarness()
    completed_task = Task(
        id="task-completed-1",
        context_id="ctx-resumed-1",
        status=TaskStatus(state=TaskState.completed),
        history=[
            Message(
                message_id="msg-user-1",
                role=Role.user,
                parts=[Part(root=TextPart(text="Resume prior work"))],
                context_id="ctx-resumed-1",
                task_id="task-completed-1",
            ),
            Message(
                message_id="msg-agent-1",
                role=Role.agent,
                parts=[Part(root=TextPart(text="Recovered completed task output"))],
                context_id="ctx-resumed-1",
                task_id="task-completed-1",
            ),
        ],
    )
    empty_task = Task(
        id="task-completed-2",
        context_id="ctx-resumed-2",
        status=TaskStatus(state=TaskState.completed),
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.add_agent_message(completed_task)
        panel.add_agent_message(empty_task)
        await pilot.pause()

        chat_texts = _chat_texts(panel)
        assert any("Recovered completed task output" in text for text in chat_texts)
        assert any("(no text in response)" in text for text in chat_texts)


@pytest.mark.asyncio
async def test_messages_panel_renders_markdown_message_bodies() -> None:
    """Conversation messages should keep markdown available for rich rendering."""
    app = _MessagesPanelHarness()
    response = Message(
        message_id="msg-markdown-1",
        role=Role.agent,
        parts=[
            Part(
                root=TextPart(
                    text="## Handler CLI\n\nUse `handler message send`:\n\n```bash\nhandler message send http://agent.test 'hi'\n```"
                )
            )
        ],
        context_id="ctx-markdown",
        task_id="task-markdown",
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.add_message("user", "Please show `handler message send`")
        panel.add_agent_message(response)
        await pilot.pause()

        markdown_widgets = list(panel.query(Markdown))
        assert any(
            "Please show `handler message send`" in widget.source
            for widget in markdown_widgets
        )
        assert any("```bash" in widget.source for widget in markdown_widgets)


@pytest.mark.asyncio
async def test_messages_panel_opens_markdown_links() -> None:
    """Clicking a markdown link in a message should open the target URL."""
    app = _MessagesPanelHarness()
    open_url = Mock()
    setattr(app, "open_url", open_url)

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.add_message(
            "agent",
            "Read the [authentication guide](https://handler.alduncanson.com/guides/auth).",
        )
        await pilot.pause()

        markdown = panel.query_one(Markdown)
        markdown.post_message(
            Markdown.LinkClicked(
                markdown,
                "https://handler.alduncanson.com/guides/auth",
            )
        )
        await pilot.pause()

        open_url.assert_called_once_with("https://handler.alduncanson.com/guides/auth")


@pytest.mark.asyncio
async def test_messages_panel_opens_relative_markdown_links_as_docs_urls() -> None:
    """Relative docs links from MCP responses should open against Handler docs."""
    app = _MessagesPanelHarness()
    open_url = Mock()
    setattr(app, "open_url", open_url)

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.add_message("agent", "See [servers](/guides/servers).")
        await pilot.pause()

        markdown = panel.query_one(Markdown)
        markdown.post_message(Markdown.LinkClicked(markdown, "/guides/servers"))
        await pilot.pause()

        open_url.assert_called_once_with(
            "https://handler.alduncanson.com/guides/servers"
        )


@pytest.mark.asyncio
async def test_agent_message_actions_open_task_and_artifact_panels() -> None:
    """Agent timeline cards should make related task/artifact payloads discoverable."""
    app = _MessagesPanelHarness()
    task = Task(
        id="task-with-artifacts",
        context_id="ctx-with-artifacts",
        status=TaskStatus(state=TaskState.completed),
        artifacts=[
            Artifact(
                artifact_id="artifact-data",
                name="Processing Result",
                description="Structured processing payload",
                parts=[Part(root=DataPart(data={"status": "processed"}))],
            )
        ],
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.add_agent_message(task)
        panel.update_task(task)
        for artifact in task.artifacts or []:
            panel.update_artifact(artifact, task.id, task.context_id)
        await pilot.pause()

        chat_texts = _chat_texts(panel)
        assert any("Processing Result (data)" in text for text in chat_texts)
        assert not panel.query(".message-artifact-summary")
        metadata_values = _rendered_texts(panel.query_one(".message-metadata-row"))
        assert "artifact" in metadata_values
        assert "Processing Result (data)" in metadata_values

        panel.query_one(".view-artifacts", Button).press()
        await pilot.pause()

        tabs = panel.query_one("#messages-tabs", TabbedContent)
        assert tabs.active == "artifacts-tab"
        selected_artifact = panel.query_one(ArtifactsPanel).get_selected_artifact()
        assert selected_artifact is not None
        assert selected_artifact.artifact_id == "artifact-data"

        panel.query_one(".view-task", Button).press()
        await pilot.pause()

        assert tabs.active == "tasks-tab"
        selected_task = panel.query_one(TasksPanel).get_selected_task()
        assert selected_task is not None
        assert selected_task.task_id == "task-with-artifacts"


@pytest.mark.asyncio
async def test_messages_panel_action_availability_tracks_the_active_tab() -> None:
    """Tab-specific actions should only be enabled where the user can actually use them."""
    app = _MessagesPanelHarness()

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        tabs = panel.query_one("#messages-tabs", TabbedContent)

        tabs.active = "messages-tab"
        await pilot.pause()
        assert panel.check_action("scroll_down", ()) is True
        assert panel.check_action("scroll_half_down", ()) is True
        assert panel.check_action("scroll_left", ()) is False
        assert panel.check_action("copy_task_id", ()) is False

        tabs.active = "logs-tab"
        await pilot.pause()
        assert panel.check_action("scroll_down", ()) is True
        assert panel.check_action("scroll_half_up", ()) is True
        assert panel.check_action("scroll_right", ()) is True
        assert panel.check_action("copy_artifact_id", ()) is False

        tabs.active = "tasks-tab"
        await pilot.pause()
        assert panel.check_action("scroll_up", ()) is True
        assert panel.check_action("scroll_half_down", ()) is False
        assert panel.check_action("copy_task_id", ()) is True
        assert panel.check_action("copy_context_id", ()) is True

        tabs.active = "artifacts-tab"
        await pilot.pause()
        assert panel.check_action("scroll_down", ()) is True
        assert panel.check_action("copy_artifact_id", ()) is True
        assert panel.check_action("copy_task_id", ()) is False

        tabs.active = "auth-tab"
        await pilot.pause()
        assert panel.check_action("scroll_down", ()) is False
        assert panel.check_action("copy_artifact_id", ()) is False
        assert panel.check_action("next_tab", ()) is True


@pytest.mark.asyncio
async def test_messages_panel_tab_actions_follow_the_selected_tab() -> None:
    """Scrolling and copy actions should target the visible task or artifact list only."""
    app = _MessagesPanelHarness()
    copy_mock = Mock()
    setattr(app, "copy_to_clipboard", copy_mock)
    older_task = _make_task("task-older", "ctx-older")
    newer_task = _make_task("task-newer", "ctx-newer")
    older_artifact = _make_artifact("artifact-older", name="Older Artifact")
    newer_artifact = _make_artifact("artifact-newer", name="Newer Artifact")

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.add_task(older_task)
        panel.add_task(newer_task)
        panel.add_artifact(older_artifact, older_task.id, older_task.context_id)
        panel.add_artifact(newer_artifact, newer_task.id, newer_task.context_id)
        await pilot.pause()

        panel.action_copy_task_id()
        assert copy_mock.call_args_list == []

        panel.query_one("#messages-tabs", TabbedContent).active = "tasks-tab"
        await pilot.pause()

        assert panel.query_one(TasksPanel).get_selected_task() is not None
        assert panel.query_one(TasksPanel).get_selected_task().task_id == "task-newer"

        panel.action_scroll_down()
        await pilot.pause()
        assert panel.query_one(TasksPanel).get_selected_task().task_id == "task-newer"

        panel.action_scroll_down()
        await pilot.pause()

        selected_task = panel.query_one(TasksPanel).get_selected_task()
        assert selected_task is not None
        assert selected_task.task_id == "task-older"

        panel.action_copy_task_id()
        panel.action_copy_context_id()
        panel.action_scroll_up()
        await pilot.pause()
        assert panel.query_one(TasksPanel).get_selected_task().task_id == "task-newer"

        panel.query_one("#messages-tabs", TabbedContent).active = "artifacts-tab"
        await pilot.pause()

        assert panel.query_one(ArtifactsPanel).get_selected_artifact() is not None
        assert (
            panel.query_one(ArtifactsPanel).get_selected_artifact().artifact_id
            == "artifact-newer"
        )

        panel.action_scroll_down()
        await pilot.pause()
        assert (
            panel.query_one(ArtifactsPanel).get_selected_artifact().artifact_id
            == "artifact-newer"
        )

        panel.action_scroll_down()
        await pilot.pause()

        selected_artifact = panel.query_one(ArtifactsPanel).get_selected_artifact()
        assert selected_artifact is not None
        assert selected_artifact.artifact_id == "artifact-older"

        panel.action_copy_artifact_id()
        panel.action_scroll_up()
        await pilot.pause()
        assert (
            panel.query_one(ArtifactsPanel).get_selected_artifact().artifact_id
            == "artifact-newer"
        )

        assert copy_mock.call_args_list == [
            call("task-older"),
            call("ctx-older"),
            call("artifact-older"),
        ]


@pytest.mark.asyncio
async def test_messages_panel_tab_navigation_actions_switch_tabs() -> None:
    """Explicit tab actions should move through tabs without losing panel focus."""
    app = _MessagesPanelHarness()

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        tabs = panel.query_one("#messages-tabs", TabbedContent)
        panel.focus()
        await pilot.pause()

        assert tabs.active == "messages-tab"

        panel.action_next_tab()
        await pilot.pause()
        assert tabs.active == "tasks-tab"
        assert app.focused is panel

        panel.action_next_tab()
        await pilot.pause()
        assert tabs.active == "artifacts-tab"

        panel.action_previous_tab()
        await pilot.pause()
        assert tabs.active == "tasks-tab"


@pytest.mark.asyncio
async def test_messages_panel_clear_logs_only_resets_log_history() -> None:
    """Clearing logs should leave the visible chat transcript untouched."""
    app = _MessagesPanelHarness()

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.add_message("system", "Resumed session warning")
        panel.load_logs(["first log line", "second log line"])
        await pilot.pause()

        assert len(_chat_texts(panel)) == 1
        assert any("first log line" in line for line in _log_lines(panel))

        await panel.clear_logs()
        await pilot.pause()

        assert len(_chat_texts(panel)) == 1
        assert _log_lines(panel) == []


@pytest.mark.asyncio
async def test_messages_panel_reset_session_clears_chat_tasks_and_artifacts() -> None:
    """Resetting a live session should clear resumed conversation state, not connection config."""
    app = _MessagesPanelHarness()
    task = _make_task()
    artifact = _make_artifact()
    credentials = create_oauth2_auth(
        "https://auth.example.com/token",
        "client-id",
        "client-secret",
        scopes=["read", "write"],
    )
    credentials.custom_headers = {"X-Trace-ID": "trace-123"}

    async with app.run_test() as pilot:
        await pilot.pause()

        panel = app.query_one(TabbedMessagesPanel)
        panel.set_auth_credentials(credentials)
        panel.add_message("user", "Hello there")
        panel.add_task(task)
        panel.add_artifact(artifact, task.id, task.context_id)
        panel.add_log("background log line")
        await pilot.pause()

        assert len(_chat_texts(panel)) == 1
        assert panel.query_one(TasksPanel).get_selected_task() is not None
        assert panel.query_one(ArtifactsPanel).get_selected_artifact() is not None

        await panel.reset_session()
        await pilot.pause()

        assert _chat_texts(panel) == []
        assert panel.query_one(TasksPanel).get_selected_task() is None
        assert panel.query_one(ArtifactsPanel).get_selected_artifact() is None
        assert any("background log line" in line for line in _log_lines(panel))

        restored = panel.get_auth_credentials()
        assert restored is not None
        assert restored.auth_type == AuthType.OAUTH2
        assert restored.token_url == "https://auth.example.com/token"
        assert restored.client_id == "client-id"
        assert restored.client_secret == "client-secret"
        assert restored.scopes == ["read", "write"]
        assert restored.custom_headers == {"X-Trace-ID": "trace-123"}
