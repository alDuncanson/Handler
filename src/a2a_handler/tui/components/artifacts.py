"""Artifacts panel component for viewing artifact history and details."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message as TextualMessage
from textual.reactive import reactive
from textual.widgets import Collapsible, Label, ListItem, ListView, Static

from a2a_handler.common import get_logger

if TYPE_CHECKING:
    from a2a.types import Artifact

logger = get_logger(__name__)


class ArtifactEntry:
    """Represents an artifact entry for display."""

    def __init__(
        self,
        artifact: Artifact,
        task_id: str,
        context_id: str,
        received_at: datetime | None = None,
    ) -> None:
        self.artifact = artifact
        self.task_id = task_id
        self.context_id = context_id
        self.received_at = received_at or datetime.now()

    @property
    def artifact_id(self) -> str:
        return self.artifact.artifact_id or "unnamed"

    @property
    def name(self) -> str | None:
        return self.artifact.name

    @property
    def description(self) -> str | None:
        return self.artifact.description


class ArtifactListItem(ListItem):
    """A single artifact item in the list."""

    def __init__(
        self,
        entry: ArtifactEntry,
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
        artifact_id_short = self.entry.artifact_id[:8]
        display_name = self.entry.name or artifact_id_short
        yield Label(f"{time_str}  {display_name}")


class ArtifactDetailPanel(VerticalScroll):
    """Panel showing detailed information about the selected artifact."""

    def compose(self) -> ComposeResult:
        yield Static(
            "Select an artifact to view details", id="artifact-detail-placeholder"
        )
        yield Container(id="artifact-detail-content", classes="hidden")

    def _field(
        self, label: str, value: str, value_class: str = "artifact-value"
    ) -> Horizontal:
        """Create a label-value field row."""
        return Horizontal(
            Label(f"{label}: ", classes="artifact-label"),
            Label(value, classes=value_class),
            classes="artifact-field-row",
        )

    def _section_heading(self, title: str) -> Static:
        """Create a section heading."""
        return Static(title, classes="section-heading")

    def show_artifact(self, entry: ArtifactEntry | None) -> None:
        placeholder = self.query_one("#artifact-detail-placeholder", Static)
        content = self.query_one("#artifact-detail-content", Container)

        if entry is None:
            placeholder.remove_class("hidden")
            content.add_class("hidden")
            return

        placeholder.add_class("hidden")
        content.remove_class("hidden")
        content.remove_children()

        artifact = entry.artifact

        content.mount(self._section_heading("Metadata"))
        content.mount(
            self._field("Artifact ID", entry.artifact_id),
            self._field("Task ID", entry.task_id),
            self._field("Context ID", entry.context_id),
            self._field("Received", entry.received_at.strftime("%Y-%m-%d %H:%M:%S")),
        )

        if entry.name:
            content.mount(self._field("Name", entry.name))

        if entry.description:
            content.mount(self._field("Description", entry.description))

        if artifact.parts:
            content.mount(self._section_heading("Content"))
            from a2a_handler.service import extract_text_from_message_parts

            text = extract_text_from_message_parts(artifact.parts)
            if text:
                content.mount(Static(text, classes="artifact-content"))

        content.mount(self._section_heading("Raw JSON"))
        raw_json = json.dumps(artifact.model_dump(), indent=2, default=str)
        content.mount(
            Collapsible(
                Static(raw_json),
                title="View JSON",
                collapsed=True,
            )
        )


class ArtifactsPanel(Container):
    """Panel with split view: artifact list on left, details on right."""

    BINDINGS = [
        Binding("j", "cursor_down", "↓ Select", show=True, key_display="j/↓"),
        Binding("k", "cursor_up", "↑ Select", show=True, key_display="k/↑"),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("ctrl+d", "scroll_detail_down", "½ Page ↓", show=True),
        Binding("ctrl+u", "scroll_detail_up", "½ Page ↑", show=True),
        Binding("enter", "select_artifact", "View", show=True),
        Binding("y", "copy_artifact_id", "Copy ID", show=True),
        Binding("Y", "copy_task_id", "Copy Task", show=True),
    ]

    can_focus = False

    selected_index: reactive[int] = reactive(0)
    _artifacts: list[ArtifactEntry] = []

    class ArtifactSelected(TextualMessage):
        """Posted when an artifact is selected."""

        def __init__(self, entry: ArtifactEntry) -> None:
            super().__init__()
            self.entry = entry

    def compose(self) -> ComposeResult:
        with Horizontal(id="artifacts-split"):
            yield ListView(id="artifacts-list")
            yield ArtifactDetailPanel(id="artifact-detail")

    def on_mount(self) -> None:
        self._artifacts = []
        for widget in self.query("ListView, ArtifactDetailPanel"):
            widget.can_focus = False
        logger.debug("Artifacts panel mounted")

    def _get_list_view(self) -> ListView:
        return self.query_one("#artifacts-list", ListView)

    def _get_detail_panel(self) -> ArtifactDetailPanel:
        return self.query_one("#artifact-detail", ArtifactDetailPanel)

    def add_artifact(self, artifact: Artifact, task_id: str, context_id: str) -> None:
        """Add an artifact to the list."""
        entry = ArtifactEntry(artifact, task_id, context_id)
        self._artifacts.insert(0, entry)
        list_view = self._get_list_view()
        list_view.insert(0, [ArtifactListItem(entry)])
        logger.debug("Added artifact %s to artifacts panel", entry.artifact_id[:8])

        if len(self._artifacts) == 1:
            self._update_detail()

    def update_artifact(
        self, artifact: Artifact, task_id: str, context_id: str
    ) -> None:
        """Update an existing artifact or add if new."""
        artifact_id = artifact.artifact_id or "unnamed"
        for i, entry in enumerate(self._artifacts):
            if entry.artifact_id == artifact_id and entry.task_id == task_id:
                self._artifacts[i] = ArtifactEntry(
                    artifact, task_id, context_id, entry.received_at
                )
                list_view = self._get_list_view()
                children = list(list_view.children)
                if i < len(children):
                    old_item = children[i]
                    new_item = ArtifactListItem(self._artifacts[i])
                    old_item.remove()
                    list_view.insert(i, [new_item])

                if i == self.selected_index:
                    self._update_detail()
                logger.debug("Updated artifact %s", artifact_id[:8])
                return

        self.add_artifact(artifact, task_id, context_id)

    def _update_detail(self) -> None:
        """Update the detail panel with the currently selected artifact."""
        detail = self._get_detail_panel()
        if 0 <= self.selected_index < len(self._artifacts):
            detail.show_artifact(self._artifacts[self.selected_index])
        else:
            detail.show_artifact(None)

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

    def action_select_artifact(self) -> None:
        list_view = self._get_list_view()
        list_view.action_select_cursor()

    def select_artifact(
        self, *, task_id: str | None = None, artifact_id: str | None = None
    ) -> bool:
        """Select an artifact by artifact ID and/or task ID if present."""
        for index, entry in enumerate(self._artifacts):
            artifact_matches = artifact_id is None or entry.artifact_id == artifact_id
            task_matches = task_id is None or entry.task_id == task_id
            if artifact_matches and task_matches:
                self.selected_index = index
                self._get_list_view().index = index
                self._update_detail()
                return True
        return False

    def action_copy_artifact_id(self) -> None:
        """Copy the selected artifact ID to clipboard."""
        if 0 <= self.selected_index < len(self._artifacts):
            artifact_id = self._artifacts[self.selected_index].artifact_id
            self.app.copy_to_clipboard(artifact_id)
            self.notify(f"Copied artifact ID: {artifact_id[:16]}...")

    def action_copy_task_id(self) -> None:
        """Copy the selected task ID to clipboard."""
        if 0 <= self.selected_index < len(self._artifacts):
            task_id = self._artifacts[self.selected_index].task_id
            self.app.copy_to_clipboard(task_id)
            self.notify(f"Copied task ID: {task_id[:16]}...")

    def get_selected_artifact(self) -> ArtifactEntry | None:
        """Get the currently selected artifact entry."""
        if 0 <= self.selected_index < len(self._artifacts):
            return self._artifacts[self.selected_index]
        return None

    def clear(self) -> None:
        """Clear all artifacts."""
        self._artifacts = []
        list_view = self._get_list_view()
        list_view.clear()
        self._update_detail()
        logger.info("Cleared artifacts panel")
