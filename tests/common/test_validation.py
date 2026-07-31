"""Tests for the agent card validation module."""

import json
import tempfile
from pathlib import Path

import httpx
import pytest
from a2a.types import AgentCard, AgentSkill
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from google.protobuf.json_format import ParseDict, ParseError

from a2a_handler.service import LEGACY_AGENT_CARD_WELL_KNOWN_PATH
from a2a_handler.validation import (
    ValidationSource,
    validate_agent_card_from_file,
    validate_agent_card_from_url,
)
from tests.factories import make_agent_card


def _minimal_valid_agent_card() -> dict:
    """Return a minimal valid agent card per the A2A v1.0 spec.

    In v1.0 the transport URL and protocol version live on each supported
    interface rather than as a top-level ``url``/``protocolVersion`` field.
    """
    return {
        "name": "Test Agent",
        "description": "A test agent",
        "supportedInterfaces": [
            {
                "url": "http://localhost:8000",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "version": "1.0.0",
        "capabilities": {},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "test_skill",
                "name": "Test Skill",
                "description": "A test skill",
                "tags": ["test"],
            }
        ],
    }


def _parse_card(data: dict) -> AgentCard:
    """Strictly validate a card dict against the v1.0 ``AgentCard`` schema."""
    return ParseDict(data, AgentCard(), ignore_unknown_fields=False)


class TestAgentCardValidation:
    """Tests for agent card validation using the A2A SDK."""

    def test_valid_minimal_card(self):
        """Test validation of a minimal valid agent card."""
        data = _minimal_valid_agent_card()
        card = _parse_card(data)

        assert card.name == "Test Agent"
        assert card.description == "A test agent"
        assert len(card.skills) == 1

    def test_unknown_top_level_field_fails_validation(self):
        """Strict v1.0 validation rejects unknown fields such as a legacy ``url``."""
        data = {"url": "http://localhost:8000"}

        with pytest.raises(ParseError):
            _parse_card(data)

    def test_skill_with_unknown_field_fails_validation(self):
        """Strict v1.0 validation rejects unknown fields nested in a skill."""
        data = _minimal_valid_agent_card()
        data["skills"] = [{"id": "test", "name": "Test", "unknownSkillField": "boom"}]

        with pytest.raises(ParseError):
            _parse_card(data)


class TestValidateAgentCardFromFile:
    """Tests for validate_agent_card_from_file function."""

    def test_valid_file(self):
        """Test validation of a valid agent card file."""
        data = _minimal_valid_agent_card()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()

            result = validate_agent_card_from_file(f.name)

            assert result.valid is True
            assert result.source_type == ValidationSource.FILE
            assert result.agent_card is not None

            Path(f.name).unlink()

    def test_nonexistent_file(self):
        """Test validation fails for nonexistent file."""
        result = validate_agent_card_from_file("/nonexistent/path/agent.json")

        assert result.valid is False
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "file_error"

    def test_invalid_json_file(self):
        """Test validation fails for invalid JSON file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            f.flush()

            result = validate_agent_card_from_file(f.name)

            assert result.valid is False
            assert len(result.issues) == 1
            assert result.issues[0].issue_type == "json_error"

            Path(f.name).unlink()

    def test_directory_path(self):
        """Test validation fails when path is a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = validate_agent_card_from_file(tmpdir)

            assert result.valid is False
            assert len(result.issues) == 1
            assert result.issues[0].issue_type == "file_error"


class TestValidationResult:
    """Tests for ValidationResult properties."""

    def test_agent_name_from_card(self):
        """Test agent_name property returns name from agent card."""
        data = _minimal_valid_agent_card()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()

            result = validate_agent_card_from_file(f.name)
            assert result.agent_name == "Test Agent"

            Path(f.name).unlink()

    def test_agent_name_from_raw_data(self):
        """Test agent_name property returns name from raw data when card is None."""
        data = {"name": "Raw Agent", "url": "invalid"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()

            result = validate_agent_card_from_file(f.name)
            assert result.valid is False
            assert result.agent_name == "Raw Agent"

            Path(f.name).unlink()

    def test_protocol_version_from_sdk(self):
        """Test protocol_version returns the SDK default version."""
        data = _minimal_valid_agent_card()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()

            result = validate_agent_card_from_file(f.name)
            assert result.protocol_version is not None
            assert len(result.protocol_version) > 0

            Path(f.name).unlink()

    def test_protocol_version_explicit(self):
        """Test protocol_version reflects an interface's explicit version.

        In v1.0 the protocol version lives on each supported interface rather
        than as a top-level card field.
        """
        data = _minimal_valid_agent_card()
        data["supportedInterfaces"][0]["protocolVersion"] = "2.0"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()

            result = validate_agent_card_from_file(f.name)
            assert result.protocol_version == "2.0"

            Path(f.name).unlink()


def _make_agent_card() -> AgentCard:
    """Create a valid AgentCard instance for testing."""
    return make_agent_card(
        name="Test Agent",
        description="A test agent",
        version="1.0.0",
        url="http://localhost:8000",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[AgentSkill(id="test", name="Test", description="Test", tags=["test"])],
    )


def _card_serving_client(
    card: dict,
    *,
    serve_paths: tuple[str, ...] = (AGENT_CARD_WELL_KNOWN_PATH,),
) -> tuple[httpx.AsyncClient, list[str]]:
    """Build a client that serves ``card`` JSON only on ``serve_paths``.

    Returns the client and a list that records every requested path, so tests
    can assert which well-known paths were tried.
    """
    requested: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if request.url.path in serve_paths:
            return httpx.Response(200, json=card)
        return httpx.Response(404, text="Not Found")

    return httpx.AsyncClient(transport=httpx.MockTransport(handle)), requested


class TestValidateAgentCardFromUrl:
    """Tests for validate_agent_card_from_url function."""

    @pytest.mark.asyncio
    async def test_validate_url_success(self):
        """Test successful validation from a URL."""
        card = _minimal_valid_agent_card()
        client, _ = _card_serving_client(card)

        async with client:
            result = await validate_agent_card_from_url("http://localhost:8000", client)

        assert result.valid is True
        assert result.source_type == ValidationSource.URL
        assert result.agent_card is not None
        assert result.agent_card.name == "Test Agent"
        assert result.source == "http://localhost:8000"

    @pytest.mark.asyncio
    async def test_validate_url_retains_served_json(self):
        """The served JSON is retained so lossy-parsed fields stay inspectable."""
        card = _minimal_valid_agent_card()
        card["protocolVersion"] = "0.3"
        client, _ = _card_serving_client(card)

        async with client:
            result = await validate_agent_card_from_url("http://localhost:8000", client)

        assert result.raw_data == card

    @pytest.mark.asyncio
    async def test_validate_url_validation_error(self):
        """Test a malformed card from a URL returns validation issues.

        A card whose structure cannot be parsed surfaces as
        ``AgentCardResolutionError`` with no status code, which maps to a
        ``validation_error`` issue. The card is served on both well-known paths
        so the legacy-path fallback also fails to parse rather than 404ing.
        """
        client, _ = _card_serving_client(
            {"name": {"not": "a string"}},
            serve_paths=(
                AGENT_CARD_WELL_KNOWN_PATH,
                LEGACY_AGENT_CARD_WELL_KNOWN_PATH,
            ),
        )

        async with client:
            result = await validate_agent_card_from_url("http://localhost:8000", client)

        assert result.valid is False
        assert result.source_type == ValidationSource.URL
        assert len(result.issues) > 0
        assert result.issues[0].issue_type == "validation_error"

    @pytest.mark.asyncio
    async def test_validate_url_http_error(self):
        """Test HTTP error from a URL returns http_error issue."""
        # Serve nothing, so both the current and legacy paths 404.
        client, _ = _card_serving_client({}, serve_paths=())

        async with client:
            result = await validate_agent_card_from_url("http://localhost:8000", client)

        assert result.valid is False
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "http_error"

    @pytest.mark.asyncio
    async def test_validate_url_connection_error(self):
        """Test connection error from a URL returns connection_error issue."""

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as client:
            result = await validate_agent_card_from_url("http://localhost:8000", client)

        assert result.valid is False
        assert len(result.issues) == 1
        assert result.issues[0].issue_type == "connection_error"

    @pytest.mark.asyncio
    async def test_validate_url_fallback_to_prev_path(self):
        """Test fallback to the previous well-known path when the current 404s."""
        card = _minimal_valid_agent_card()
        client, requested = _card_serving_client(
            card, serve_paths=(LEGACY_AGENT_CARD_WELL_KNOWN_PATH,)
        )

        async with client:
            result = await validate_agent_card_from_url("http://localhost:8000", client)

        assert result.valid is True
        assert result.agent_card is not None
        assert result.agent_card.name == "Test Agent"
        assert requested == [
            AGENT_CARD_WELL_KNOWN_PATH,
            LEGACY_AGENT_CARD_WELL_KNOWN_PATH,
        ]
