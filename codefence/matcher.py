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
    IndexEntry,
    build_hash_lookup,
    build_identifier_normalized_lookup,
    index_repository,
)
from codefence.token_similarity import (
    DEFAULT_SHINGLE_SIZE,
    datasketch_available,
    describe_literal_evidence,
    exact_jaccard,
    fingerprint_function_tokens,
    literal_token_multiset,
    minhash_jaccard_estimate,
    passes_token_candidate_filters,
)

MatchType = Literal[
    "exact_ast",
    "identifier_normalized",
    "token_jaccard",
    "token_minhash",
]
EvidenceKind = Literal["confirmed", "review_required"]


@dataclass(frozen=True)
class MatchResult:
    file_path: Path
    function_name: str
    match_type: MatchType
    snippet_function_name: str
    evidence_kind: EvidenceKind = "confirmed"
    ast_node_count: int | None = None
    min_nodes_threshold: int | None = None
    identifier_mappings: tuple[tuple[str, str], ...] = ()
    jaccard_score: float | None = None
    minhash_jaccard_estimate: float | None = None
    review_threshold: float | None = None
    shingle_size: int | None = None
    shared_shingle_count: int | None = None
    literals_differ: bool = False
    literal_evidence_note: str | None = None
    review_reason: str | None = None
    explanation: str | None = None


@dataclass(frozen=True)
class SnippetMatchReport:
    status: Literal["match", "no_match", "error"]
    matches: tuple[MatchResult, ...]
    message: str | None = None
    skipped_files: tuple[str, ...] = ()
    identifier_norm_size_skips: tuple[str, ...] = ()
    token_review_skips: tuple[str, ...] = ()


# Experimental review threshold (characterization only; not a production gate).
DEFAULT_REVIEW_JACCARD_THRESHOLD = 0.55
DEFAULT_MIN_TOKEN_COUNT = 12
DEFAULT_MIN_SHINGLE_COUNT = 5


def validate_review_jaccard_threshold(value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ValueError(
            f"review_jaccard_threshold must be between 0.0 and 1.0 inclusive (got {value})."
        )


def validate_shingle_size(value: int) -> None:
    if value < 1:
        raise ValueError(f"shingle_size must be at least 1 (got {value}).")


def match_snippet_against_repo(
    repo_root: Path,
    snippet_source: str,
    *,
    snippet_filename: str = "<snippet>",
    min_nodes: int = DEFAULT_MIN_NODES,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
    review_jaccard_threshold: float = DEFAULT_REVIEW_JACCARD_THRESHOLD,
    min_token_count: int = DEFAULT_MIN_TOKEN_COUNT,
    min_shingle_count: int = DEFAULT_MIN_SHINGLE_COUNT,
) -> SnippetMatchReport:
    index_report = index_repository(repo_root)
    return match_snippet_against_index(
        index_report,
        snippet_source,
        snippet_filename=snippet_filename,
        min_nodes=min_nodes,
        shingle_size=shingle_size,
        review_jaccard_threshold=review_jaccard_threshold,
        min_token_count=min_token_count,
        min_shingle_count=min_shingle_count,
    )


def _collect_skipped_file_labels(index_report: IndexBuildReport) -> tuple[str, ...]:
    return tuple(str(path) for path in index_report.skipped_paths)


def _index_scan_incomplete(index_report: IndexBuildReport) -> bool:
    return bool(index_report.read_errors or index_report.parse_errors)


def _explain_token_review(
    *,
    protected_function: str,
    snippet_function: str,
    jaccard: float,
    minhash_estimate: float,
    threshold: float,
    shingle_size: int,
    shared_shingles: int,
    literal_note: str,
    review_reason: str,
) -> str:
    minhash_part = (
        f"MinHash Jaccard estimate={minhash_estimate:.4f} (supporting evidence only). "
        if datasketch_available()
        else "MinHash unavailable (install datasketch for estimates). "
    )
    return (
        "Token similarity suggests manual review; this is not confirmed proprietary leakage. "
        f"Exact Jaccard={jaccard:.4f} (authoritative for candidacy); {minhash_part}"
        f"Shared shingles={shared_shingles}; review threshold={threshold:.4f}; "
        f"shingle size={shingle_size}. {literal_note} "
        f"Reason: {review_reason} "
        f"Protected function: {protected_function}; outgoing function: {snippet_function}. "
        "Similarity is evidence for review, not proof of ownership."
    )


def _find_token_review_matches(
    *,
    snippet_source: str,
    snippet_functions: tuple,
    index_entries: list[IndexEntry],
    shingle_size: int,
    review_jaccard_threshold: float,
    min_token_count: int,
    min_shingle_count: int,
) -> tuple[tuple[MatchResult, ...], tuple[str, ...], str | None]:
    reviews: list[MatchResult] = []
    skips: list[str] = []
    token_error: str | None = None

    for func in snippet_functions:
        snippet_fp = fingerprint_function_tokens(
            snippet_source,
            func.node,
            shingle_size=shingle_size,
        )
        if not snippet_fp.ok:
            token_error = (
                snippet_fp.unsupported_reason
                or f"Token fingerprinting failed for outgoing function '{func.qualified_name}'."
            )
            continue

        if not passes_token_candidate_filters(
            token_count=len(snippet_fp.normalized_tokens),
            shingle_count=len(snippet_fp.shingles),
            min_tokens=min_token_count,
            min_shingles=min_shingle_count,
        ):
            skips.append(
                f"Token review skipped for outgoing function '{func.qualified_name}' "
                f"({len(snippet_fp.normalized_tokens)} tokens, {len(snippet_fp.shingles)} shingles; "
                f"minimums {min_token_count} tokens and {min_shingle_count} shingles)."
            )
            continue

        for entry in index_entries:
            if entry.token_unsupported_reason or not entry.token_shingles:
                continue
            if not passes_token_candidate_filters(
                token_count=entry.token_count,
                shingle_count=len(entry.token_shingles),
                min_tokens=min_token_count,
                min_shingles=min_shingle_count,
            ):
                continue

            jaccard = exact_jaccard(snippet_fp.shingles, entry.token_shingles)
            shared_shingles = len(snippet_fp.shingles & entry.token_shingles)
            minhash_est = minhash_jaccard_estimate(
                snippet_fp.minhash_hashvalues,
                entry.token_minhash_hashvalues,
            )

            if jaccard < review_jaccard_threshold:
                continue

            outgoing_literals = literal_token_multiset(snippet_fp.normalized_tokens)
            literals_differ, literal_note = describe_literal_evidence(
                entry.token_literal_multiset,
                outgoing_literals,
            )
            review_reason = (
                f"exact Jaccard {jaccard:.4f} >= review threshold {review_jaccard_threshold:.4f}"
            )
            if literals_differ:
                review_reason += "; literal tokens differ (evidence only)"

            explanation = _explain_token_review(
                protected_function=entry.qualified_name,
                snippet_function=func.qualified_name,
                jaccard=jaccard,
                minhash_estimate=minhash_est,
                threshold=review_jaccard_threshold,
                shingle_size=shingle_size,
                shared_shingles=shared_shingles,
                literal_note=literal_note,
                review_reason=review_reason,
            )

            common_fields = dict(
                file_path=entry.file_path,
                function_name=entry.qualified_name,
                snippet_function_name=func.qualified_name,
                evidence_kind="review_required",
                jaccard_score=jaccard,
                minhash_jaccard_estimate=minhash_est if datasketch_available() else None,
                review_threshold=review_jaccard_threshold,
                shingle_size=shingle_size,
                shared_shingle_count=shared_shingles,
                literals_differ=literals_differ,
                literal_evidence_note=literal_note,
                review_reason=review_reason,
                explanation=explanation,
            )

            reviews.append(MatchResult(match_type="token_jaccard", **common_fields))
            if datasketch_available():
                reviews.append(MatchResult(match_type="token_minhash", **common_fields))

    return tuple(reviews), tuple(skips), token_error


def match_snippet_against_index(
    index_report: IndexBuildReport,
    snippet_source: str,
    *,
    snippet_filename: str = "<snippet>",
    min_nodes: int = DEFAULT_MIN_NODES,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
    review_jaccard_threshold: float = DEFAULT_REVIEW_JACCARD_THRESHOLD,
    min_token_count: int = DEFAULT_MIN_TOKEN_COUNT,
    min_shingle_count: int = DEFAULT_MIN_SHINGLE_COUNT,
) -> SnippetMatchReport:
    validate_min_nodes_threshold(min_nodes)
    validate_shingle_size(shingle_size)
    validate_review_jaccard_threshold(review_jaccard_threshold)
    if min_token_count < 0 or min_shingle_count < 0:
        raise ValueError("min_token_count and min_shingle_count must be non-negative.")

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
                    evidence_kind="confirmed",
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
                    evidence_kind="confirmed",
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

    token_reviews, token_skips, token_error = _find_token_review_matches(
        snippet_source=snippet_source,
        snippet_functions=outcome.functions,
        index_entries=index_report.entries,
        shingle_size=shingle_size,
        review_jaccard_threshold=review_jaccard_threshold,
        min_token_count=min_token_count,
        min_shingle_count=min_shingle_count,
    )

    if token_reviews:
        return SnippetMatchReport(
            status="match",
            matches=token_reviews,
            skipped_files=skipped,
            identifier_norm_size_skips=tuple(size_skips),
            token_review_skips=token_skips,
        )

    if token_error:
        return SnippetMatchReport(
            status="error",
            matches=(),
            message=token_error,
            skipped_files=skipped,
            identifier_norm_size_skips=tuple(size_skips),
            token_review_skips=token_skips,
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
            token_review_skips=token_skips,
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
        token_review_skips=token_skips,
    )
