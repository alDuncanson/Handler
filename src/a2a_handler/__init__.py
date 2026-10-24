"""Handler - A2A protocol client and TUI for agent interaction.

Provides CLI and TUI interfaces for communicating with A2A protocol agents.
"""

from importlib.metadata import version

from a2a_handler.tui import HandlerTUI, main

__version__ = version("a2a-handler")

__all__ = ["HandlerTUI", "__version__", "main"]
