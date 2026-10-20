"""Build an in-memory index of normalized function structures from local ``.py`` files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import ast

from codefence.ast_util import extract_functions_from_tree, hash_function_node
from codefence.id_normalize import normalize_function_identifiers

# Directory names skipped during repository walks (not file patterns).
DEFAULT_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".tox",
        "dist",
        "build",
    }
)


@dataclass(frozen=True)
class IndexEntry:
    file_path: Path
    qualified_name: str
    structure_hash: str
    identifier_normalized_hash: str | None = None
    id_norm_binding_map: tuple[tuple[str, str], ...] = ()
    ast_node_count: int = 0
    id_norm_unsupported_reason: str | None = None


@dataclass
class IndexBuildReport:
    entries: list[IndexEntry]
    files_indexed: int
    files_skipped: int
    read_errors: list[str]
    parse_errors: list[str]
    skipped_paths: list[Path]


def _should_skip_dir(name: str) -> bool:
    if name in DEFAULT_SKIP_DIR_NAMES:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def iter_python_files(root: Path) -> list[Path]:
    """List ``.py`` files under ``root``, skipping symlinks and ignored directories."""
    root = root.resolve()
    found: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Prune ignored directories in place so os.walk does not descend into them.
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]

        current = Path(dirpath)
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = current / filename
            if path.is_symlink():
                continue
            found.append(path)

    return sorted(found)


def index_repository(root: Path) -> IndexBuildReport:
    """Parse every indexed ``.py`` file and record function structure hashes."""
    entries: list[IndexEntry] = []
    read_errors: list[str] = []
    parse_errors: list[str] = []
    skipped_paths: list[Path] = []
    files_indexed = 0
    files_skipped = 0

    for path in iter_python_files(root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            read_errors.append(f"{path}: {exc}")
            skipped_paths.append(path)
            files_skipped += 1
            continue

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            parse_errors.append(f"{path}: syntax error at line {exc.lineno}: {exc.msg}")
            skipped_paths.append(path)
            files_skipped += 1
            continue

        functions = extract_functions_from_tree(tree)
        files_indexed += 1
        for func in functions:
            id_outcome = normalize_function_identifiers(func.node)
            entries.append(
                IndexEntry(
                    file_path=path,
                    qualified_name=func.qualified_name,
                    structure_hash=hash_function_node(func.node),
                    identifier_normalized_hash=id_outcome.structure_hash if id_outcome.ok else None,
                    id_norm_binding_map=id_outcome.original_to_normalized if id_outcome.ok else (),
                    ast_node_count=id_outcome.node_count,
                    id_norm_unsupported_reason=id_outcome.unsupported_reason,
                )
            )

    return IndexBuildReport(
        entries=entries,
        files_indexed=files_indexed,
        files_skipped=files_skipped,
        read_errors=read_errors,
        parse_errors=parse_errors,
        skipped_paths=skipped_paths,
    )


def build_hash_lookup(entries: list[IndexEntry]) -> dict[str, list[IndexEntry]]:
    lookup: dict[str, list[IndexEntry]] = {}
    for entry in entries:
        lookup.setdefault(entry.structure_hash, []).append(entry)
    return lookup


def build_identifier_normalized_lookup(
    entries: list[IndexEntry],
) -> dict[str, list[IndexEntry]]:
    lookup: dict[str, list[IndexEntry]] = {}
    for entry in entries:
        if entry.identifier_normalized_hash is None:
            continue
        lookup.setdefault(entry.identifier_normalized_hash, []).append(entry)
    return lookup
