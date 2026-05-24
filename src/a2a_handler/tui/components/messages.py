"""Messages panel component for displaying chat history."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from a2a.types import DataPart, FilePart, Task, TextPart
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import Button, Markdown, Static, TabbedContent, TabPane, Tabs

from a2a_handler.auth import AuthCredentials, AuthType
from a2a_handler.common import get_logger
from a2a_handler.service import (
    extract_text,
    response_context_id,
    response_state,
    response_task_id,
)
from a2a_handler.tui.components.artifacts import ArtifactsPanel
from a2a_handler.tui.components.auth import AuthPanel
from a2a_handler.tui.components.headers import HeadersPanel
from a2a_handler.tui.components.logs import LogsPanel
from a2a_handler.tui.components.tasks import TasksPanel

if TYPE_CHECKING:
    from a2a.types import Artifact, Task

    from a2a_handler.service import A2AResponse

logger = get_logger(__name__)

HANDLER_DOCS_URL = "https://handler.alduncanson.com/"


def _part_kind(part: Any) -> str:
    """Return a compact display label for an A2A part."""
    root = getattr(part, "root", part)
    if isinstance(root, TextPart):
        return "text"
    if isinstance(root, DataPart):
        return "data"
    if isinstance(root, FilePart):
        return "file"
    return getattr(root, "kind", type(root).__name__)


def _artifact_label(artifact: Artifact) -> str:
    """Return a human-readable artifact identifier for timeline summaries."""
    return artifact.name or artifact.artifact_id or "unnamed artifact"


def _artifact_summary(artifact: Artifact) -> str:
    """Summarize an artifact without forcing users into the raw protocol view."""
    kinds = [_part_kind(part) for part in artifact.parts or []]
    part_summary = ", ".join(kinds) if kinds else "no parts"
    return f"{_artifact_label(artifact)} ({part_summary})"


def _external_link_url(href: str) -> str | None:
    """Return an external URL for a markdown link if Handler can open it."""
    parsed = urlparse(href)
    if parsed.scheme in {"http", "https"}:
        return href
    if parsed.scheme:
        return None
    if href.startswith("#"):
        return None
    return urljoin(HANDLER_DOCS_URL, href)


class MessageActionButton(Button):
    """Button carrying protocol navigation metadata for a message card."""

    def __init__(
        self,
        label: str,
        *,
        task_id: str | None = None,
        artifact_id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(label, classes=classes)
        self.task_id = task_id
        self.artifact_id = artifact_id


class Message(Container):
    """A single message card in the conversation timeline."""

    def __init__(
        self,
        role: str,
        content: str,
        timestamp: datetime | None = None,
        metadata: str | None = None,
        markdown: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.role = role
        self.timestamp = timestamp or datetime.now()
        self.body = content
        self.metadata = metadata
        self.markdown = markdown
        self.content = self._plain_text()
        self.add_class(f"message-{role}")

    def _plain_text(self) -> str:
        """Return the text used by existing tests and simple transcript scans."""
        formatted_time = self.timestamp.strftime("%H:%M:%S")
        parts = [f"{formatted_time} {self.body}"]
        if self.metadata:
            parts.append(self.metadata)
        return "\n".join(parts)

    def compose(self) -> ComposeResult:
        formatted_time = self.timestamp.strftime("%H:%M:%S")
        yield Static(
            f"{formatted_time} {self.role.title()}",
            classes="message-header",
        )
        if self.markdown:
            yield Markdown(self.body, classes="message-body", open_links=False)
        else:
            yield Static(self.body, classes="message-body message-body-plain")
        if self.metadata:
            yield Static(self.metadata, classes="message-metadata")

    def on_mount(self) -> None:
        for widget in self.query("Markdown, Static"):
            widget.can_focus = False

    @on(Markdown.LinkClicked)
    def _open_markdown_link(self, event: Markdown.LinkClicked) -> None:
        """Open external markdown links from message bodies."""
        event.stop()
        url = _external_link_url(event.href)
        if url is None:
            self.notify(f"Unsupported link: {event.href}", severity="warning")
            return
        self.app.open_url(url)


class AgentMessage(Message):
    """An agent message with A2A protocol metadata."""

    def __init__(
        self,
        response: A2AResponse,
        timestamp: datetime | None = None,
        **kwargs: Any,
    ) -> None:
        content = extract_text(response) or "(no text in response)"
        self.task_id = response_task_id(response)
        self.context_id = response_context_id(response)
        self.artifacts = list(response.artifacts or []) if isinstance(response, Task) else []
        metadata = self._metadata(response)
        super().__init__(
            "agent",
            content,
            timestamp=timestamp,
            metadata=metadata,
            markdown=True,
            **kwargs,
        )

    def _metadata(self, response: A2AResponse) -> str | None:
        """Build compact protocol metadata for the message footer."""
        fields = []
        state = response_state(response)
        task_id = response_task_id(response)
        context_id = response_context_id(response)
        if state:
            fields.append(f"state: {state.value}")
        if task_id:
            fields.append(f"task: {task_id}")
        if context_id:
            fields.append(f"context: {context_id}")
        if self.artifacts:
            artifact_summaries = "; ".join(
                _artifact_summary(artifact) for artifact in self.artifacts
            )
            fields.append(f"artifacts: {artifact_summaries}")
        return " · ".join(fields) if fields else None

    def compose(self) -> ComposeResult:
        yield from super().compose()
        if self.task_id or self.artifacts:
            with Horizontal(classes="message-actions"):
                if self.task_id:
                    yield MessageActionButton(
                        "View task",
                        task_id=self.task_id,
                        classes="message-action view-task",
                    )
                if self.artifacts:
                    yield MessageActionButton(
                        "View artifacts",
                        classes="message-action view-artifacts",
                        task_id=self.task_id,
                        artifact_id=self.artifacts[0].artifact_id,
                    )


class ChatScrollContainer(VerticalScroll):
    """Scrollable chat area."""

    can_focus = False


class TabbedMessagesPanel(Container):
    """Panel with tabs for Messages and Logs."""

    BINDINGS = [
        Binding("h", "previous_tab", "← Tab", show=True, key_display="h/←"),
        Binding("l", "next_tab", "→ Tab", show=True, key_display="l/→"),
        Binding("left", "previous_tab", "Previous Tab", show=False),
        Binding("right", "next_tab", "Next Tab", show=False),
        Binding("j", "scroll_down", "↓ Scroll", show=True, key_display="j/↓"),
        Binding("k", "scroll_up", "↑ Scroll", show=True, key_display="k/↑"),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("ctrl+h", "scroll_left", "← Scroll", show=True),
        Binding("ctrl+l", "scroll_right", "→ Scroll", show=True),
        Binding("ctrl+left", "scroll_left", "Scroll Left", show=False),
        Binding("ctrl+right", "scroll_right", "Scroll Right", show=False),
        Binding("ctrl+d", "scroll_half_down", "½ Page ↓", show=True),
        Binding("ctrl+u", "scroll_half_up", "½ Page ↑", show=True),
        Binding("y", "copy_task_id", "Copy ID", show=False),
        Binding("Y", "copy_context_id", "Copy Ctx", show=False),
        Binding("a", "copy_artifact_id", "Copy ID", show=False),
    ]

    can_focus = True

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Show/hide actions based on active tab context."""
        active = self._get_active_tab_id()
        if action in ("scroll_down", "scroll_up"):
            return active in ("messages-tab", "logs-tab", "tasks-tab", "artifacts-tab")
        if action in ("scroll_half_down", "scroll_half_up"):
            return active in ("messages-tab", "logs-tab")
        if action in ("scroll_left", "scroll_right"):
            return active == "logs-tab"
        if action in ("copy_task_id", "copy_context_id"):
            return active == "tasks-tab"
        if action in ("copy_artifact_id",):
            return active == "artifacts-tab"
        return True

    def compose(self) -> ComposeResult:
        with TabbedContent(id="messages-tabs"):
            with TabPane("Messages", id="messages-tab"):
                yield ChatScrollContainer(id="chat")
            with TabPane("Tasks", id="tasks-tab"):
                yield TasksPanel(id="tasks-panel")
            with TabPane("Artifacts", id="artifacts-tab"):
                yield ArtifactsPanel(id="artifacts-panel")
            with TabPane("Auth", id="auth-tab"):
                yield AuthPanel(id="auth-panel")
            with TabPane("Headers", id="headers-tab"):
                yield HeadersPanel(id="headers-panel")
            with TabPane("Logs", id="logs-tab"):
                yield LogsPanel(id="logs-panel")

    def on_mount(self) -> None:
        for widget in self.query("TabbedContent, Tabs, Tab, TabPane"):
            widget.can_focus = False
        logger.debug("Tabbed messages panel mounted")

    @on(TabbedContent.TabActivated)
    def _on_tab_activated(self) -> None:
        """Refresh bindings when switching tabs."""
        self.refresh_bindings()

    def _get_chat_container(self) -> ChatScrollContainer:
        return self.query_one("#chat", ChatScrollContainer)

    def _get_logs_panel(self) -> LogsPanel:
        return self.query_one("#logs-panel", LogsPanel)

    def _get_auth_panel(self) -> AuthPanel:
        return self.query_one("#auth-panel", AuthPanel)

    def _get_headers_panel(self) -> HeadersPanel:
        return self.query_one("#headers-panel", HeadersPanel)

    def _get_tasks_panel(self) -> TasksPanel:
        return self.query_one("#tasks-panel", TasksPanel)

    def _get_artifacts_panel(self) -> ArtifactsPanel:
        return self.query_one("#artifacts-panel", ArtifactsPanel)

    def add_message(self, role: str, content: str) -> None:
        logger.debug("Adding %s message: %s", role, content[:50])
        chat_container = self._get_chat_container()
        message_widget = Message(role, content, markdown=role != "system")
        chat_container.mount(message_widget)
        chat_container.scroll_end(animate=False)

    def add_agent_message(self, response: A2AResponse) -> None:
        logger.debug(
            "Adding agent message - task_id=%s, state=%s",
            response_task_id(response),
            response_state(response),
        )
        chat_container = self._get_chat_container()
        message_widget = AgentMessage(response)
        chat_container.mount(message_widget)
        chat_container.scroll_end(animate=False)

    def add_system_message(self, content: str) -> None:
        logger.info("System message: %s", content)
        self.add_message("system", content)

    @on(Button.Pressed, ".view-task")
    def _view_message_task(self, event: Button.Pressed) -> None:
        """Switch to the Tasks tab for an agent message's task."""
        event.stop()
        if not isinstance(event.button, MessageActionButton):
            return
        task_id = event.button.task_id
        if not task_id:
            return
        self.show_task(task_id)

    @on(Button.Pressed, ".view-artifacts")
    def _view_message_artifacts(self, event: Button.Pressed) -> None:
        """Switch to the Artifacts tab for an agent message's artifacts."""
        event.stop()
        if not isinstance(event.button, MessageActionButton):
            return
        task_id = event.button.task_id
        artifact_id = event.button.artifact_id
        self.show_artifacts(task_id=task_id, artifact_id=artifact_id)

    def add_log(self, line: str) -> None:
        """Add a log line to the logs panel."""
        logs_panel = self._get_logs_panel()
        logs_panel.add_log(line)

    def load_logs(self, lines: list[str]) -> None:
        """Load multiple log lines at once."""
        logs_panel = self._get_logs_panel()
        logs_panel.load_logs(lines)

    async def clear(self) -> None:
        logger.info("Clearing chat messages")
        chat_container = self._get_chat_container()
        await chat_container.remove_children()
        self.add_system_message("Chat cleared")

    async def clear_logs(self) -> None:
        """Clear the logs panel."""
        logs_panel = self._get_logs_panel()
        logs_panel.clear()

    async def reset_session(self) -> None:
        """Clear connection-scoped message, task, and artifact state."""
        chat_container = self._get_chat_container()
        await chat_container.remove_children()
        self._get_tasks_panel().clear()
        self._get_artifacts_panel().clear()

    def get_auth_credentials(self) -> "AuthCredentials | None":
        """Get configured auth credentials and custom headers."""
        auth_panel = self._get_auth_panel()
        credentials = auth_panel.get_credentials()
        custom_headers = self._get_headers_panel().get_headers()
        if custom_headers:
            if credentials is None:
                credentials = AuthCredentials(
                    auth_type=AuthType.BEARER,
                    custom_headers=custom_headers,
                )
            else:
                credentials.custom_headers = custom_headers
        return credentials

    def set_auth_credentials(self, credentials: "AuthCredentials | None") -> None:
        """Preconfigure auth and headers panel fields from resolved credentials."""
        auth_panel = self._get_auth_panel()
        headers_panel = self._get_headers_panel()
        auth_panel.clear()
        headers_panel.clear()
        if credentials is None:
            return

        if credentials.auth_type == AuthType.BEARER and credentials.value:
            auth_panel.set_bearer_token(credentials.value)
        elif credentials.auth_type == AuthType.API_KEY:
            auth_panel.set_api_key(
                credentials.value,
                credentials.header_name or "X-API-Key",
            )
        elif (
            credentials.auth_type == AuthType.MTLS
            and credentials.cert_path
            and credentials.key_path
        ):
            auth_panel.set_mtls(
                credentials.cert_path,
                credentials.key_path,
                credentials.ca_cert_path,
            )
        elif (
            credentials.auth_type == AuthType.OAUTH2
            and credentials.token_url
            and credentials.client_id
            and credentials.client_secret
        ):
            auth_panel.set_oauth2(
                credentials.token_url,
                credentials.client_id,
                credentials.client_secret,
                credentials.scopes,
            )

        headers_panel.set_headers(credentials.custom_headers)

    def add_task(self, task: "Task") -> None:
        """Add a task to the tasks panel."""
        tasks_panel = self._get_tasks_panel()
        tasks_panel.add_task(task)

    def update_task(self, task: "Task") -> None:
        """Update an existing task or add if new."""
        tasks_panel = self._get_tasks_panel()
        tasks_panel.update_task(task)

    def add_artifact(self, artifact: "Artifact", task_id: str, context_id: str) -> None:
        """Add an artifact to the artifacts panel."""
        artifacts_panel = self._get_artifacts_panel()
        artifacts_panel.add_artifact(artifact, task_id, context_id)

    def update_artifact(
        self, artifact: "Artifact", task_id: str, context_id: str
    ) -> None:
        """Update an existing artifact or add if new."""
        artifacts_panel = self._get_artifacts_panel()
        artifacts_panel.update_artifact(artifact, task_id, context_id)

    def show_task(self, task_id: str) -> None:
        """Open the Tasks tab and select the requested task when present."""
        tabbed_content = self.query_one("#messages-tabs", TabbedContent)
        tabbed_content.active = "tasks-tab"
        self._get_tasks_panel().select_task(task_id)
        self.focus()

    def show_artifacts(
        self, *, task_id: str | None = None, artifact_id: str | None = None
    ) -> None:
        """Open the Artifacts tab and select the requested artifact when present."""
        tabbed_content = self.query_one("#messages-tabs", TabbedContent)
        tabbed_content.active = "artifacts-tab"
        self._get_artifacts_panel().select_artifact(
            task_id=task_id,
            artifact_id=artifact_id,
        )
        self.focus()

    def _get_active_tab_id(self) -> str:
        tabbed_content = self.query_one("#messages-tabs", TabbedContent)
        return tabbed_content.active

    def action_previous_tab(self) -> None:
        """Switch to the previous tab."""
        tabs = self.query_one("#messages-tabs Tabs", Tabs)
        tabs.action_previous_tab()
        self.focus()

    def action_next_tab(self) -> None:
        """Switch to the next tab."""
        tabs = self.query_one("#messages-tabs Tabs", Tabs)
        tabs.action_next_tab()
        self.focus()

    def action_scroll_down(self) -> None:
        active = self._get_active_tab_id()
        if active == "messages-tab":
            self._get_chat_container().scroll_down()
        elif active == "logs-tab":
            self._get_logs_panel().scroll_down()
        elif active == "tasks-tab":
            self._get_tasks_panel().action_cursor_down()
        elif active == "artifacts-tab":
            self._get_artifacts_panel().action_cursor_down()

    def action_scroll_up(self) -> None:
        active = self._get_active_tab_id()
        if active == "messages-tab":
            self._get_chat_container().scroll_up()
        elif active == "logs-tab":
            self._get_logs_panel().scroll_up()
        elif active == "tasks-tab":
            self._get_tasks_panel().action_cursor_up()
        elif active == "artifacts-tab":
            self._get_artifacts_panel().action_cursor_up()

    def action_scroll_left(self) -> None:
        active = self._get_active_tab_id()
        if active == "logs-tab":
            self._get_logs_panel().scroll_left()

    def action_scroll_right(self) -> None:
        active = self._get_active_tab_id()
        if active == "logs-tab":
            self._get_logs_panel().scroll_right()

    def action_scroll_half_down(self) -> None:
        active = self._get_active_tab_id()
        if active == "messages-tab":
            container = self._get_chat_container()
            container.scroll_relative(y=container.size.height // 2)
        elif active == "logs-tab":
            panel = self._get_logs_panel()
            panel.scroll_relative(y=panel.size.height // 2)

    def action_scroll_half_up(self) -> None:
        active = self._get_active_tab_id()
        if active == "messages-tab":
            container = self._get_chat_container()
            container.scroll_relative(y=-(container.size.height // 2))
        elif active == "logs-tab":
            panel = self._get_logs_panel()
            panel.scroll_relative(y=-(panel.size.height // 2))

    def action_copy_task_id(self) -> None:
        """Copy the selected task ID to clipboard."""
        active = self._get_active_tab_id()
        if active == "tasks-tab":
            tasks_panel = self._get_tasks_panel()
            tasks_panel.action_copy_task_id()

    def action_copy_context_id(self) -> None:
        """Copy the selected context ID to clipboard."""
        active = self._get_active_tab_id()
        if active == "tasks-tab":
            tasks_panel = self._get_tasks_panel()
            tasks_panel.action_copy_context_id()

    def action_copy_artifact_id(self) -> None:
        """Copy the selected artifact ID to clipboard."""
        active = self._get_active_tab_id()
        if active == "artifacts-tab":
            artifacts_panel = self._get_artifacts_panel()
            artifacts_panel.action_copy_artifact_id()
