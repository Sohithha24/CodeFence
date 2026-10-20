"""Match an outgoing snippet against a protected function index."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from codefence.ast_util import hash_function_node, parse_source_functions
from codefence.id_normalize import (
    DEFAULT_MIN_NODES,
    build_identifier_mappings,
    explain_identifier_match,
    normalize_function_identifiers,
    validate_min_nodes_threshold,
)
from codefence.indexer import (
    IndexBuildReport,
    build_hash_lookup,
    build_identifier_normalized_lookup,
    index_repository,
)

MatchType = Literal["exact_ast", "identifier_normalized"]


@dataclass(frozen=True)
class MatchResult:
    file_path: Path
    function_name: str
    match_type: MatchType
    snippet_function_name: str
    ast_node_count: int | None = None
    min_nodes_threshold: int | None = None
    identifier_mappings: tuple[tuple[str, str], ...] = ()
    explanation: str | None = None


@dataclass(frozen=True)
class SnippetMatchReport:
    status: Literal["match", "no_match", "error"]
    matches: tuple[MatchResult, ...]
    message: str | None = None
    skipped_files: tuple[str, ...] = ()
    identifier_norm_size_skips: tuple[str, ...] = ()


def match_snippet_against_repo(
    repo_root: Path,
    snippet_source: str,
    *,
    snippet_filename: str = "<snippet>",
    min_nodes: int = DEFAULT_MIN_NODES,
) -> SnippetMatchReport:
    index_report = index_repository(repo_root)
    return match_snippet_against_index(
        index_report,
        snippet_source,
        snippet_filename=snippet_filename,
        min_nodes=min_nodes,
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
    min_nodes: int = DEFAULT_MIN_NODES,
) -> SnippetMatchReport:
    validate_min_nodes_threshold(min_nodes)
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

    exact_lookup = build_hash_lookup(index_report.entries)
    id_norm_lookup = build_identifier_normalized_lookup(index_report.entries)
    matches: list[MatchResult] = []
    size_skips: list[str] = []
    snippet_norm_blocked = False
    snippet_norm_blocked_reason: str | None = None

    for func in outcome.functions:
        digest = hash_function_node(func.node)
        for entry in exact_lookup.get(digest, ()):
            matches.append(
                MatchResult(
                    file_path=entry.file_path,
                    function_name=entry.qualified_name,
                    match_type="exact_ast",
                    snippet_function_name=func.qualified_name,
                )
            )

        id_outcome = normalize_function_identifiers(func.node)
        if not id_outcome.ok:
            snippet_norm_blocked = True
            snippet_norm_blocked_reason = id_outcome.unsupported_reason
            continue

        if id_outcome.node_count < min_nodes:
            size_skips.append(
                f"Identifier-normalized matching skipped for outgoing function "
                f"'{func.qualified_name}' ({id_outcome.node_count} AST nodes; "
                f"minimum for this method is {min_nodes}). "
                f"This is not a statement that the code is safe to share."
            )
            continue

        if id_outcome.structure_hash is None:
            continue

        for entry in id_norm_lookup.get(id_outcome.structure_hash, ()):
            if entry.ast_node_count < min_nodes:
                continue
            mappings = build_identifier_mappings(
                id_outcome.original_to_normalized,
                entry.id_norm_binding_map,
            )
            explanation = explain_identifier_match(
                protected_function=entry.qualified_name,
                snippet_function=func.qualified_name,
                node_count=id_outcome.node_count,
                min_nodes=min_nodes,
                mappings=mappings,
            )
            matches.append(
                MatchResult(
                    file_path=entry.file_path,
                    function_name=entry.qualified_name,
                    match_type="identifier_normalized",
                    snippet_function_name=func.qualified_name,
                    ast_node_count=id_outcome.node_count,
                    min_nodes_threshold=min_nodes,
                    identifier_mappings=mappings,
                    explanation=explanation,
                )
            )

    if matches:
        return SnippetMatchReport(
            status="match",
            matches=tuple(matches),
            skipped_files=skipped,
            identifier_norm_size_skips=tuple(size_skips),
        )

    if snippet_norm_blocked:
        return SnippetMatchReport(
            status="error",
            matches=(),
            message=(
                snippet_norm_blocked_reason
                or "Outgoing snippet could not be analyzed for identifier-normalized matching."
            ),
            skipped_files=skipped,
            identifier_norm_size_skips=tuple(size_skips),
        )

    if _index_scan_incomplete(index_report):
        return SnippetMatchReport(
            status="error",
            matches=(),
            message=(
                "Repository scan incomplete; one or more protected files could not be "
                "read or parsed. A no-match result is not available."
            ),
            skipped_files=skipped,
            identifier_norm_size_skips=tuple(size_skips),
        )

    return SnippetMatchReport(
        status="no_match",
        matches=(),
        message=(
            "No matching function structure found in the indexed repository. "
            "This is not a guarantee that code is safe to share."
        ),
        skipped_files=skipped,
        identifier_norm_size_skips=tuple(size_skips),
    )
