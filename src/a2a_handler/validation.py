"""Agent card validation utilities for the A2A protocol.

Validates agent cards from URLs or local files using the A2A SDK.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
from a2a.client.errors import AgentCardResolutionError
from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict, ParseError

from a2a_handler.common import get_logger
from a2a_handler.common.input_validation import InputValidationError
from a2a_handler.service import (
    UNKNOWN_PROTOCOL_VERSION,
    A2AService,
    card_protocol_version,
)

logger = get_logger(__name__)


class ValidationSource(Enum):
    """Source type for agent card validation."""

    URL = "url"
    FILE = "file"


@dataclass
class ValidationIssue:
    """Represents a single validation issue."""

    field_name: str
    message: str
    issue_type: str = "error"


@dataclass
class ValidationResult:
    """Result of validating an agent card."""

    valid: bool
    source: str
    source_type: ValidationSource
    agent_card: AgentCard | None = None
    issues: list[ValidationIssue] = field(default_factory=list)
    raw_data: dict[str, Any] | None = None

    @property
    def agent_name(self) -> str:
        """Get the agent name if available."""
        if self.agent_card:
            return self.agent_card.name
        if self.raw_data:
            return self.raw_data.get("name", "Unknown")
        return "Unknown"

    @property
    def protocol_version(self) -> str:
        """The protocol version the card advertises, or ``Unknown``.

        Delegates to the service's reading, which consults the served JSON
        for cards whose version the parsed card lost.
        """
        version = card_protocol_version(self.agent_card, self.raw_data)
        return "Unknown" if version == UNKNOWN_PROTOCOL_VERSION else version


def _caused_by_request_error(error: BaseException) -> bool:
    """Whether a network failure sits anywhere in the error's cause chain.

    The service reports the standard path's error even when the legacy
    path failed too, chaining one onto the other, so the httpx error can
    be more than one link down.
    """
    cause: BaseException | None = error
    while cause is not None:
        if isinstance(cause, httpx.RequestError):
            return True
        cause = cause.__cause__
    return False


async def validate_agent_card_from_url(
    agent_url: str,
    http_client: httpx.AsyncClient | None = None,
) -> ValidationResult:
    """Fetch and validate an agent card from a URL using the A2A SDK.

    Args:
        agent_url: The base URL of the agent
        http_client: Optional HTTP client to use

    Returns:
        ValidationResult with validation status and any issues
    """
    logger.info("Validating agent card from URL: %s", agent_url)

    should_close_client = http_client is None
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=30)

    try:
        service = A2AService(http_client, agent_url)
        agent_card = await service.get_card()
        logger.info("Agent card validation successful for %s", agent_card.name)
        return ValidationResult(
            valid=True,
            source=agent_url,
            source_type=ValidationSource.URL,
            agent_card=agent_card,
            raw_data=service.raw_card,
        )

    except InputValidationError as e:
        return ValidationResult(
            valid=False,
            source=agent_url,
            source_type=ValidationSource.URL,
            issues=[
                ValidationIssue(
                    field_name="agent_url",
                    message=e.message,
                    issue_type="validation_error",
                )
            ],
        )

    except AgentCardResolutionError as e:
        logger.warning("Agent card resolution failed: %s", e)
        status_code = getattr(e, "status_code", None)
        if status_code:
            field_name, issue_type = "http", "http_error"
        elif _caused_by_request_error(e):
            field_name, issue_type = "connection", "connection_error"
        else:
            field_name, issue_type = "agent_card", "validation_error"
        return ValidationResult(
            valid=False,
            source=agent_url,
            source_type=ValidationSource.URL,
            issues=[
                ValidationIssue(
                    field_name=field_name,
                    message=str(e),
                    issue_type=issue_type,
                )
            ],
        )

    finally:
        if should_close_client:
            await http_client.aclose()


def validate_agent_card_from_file(file_path: str | Path) -> ValidationResult:
    """Validate an agent card from a local file.

    The card is validated strictly against the A2A v1.0 ``AgentCard`` schema:
    unknown fields (including v0.3-only fields such as a top-level ``url``)
    are reported as validation errors.

    Args:
        file_path: Path to the agent card JSON file

    Returns:
        ValidationResult with validation status and any issues
    """
    path = Path(file_path)
    logger.info("Validating agent card from file: %s", path)

    if not path.exists():
        logger.error("File not found: %s", path)
        return ValidationResult(
            valid=False,
            source=str(path),
            source_type=ValidationSource.FILE,
            issues=[
                ValidationIssue(
                    field_name="file",
                    message=f"File not found: {path}",
                    issue_type="file_error",
                )
            ],
        )

    if not path.is_file():
        logger.error("Path is not a file: %s", path)
        return ValidationResult(
            valid=False,
            source=str(path),
            source_type=ValidationSource.FILE,
            issues=[
                ValidationIssue(
                    field_name="file",
                    message=f"Path is not a file: {path}",
                    issue_type="file_error",
                )
            ],
        )

    card_data: dict[str, Any] | None = None

    try:
        with open(path, encoding="utf-8") as f:
            card_data = json.load(f)

        agent_card = ParseDict(card_data, AgentCard(), ignore_unknown_fields=False)
        logger.info("Agent card validation successful for %s", agent_card.name)

        return ValidationResult(
            valid=True,
            source=str(path),
            source_type=ValidationSource.FILE,
            agent_card=agent_card,
            raw_data=card_data,
        )

    except ParseError as e:
        logger.warning("Agent card validation failed: %s", e)
        return ValidationResult(
            valid=False,
            source=str(path),
            source_type=ValidationSource.FILE,
            issues=[
                ValidationIssue(
                    field_name="agent_card",
                    message=str(e),
                    issue_type="validation_error",
                )
            ],
            raw_data=card_data,
        )

    except json.JSONDecodeError as e:
        logger.error("JSON decode error: %s", e)
        return ValidationResult(
            valid=False,
            source=str(path),
            source_type=ValidationSource.FILE,
            issues=[
                ValidationIssue(
                    field_name="json",
                    message=f"Invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}",
                    issue_type="json_error",
                )
            ],
        )

    except PermissionError:
        logger.error("Permission denied reading file: %s", path)
        return ValidationResult(
            valid=False,
            source=str(path),
            source_type=ValidationSource.FILE,
            issues=[
                ValidationIssue(
                    field_name="file",
                    message=f"Permission denied: {path}",
                    issue_type="file_error",
                )
            ],
        )

    except OSError as e:
        logger.error("Error reading file: %s", e)
        return ValidationResult(
            valid=False,
            source=str(path),
            source_type=ValidationSource.FILE,
            issues=[
                ValidationIssue(
                    field_name="file",
                    message=str(e),
                    issue_type="file_error",
                )
            ],
        )
