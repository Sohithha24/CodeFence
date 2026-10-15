"""Parse Python source and normalize function ASTs for exact structural matching."""

from __future__ import annotations

import ast
import copy
import hashlib
import textwrap
from dataclasses import dataclass
from typing import Iterable, Iterator, Literal

ParseOutcomeKind = Literal[
    "ok",
    "syntax_error",
    "no_functions",
    "unsupported_partial",
    "unsupported_scope",
]


@dataclass(frozen=True)
class ParsedFunction:
    """One function extracted from source, with a stable qualified name."""

    qualified_name: str
    node: ast.AST  # ast.FunctionDef or ast.AsyncFunctionDef


@dataclass(frozen=True)
class ParseOutcome:
    kind: ParseOutcomeKind
    functions: tuple[ParsedFunction, ...]
    message: str | None = None


def _is_docstring_statement(statement: ast.AST) -> bool:
    """True for the first-statement docstring pattern (``Expr`` with string constant)."""
    if not isinstance(statement, ast.Expr):
        return False
    value = statement.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return True
    return False


def _body_without_leading_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if body and _is_docstring_statement(body[0]):
        return body[1:]
    return body


class _DocstringStripper(ast.NodeTransformer):
    """
    Remove docstrings from functions, async functions, and classes in a subtree.

    Ordinary string expressions (e.g. ``x = "hello"``) are not removed.
    """

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node = self.generic_visit(node)
        node.body = _body_without_leading_docstring(node.body)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node = self.generic_visit(node)
        node.body = _body_without_leading_docstring(node.body)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node = self.generic_visit(node)
        node.body = _body_without_leading_docstring(node.body)
        return node


def strip_docstrings(node: ast.AST) -> ast.AST:
    """Return a copy of ``node`` with docstrings stripped from defs/classes in its subtree."""
    copied = copy.deepcopy(node)
    return _DocstringStripper().visit(copied)


def normalize_function_node(node: ast.AST) -> str:
    """
    Structural AST text; ignores formatting, comments, and docstrings.

    Identifier names stay as-is (rename-tolerant matching is a later milestone).
    """
    stripped = strip_docstrings(node)
    return ast.dump(stripped, include_attributes=False)


def structure_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_function_node(node: ast.AST) -> str:
    return structure_hash(normalize_function_node(node))


class _FunctionCollector(ast.NodeVisitor):
    """Walk a module tree and collect every function with a qualified name."""

    def __init__(self) -> None:
        self._name_stack: list[str] = []
        self.functions: list[ParsedFunction] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._name_stack.append(node.name)
        self.generic_visit(node)
        self._name_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._register(node)
        self._name_stack.append(node.name)
        self.generic_visit(node)
        self._name_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._register(node)
        self._name_stack.append(node.name)
        self.generic_visit(node)
        self._name_stack.pop()

    def _register(self, node: ast.AST) -> None:
        name = getattr(node, "name", "?")
        if self._name_stack:
            qualified = ".".join(self._name_stack + [name])
        else:
            qualified = name
        self.functions.append(ParsedFunction(qualified_name=qualified, node=node))


def extract_functions_from_tree(tree: ast.AST) -> list[ParsedFunction]:
    collector = _FunctionCollector()
    collector.visit(tree)
    return collector.functions


def parse_source_functions(source: str, *, filename: str = "<snippet>") -> ParseOutcome:
    """
    Parse source and return all function definitions found in the tree.

    Methods are named ``ClassName.method_name``. Nested functions use dotted
    paths such as ``outer.inner``.
    """
    stripped = source.strip()
    if not stripped:
        return ParseOutcome(
            kind="no_functions",
            functions=(),
            message="Empty input: provide a Python function snippet or file.",
        )

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        if _parses_as_wrapped_body(source):
            return ParseOutcome(
                kind="unsupported_partial",
                functions=(),
                message=(
                    "Unsupported partial snippet: input looks like a function body without "
                    "a complete ``def ...`` header. Provide the full function definition."
                ),
            )
        return ParseOutcome(
            kind="syntax_error",
            functions=(),
            message=f"Syntax error at line {exc.lineno}, column {exc.offset}: {exc.msg}",
        )

    functions = extract_functions_from_tree(tree)
    if (
        functions
        and isinstance(tree, ast.Module)
        and _module_has_out_of_scope_statements(tree)
    ):
        return ParseOutcome(
            kind="unsupported_scope",
            functions=tuple(functions),
            message=(
                "One or more parts of the snippet are outside supported function-only scope. "
                "The submission cannot be treated as a clean no-match result."
            ),
        )

    if functions:
        return ParseOutcome(kind="ok", functions=tuple(functions))

    if _parses_as_wrapped_body(source):
        return ParseOutcome(
            kind="unsupported_partial",
            functions=(),
            message=(
                "Unsupported partial snippet: input looks like a function body without "
                "a complete ``def ...`` header. Provide the full function definition."
            ),
        )

    return ParseOutcome(
        kind="no_functions",
        functions=(),
        message=(
            "No complete function definition found. "
            "Paste or provide a full ``def ...`` (or ``async def ...``) block."
        ),
    )


def _module_has_out_of_scope_statements(module: ast.Module) -> bool:
    """Top-level content other than defs/classes (and an optional module docstring)."""
    for index, statement in enumerate(module.body):
        if index == 0 and _is_docstring_statement(statement):
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        return True
    return False


def _parses_as_wrapped_body(source: str) -> bool:
    """True when source is valid indented body lines but not a standalone module function."""
    wrapped = "def __codefence_wrap__():\n" + textwrap.indent(source, "    ")
    try:
        tree = ast.parse(wrapped)
    except SyntaxError:
        return False
    funcs = extract_functions_from_tree(tree)
    return len(funcs) >= 1


def iter_function_nodes(functions: Iterable[ParsedFunction]) -> Iterator[ast.AST]:
    for item in functions:
        yield item.node
