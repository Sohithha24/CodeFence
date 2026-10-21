"""Command-line interface for Milestone 1 demos."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codefence.id_normalize import DEFAULT_MIN_NODES
from codefence.indexer import index_repository
from codefence.matcher import (
    DEFAULT_MIN_SHINGLE_COUNT,
    DEFAULT_MIN_TOKEN_COUNT,
    DEFAULT_REVIEW_JACCARD_THRESHOLD,
    match_snippet_against_repo,
)
from codefence.token_similarity import DEFAULT_SHINGLE_SIZE

# ``match`` exit codes for fail-closed integrations.
EXIT_NO_MATCH = 0
EXIT_MATCH = 1
EXIT_ERROR = 2


class _CliError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _read_snippet(args: argparse.Namespace) -> tuple[str, str]:
    if args.snippet_file and args.snippet:
        raise _CliError("Use only one of --snippet or --snippet-file.")
    if args.snippet_file:
        path = Path(args.snippet_file)
        if not path.is_file():
            raise _CliError("Snippet file not found or not readable.")
        try:
            return path.read_text(encoding="utf-8"), str(path)
        except OSError:
            raise _CliError("Snippet file not found or not readable.") from None
    if args.snippet is not None:
        return args.snippet, "<snippet>"
    raise _CliError("Provide --snippet or --snippet-file.")


def _print_skipped_files(skipped: tuple[str, ...]) -> None:
    for label in skipped:
        print(f"Skipped protected file: {label}", file=sys.stderr)


def cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return EXIT_ERROR

    report = index_repository(root)
    print(f"Repository: {root}")
    print(f"Files indexed: {report.files_indexed}")
    print(f"Files skipped: {report.files_skipped}")
    print(f"Functions indexed: {len(report.entries)}")
    for err in report.read_errors:
        print(f"Read error: {err}", file=sys.stderr)
    for err in report.parse_errors:
        print(f"Parse error: {err}", file=sys.stderr)
    for entry in report.entries:
        print(f"  {entry.qualified_name}  ({entry.file_path})")
    return EXIT_NO_MATCH


def cmd_match(args: argparse.Namespace) -> int:
    root = Path(args.repo).resolve()
    if not root.is_dir():
        print("Repository path is not a directory.", file=sys.stderr)
        return EXIT_ERROR

    if args.min_nodes < 0:
        print(
            f"Invalid --min-nodes value: {args.min_nodes}. "
            "The threshold must be zero or positive.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    if args.shingle_size < 1:
        print("Invalid --shingle-size: must be at least 1.", file=sys.stderr)
        return EXIT_ERROR
    if args.review_jaccard < 0.0 or args.review_jaccard > 1.0:
        print("Invalid --review-jaccard: must be between 0.0 and 1.0.", file=sys.stderr)
        return EXIT_ERROR

    try:
        snippet, snippet_name = _read_snippet(args)
        report = match_snippet_against_repo(
            root,
            snippet,
            snippet_filename=snippet_name,
            min_nodes=args.min_nodes,
            shingle_size=args.shingle_size,
            review_jaccard_threshold=args.review_jaccard,
            min_token_count=args.min_tokens,
            min_shingle_count=args.min_shingles,
        )
    except _CliError as exc:
        print(exc.message, file=sys.stderr)
        return EXIT_ERROR
    except Exception:
        print("Unexpected scanner failure.", file=sys.stderr)
        return EXIT_ERROR

    if report.skipped_files:
        _print_skipped_files(report.skipped_files)

    for note in report.identifier_norm_size_skips:
        print(note, file=sys.stderr)
    for note in report.token_review_skips:
        print(note, file=sys.stderr)

    if report.status == "error":
        print(report.message or "Scan could not be completed.", file=sys.stderr)
        return EXIT_ERROR

    if report.status == "no_match":
        print(report.message or "No match.")
        return EXIT_NO_MATCH

    for match in report.matches:
        prefix = (
            "REVIEW_REQUIRED"
            if match.evidence_kind == "review_required"
            else "MATCH"
        )
        print(
            f"{prefix} ({match.match_type}): "
            f"{match.function_name} in {match.file_path} "
            f"(snippet function: {match.snippet_function_name})"
        )
        if match.match_type == "identifier_normalized":
            print(f"  AST nodes: {match.ast_node_count}; min threshold: {match.min_nodes_threshold}")
            if match.identifier_mappings:
                mapping_text = ", ".join(
                    f"{outgoing} -> {protected}" for outgoing, protected in match.identifier_mappings
                )
                print(f"  Identifier mappings: {mapping_text}")
        if match.match_type in ("token_jaccard", "token_minhash"):
            minhash_text = (
                f"{match.minhash_jaccard_estimate:.4f}"
                if match.minhash_jaccard_estimate is not None
                else "n/a"
            )
            print(
                f"  Exact Jaccard: {match.jaccard_score:.4f}; "
                f"MinHash estimate (supporting): {minhash_text}; "
                f"shared shingles: {match.shared_shingle_count}; "
                f"review threshold: {match.review_threshold:.4f}; "
                f"shingle size: {match.shingle_size}"
            )
            if match.literal_evidence_note:
                print(f"  Literal evidence: {match.literal_evidence_note}")
            if match.review_reason:
                print(f"  Review reason: {match.review_reason}")
        if match.explanation:
            print(f"  Explanation: {match.explanation}")
    return EXIT_MATCH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codefence",
        description="Match outgoing Python functions against an authorized local index.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    index_p = sub.add_parser("index", help="List functions indexed under a repository folder.")
    index_p.add_argument(
        "--repo",
        required=True,
        help="Path to authorized local folder of Python source.",
    )
    index_p.set_defaults(func=cmd_index)

    match_p = sub.add_parser("match", help="Check a snippet against indexed repository code.")
    match_p.add_argument("--repo", required=True, help="Path to authorized local folder.")
    match_p.add_argument("--snippet", help="Snippet text (quote for multiline shells).")
    match_p.add_argument("--snippet-file", help="Path to a file containing the snippet.")
    match_p.add_argument(
        "--min-nodes",
        type=int,
        default=DEFAULT_MIN_NODES,
        help=(
            "Minimum AST node count (after docstring removal) required for "
            "identifier_normalized matching only (default: %(default)s). "
            "Lowering this value increases false-positive risk."
        ),
    )
    match_p.add_argument(
        "--shingle-size",
        type=int,
        default=DEFAULT_SHINGLE_SIZE,
        help="Contiguous token shingle size for token similarity (default: %(default)s).",
    )
    match_p.add_argument(
        "--review-jaccard",
        type=float,
        default=DEFAULT_REVIEW_JACCARD_THRESHOLD,
        help=(
            "Experimental Jaccard threshold for REVIEW_REQUIRED token candidates "
            "(default: %(default)s; not a production block threshold)."
        ),
    )
    match_p.add_argument(
        "--min-tokens",
        type=int,
        default=DEFAULT_MIN_TOKEN_COUNT,
        help="Minimum normalized tokens required for token review candidates.",
    )
    match_p.add_argument(
        "--min-shingles",
        type=int,
        default=DEFAULT_MIN_SHINGLE_COUNT,
        help="Minimum shingles required for token review candidates.",
    )
    match_p.set_defaults(func=cmd_match)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
