"""Tasks panel component for viewing task history and details."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from a2a.types import DataPart, FilePart, TextPart
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message as TextualMessage
from textual.reactive import reactive
from textual.widgets import Collapsible, Label, ListItem, ListView, Static

from a2a_handler.common import get_logger

if TYPE_CHECKING:
    from a2a.types import Message, Part, Task, TaskState

logger = get_logger(__name__)


class TaskEntry:
    """Represents a task entry for display."""

    def __init__(self, task: Task, received_at: datetime | None = None) -> None:
        self.task = task
        self.received_at = received_at or datetime.now()

    @property
    def task_id(self) -> str:
        return self.task.id

    @property
    def context_id(self) -> str:
        return self.task.context_id

    @property
    def state(self) -> TaskState | None:
        if self.task.status:
            return self.task.status.state
        return None

    @property
    def state_str(self) -> str:
        return str(self.state.value) if self.state else "unknown"


def _truncate_preview(value: str, limit: int = 120) -> str:
    """Return a single-line preview capped to a readable width."""
    preview = value.replace("\n", " ").strip()
    if len(preview) > limit:
        return f"{preview[: limit - 3]}..."
    return preview


def _part_kind(part: Part) -> str:
    """Return a display label for an A2A message part kind."""
    root = part.root
    if isinstance(root, TextPart):
        return "text"
    if isinstance(root, DataPart):
        return "data"
    if isinstance(root, FilePart):
        return "file"
    return getattr(root, "kind", type(root).__name__)


def _data_part_preview(part: DataPart) -> str:
    """Build a compact preview for structured A2A data parts."""
    data = part.data
    for key in (
        "name",
        "type",
        "functionCall",
        "function_call",
        "functionResponse",
        "function_response",
        "toolCall",
        "tool_call",
        "toolResult",
        "tool_result",
    ):
        if key in data:
            return _truncate_preview(f"{key}: {data[key]}")
    return _truncate_preview(json.dumps(data, default=str))


def _file_part_preview(part: FilePart) -> str:
    """Build a compact preview for file parts."""
    file_part = part.file
    name = getattr(file_part, "name", None)
    uri = getattr(file_part, "uri", None)
    mime_type = getattr(file_part, "mime_type", None)
    if name and mime_type:
        return f"{name} ({mime_type})"
    if name:
        return name
    if uri:
        return _truncate_preview(uri)
    if mime_type:
        return mime_type
    return "inline file"


def _part_preview(part: Part) -> str:
    """Return a human-readable preview for any A2A message part."""
    root = part.root
    if isinstance(root, TextPart):
        return _truncate_preview(root.text)
    if isinstance(root, DataPart):
        return _data_part_preview(root)
    if isinstance(root, FilePart):
        return _file_part_preview(root)
    return _truncate_preview(json.dumps(part.model_dump(), default=str))


def _message_part_kinds(message: Message) -> str:
    """Summarize the part kinds carried by a protocol message."""
    if not message.parts:
        return "no parts"
    kinds = [_part_kind(part) for part in message.parts]
    return ", ".join(kinds)


def _message_preview(message: Message) -> str:
    """Return the best available single-line preview for a protocol message."""
    if not message.parts:
        return "(no parts)"
    previews = [_part_preview(part) for part in message.parts]
    return _truncate_preview(" | ".join(preview for preview in previews if preview))


class TaskListItem(ListItem):
    """A single task item in the list."""

    def __init__(
        self,
        entry: TaskEntry,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.entry = entry

    def compose(self) -> ComposeResult:
        time_str = self.entry.received_at.strftime("%H:%M:%S")
        task_id_short = self.entry.task_id[:8] if self.entry.task_id else "?"
        yield Label(f"{time_str}  {task_id_short}")


class TaskDetailPanel(VerticalScroll):
    """Panel showing detailed information about the selected task."""

    def compose(self) -> ComposeResult:
        yield Static("Select a task to view details", id="task-detail-placeholder")
        yield Container(id="task-detail-content", classes="hidden")

    def _field(
        self, label: str, value: str, value_class: str = "task-value"
    ) -> Horizontal:
        """Create a label-value field row."""
        return Horizontal(
            Label(f"{label}: ", classes="task-label"),
            Label(value, classes=value_class),
            classes="task-field-row",
        )

    def _section_heading(self, title: str) -> Static:
        """Create a section heading."""
        return Static(title, classes="section-heading")

    def show_task(self, entry: TaskEntry | None) -> None:
        placeholder = self.query_one("#task-detail-placeholder", Static)
        content = self.query_one("#task-detail-content", Container)

        if entry is None:
            placeholder.remove_class("hidden")
            content.add_class("hidden")
            return

        placeholder.add_class("hidden")
        content.remove_class("hidden")
        content.remove_children()

        task = entry.task

        content.mount(self._section_heading("Metadata"))
        content.mount(
            self._field("Task ID", task.id),
            self._field("Context ID", task.context_id),
            self._field("State", entry.state_str, "task-value-state"),
            self._field("Received", entry.received_at.strftime("%Y-%m-%d %H:%M:%S")),
        )

        if task.status:
            if task.status.timestamp:
                content.mount(self._field("Last Updated", task.status.timestamp))
            if task.status.message:
                msg = task.status.message
                if hasattr(msg, "parts") and msg.parts:
                    from a2a_handler.service import extract_text_from_message_parts

                    text = extract_text_from_message_parts(msg.parts)
                    if text:
                        content.mount(self._field("Status Message", text[:200]))

        if task.artifacts:
            content.mount(self._section_heading("Artifacts"))
            for artifact in task.artifacts:
                artifact_id = artifact.artifact_id or "unnamed"
                content.mount(Static(artifact_id, classes="artifact-id"))
                if artifact.parts:
                    from a2a_handler.service import extract_text_from_message_parts

                    text = extract_text_from_message_parts(artifact.parts)
                    if text:
                        preview = text[:100].replace("\n", " ")
                        if len(text) > 100:
                            preview += "..."
                        content.mount(Static(preview, classes="artifact-preview"))

                raw_json = json.dumps(artifact.model_dump(), indent=2, default=str)
                content.mount(
                    Collapsible(
                        Static(raw_json),
                        title="Raw JSON",
                        collapsed=True,
                    )
                )

        if task.history:
            content.mount(self._section_heading("Task History"))
            for message in task.history:
                role_value = (
                    message.role.value
                    if hasattr(message.role, "value")
                    else str(message.role)
                    if hasattr(message, "role")
                    else "unknown"
                )
                role_class = (
                    "history-role-agent"
                    if role_value == "agent"
                    else "history-role-user"
                )

                content.mount(
                    Container(
                        Static(role_value, classes=role_class),
                        Static(
                            f"parts: {_message_part_kinds(message)}",
                            classes="history-part-kinds",
                        ),
                        Static(_message_preview(message), classes="history-message"),
                        classes="history-item",
                    )
                )

                raw_json = json.dumps(message.model_dump(), indent=2, default=str)
                content.mount(
                    Collapsible(
                        Static(raw_json),
                        title="Raw JSON",
                        collapsed=True,
                    )
                )


class TasksPanel(Container):
    """Panel with split view: task list on left, details on right."""

    BINDINGS = [
        Binding("j", "cursor_down", "↓ Select", show=True, key_display="j/↓"),
        Binding("k", "cursor_up", "↑ Select", show=True, key_display="k/↑"),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("ctrl+d", "scroll_detail_down", "½ Page ↓", show=True),
        Binding("ctrl+u", "scroll_detail_up", "½ Page ↑", show=True),
        Binding("enter", "select_task", "View", show=True),
        Binding("y", "copy_task_id", "Copy ID", show=True),
        Binding("Y", "copy_context_id", "Copy Ctx", show=True),
    ]

    can_focus = False

    selected_index: reactive[int] = reactive(0)
    _tasks: list[TaskEntry] = []

    class TaskSelected(TextualMessage):
        """Posted when a task is selected."""

        def __init__(self, entry: TaskEntry) -> None:
            super().__init__()
            self.entry = entry

    def compose(self) -> ComposeResult:
        with Horizontal(id="tasks-split"):
            yield ListView(id="tasks-list")
            yield TaskDetailPanel(id="task-detail")

    def on_mount(self) -> None:
        self._tasks = []
        for widget in self.query("ListView, TaskDetailPanel"):
            widget.can_focus = False
        logger.debug("Tasks panel mounted")

    def _get_list_view(self) -> ListView:
        return self.query_one("#tasks-list", ListView)

    def _get_detail_panel(self) -> TaskDetailPanel:
        return self.query_one("#task-detail", TaskDetailPanel)

    def add_task(self, task: Task) -> None:
        """Add a task to the list."""
        entry = TaskEntry(task)
        self._tasks.insert(0, entry)
        list_view = self._get_list_view()
        list_view.insert(0, [TaskListItem(entry)])
        logger.debug("Added task %s to tasks panel", task.id[:8])

        if len(self._tasks) == 1:
            self._update_detail()

    def update_task(self, task: Task) -> None:
        """Update an existing task or add if new."""
        for i, entry in enumerate(self._tasks):
            if entry.task_id == task.id:
                self._tasks[i] = TaskEntry(task, entry.received_at)
                list_view = self._get_list_view()
                children = list(list_view.children)
                if i < len(children):
                    old_item = children[i]
                    new_item = TaskListItem(self._tasks[i])
                    old_item.remove()
                    list_view.insert(i, [new_item])

                if i == self.selected_index:
                    self._update_detail()
                logger.debug("Updated task %s", task.id[:8])
                return

        self.add_task(task)

    def _update_detail(self) -> None:
        """Update the detail panel with the currently selected task."""
        detail = self._get_detail_panel()
        if 0 <= self.selected_index < len(self._tasks):
            detail.show_task(self._tasks[self.selected_index])
        else:
            detail.show_task(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle list item selection."""
        list_view = self._get_list_view()
        if event.item and event.item in list_view.children:
            self.selected_index = list_view.children.index(event.item)
            self._update_detail()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Handle list item highlight (cursor movement)."""
        list_view = self._get_list_view()
        if event.item and event.item in list_view.children:
            self.selected_index = list_view.children.index(event.item)
            self._update_detail()

    def action_cursor_down(self) -> None:
        list_view = self._get_list_view()
        list_view.action_cursor_down()

    def action_cursor_up(self) -> None:
        list_view = self._get_list_view()
        list_view.action_cursor_up()

    def action_scroll_detail_down(self) -> None:
        """Scroll the detail panel down by half a page."""
        detail = self._get_detail_panel()
        detail.scroll_relative(y=detail.size.height // 2, animate=False)

    def action_scroll_detail_up(self) -> None:
        """Scroll the detail panel up by half a page."""
        detail = self._get_detail_panel()
        detail.scroll_relative(y=-(detail.size.height // 2), animate=False)

    def action_select_task(self) -> None:
        list_view = self._get_list_view()
        list_view.action_select_cursor()

    def select_task(self, task_id: str) -> bool:
        """Select a task by ID if it is present in the panel."""
        for index, entry in enumerate(self._tasks):
            if entry.task_id == task_id:
                self.selected_index = index
                self._get_list_view().index = index
                self._update_detail()
                return True
        return False

    def action_copy_task_id(self) -> None:
        """Copy the selected task ID to clipboard."""
        if 0 <= self.selected_index < len(self._tasks):
            task_id = self._tasks[self.selected_index].task_id
            self.app.copy_to_clipboard(task_id)
            self.notify(f"Copied task ID: {task_id[:16]}...")

    def action_copy_context_id(self) -> None:
        """Copy the selected context ID to clipboard."""
        if 0 <= self.selected_index < len(self._tasks):
            context_id = self._tasks[self.selected_index].context_id
            self.app.copy_to_clipboard(context_id)
            self.notify(f"Copied context ID: {context_id[:16]}...")

    def get_selected_task(self) -> TaskEntry | None:
        """Get the currently selected task entry."""
        if 0 <= self.selected_index < len(self._tasks):
            return self._tasks[self.selected_index]
        return None

    def clear(self) -> None:
        """Clear all tasks."""
        self._tasks = []
        list_view = self._get_list_view()
        list_view.clear()
        self._update_detail()
        logger.info("Cleared tasks panel")
