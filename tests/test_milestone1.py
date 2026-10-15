"""Milestone 1: exact AST matching, formatting invariance, and error handling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codefence.ast_util import parse_source_functions
from codefence.matcher import match_snippet_against_repo

REPO = Path(__file__).resolve().parent.parent / "examples" / "synthetic_repo"

CLAMP_SOURCE = """
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
"""


class TestExactAndNormalizedMatch(unittest.TestCase):
    def test_exact_copy_matches(self) -> None:
        report = match_snippet_against_repo(REPO, CLAMP_SOURCE.strip())
        self.assertEqual(report.status, "match")
        self.assertTrue(report.matches)
        self.assertEqual(report.matches[0].function_name, "clamp")
        self.assertEqual(report.matches[0].match_type, "exact_ast")
        self.assertIn("helpers.py", str(report.matches[0].file_path))

    def test_spacing_and_comments_ignored(self) -> None:
        spaced = """
# header comment
def clamp( value , low , high ):  # inline
    if value<low:
        return low  # keep low
    if value > high:
        return high
    return value
"""
        report = match_snippet_against_repo(REPO, spaced)
        self.assertEqual(report.status, "match")
        self.assertEqual(report.matches[0].function_name, "clamp")

    def test_unrelated_code_no_match(self) -> None:
        unrelated = """
def add(a, b):
    return a + b
"""
        report = match_snippet_against_repo(REPO, unrelated)
        self.assertEqual(report.status, "no_match")

    def test_method_qualified_name(self) -> None:
        method_snippet = """
class Widget:
    def spin(self, degrees):
        total = degrees % 360
        return total
"""
        report = match_snippet_against_repo(REPO, method_snippet)
        self.assertEqual(report.status, "match")
        self.assertEqual(report.matches[0].function_name, "Widget.spin")

    def test_syntax_error_reported(self) -> None:
        report = match_snippet_against_repo(REPO, "def broken(")
        self.assertEqual(report.status, "error")
        self.assertIn("Syntax error", report.message or "")

    def test_partial_body_reported(self) -> None:
        report = match_snippet_against_repo(
            REPO,
            "    return value\n",
        )
        self.assertEqual(report.status, "error")
        self.assertIn("partial", (report.message or "").lower())

    def test_index_skips_symlinked_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.py"
            real.write_text("def ok():\n    return 1\n", encoding="utf-8")
            link = root / "link.py"
            try:
                link.symlink_to(real)
            except OSError:
                self.skipTest("Symlinks not supported on this platform.")
            report = match_snippet_against_repo(root, "def ok():\n    return 1\n")
            self.assertEqual(report.status, "match")
            self.assertIn("real.py", str(report.matches[0].file_path))
            self.assertNotIn("link.py", str(report.matches[0].file_path))


class TestParseHelpers(unittest.TestCase):
    def test_nested_function_qualified_name(self) -> None:
        source = Path(REPO / "nested_sample.py").read_text(encoding="utf-8")
        outcome = parse_source_functions(source)
        self.assertEqual(outcome.kind, "ok")
        names = {f.qualified_name for f in outcome.functions}
        self.assertIn("outer_factor", names)
        self.assertIn("outer_factor.inner_double", names)


if __name__ == "__main__":
    unittest.main()
