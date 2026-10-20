"""Milestone 2A: identifier-normalized AST matching and false-positive controls."""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from codefence.ast_util import parse_source_functions
from codefence.cli import EXIT_ERROR, EXIT_MATCH, EXIT_NO_MATCH
from codefence.id_normalize import (
    DEFAULT_MIN_NODES,
    build_identifier_mappings,
    normalize_function_identifiers,
)
from codefence.indexer import index_repository
from codefence.matcher import match_snippet_against_index, match_snippet_against_repo

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_REPO = ROOT / "examples" / "synthetic_repo"

CALCULATE_RISK = textwrap.dedent(
    """
    def calculate_risk(amount, probability):
        score = amount * probability
        return score
    """
).strip()

ESTIMATE_LOSS = textwrap.dedent(
    """
    def estimate_loss(value, chance):
        result = value * chance
        return result
    """
).strip()

RENAMED_CLAMP = textwrap.dedent(
    """
    def bound(x, lo, hi):
        if x < lo:
            return lo
        if x > hi:
            return hi
        return x
    """
).strip()


def _write_repo(*files: tuple[str, str]) -> Path:
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    for name, source in files:
        (root / name).write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return root


def _func_node(source: str) -> ast.AST:
    outcome = parse_source_functions(source)
    assert outcome.kind == "ok" and outcome.functions
    return outcome.functions[0].node


class TestIdentifierNormalizationCore(unittest.TestCase):
    def test_identical_functions_share_normalized_hash(self) -> None:
        a = normalize_function_identifiers(_func_node(CALCULATE_RISK))
        b = normalize_function_identifiers(_func_node(CALCULATE_RISK))
        self.assertTrue(a.ok and b.ok)
        self.assertEqual(a.structure_hash, b.structure_hash)

    def test_renamed_function_name_parameters_and_locals(self) -> None:
        a = normalize_function_identifiers(_func_node(CALCULATE_RISK))
        b = normalize_function_identifiers(_func_node(ESTIMATE_LOSS))
        self.assertTrue(a.ok and b.ok)
        self.assertEqual(a.structure_hash, b.structure_hash)
        mappings = build_identifier_mappings(b.original_to_normalized, a.original_to_normalized)
        self.assertIn(("estimate_loss", "calculate_risk"), mappings)
        self.assertIn(("value", "amount"), mappings)
        self.assertIn(("chance", "probability"), mappings)
        self.assertIn(("result", "score"), mappings)

    def test_different_executable_logic_differs(self) -> None:
        other = "def f(a, b):\n    return a - b\n"
        a = normalize_function_identifiers(_func_node(CALCULATE_RISK))
        b = normalize_function_identifiers(_func_node(other))
        self.assertNotEqual(a.structure_hash, b.structure_hash)

    def test_different_literal_values_differs(self) -> None:
        with_lit = "def f(x):\n    return x + 1\n"
        other_lit = "def f(x):\n    return x + 2\n"
        a = normalize_function_identifiers(_func_node(with_lit))
        b = normalize_function_identifiers(_func_node(other_lit))
        self.assertNotEqual(a.structure_hash, b.structure_hash)

    def test_builtins_unchanged(self) -> None:
        src = "def f(items):\n    return len(items)\n"
        out = normalize_function_identifiers(_func_node(src))
        self.assertTrue(out.ok)
        self.assertIn("len", out.normalized_dump or "")

    def test_imported_symbols_unchanged(self) -> None:
        src = textwrap.dedent(
            """
            def f(x):
                import math
                return math.sqrt(x)
            """
        ).strip()
        out = normalize_function_identifiers(_func_node(src))
        self.assertTrue(out.ok)
        self.assertIn("math", out.normalized_dump or "")

    def test_attribute_names_unchanged(self) -> None:
        src = textwrap.dedent(
            """
            def f(customer):
                return customer.balance
            """
        ).strip()
        out = normalize_function_identifiers(_func_node(src))
        self.assertTrue(out.ok)
        self.assertIn("balance", out.normalized_dump or "")

    def test_keyword_argument_labels_unchanged(self) -> None:
        src = textwrap.dedent(
            """
            def f(value):
                return pow(base=value, exp=2)
            """
        ).strip()
        out = normalize_function_identifiers(_func_node(src))
        self.assertTrue(out.ok)
        dump = out.normalized_dump or ""
        self.assertIn("base", dump)
        self.assertIn("exp", dump)

    def test_below_min_nodes_count(self) -> None:
        out = normalize_function_identifiers(_func_node(CALCULATE_RISK))
        self.assertTrue(out.ok)
        self.assertLess(out.node_count, DEFAULT_MIN_NODES)

    def test_at_or_above_min_nodes_count(self) -> None:
        out = normalize_function_identifiers(_func_node(RENAMED_CLAMP))
        self.assertTrue(out.ok)
        self.assertGreaterEqual(out.node_count, DEFAULT_MIN_NODES)

    def test_unsupported_nested_function(self) -> None:
        src = textwrap.dedent(
            """
            def outer(x):
                def inner(y):
                    return y
                return inner(x)
            """
        ).strip()
        out = normalize_function_identifiers(_func_node(src))
        self.assertFalse(out.ok)
        self.assertIn("nested", (out.unsupported_reason or "").lower())

    def test_implicit_global_read_not_renamed(self) -> None:
        src = textwrap.dedent(
            """
            def read_global():
                return shared_counter
            """
        ).strip()
        out = normalize_function_identifiers(_func_node(src))
        self.assertTrue(out.ok)
        self.assertIn("shared_counter", out.normalized_dump or "")

    def test_explicit_global_declaration_preserves_name(self) -> None:
        src = textwrap.dedent(
            """
            def touch_global():
                global shared_counter
                return shared_counter
            """
        ).strip()
        out = normalize_function_identifiers(_func_node(src))
        self.assertTrue(out.ok)
        dump = out.normalized_dump or ""
        self.assertIn("shared_counter", dump)
        self.assertNotIn("VAR_", dump)

    def test_shadowed_builtin_treated_as_local_binding(self) -> None:
        src = textwrap.dedent(
            """
            def shadow_len():
                len = 3
                return len + 1
            """
        ).strip()
        out = normalize_function_identifiers(_func_node(src))
        self.assertTrue(out.ok)
        dump = out.normalized_dump or ""
        self.assertNotIn("id='len'", dump)
        self.assertIn("VAR_", dump)


class TestMatcherIntegration(unittest.TestCase):
    def test_renamed_clamp_detected_in_synthetic_repo(self) -> None:
        report = match_snippet_against_repo(SYNTHETIC_REPO, RENAMED_CLAMP)
        self.assertEqual(report.status, "match")
        id_matches = [m for m in report.matches if m.match_type == "identifier_normalized"]
        self.assertTrue(id_matches)
        self.assertEqual(id_matches[0].function_name, "clamp")
        expected_mappings = {
            ("bound", "clamp"),
            ("x", "value"),
            ("lo", "low"),
            ("hi", "high"),
        }
        self.assertEqual(set(id_matches[0].identifier_mappings), expected_mappings)

    def test_multi_function_snippet_errors_when_id_norm_unreliable(self) -> None:
        """One unsupported function forces ERROR if nothing else matches (fail-closed)."""
        snippet = textwrap.dedent(
            """
            def add(a, b):
                return a + b

            def outer(x):
                def inner(y):
                    return y
                return inner(x)
            """
        ).strip()
        report = match_snippet_against_repo(SYNTHETIC_REPO, snippet)
        self.assertEqual(report.status, "error")
        self.assertIn("unsupported", (report.message or "").lower())

    def test_negative_min_nodes_rejected_by_matcher_api(self) -> None:
        with self.assertRaises(ValueError):
            match_snippet_against_repo(SYNTHETIC_REPO, RENAMED_CLAMP, min_nodes=-1)

    def test_unrelated_function_rejected(self) -> None:
        report = match_snippet_against_repo(
            SYNTHETIC_REPO,
            "def add(a, b):\n    return a + b\n",
        )
        self.assertEqual(report.status, "no_match")

    def test_below_threshold_no_identifier_match(self) -> None:
        repo = _write_repo(("risk.py", CALCULATE_RISK))
        index = index_repository(repo)
        report = match_snippet_against_index(index, ESTIMATE_LOSS, min_nodes=DEFAULT_MIN_NODES)
        self.assertEqual(report.status, "no_match")
        self.assertTrue(report.identifier_norm_size_skips)

    def test_exact_ast_still_matches_small_functions(self) -> None:
        repo = _write_repo(("risk.py", CALCULATE_RISK))
        report = match_snippet_against_repo(repo, CALCULATE_RISK, min_nodes=DEFAULT_MIN_NODES)
        self.assertEqual(report.status, "match")
        self.assertTrue(any(m.match_type == "exact_ast" for m in report.matches))

    def test_multiple_protected_matches_returned(self) -> None:
        repo = _write_repo(
            ("a.py", CALCULATE_RISK),
            ("b.py", CALCULATE_RISK.replace("calculate_risk", "risk_calc")),
        )
        report = match_snippet_against_repo(repo, ESTIMATE_LOSS, min_nodes=5)
        self.assertEqual(report.status, "match")
        id_matches = [m for m in report.matches if m.match_type == "identifier_normalized"]
        self.assertGreaterEqual(len(id_matches), 2)

    def test_invalid_python_is_error(self) -> None:
        report = match_snippet_against_repo(SYNTHETIC_REPO, "def broken(")
        self.assertEqual(report.status, "error")

    def test_unsupported_scoping_errors_without_exact_match(self) -> None:
        nested = textwrap.dedent(
            """
            def outer(x):
                def inner(y):
                    return y
                return inner(x)
            """
        ).strip()
        report = match_snippet_against_repo(SYNTHETIC_REPO, nested)
        self.assertEqual(report.status, "error")
        self.assertIn("unsupported", (report.message or "").lower())

    def test_exact_ast_regression_unchanged(self) -> None:
        snippet = Path(SYNTHETIC_REPO / "helpers.py").read_text(encoding="utf-8")
        report = match_snippet_against_repo(SYNTHETIC_REPO, snippet)
        self.assertEqual(report.status, "match")
        self.assertTrue(any(m.match_type == "exact_ast" for m in report.matches))


class TestBoilerplateFalsePositiveFixtures(unittest.TestCase):
    """Short patterns that must not be flagged solely via identifier normalization."""

    INIT_METHOD = textwrap.dedent(
        """
        class Account:
            def __init__(self, owner, balance):
                self.owner = owner
                self.balance = balance
        """
    ).strip()

    GETTER = textwrap.dedent(
        """
        class Account:
            def get_balance(self):
                return self.balance
        """
    ).strip()

    MAIN_CALLER = textwrap.dedent(
        """
        def run_report():
            return produce_report()

        def produce_report():
            return 1
        """
    ).strip()

    SIMILAR_ARITH_A = "def alpha(x, y):\n    return x * y + 1\n"
    SIMILAR_ARITH_B = "def beta(a, b):\n    return a * b + 1\n"

    def test_init_method_no_identifier_match_at_default_threshold(self) -> None:
        repo = _write_repo(("account.py", self.INIT_METHOD))
        variant = self.INIT_METHOD.replace("Account", "Wallet").replace("owner", "holder")
        report = match_snippet_against_repo(repo, variant, min_nodes=DEFAULT_MIN_NODES)
        self.assertEqual(report.status, "no_match")
        self.assertFalse(any(m.match_type == "identifier_normalized" for m in report.matches))

    def test_one_line_getter_no_identifier_match(self) -> None:
        repo = _write_repo(("account.py", self.GETTER))
        variant = self.GETTER.replace("get_balance", "read_balance").replace("balance", "funds")
        report = match_snippet_against_repo(repo, variant, min_nodes=DEFAULT_MIN_NODES)
        self.assertEqual(report.status, "no_match")

    def test_main_caller_no_false_id_match_at_default_threshold(self) -> None:
        repo = _write_repo(
            (
                "app.py",
                textwrap.dedent(
                    """
                    def produce_report():
                        return 1
                    """
                ).strip(),
            )
        )
        snippet = textwrap.dedent(
            """
            def run_report():
                return build_report()
            """
        ).strip()
        report = match_snippet_against_repo(repo, snippet, min_nodes=DEFAULT_MIN_NODES)
        self.assertEqual(report.status, "no_match")
        self.assertFalse(any(m.match_type == "identifier_normalized" for m in report.matches))

    def test_similar_arithmetic_below_threshold_classified_no_match(self) -> None:
        repo = _write_repo(("a.py", self.SIMILAR_ARITH_A))
        report = match_snippet_against_index(
            index_repository(repo),
            self.SIMILAR_ARITH_B,
            min_nodes=DEFAULT_MIN_NODES,
        )
        self.assertEqual(report.status, "no_match")
        self.assertFalse(any(m.match_type == "identifier_normalized" for m in report.matches))

    def test_similar_arithmetic_with_low_threshold_can_match(self) -> None:
        repo = _write_repo(("a.py", self.SIMILAR_ARITH_A))
        report = match_snippet_against_index(
            index_repository(repo),
            self.SIMILAR_ARITH_B,
            min_nodes=5,
        )
        self.assertEqual(report.status, "match")
        self.assertTrue(any(m.match_type == "identifier_normalized" for m in report.matches))


class TestCliIdentifierNormalization(unittest.TestCase):
    def test_renamed_match_exit_code_and_output(self) -> None:
        cmd = [
            sys.executable,
            "-m",
            "codefence",
            "match",
            "--repo",
            str(SYNTHETIC_REPO),
            "--snippet",
            RENAMED_CLAMP,
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, EXIT_MATCH)
        self.assertIn("identifier_normalized", result.stdout)
        self.assertIn("Identifier mappings", result.stdout)
        self.assertNotIn("def bound", result.stdout)

    def test_unrelated_exit_no_match(self) -> None:
        cmd = [
            sys.executable,
            "-m",
            "codefence",
            "match",
            "--repo",
            str(SYNTHETIC_REPO),
            "--snippet",
            "def add(a, b):\n    return a + b\n",
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, EXIT_NO_MATCH)

    def test_nested_snippet_exit_error(self) -> None:
        nested = "def outer(x):\n    def inner(y):\n        return y\n    return inner(x)\n"
        cmd = [
            sys.executable,
            "-m",
            "codefence",
            "match",
            "--repo",
            str(SYNTHETIC_REPO),
            "--snippet",
            nested,
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, EXIT_ERROR)

    def test_negative_min_nodes_cli_exit_error(self) -> None:
        cmd = [
            sys.executable,
            "-m",
            "codefence",
            "match",
            "--repo",
            str(SYNTHETIC_REPO),
            "--snippet",
            RENAMED_CLAMP,
            "--min-nodes",
            "-1",
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, EXIT_ERROR)
        self.assertIn("min-nodes", result.stderr.lower())

    def test_default_min_nodes_is_twenty(self) -> None:
        from codefence.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["match", "--repo", str(SYNTHETIC_REPO), "--snippet", "def ok(): return 1"]
        )
        self.assertEqual(args.min_nodes, DEFAULT_MIN_NODES)


if __name__ == "__main__":
    unittest.main()
