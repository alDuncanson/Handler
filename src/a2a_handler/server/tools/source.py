"""Local Handler source lookup tool for the embedded Handler agent."""

from __future__ import annotations

from pathlib import Path

from google.adk.tools import FunctionTool

from a2a_handler.server.tools.a2a_docs import _bounded_text, _line_score, _query_terms

HANDLER_SOURCE_MAX_FILE_BYTES = 200_000
HANDLER_SOURCE_MAX_SEARCH_CHARS = 12_000
HANDLER_SOURCE_EXTENSIONS = frozenset({".py", ".tcss"})


def _handler_source_root() -> Path:
    """Return the installed Handler package source root."""
    return Path(__file__).resolve().parents[2]


def _iter_handler_source_files(path_filter: str = ""):
    """Yield searchable Handler source files from the installed package."""
    root = _handler_source_root()
    normalized_filter = path_filter.strip().lower()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix not in HANDLER_SOURCE_EXTENSIONS:
            continue
        if path.stat().st_size > HANDLER_SOURCE_MAX_FILE_BYTES:
            continue
        relative_path = path.relative_to(root).as_posix()
        if normalized_filter and normalized_filter not in relative_path.lower():
            continue
        yield relative_path, path


def search_handler_source(
    query: str,
    path_filter: str = "",
    max_results: int = 8,
) -> str:
    """Search the locally installed Handler package source.

    Args:
        query: Plain-text search terms, such as "loading indicator".
        path_filter: Optional substring to restrict relative source paths.
        max_results: Maximum matching excerpts to return.

    Returns:
        Ranked, rg-style excerpts from the installed `a2a_handler` package.
    """
    terms = _query_terms(query)
    if not terms:
        return "Provide one or more source search terms, for example: agent card."

    matches: list[tuple[int, str, int, list[str]]] = []
    try:
        source_files = list(_iter_handler_source_files(path_filter))
    except Exception as error:
        return f"Failed to search Handler source: {error}"

    for relative_path, path in source_files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines):
            score = _line_score(line, terms)
            if score <= 0:
                continue
            start = max(0, index - 2)
            end = min(len(lines), index + 3)
            excerpt_lines = []
            for line_number in range(start, end):
                marker = ">" if line_number == index else " "
                excerpt_lines.append(
                    f"{marker} {line_number + 1}: {lines[line_number]}"
                )
            matches.append((score, relative_path, index, excerpt_lines))

    if not matches:
        suffix = f" in paths matching '{path_filter}'" if path_filter else ""
        return f"No Handler source matches for: {query}{suffix}"

    max_results = max(1, min(max_results, 20))
    output = ["Source: locally installed a2a_handler package"]
    seen_locations: set[tuple[str, int]] = set()
    for _score, relative_path, index, excerpt_lines in sorted(matches, reverse=True):
        location = (relative_path, index)
        if location in seen_locations:
            continue
        seen_locations.add(location)
        output.append(f"File: {relative_path}\n" + "\n".join(excerpt_lines))
        if len(output) > max_results:
            break

    return _bounded_text(
        "\n\n".join(output),
        HANDLER_SOURCE_MAX_SEARCH_CHARS,
        truncated_hint="Narrow the query or use path_filter for targeted source excerpts.",
    )


def create_handler_source_tools() -> list[FunctionTool]:
    """Create local function tools for Handler source lookup."""
    return [FunctionTool(search_handler_source)]
