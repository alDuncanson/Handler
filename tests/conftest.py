"""Global test fixtures."""

import pytest

from a2a_handler.common.output import configure_output


@pytest.fixture(autouse=True)
def reset_output_defaults():
    """Reset global output defaults to avoid cross-test leakage."""
    configure_output(output_format="json", quiet=False)
