"""Tests for CLI card commands."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from click.testing import CliRunner
from a2a.types import AgentCard, AgentSkill, AgentCapabilities

from a2a_handler.cli import cli
from a2a_handler.cli.card import card, _format_agent_card, _format_validation_result
from a2a_handler.common import Output
from a2a_handler.validation import ValidationResult, ValidationIssue, ValidationSource


@pytest.fixture
def runner():
    """Create a CLI runner."""
    return CliRunner()


def _make_agent_card() -> AgentCard:
    """Create a test agent card."""
    return AgentCard(
        name="Test Agent",
        description="A test agent",
        url="http://localhost:8000",
        version="1.0.0",
        capabilities=AgentCapabilities(),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="test_skill",
                name="Test Skill",
                description="A test skill",
                tags=["test"],
            )
        ],
    )


class TestCardGet:
    """Tests for card get command."""

    def test_card_get_success(self, runner):
        """Test successful card get command."""
        mock_card = _make_agent_card()

        with (
            patch("a2a_handler.cli.card.build_http_client") as mock_client,
            patch("a2a_handler.cli.card.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_card.return_value = mock_card
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                card, ["get", "--url", "http://localhost:8000"]
            )

            assert result.exit_code == 0
            assert "Test Agent" in result.output
            assert "test_skill" in result.output

    def test_card_get_connection_error(self, runner):
        """Test card get handles connection errors."""
        import httpx

        with (
            patch("a2a_handler.cli.card.build_http_client") as mock_client,
            patch("a2a_handler.cli.card.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_card.side_effect = httpx.ConnectError("Connection refused")
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                card, ["get", "--url", "http://localhost:8000"]
            )

            assert result.exit_code == 1

    def test_card_get_uses_bearer_flag_credentials(self, runner):
        """Test card get passes --bearer credentials to service."""
        mock_card = _make_agent_card()

        with (
            patch("a2a_handler.cli.card.build_http_client") as mock_client,
            patch("a2a_handler.cli.card.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_card.return_value = mock_card
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                card, ["get", "--url", "http://localhost:8000", "--bearer", "test-token"]
            )

            assert result.exit_code == 0
            call_kwargs = mock_service_cls.call_args
            assert call_kwargs[1]["credentials"] is not None

    def test_card_get_json_output_is_structured(self, runner):
        """Test card get emits structured payload in global json mode."""
        mock_card = _make_agent_card()

        with (
            patch("a2a_handler.cli.card.build_http_client") as mock_client,
            patch("a2a_handler.cli.card.A2AService") as mock_service_cls,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_service = AsyncMock()
            mock_service.get_card.return_value = mock_card
            mock_service_cls.return_value = mock_service

            result = runner.invoke(
                cli,
                [
                    "--output",
                    "json",
                    "card",
                    "get",
                    "--url",
                    "http://localhost:8000",
                ],
            )

            assert result.exit_code == 0
            assert '"name": "Test Agent"' in result.output

    def test_card_get_rejects_invalid_agent_url(self, runner):
        """Test card get rejects malformed URLs early."""
        result = runner.invoke(card, ["get", "--url", "not-a-url"])

        assert result.exit_code == 1
        assert "agent_url must be a valid http(s) URL" in result.output


class TestCardValidate:
    """Tests for card validate command."""

    def test_validate_valid_file(self, runner):
        """Test validating a valid card file."""
        card_data = {
            "name": "Test Agent",
            "description": "A test agent",
            "url": "http://localhost:8000",
            "version": "1.0.0",
            "capabilities": {},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [
                {
                    "id": "test",
                    "name": "Test",
                    "description": "Test skill",
                    "tags": ["test"],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(card_data, f)
            f.flush()

            result = runner.invoke(card, ["validate", "--file", f.name])

            assert result.exit_code == 0
            assert '"valid": true' in result.output

            Path(f.name).unlink()

    def test_validate_invalid_file(self, runner):
        """Test validating an invalid card file."""
        card_data = {"name": "Test Agent"}  # Missing required fields

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(card_data, f)
            f.flush()

            result = runner.invoke(card, ["validate", "--file", f.name])

            assert result.exit_code == 1
            assert '"valid": false' in result.output

            Path(f.name).unlink()

    def test_validate_nonexistent_file(self, runner):
        """Test validating a nonexistent file."""
        result = runner.invoke(
            card, ["validate", "--file", "/nonexistent/path/agent.json"]
        )

        assert result.exit_code == 1

    def test_validate_url(self, runner):
        """Test validating a card from URL."""
        mock_result = ValidationResult(
            valid=True,
            source="http://localhost:8000/.well-known/agent.json",
            source_type=ValidationSource.URL,
            agent_card=_make_agent_card(),
        )

        with (
            patch("a2a_handler.cli.card.build_http_client") as mock_client,
            patch("a2a_handler.cli.card.validate_agent_card_from_url") as mock_validate,
        ):
            mock_http = AsyncMock()
            mock_http.__aenter__.return_value = mock_http
            mock_http.__aexit__.return_value = None
            mock_client.return_value = mock_http

            mock_validate.return_value = mock_result

            result = runner.invoke(
                card, ["validate", "--url", "http://localhost:8000"]
            )

            assert result.exit_code == 0
            assert '"valid": true' in result.output

    def test_validate_rejects_invalid_url(self, runner):
        """Test validating malformed URL source fails with validation envelope."""
        result = runner.invoke(card, ["validate", "--url", "http:///"])

        assert result.exit_code == 1
        assert "agent_url must be a valid http(s) URL" in result.output


class TestFormatAgentCard:
    """Tests for _format_agent_card helper."""

    def test_format_agent_card(self):
        """Test formatting an agent card."""
        mock_card = _make_agent_card()
        output = MagicMock(spec=Output)

        _format_agent_card(mock_card, output)

        output.json.assert_called_once()
        # Verify the output payload is structured data
        call_args = output.json.call_args[0][0]
        parsed = call_args
        assert parsed["name"] == "Test Agent"

    def test_format_non_agent_card(self):
        """Test formatting when not an AgentCard type."""
        output = MagicMock(spec=Output)

        _format_agent_card({"name": "raw dict"}, output)

        output.json.assert_called_once_with({"name": "raw dict"})


class TestFormatValidationResult:
    """Tests for _format_validation_result helper."""

    def test_format_valid_result(self):
        """Test formatting a valid result."""
        mock_result = ValidationResult(
            valid=True,
            source="test.json",
            source_type=ValidationSource.FILE,
            agent_card=_make_agent_card(),
        )
        output = MagicMock(spec=Output)

        _format_validation_result(mock_result, output)

        output.json.assert_called_once()
        call_args = output.json.call_args[0][0]
        assert call_args["valid"] is True
        assert call_args["agent_name"] == "Test Agent"

    def test_format_invalid_result(self):
        """Test formatting an invalid result."""
        mock_result = ValidationResult(
            valid=False,
            source="test.json",
            source_type=ValidationSource.FILE,
            issues=[
                ValidationIssue(
                    field_name="url",
                    message="Missing required field",
                    issue_type="validation_error",
                )
            ],
        )
        output = MagicMock(spec=Output)

        _format_validation_result(mock_result, output)

        output.json.assert_called_once()
        call_args = output.json.call_args[0][0]
        assert call_args["valid"] is False
        assert len(call_args["issues"]) == 1
