"""Tests for the Output class and related utilities."""

import pytest

from a2a_handler.common.output import (
    Output,
    configure_output,
    TERMINAL_STATES,
    SUCCESS_STATES,
    ERROR_STATES,
    WARNING_STATES,
)


@pytest.fixture(autouse=True)
def reset_output_defaults() -> None:
    """Reset global output defaults to avoid cross-test leakage."""
    configure_output(output_format="text", quiet=False)


class TestStateConstants:
    """Tests for state constant sets."""

    def test_terminal_states(self):
        """Test terminal states include expected values."""
        assert "completed" in TERMINAL_STATES
        assert "failed" in TERMINAL_STATES
        assert "canceled" in TERMINAL_STATES
        assert "rejected" in TERMINAL_STATES

    def test_success_states(self):
        """Test success states."""
        assert "completed" in SUCCESS_STATES

    def test_error_states(self):
        """Test error states."""
        assert "failed" in ERROR_STATES
        assert "rejected" in ERROR_STATES

    def test_warning_states(self):
        """Test warning states."""
        assert "canceled" in WARNING_STATES


class TestOutput:
    """Tests for Output class."""

    @pytest.fixture
    def output(self):
        """Create an Output instance for testing."""
        return Output(output_format="text")

    @pytest.fixture
    def captured_output(self, output):
        """Create output capture context."""
        captured = []

        def capture_print(text):
            captured.append(text)

        output._print = capture_print
        return captured

    def test_line_basic(self, output, captured_output):
        """Test basic line output."""
        output.line("Hello, world!")
        assert captured_output == ["Hello, world!"]

    def test_field_basic(self, output, captured_output):
        """Test basic field output."""
        output.field("Name", "Value")
        assert captured_output == ["Name: Value"]

    def test_field_with_none_value(self, output, captured_output):
        """Test field with None value."""
        output.field("Name", None)
        assert captured_output == ["Name: none"]

    def test_header(self, output, captured_output):
        """Test header output."""
        output.header("Section Title")
        assert captured_output == ["\nSection Title"]

    def test_subheader(self, output, captured_output):
        """Test subheader output."""
        output.subheader("Sub Section")
        assert captured_output == ["Sub Section"]

    def test_blank(self, output, captured_output):
        """Test blank line output."""
        output.blank()
        assert captured_output == [""]

    def test_state_completed(self, output, captured_output):
        """Test state output for completed."""
        output.state("Status", "completed")
        assert captured_output == ["Status: completed"]

    def test_state_failed(self, output, captured_output):
        """Test state output for failed."""
        output.state("Status", "failed")
        assert captured_output == ["Status: failed"]

    def test_state_canceled(self, output, captured_output):
        """Test state output for canceled."""
        output.state("Status", "canceled")
        assert captured_output == ["Status: canceled"]

    def test_state_working(self, output, captured_output):
        """Test state output for working."""
        output.state("Status", "working")
        assert captured_output == ["Status: working"]

    def test_success(self, output, captured_output):
        """Test success message."""
        output.success("Operation successful!")
        assert captured_output == ["Operation successful!"]

    def test_error(self, output, captured_output):
        """Test error message."""
        output.error("Something went wrong!")
        assert captured_output == ["Something went wrong!"]

    def test_warning(self, output, captured_output):
        """Test warning message."""
        output.warning("Be careful!")
        assert captured_output == ["Be careful!"]

    def test_dim(self, output, captured_output):
        """Test dim message."""
        output.dim("Muted text")
        assert captured_output == ["Muted text"]

    def test_json(self, output, captured_output):
        """Test JSON output."""
        output.json({"key": "value"})
        assert len(captured_output) == 1
        assert '"key"' in captured_output[0]
        assert '"value"' in captured_output[0]

    def test_json_with_non_serializable(self, output, captured_output):
        """Test JSON output with non-serializable type (uses default=str)."""
        from datetime import datetime

        now = datetime.now()
        output.json({"time": now})
        assert len(captured_output) == 1

    def test_markdown(self, output, captured_output):
        """Test markdown output."""
        output.markdown("# Header\n\nParagraph text")
        assert captured_output == ["# Header\n\nParagraph text"]

    def test_list_item(self, output, captured_output):
        """Test list item output."""
        output.list_item("First item")
        assert "•" in captured_output[0]
        assert "First item" in captured_output[0]

    def test_list_item_custom_bullet(self, output, captured_output):
        """Test list item with custom bullet."""
        output.list_item("Item", bullet="→")
        assert "→" in captured_output[0]
        assert "Item" in captured_output[0]


class TestStructuredOutput:
    """Tests for json/ndjson output modes."""

    def test_json_mode_emits_structured_line(self):
        output = Output(output_format="json")
        captured: list[str] = []
        setattr(output, "_print", captured.append)

        output.line("hello")

        assert len(captured) == 1
        assert '"type": "line"' in captured[0]
        assert '"text": "hello"' in captured[0]

    def test_ndjson_mode_emits_single_line(self):
        output = Output(output_format="ndjson")
        captured: list[str] = []
        setattr(output, "_print", captured.append)

        output.error_obj(code="x", message="bad")

        assert captured == ['{"type": "error", "code": "x", "message": "bad"}']

    def test_quiet_mode_suppresses_non_errors(self):
        output = Output(output_format="text", quiet=True)
        captured: list[str] = []
        setattr(output, "_print", captured.append)

        output.line("hidden")
        output.error("visible")

        assert captured == ["visible"]
