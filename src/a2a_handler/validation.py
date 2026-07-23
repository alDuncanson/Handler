"""Agent card validation utilities for the A2A protocol.

Validates agent cards from URLs or local files using the A2A SDK.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
from a2a.client import A2ACardResolver
from a2a.client.errors import AgentCardResolutionError
from a2a.types import AgentCard
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from google.protobuf.json_format import ParseDict, ParseError

from a2a_handler.common import get_logger
from a2a_handler.service import LEGACY_AGENT_CARD_WELL_KNOWN_PATH

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
        """Get the protocol version if available.

        In A2A v1.0 the protocol version lives on each supported interface
        rather than at the top level of the card. Fall back to the legacy
        top-level ``protocolVersion`` for v0.3-shaped raw data.
        """
        if self.agent_card and self.agent_card.supported_interfaces:
            versions = sorted(
                {
                    interface.protocol_version
                    for interface in self.agent_card.supported_interfaces
                    if interface.protocol_version
                }
            )
            if versions:
                return ", ".join(versions)
        if self.raw_data:
            interfaces = self.raw_data.get("supportedInterfaces") or self.raw_data.get(
                "supported_interfaces"
            )
            if isinstance(interfaces, list):
                versions = sorted(
                    {
                        interface.get("protocolVersion")
                        or interface.get("protocol_version")
                        for interface in interfaces
                        if isinstance(interface, dict)
                    }
                    - {None}
                )
                if versions:
                    return ", ".join(versions)
            return self.raw_data.get("protocolVersion", "Unknown")
        return "Unknown"


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
        resolver = A2ACardResolver(http_client, agent_url)
        try:
            agent_card = await resolver.get_agent_card()
        except (AgentCardResolutionError, httpx.HTTPStatusError):
            logger.info(
                "Agent card not found at %s, trying %s",
                AGENT_CARD_WELL_KNOWN_PATH,
                LEGACY_AGENT_CARD_WELL_KNOWN_PATH,
            )
            fallback_resolver = A2ACardResolver(
                http_client,
                agent_url,
                agent_card_path=LEGACY_AGENT_CARD_WELL_KNOWN_PATH,
            )
            agent_card = await fallback_resolver.get_agent_card()

        logger.info("Agent card validation successful for %s", agent_card.name)
        return ValidationResult(
            valid=True,
            source=agent_url,
            source_type=ValidationSource.URL,
            agent_card=agent_card,
        )

    except AgentCardResolutionError as e:
        logger.warning("Agent card resolution failed: %s", e)
        status_code = getattr(e, "status_code", None)
        issue_type = "http_error" if status_code else "validation_error"
        return ValidationResult(
            valid=False,
            source=agent_url,
            source_type=ValidationSource.URL,
            issues=[
                ValidationIssue(
                    field_name="agent_card",
                    message=str(e),
                    issue_type=issue_type,
                )
            ],
        )

    except httpx.HTTPStatusError as e:
        logger.error("HTTP error fetching agent card: %s", e)
        return ValidationResult(
            valid=False,
            source=agent_url,
            source_type=ValidationSource.URL,
            issues=[
                ValidationIssue(
                    field_name="http",
                    message=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                    issue_type="http_error",
                )
            ],
        )

    except httpx.RequestError as e:
        logger.error("Request error fetching agent card: %s", e)
        return ValidationResult(
            valid=False,
            source=agent_url,
            source_type=ValidationSource.URL,
            issues=[
                ValidationIssue(
                    field_name="connection",
                    message=str(e),
                    issue_type="connection_error",
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
