"""Command-line interface for Milestone 1 demos."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codefence.indexer import index_repository
from codefence.matcher import match_snippet_against_repo

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

    try:
        snippet, snippet_name = _read_snippet(args)
        report = match_snippet_against_repo(root, snippet, snippet_filename=snippet_name)
    except _CliError as exc:
        print(exc.message, file=sys.stderr)
        return EXIT_ERROR
    except Exception:
        print("Unexpected scanner failure.", file=sys.stderr)
        return EXIT_ERROR

    if report.skipped_files:
        _print_skipped_files(report.skipped_files)

    if report.status == "error":
        print(report.message or "Scan could not be completed.", file=sys.stderr)
        return EXIT_ERROR

    if report.status == "no_match":
        print(report.message or "No match.")
        return EXIT_NO_MATCH

    for match in report.matches:
        print(
            f"MATCH ({match.match_type}): "
            f"{match.function_name} in {match.file_path} "
            f"(snippet function: {match.snippet_function_name})"
        )
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
    match_p.set_defaults(func=cmd_match)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
