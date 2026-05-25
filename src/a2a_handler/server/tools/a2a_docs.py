"""A2A protocol documentation tools for the embedded Handler agent."""

from __future__ import annotations

import os
import re
import urllib.request
from functools import lru_cache

from google.adk.tools import FunctionTool

DEFAULT_A2A_LLMS_URL = "https://a2a-protocol.org/llms.txt"
DEFAULT_A2A_LLMS_FULL_URL = "https://a2a-protocol.org/llms-full.txt"
A2A_DOCS_FETCH_TIMEOUT_SECONDS = 10
A2A_DOCS_MAX_FETCH_CHARS = 20_000
A2A_DOCS_MAX_SEARCH_CHARS = 12_000


def _a2a_docs_url(source: str) -> str:
    """Return the configured URL for the requested A2A docs source."""
    normalized = source.strip().lower()
    if normalized in {"full", "llms-full", "llms-full.txt"}:
        return os.getenv("A2A_LLMS_FULL_URL", DEFAULT_A2A_LLMS_FULL_URL)
    return os.getenv("A2A_LLMS_URL", DEFAULT_A2A_LLMS_URL)


@lru_cache(maxsize=4)
def _fetch_a2a_docs_text(source: str) -> str:
    """Fetch and cache A2A protocol docs from the public llms text endpoints."""
    url = _a2a_docs_url(source)
    request = urllib.request.Request(url, headers={"User-Agent": "a2a-handler/agent"})
    with urllib.request.urlopen(
        request,
        timeout=A2A_DOCS_FETCH_TIMEOUT_SECONDS,
    ) as response:
        return response.read().decode("utf-8", errors="replace")


def _bounded_text(
    text: str,
    max_chars: int,
    *,
    truncated_hint: str = "Use search_a2a_protocol_docs for targeted excerpts.",
) -> str:
    """Return text truncated to a safe size for an LLM tool response."""
    safe_max_chars = max(1_000, min(max_chars, A2A_DOCS_MAX_FETCH_CHARS))
    if len(text) <= safe_max_chars:
        return text
    return text[:safe_max_chars] + f"\n\n[truncated] {truncated_hint}"


def fetch_a2a_protocol_docs(source: str = "summary", max_chars: int = 12_000) -> str:
    """Fetch A2A protocol documentation text.

    Args:
        source: Use "summary" for llms.txt or "full" for llms-full.txt.
        max_chars: Maximum characters to return. Large responses are truncated.

    Returns:
        A bounded documentation excerpt from the official A2A protocol site.
    """
    try:
        return _bounded_text(_fetch_a2a_docs_text(source), max_chars)
    except Exception as error:
        return f"Failed to fetch A2A protocol docs: {error}"


def _line_score(line: str, terms: list[str]) -> int:
    """Score a line by query term frequency."""
    lowered = line.lower()
    return sum(lowered.count(term) for term in terms)


def _query_terms(query: str) -> list[str]:
    """Return normalized query terms for lightweight lexical search."""
    return [term.lower() for term in re.findall(r"\w+", query) if len(term) > 1]


def search_a2a_protocol_docs(query: str, max_results: int = 5) -> str:
    """Search official A2A protocol documentation excerpts.

    Args:
        query: Plain-text search terms, such as "tasks vs messages".
        max_results: Maximum matching excerpts to return.

    Returns:
        Ranked, rg-style excerpts from the A2A llms-full.txt documentation.
    """
    terms = _query_terms(query)
    if not terms:
        return (
            "Provide one or more search terms, for example: tasks messages artifacts."
        )

    try:
        text = _fetch_a2a_docs_text("full")
        source = _a2a_docs_url("full")
    except Exception:
        try:
            text = _fetch_a2a_docs_text("summary")
            source = _a2a_docs_url("summary")
        except Exception as error:
            return f"Failed to search A2A protocol docs: {error}"

    lines = text.splitlines()
    scored_lines = [
        (score, index)
        for index, line in enumerate(lines)
        if (score := _line_score(line, terms)) > 0
    ]
    if not scored_lines:
        return f"No A2A protocol docs matches for: {query}"

    max_results = max(1, min(max_results, 10))
    excerpts: list[str] = [f"Source: {source}"]
    used_ranges: list[range] = []
    for _score, index in sorted(scored_lines, reverse=True):
        start = max(0, index - 2)
        end = min(len(lines), index + 3)
        current_range = range(start, end)
        if any(set(current_range).intersection(used) for used in used_ranges):
            continue
        used_ranges.append(current_range)
        excerpt_lines = []
        for line_number in current_range:
            marker = ">" if line_number == index else " "
            excerpt_lines.append(f"{marker} {line_number + 1}: {lines[line_number]}")
        excerpts.append("\n".join(excerpt_lines))
        if len(excerpts) > max_results:
            break

    return _bounded_text("\n\n".join(excerpts), A2A_DOCS_MAX_SEARCH_CHARS)


def create_a2a_docs_tools() -> list[FunctionTool]:
    """Create local function tools for A2A protocol documentation lookup."""
    return [
        FunctionTool(fetch_a2a_protocol_docs),
        FunctionTool(search_a2a_protocol_docs),
    ]
