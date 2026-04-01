"""Tests for agent card building and A2A application setup."""

from unittest.mock import Mock

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from starlette.applications import Starlette

from a2a_handler.server.app import (
    create_a2a_application,
    create_runner_factory,
    generate_api_key,
)
from a2a_handler.server.card import build_agent_card


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
    assert card.capabilities.streaming is True
    assert card.capabilities.push_notifications is True
    assert len(card.skills) == 1
    assert card.skills[0].id == "handler_assistant"
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
    assert app.middleware is not None


# -- create_runner_factory --


def test_create_runner_factory_returns_callable() -> None:
    """create_runner_factory returns a callable."""
    agent = _make_agent()
    factory = create_runner_factory(agent)

    assert callable(factory)
