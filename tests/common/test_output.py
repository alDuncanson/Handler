"""Tests for the Output class and related utilities."""

import json

from a2a_handler.common.output import Output


class TestOutput:
    """Tests for Output class."""

    def test_json(self, capsys):
        """Test JSON output."""
        output = Output()
        output.json({"key": "value"})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == {"key": "value"}

    def test_json_with_non_serializable(self, capsys):
        """Test JSON output with non-serializable type (uses default=str)."""
        from datetime import datetime

        output = Output()
        now = datetime.now()
        output.json({"time": now})
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "time" in data

    def test_error(self, capsys):
        """Test error output."""
        output = Output()
        output.error(code="test_error", message="Something went wrong")
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["type"] == "error"
        assert data["code"] == "test_error"
        assert data["message"] == "Something went wrong"

    def test_error_with_details(self, capsys):
        """Test error output with details and suggestion."""
        output = Output()
        output.error(
            code="test_error",
            message="Something went wrong",
            details={"url": "http://localhost"},
            suggestion="Try again",
        )
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["details"] == {"url": "http://localhost"}
        assert data["suggestion"] == "Try again"

    def test_quiet_mode_suppresses_json(self, capsys):
        """Test quiet mode suppresses json output."""
        output = Output(quiet=True)
        output.json({"key": "value"})
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_quiet_mode_does_not_suppress_errors(self, capsys):
        """Test quiet mode does not suppress error output."""
        output = Output(quiet=True)
        output.error(code="x", message="bad")
        captured = capsys.readouterr()
        assert captured.err != ""


class TestNdjsonOutput:
    """Tests for NDJSON output mode."""

    def test_json_emits_compact(self, capsys):
        """json() in ndjson mode emits compact single-line JSON."""
        output = Output(output_format="ndjson")
        output.json({"name": "test"})
        captured = capsys.readouterr()
        assert captured.out.strip() == '{"name": "test"}'

    def test_error_emits_compact(self, capsys):
        """error() in ndjson mode emits compact single-line JSON."""
        output = Output(output_format="ndjson")
        output.error(code="x", message="bad")
        captured = capsys.readouterr()
        assert (
            captured.err.strip() == '{"type": "error", "code": "x", "message": "bad"}'
        )
