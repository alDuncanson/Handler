"""Tests for agent card building and A2A application setup."""

from unittest.mock import Mock

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from google.adk.tools.mcp_tool.mcp_toolset import StreamableHTTPConnectionParams
from starlette.applications import Starlette

from a2a_handler.server import agent as agent_module
from a2a_handler.server.tools import a2a_docs as a2a_docs_module
from a2a_handler.server.tools import source as source_module
from a2a_handler.server.agent import create_llm_agent
from a2a_handler.server.tools import (
    DEFAULT_A2A_LLMS_FULL_URL,
    DEFAULT_HANDLER_DOCS_MCP_URL,
    create_a2a_docs_tools,
    create_handler_docs_toolset,
    create_handler_source_tools,
    fetch_a2a_protocol_docs,
    search_a2a_protocol_docs,
    search_handler_source,
)
from a2a_handler.server.app import (
    create_a2a_application,
    create_runner_factory,
    generate_api_key,
)
from a2a_handler.server.card import build_agent_card
from a2a_handler import __version__


def _make_agent(name: str = "TestAgent", description: str = "Test desc") -> Mock:
    agent = Mock()
    agent.name = name
    agent.description = description
    return agent


def _make_agent_card() -> AgentCard:
    return AgentCard(
        name="Test",
        description="Test agent",
        url="http://localhost:8000/",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
        skills=[AgentSkill(id="test", name="Test", description="Test", tags=["test"])],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )


# -- build_agent_card --


def test_build_agent_card_basic() -> None:
    """Default args produce card with expected name, url, capabilities, skills, and modes."""
    agent = _make_agent()
    card = build_agent_card(agent, host="localhost", port=8000)

    assert card.name == "TestAgent"
    assert card.url == "http://localhost:8000/"
    assert card.version == __version__
    assert card.capabilities.streaming is True
    assert card.capabilities.push_notifications is True
    assert [skill.id for skill in card.skills] == [
        "handler_assistant",
        "a2a_protocol_reference",
        "handler_source_reference",
    ]
    skill_text = " ".join(
        [skill.description or "" for skill in card.skills]
        + [tag for skill in card.skills for tag in skill.tags]
    )
    assert "A2A protocol" in skill_text
    assert "source" in skill_text
    assert "streaming" in skill_text
    assert card.default_input_modes == ["text/plain"]
    assert card.default_output_modes == ["text/plain"]


def test_build_agent_card_replaces_0000_with_localhost() -> None:
    """Host 0.0.0.0 is replaced with localhost in the URL."""
    card = build_agent_card(_make_agent(), host="0.0.0.0", port=9000)

    assert "localhost" in card.url
    assert "0.0.0.0" not in card.url
    assert card.url == "http://localhost:9000/"


def test_build_agent_card_custom_host_port() -> None:
    """Custom host and port appear in the card URL."""
    card = build_agent_card(_make_agent(), host="192.168.1.10", port=5555)

    assert card.url == "http://192.168.1.10:5555/"


def test_build_agent_card_with_auth() -> None:
    """require_auth=True populates security_schemes and security."""
    card = build_agent_card(
        _make_agent(), host="localhost", port=8000, require_auth=True
    )

    assert card.security_schemes is not None
    assert "apiKey" in card.security_schemes
    assert card.security is not None
    assert card.security == [{"apiKey": []}]


def test_build_agent_card_without_auth() -> None:
    """require_auth=False leaves security_schemes and security as None."""
    card = build_agent_card(
        _make_agent(), host="localhost", port=8000, require_auth=False
    )

    assert card.security_schemes is None
    assert card.security is None


# -- generate_api_key --


def test_generate_api_key_returns_string() -> None:
    """generate_api_key returns a non-empty string."""
    key = generate_api_key()

    assert isinstance(key, str)
    assert len(key) > 0


def test_generate_api_key_is_unique() -> None:
    """Two calls to generate_api_key return different values."""
    key1 = generate_api_key()
    key2 = generate_api_key()

    assert key1 != key2


# -- create_a2a_application --


def test_create_a2a_application_returns_starlette() -> None:
    """create_a2a_application returns a Starlette instance."""
    agent = _make_agent()
    card = _make_agent_card()
    app = create_a2a_application(agent, card)

    assert isinstance(app, Starlette)


def test_create_a2a_application_with_auth_adds_middleware() -> None:
    """Providing an api_key adds middleware to the application."""
    agent = _make_agent()
    card = _make_agent_card()
    app = create_a2a_application(agent, card, api_key="test-key")

    assert len(app.middleware_stack.__class__.__mro__) > 0  # middleware is wrapped
    # More directly: the app was created with middleware list
    assert app.user_middleware


# -- create_runner_factory --


def test_create_runner_factory_returns_callable() -> None:
    """create_runner_factory returns a callable."""
    agent = _make_agent()
    factory = create_runner_factory(agent)

    assert callable(factory)


# -- embedded agent docs MCP --


def test_create_handler_docs_toolset_uses_hosted_docs_mcp(monkeypatch) -> None:
    """The embedded agent docs toolset defaults to Handler's hosted MCP endpoint."""
    monkeypatch.delenv("HANDLER_DOCS_MCP_URL", raising=False)

    toolset = create_handler_docs_toolset()

    connection_params = toolset._connection_params
    assert isinstance(connection_params, StreamableHTTPConnectionParams)
    assert connection_params.url == DEFAULT_HANDLER_DOCS_MCP_URL
    assert toolset.tool_name_prefix == "handler_docs"


def test_create_handler_docs_toolset_allows_url_override(monkeypatch) -> None:
    """The docs MCP endpoint can be overridden for local docs testing."""
    monkeypatch.setenv("HANDLER_DOCS_MCP_URL", "https://docs.example.com/mcp")

    toolset = create_handler_docs_toolset()

    connection_params = toolset._connection_params
    assert isinstance(connection_params, StreamableHTTPConnectionParams)
    assert connection_params.url == "https://docs.example.com/mcp"


def test_create_llm_agent_registers_docs_mcp_toolset(monkeypatch) -> None:
    """The embedded agent can consult Handler docs, source, and A2A docs."""
    monkeypatch.delenv("HANDLER_DOCS_MCP_ENABLED", raising=False)
    monkeypatch.delenv("A2A_DOCS_TOOLS_ENABLED", raising=False)
    monkeypatch.delenv("HANDLER_SOURCE_TOOLS_ENABLED", raising=False)
    monkeypatch.setenv("HANDLER_DOCS_MCP_URL", "https://docs.example.com/mcp")
    monkeypatch.setattr(
        agent_module,
        "create_language_model",
        lambda model=None: "test-model",
    )

    agent = create_llm_agent(model="gemma4:e2b")

    assert len(agent.tools) == 4
    assert agent.tools[0]._connection_params.url == "https://docs.example.com/mcp"
    assert agent.tools[1].name == "fetch_a2a_protocol_docs"
    assert agent.tools[2].name == "search_a2a_protocol_docs"
    assert agent.tools[3].name == "search_handler_source"
    assert "hosted documentation" in agent.instruction
    assert "A2A protocol documentation" in agent.instruction
    assert "locally installed source code" in agent.instruction
    assert "A2A protocol reference" in agent.description
    assert "local Handler source lookup" in agent.description
    assert "Format answers as concise Markdown" in agent.instruction


def test_create_llm_agent_can_disable_docs_mcp_toolset(monkeypatch) -> None:
    """Docs MCP can be disabled for fully offline embedded-agent runs."""
    monkeypatch.setenv("HANDLER_DOCS_MCP_ENABLED", "false")
    monkeypatch.setenv("A2A_DOCS_TOOLS_ENABLED", "false")
    monkeypatch.setenv("HANDLER_SOURCE_TOOLS_ENABLED", "false")
    monkeypatch.setattr(
        agent_module,
        "create_language_model",
        lambda model=None: "test-model",
    )

    agent = create_llm_agent(model="gemma4:e2b")

    assert agent.tools == []


def test_create_a2a_docs_tools_registers_fetch_and_search_tools() -> None:
    """The embedded agent exposes local tools for A2A protocol docs lookup."""
    tools = create_a2a_docs_tools()

    assert [tool.name for tool in tools] == [
        "fetch_a2a_protocol_docs",
        "search_a2a_protocol_docs",
    ]


def test_fetch_a2a_protocol_docs_uses_bounded_llms_text(monkeypatch) -> None:
    """A2A docs fetch should return bounded official llms text."""
    monkeypatch.setattr(
        a2a_docs_module,
        "_fetch_a2a_docs_text",
        lambda source: f"{source}: " + "A" * 2_000,
    )

    result = fetch_a2a_protocol_docs(source="summary", max_chars=1_200)

    assert result.startswith("summary: ")
    assert len(result) < 1_350
    assert "[truncated]" in result


def test_search_a2a_protocol_docs_returns_rg_style_excerpts(monkeypatch) -> None:
    """A2A docs search should prefer llms-full text and return focused excerpts."""
    docs = "\n".join(
        [
            "# A2A docs",
            "Messages carry user and agent content.",
            "Tasks track long-running work and produce artifacts.",
            "Artifacts contain text, data, or file parts.",
        ]
    )
    monkeypatch.setattr(a2a_docs_module, "_fetch_a2a_docs_text", lambda source: docs)

    result = search_a2a_protocol_docs("tasks artifacts", max_results=2)

    assert f"Source: {DEFAULT_A2A_LLMS_FULL_URL}" in result
    assert "> 3: Tasks track long-running work and produce artifacts." in result
    assert "Artifacts contain text" in result


def test_create_handler_source_tools_registers_source_search_tool() -> None:
    """The embedded agent exposes a local Handler source search tool."""
    tools = create_handler_source_tools()

    assert [tool.name for tool in tools] == ["search_handler_source"]


def test_search_handler_source_returns_installed_package_excerpts(monkeypatch) -> None:
    """Handler source search should read only local installed package files."""
    monkeypatch.setattr(
        source_module,
        "_iter_handler_source_files",
        lambda path_filter="": [
            (
                "server/agent.py",
                source_module._handler_source_root() / "server/agent.py",
            )
        ],
    )

    result = search_handler_source("create_llm_agent", path_filter="server")

    assert "Source: locally installed a2a_handler package" in result
    assert "File: server/agent.py" in result
    assert "create_llm_agent" in result


def test_search_handler_source_supports_no_matches(monkeypatch) -> None:
    """Handler source search should explain empty search results."""
    monkeypatch.setattr(
        source_module, "_iter_handler_source_files", lambda path_filter="": []
    )

    result = search_handler_source("definitely_missing", path_filter="tui")

    assert "No Handler source matches" in result
    assert "paths matching 'tui'" in result
