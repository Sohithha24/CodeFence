"""AST identifier normalization for rename-tolerant structural matching (Milestone 2A)."""

from __future__ import annotations

import ast
import builtins as _builtins_module
import copy
from dataclasses import dataclass

from codefence.ast_util import strip_docstrings, structure_hash

# Provisional default; tune with labeled evaluation data (not a validated security bound).
DEFAULT_MIN_NODES = 20


def validate_min_nodes_threshold(min_nodes: int) -> None:
    """Reject invalid ``min_nodes`` values before identifier-normalized matching."""
    if min_nodes < 0:
        raise ValueError(
            f"min_nodes must be zero or positive (got {min_nodes}). "
            "Negative thresholds are not allowed."
        )

_BUILTIN_NAMES = frozenset(name for name in dir(_builtins_module) if not name.startswith("_"))


@dataclass(frozen=True)
class IdentifierNormalizeOutcome:
    """Result of normalizing one function definition."""

    ok: bool
    structure_hash: str | None
    normalized_dump: str | None
    node_count: int
    original_to_normalized: tuple[tuple[str, str], ...]
    unsupported_reason: str | None = None


def count_ast_nodes(node: ast.AST) -> int:
    """Count nodes in a tree (used after docstring stripping)."""
    return sum(1 for _ in ast.walk(node))


def _unsupported_in_function(root: ast.AST) -> str | None:
    """Return a reason if the function body uses scoping we do not normalize in 2A."""

    unsupported: list[str] = []

    class _Detector(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node is not root:
                unsupported.append("nested function definitions")
                return
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            if node is not root:
                unsupported.append("nested async function definitions")
                return
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            unsupported.append("class definitions inside functions")

        def visit_Lambda(self, node: ast.Lambda) -> None:
            unsupported.append("lambda expressions")

        def visit_ListComp(self, node: ast.ListComp) -> None:
            unsupported.append("list comprehensions")

        def visit_SetComp(self, node: ast.SetComp) -> None:
            unsupported.append("set comprehensions")

        def visit_DictComp(self, node: ast.DictComp) -> None:
            unsupported.append("dict comprehensions")

        def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
            unsupported.append("generator expressions")

    _Detector().visit(root)
    if not unsupported:
        return None
    # De-duplicate while preserving order.
    seen: set[str] = set()
    parts = []
    for item in unsupported:
        if item not in seen:
            seen.add(item)
            parts.append(item)
    return "Unsupported scoping for identifier normalization: " + "; ".join(parts) + "."


class _LocalBindingCollector(ast.NodeVisitor):
    """Collect names that are locally bound in a function (excluding ``global`` names)."""

    def __init__(self, global_names: frozenset[str]) -> None:
        self.global_names = global_names
        self.local_names: set[str] = set()

    def _bind(self, name: str) -> None:
        if name not in self.global_names:
            self.local_names.add(name)

    def visit_Global(self, node: ast.Global) -> None:
        return

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        return

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            self._bind(bound)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                continue
            bound = alias.asname or alias.name
            self._bind(bound)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self._bind(node.id)

    def visit_arg(self, node: ast.arg) -> None:
        self._bind(node.arg)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self._bind(node.name)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.target)
        self.generic_visit(node)


class _IdentifierRenamer(ast.NodeTransformer):
    """
    Rename locally bound identifiers to FUNC / VAR_n; preserve imports, globals, builtins.
    """

    def __init__(
        self,
        *,
        func_original_name: str,
        local_names: set[str],
        import_preserve: set[str],
        global_names: frozenset[str],
        nonlocal_names: frozenset[str],
    ) -> None:
        self.func_original_name = func_original_name
        self.local_names = local_names
        self.import_preserve = import_preserve
        self.global_names = global_names
        self.nonlocal_names = nonlocal_names
        self._next_var = 0
        self.original_to_normalized: dict[str, str] = {}
        self._ordered_pairs: list[tuple[str, str]] = []

    def _alloc_var(self) -> str:
        label = f"VAR_{self._next_var}"
        self._next_var += 1
        return label

    def _normalize_local(self, name: str) -> str:
        if name in self.global_names or name in self.nonlocal_names:
            return name
        if name in self.import_preserve:
            return name
        if name not in self.local_names:
            return name
        if name == self.func_original_name:
            if name not in self.original_to_normalized:
                self.original_to_normalized[name] = "FUNC"
                self._ordered_pairs.append((name, "FUNC"))
            return "FUNC"
        if name not in self.original_to_normalized:
            label = self._alloc_var()
            self.original_to_normalized[name] = label
            self._ordered_pairs.append((name, label))
        return self.original_to_normalized[name]

    def _bind_parameters(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        args = node.args
        for arg in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
            self._normalize_local(arg.arg)
            arg.arg = self.original_to_normalized.get(arg.arg, arg.arg)
        if args.vararg:
            self._normalize_local(args.vararg.arg)
            args.vararg.arg = self.original_to_normalized.get(args.vararg.arg, args.vararg.arg)
        if args.kwarg:
            self._normalize_local(args.kwarg.arg)
            args.kwarg.arg = self.original_to_normalized.get(args.kwarg.arg, args.kwarg.arg)

    def _register_func_name(self) -> None:
        if self.func_original_name not in self.original_to_normalized:
            self.original_to_normalized[self.func_original_name] = "FUNC"
            self._ordered_pairs.append((self.func_original_name, "FUNC"))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        self._register_func_name()
        self._bind_parameters(node)
        node.name = "FUNC"
        node.body = [self.visit(stmt) for stmt in node.body]
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        self._register_func_name()
        self._bind_parameters(node)
        node.name = "FUNC"
        node.body = [self.visit(stmt) for stmt in node.body]
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if isinstance(node.ctx, ast.Load):
            new_id = self._normalize_local(node.id)
            if new_id == node.id and node.id in _BUILTIN_NAMES:
                return node
            if new_id == node.id and node.id not in self.local_names:
                return node
            node.id = new_id
        elif isinstance(node.ctx, ast.Store):
            if node.id in self.global_names or node.id in self.nonlocal_names:
                return node
            if node.id in self.import_preserve:
                return node
            if node.id in self.local_names:
                node.id = self._normalize_local(node.id)
        return node

    def visit_keyword(self, node: ast.keyword) -> ast.AST:
        # Keyword argument *labels* at call sites stay unchanged; normalize values only.
        if node.value is not None:
            node.value = self.visit(node.value)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        node.value = self.visit(node.value)
        return node

    def visit_Global(self, node: ast.Global) -> ast.AST:
        return node

    def visit_Nonlocal(self, node: ast.Nonlocal) -> ast.AST:
        return node


def _collect_global_nonlocal(root: ast.AST) -> tuple[frozenset[str], frozenset[str]]:
    globals_: set[str] = set()
    nonlocals_: set[str] = set()
    for node in ast.walk(root):
        if isinstance(node, ast.Global):
            globals_.update(node.names)
        elif isinstance(node, ast.Nonlocal):
            nonlocals_.update(node.names)
    return frozenset(globals_), frozenset(nonlocals_)


def _import_preserve_names(root: ast.AST) -> set[str]:
    preserved: set[str] = set()
    for node in ast.walk(root):
        if isinstance(node, ast.Import):
            for alias in node.names:
                preserved.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                preserved.add(alias.asname or alias.name)
    return preserved


def normalize_function_identifiers(node: ast.AST) -> IdentifierNormalizeOutcome:
    """
    Produce a rename-normalized structural dump for one ``FunctionDef`` / ``AsyncFunctionDef``.

    Returns ``ok=False`` when the construct cannot be normalized reliably (nested defs, etc.).
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return IdentifierNormalizeOutcome(
            ok=False,
            structure_hash=None,
            normalized_dump=None,
            node_count=0,
            original_to_normalized=(),
            unsupported_reason="Identifier normalization applies only to function definitions.",
        )

    stripped = strip_docstrings(copy.deepcopy(node))
    node_count = count_ast_nodes(stripped)

    reason = _unsupported_in_function(stripped)
    if reason:
        return IdentifierNormalizeOutcome(
            ok=False,
            structure_hash=None,
            normalized_dump=None,
            node_count=node_count,
            original_to_normalized=(),
            unsupported_reason=reason,
        )

    global_names, nonlocal_names = _collect_global_nonlocal(stripped)
    import_preserve = _import_preserve_names(stripped)
    collector = _LocalBindingCollector(global_names)
    collector.visit(stripped)
    local_names = collector.local_names | {node.name}

    renamer = _IdentifierRenamer(
        func_original_name=node.name,
        local_names=local_names,
        import_preserve=import_preserve,
        global_names=global_names,
        nonlocal_names=nonlocal_names,
    )
    normalized_tree = renamer.visit(stripped)
    assert isinstance(normalized_tree, (ast.FunctionDef, ast.AsyncFunctionDef))
    dump = ast.dump(normalized_tree, include_attributes=False)
    digest = structure_hash(dump)

    pairs = tuple(renamer._ordered_pairs)
    return IdentifierNormalizeOutcome(
        ok=True,
        structure_hash=digest,
        normalized_dump=dump,
        node_count=node_count,
        original_to_normalized=pairs,
    )


def build_identifier_mappings(
    snippet_pairs: tuple[tuple[str, str], ...],
    protected_pairs: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """
    Map outgoing identifier names to protected names via shared normalized slots.

    Example: ``value`` → ``amount`` when both map to ``VAR_0``.
    """
    norm_to_snippet: dict[str, str] = {}
    for original, norm in snippet_pairs:
        norm_to_snippet[norm] = original

    mappings: list[tuple[str, str]] = []
    for protected_orig, norm in protected_pairs:
        snippet_orig = norm_to_snippet.get(norm)
        if snippet_orig is None:
            continue
        if snippet_orig == protected_orig:
            continue
        mappings.append((snippet_orig, protected_orig))

    # Stable order: FUNC first, then VAR order.
    def sort_key(pair: tuple[str, str]) -> tuple[int, str]:
        _, norm_side = next(
            (p for p in snippet_pairs if p[0] == pair[0]),
            (pair[0], ""),
        )
        if norm_side == "FUNC":
            return (0, pair[0])
        if norm_side.startswith("VAR_"):
            try:
                return (1, f"{int(norm_side.split('_', 1)[1]):06d}")
            except ValueError:
                pass
        return (2, pair[0])

    return tuple(sorted(mappings, key=sort_key))


def explain_identifier_match(
    *,
    protected_function: str,
    snippet_function: str,
    node_count: int,
    min_nodes: int,
    mappings: tuple[tuple[str, str], ...],
) -> str:
    parts = [
        "Identifier-normalized structure matches protected code after consistent renaming.",
        f"AST nodes (after docstring removal): {node_count}; threshold for this method: {min_nodes}.",
        f"Protected function: {protected_function}; outgoing function: {snippet_function}.",
    ]
    if mappings:
        mapping_text = ", ".join(f"{out} -> {prot}" for out, prot in mappings)
        parts.append(f"Identifier mappings: {mapping_text}.")
    parts.append("Similarity is evidence for review, not proof of ownership.")
    return " ".join(parts)
