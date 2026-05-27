"""Global test fixtures."""

import pytest

from a2a_handler.common.output import configure_output
from a2a_handler.cli._helpers import configure_http_timeouts


@pytest.fixture(autouse=True)
def reset_output_defaults():
    """Reset global output defaults to avoid cross-test leakage."""
    configure_output(output_format="text", quiet=False)
    configure_http_timeouts()
