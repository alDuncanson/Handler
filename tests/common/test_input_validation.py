"""Tests for shared input validation helpers."""

import pytest

from a2a_handler.common.input_validation import (
    InputValidationError,
    parse_json_object,
    reject_unknown_keys,
    validate_agent_url,
    validate_resource_id,
    validate_webhook_url,
)


def test_validate_agent_url_accepts_http() -> None:
    assert validate_agent_url("http://localhost:8000") == "http://localhost:8000"


def test_validate_agent_url_rejects_invalid_scheme() -> None:
    with pytest.raises(InputValidationError):
        validate_agent_url("ftp://localhost")


def test_validate_resource_id_rejects_query_chars() -> None:
    with pytest.raises(InputValidationError):
        validate_resource_id("task-123?fields=id", "task_id")


def test_validate_webhook_url_rejects_non_url() -> None:
    with pytest.raises(InputValidationError):
        validate_webhook_url("not-a-url")


def test_parse_json_object_requires_object() -> None:
    with pytest.raises(InputValidationError):
        parse_json_object("[1,2,3]", "params")


def test_reject_unknown_keys() -> None:
    with pytest.raises(InputValidationError):
        reject_unknown_keys({"a": 1, "b": 2}, {"a"}, "params")
