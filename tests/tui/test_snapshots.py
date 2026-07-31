"""Snapshot tests for stable TUI states."""

from __future__ import annotations

import io
import re
import zlib
from datetime import datetime as real_datetime
from unittest.mock import AsyncMock, Mock

import pytest
from a2a.types import (
    AgentCard,
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)
from rich.console import Console
from textual.app import App as TextualApp
from textual.widgets import TabbedContent

from a2a_handler.auth import AuthType, create_oauth2_auth
from a2a_handler.servers import (
    ServerAuthConfig,
    ServerCatalog,
    ServerDefinition,
    ServerSource,
)
from a2a_handler.tui import HandlerTUI
from a2a_handler.tui.components import TabbedMessagesPanel
from tests.factories import make_agent_card, make_fetched_card


def _rendered_texts(widget) -> list[str]:
    return [str(child.render()) for child in widget.query("Label, Static")]


class _FakeTUILogHandler:
    def __init__(self) -> None:
        self._callback = None
        self._lines: list[str] = []

    def set_callback(self, callback) -> None:
        self._callback = callback

    def get_lines(self) -> list[str]:
        return list(self._lines)


class _FrozenDateTime:
    @classmethod
    def now(cls) -> real_datetime:
        return real_datetime(2024, 1, 2, 3, 4, 5)


def _make_server(
    *,
    name: str,
    agent_url: str,
    auth: ServerAuthConfig | None = None,
) -> ServerDefinition:
    return ServerDefinition(
        server_id=f"repository:{name}",
        source=ServerSource.REPOSITORY,
        name=name,
        agent_url=agent_url,
        auth=auth,
        origin_label="Repository",
    )


def _make_agent_card() -> AgentCard:
    return make_agent_card(
        name="Snapshot Agent",
        description="Stable preview agent",
        version="1.2.3",
        url="https://agent.example.com",
        protocol_version="0.3.0",
        streaming=True,
        push_notifications=False,
    )


def _mock_card_service(card: AgentCard) -> AsyncMock:
    """Mock an ``A2AService`` that resolves the given card."""
    document = make_fetched_card(card)
    return AsyncMock(
        get_card=AsyncMock(return_value=document.card),
        get_card_document=AsyncMock(return_value=document),
    )


def _make_task() -> Task:
    return Task(
        id="task-12345678",
        context_id="ctx-12345678",
        status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        history=[
            Message(
                message_id="msg-user-1",
                role=Role.ROLE_USER,
                parts=[Part(text="Summarize the latest handler changes.")],
                context_id="ctx-12345678",
                task_id="task-12345678",
            ),
            Message(
                message_id="msg-agent-1",
                role=Role.ROLE_AGENT,
                parts=[Part(text="Handler added stronger TUI coverage.")],
                context_id="ctx-12345678",
                task_id="task-12345678",
            ),
        ],
    )


def _make_artifact() -> Artifact:
    return Artifact(
        artifact_id="artifact-12345678",
        name="Release Notes",
        description="Rendered markdown summary",
        parts=[Part(text="Snapshot artifact content for the TUI panel.")],
    )


def _stable_export_screenshot(
    app: TextualApp,
    *,
    title: str | None = None,
    simplify: bool = False,
) -> str:
    """Export snapshots with a stable SVG id derived from normalized SVG output."""
    assert app._driver is not None
    width, height = app.size

    console = Console(
        width=width,
        height=height,
        file=io.StringIO(),
        force_terminal=True,
        color_system="truecolor",
        no_color=False,
        record=True,
        legacy_windows=False,
        safe_box=False,
    )
    screen_render = app.screen._compositor.render_update(
        full=True,
        screen_stack=app._background_screens,
        simplify=simplify,
    )
    console.print(screen_render)

    screenshot_title = title or app.title
    probe_id = "terminal-probe"
    probe_svg = console.export_svg(
        title=screenshot_title,
        unique_id=probe_id,
        clear=False,
    )
    normalized_probe_svg = probe_svg.replace(probe_id, "terminal-stable")
    normalized_probe_svg = re.sub(
        r"terminal-stable-r\d+",
        "terminal-stable-r",
        normalized_probe_svg,
    )
    normalized_probe_svg = re.sub(
        r"terminal-stable-line-\d+",
        "terminal-stable-line",
        normalized_probe_svg,
    )
    normalized_probe_svg = re.sub(
        r'clip-path="url\(#terminal-stable-line-\d+\)"',
        'clip-path="url(#terminal-stable-line)"',
        normalized_probe_svg,
    )
    unique_id = (
        f"terminal-{zlib.adler32(normalized_probe_svg.encode('utf-8', 'ignore'))}"
    )
    return console.export_svg(title=screenshot_title, unique_id=unique_id)


def _patch_snapshot_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repository_servers: tuple[ServerDefinition, ...] = (),
) -> None:
    from a2a_handler.common import logging as logging_module
    from a2a_handler.tui import app as app_module
    from a2a_handler.tui.components import artifacts as artifacts_module
    from a2a_handler.tui.components import messages as messages_module
    from a2a_handler.tui.components import tasks as tasks_module
    from a2a_handler.tui.server import tab as tab_module
    from a2a_handler.tui.server import tabs as tabs_module

    session_store = Mock()
    session_store.find.return_value = None
    session_store.list_all.return_value = []
    session_store.recent_agent_urls.return_value = []

    fake_handler = _FakeTUILogHandler()
    catalog = ServerCatalog(repository_servers=repository_servers)

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("CLICOLOR", "1")
    monkeypatch.setenv("CLICOLOR_FORCE", "1")

    monkeypatch.setattr(app_module, "get_theme", lambda: "gruvbox")
    monkeypatch.setattr(app_module, "save_theme", lambda theme: None)
    monkeypatch.setattr(
        app_module, "install_tui_log_handler", lambda level: fake_handler
    )
    monkeypatch.setattr(logging_module, "_tui_handler", None)
    monkeypatch.setattr(TextualApp, "export_screenshot", _stable_export_screenshot)

    monkeypatch.setattr(tab_module, "load_server_catalog", lambda: catalog)
    monkeypatch.setattr(tabs_module, "load_server_catalog", lambda: catalog)
    monkeypatch.setattr(tab_module, "get_session_store", lambda: session_store)

    monkeypatch.setattr(messages_module, "datetime", _FrozenDateTime)
    monkeypatch.setattr(tasks_module, "datetime", _FrozenDateTime)
    monkeypatch.setattr(artifacts_module, "datetime", _FrozenDateTime)


def test_handler_tui_disconnected_snapshot(
    snap_compare, monkeypatch: pytest.MonkeyPatch
):
    """The initial shell layout should remain visually stable."""
    _patch_snapshot_environment(monkeypatch)

    app = HandlerTUI()
    assert snap_compare(app, terminal_size=(120, 36))


def test_handler_tui_auth_tab_snapshot(snap_compare, monkeypatch: pytest.MonkeyPatch):
    """The auth tab should render populated OAuth2 fields consistently."""
    _patch_snapshot_environment(monkeypatch)

    async def run_before(pilot) -> None:
        panel = pilot.app.query_one(TabbedMessagesPanel)
        panel.set_auth_credentials(
            create_oauth2_auth(
                "https://auth.example.com/token",
                "snapshot-client",
                "snapshot-secret",
                scopes=["read", "write"],
            )
        )
        panel.query_one("#messages-tabs", TabbedContent).active = "auth-tab"
        await pilot.pause()

    app = HandlerTUI()
    assert snap_compare(app, run_before=run_before, terminal_size=(120, 36))


def test_handler_tui_connected_snapshot(snap_compare, monkeypatch: pytest.MonkeyPatch):
    """The connected live view should keep its core layout and badges."""
    repo_server = _make_server(
        name="snapshot",
        agent_url="https://agent.example.com",
        auth=ServerAuthConfig(auth_type=AuthType.BEARER, value="snapshot-token"),
    )
    _patch_snapshot_environment(monkeypatch, repository_servers=(repo_server,))

    async def run_before(pilot) -> None:
        await pilot.app.action_connect_server()
        await pilot.pause()

    with (
        pytest.MonkeyPatch.context() as local_patch,
    ):
        from a2a_handler.tui.server import tab as tab_module

        local_patch.setattr(
            tab_module,
            "build_http_client",
            lambda credentials=None: AsyncMock(),
        )
        local_patch.setattr(
            tab_module,
            "A2AService",
            lambda http_client, agent_url, credentials=None: _mock_card_service(
                _make_agent_card()
            ),
        )
        app = HandlerTUI()
        assert snap_compare(app, run_before=run_before, terminal_size=(120, 36))


@pytest.mark.asyncio
async def test_handler_tui_tasks_tab_shows_task_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tasks tab should show the selected task's key details reliably."""
    repo_server = _make_server(
        name="snapshot",
        agent_url="https://agent.example.com",
        auth=ServerAuthConfig(
            auth_type=AuthType.OAUTH2,
            token_url="https://agent.example.com/token",
            client_id_env="CLIENT_ID",
            client_secret_env="CLIENT_SECRET",
            scopes=["read", "write"],
        ),
    )
    _patch_snapshot_environment(monkeypatch, repository_servers=(repo_server,))
    monkeypatch.setenv("CLIENT_ID", "snapshot-client")
    monkeypatch.setenv("CLIENT_SECRET", "snapshot-secret")

    with (
        pytest.MonkeyPatch.context() as local_patch,
    ):
        from a2a_handler.tui.server import tab as tab_module

        local_patch.setattr(
            tab_module,
            "build_http_client",
            lambda credentials=None: AsyncMock(),
        )
        local_patch.setattr(
            tab_module,
            "A2AService",
            lambda http_client, agent_url, credentials=None: _mock_card_service(
                _make_agent_card()
            ),
        )
        app = HandlerTUI()

        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.app.action_connect_server()
            await pilot.pause()

            panel = pilot.app.query_one(TabbedMessagesPanel)
            panel.set_auth_credentials(
                create_oauth2_auth(
                    "https://agent.example.com/token",
                    "snapshot-client",
                    "snapshot-secret",
                    scopes=["read", "write"],
                )
            )
            panel.add_task(_make_task())
            tabs = panel.query_one("#messages-tabs", TabbedContent)
            tabs.active = "tasks-tab"
            await pilot.pause()

            detail_texts = _rendered_texts(panel.query_one("#task-detail"))
            assert tabs.active == "tasks-tab"
            assert any("task-123" in text for text in detail_texts)
            assert any("ctx-123" in text for text in detail_texts)
            assert any(
                "Handler added stronger TUI coverage." in text for text in detail_texts
            )


@pytest.mark.asyncio
async def test_handler_tui_artifacts_tab_shows_artifact_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The artifacts tab should show the selected artifact's visible details."""
    repo_server = _make_server(
        name="snapshot",
        agent_url="https://agent.example.com",
    )
    _patch_snapshot_environment(monkeypatch, repository_servers=(repo_server,))

    with (
        pytest.MonkeyPatch.context() as local_patch,
    ):
        from a2a_handler.tui.server import tab as tab_module

        local_patch.setattr(
            tab_module,
            "build_http_client",
            lambda credentials=None: AsyncMock(),
        )
        local_patch.setattr(
            tab_module,
            "A2AService",
            lambda http_client, agent_url, credentials=None: _mock_card_service(
                _make_agent_card()
            ),
        )
        app = HandlerTUI()

        async with app.run_test() as pilot:
            await pilot.app.action_connect_server()
            await pilot.pause()

            panel = pilot.app.query_one(TabbedMessagesPanel)
            panel.add_artifact(_make_artifact(), "task-12345678", "ctx-12345678")
            panel.query_one("#messages-tabs", TabbedContent).active = "artifacts-tab"
            await pilot.pause()

            detail_texts = _rendered_texts(panel.query_one("#artifact-detail"))
            assert any("Release Notes" in text for text in detail_texts)
            assert any(
                "Snapshot artifact content for the TUI panel." in text
                for text in detail_texts
            )
