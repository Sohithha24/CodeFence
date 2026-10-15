"""Match an outgoing snippet against a protected function index."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codefence.ast_util import hash_function_node, parse_source_functions
from codefence.indexer import IndexBuildReport, build_hash_lookup, index_repository

MatchType = Literal["exact_ast"]


@dataclass(frozen=True)
class MatchResult:
    file_path: Path
    function_name: str
    match_type: MatchType
    snippet_function_name: str


@dataclass(frozen=True)
class SnippetMatchReport:
    status: Literal["match", "no_match", "error"]
    matches: tuple[MatchResult, ...]
    message: str | None = None
    skipped_files: tuple[str, ...] = ()


def match_snippet_against_repo(
    repo_root: Path,
    snippet_source: str,
    *,
    snippet_filename: str = "<snippet>",
) -> SnippetMatchReport:
    index_report = index_repository(repo_root)
    return match_snippet_against_index(
        index_report,
        snippet_source,
        snippet_filename=snippet_filename,
    )


def _collect_skipped_file_labels(index_report: IndexBuildReport) -> tuple[str, ...]:
    return tuple(str(path) for path in index_report.skipped_paths)


def _index_scan_incomplete(index_report: IndexBuildReport) -> bool:
    return bool(index_report.read_errors or index_report.parse_errors)


def match_snippet_against_index(
    index_report: IndexBuildReport,
    snippet_source: str,
    *,
    snippet_filename: str = "<snippet>",
) -> SnippetMatchReport:
    skipped = _collect_skipped_file_labels(index_report)

    outcome = parse_source_functions(snippet_source, filename=snippet_filename)
    if outcome.kind != "ok":
        return SnippetMatchReport(
            status="error",
            matches=(),
            message=outcome.message,
            skipped_files=skipped,
        )

    if not index_report.entries:
        if _index_scan_incomplete(index_report):
            message = (
                "Repository scan incomplete; one or more protected files could not be "
                "read or parsed. A no-match result is not available."
            )
        else:
            message = (
                "No protected functions are available for comparison in the indexed "
                "repository. A no-match result is not available."
            )
        return SnippetMatchReport(
            status="error",
            matches=(),
            message=message,
            skipped_files=skipped,
        )

    lookup = build_hash_lookup(index_report.entries)
    matches: list[MatchResult] = []

    for func in outcome.functions:
        digest = hash_function_node(func.node)
        for entry in lookup.get(digest, ()):
            matches.append(
                MatchResult(
                    file_path=entry.file_path,
                    function_name=entry.qualified_name,
                    match_type="exact_ast",
                    snippet_function_name=func.qualified_name,
                )
            )

    if matches:
        return SnippetMatchReport(status="match", matches=tuple(matches), skipped_files=skipped)

    if _index_scan_incomplete(index_report):
        return SnippetMatchReport(
            status="error",
            matches=(),
            message=(
                "Repository scan incomplete; one or more protected files could not be "
                "read or parsed. A no-match result is not available."
            ),
            skipped_files=skipped,
        )

    return SnippetMatchReport(
        status="no_match",
        matches=(),
        message=(
            "No matching function structure found in the indexed repository. "
            "This is not a guarantee that code is safe to share."
        ),
    )
