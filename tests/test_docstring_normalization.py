"""Regression tests for docstring stripping during AST normalization."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from codefence.ast_util import hash_function_node, parse_source_functions
from codefence.matcher import match_snippet_against_repo

REPO = Path(__file__).resolve().parent.parent / "examples" / "synthetic_repo"

CLAMP_NO_DOC = """
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
"""


class TestDocstringNormalization(unittest.TestCase):
    def test_removed_function_docstring_matches(self) -> None:
        with_doc = '''
def clamp(value, low, high):
    """Keep value within bounds."""
    if value < low:
        return low
    if value > high:
        return high
    return value
'''
        report = match_snippet_against_repo(REPO, with_doc)
        self.assertEqual(report.status, "match")
        self.assertEqual(report.matches[0].function_name, "clamp")

    def test_modified_function_docstring_matches(self) -> None:
        with_doc = '''
def clamp(value, low, high):
    """Totally different documentation text."""
    if value < low:
        return low
    if value > high:
        return high
    return value
'''
        report = match_snippet_against_repo(REPO, with_doc)
        self.assertEqual(report.status, "match")

    def test_class_docstring_change_still_matches_method(self) -> None:
        snippet = '''
class Widget:
    """Revised class-level documentation."""
    def spin(self, degrees):
        total = degrees % 360
        return total
'''
        report = match_snippet_against_repo(REPO, snippet)
        self.assertEqual(report.status, "match")
        self.assertEqual(report.matches[0].function_name, "Widget.spin")

    def test_async_modified_docstring_matches(self) -> None:
        snippet = '''
async def fetch_item(key):
    """Different async docstring."""
    return key
'''
        report = match_snippet_against_repo(REPO, snippet)
        self.assertEqual(report.status, "match")
        self.assertEqual(report.matches[0].function_name, "fetch_item")

    def test_ordinary_string_expression_not_stripped(self) -> None:
        base = '''
def label_tag(name):
    tag = "item"
    return tag + name
'''
        with_doc = '''
def label_tag(name):
    """Doc only."""
    tag = "item"
    return tag + name
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sample.py").write_text(base.strip() + "\n", encoding="utf-8")

            report_match = match_snippet_against_repo(root, with_doc)
            self.assertEqual(report_match.status, "match")

            altered = with_doc.replace('"item"', '"other"')
            report_diff = match_snippet_against_repo(root, altered)
            self.assertEqual(report_diff.status, "no_match")

    def test_different_executable_logic_does_not_exact_match(self) -> None:
        different = '''
def clamp(value, low, high):
    """Harmless docstring change."""
    if value < low:
        return low
    if value > high:
        return high
    return value + 1
'''
        report = match_snippet_against_repo(REPO, different)
        self.assertFalse(any(m.match_type == "exact_ast" for m in report.matches))
        self.assertFalse(any(m.match_type == "identifier_normalized" for m in report.matches))
        token_reviews = [m for m in report.matches if m.match_type == "token_jaccard"]
        if token_reviews:
            self.assertEqual(report.status, "match")
            self.assertTrue(token_reviews[0].literals_differ)
        else:
            self.assertEqual(report.status, "no_match")

    def test_same_hash_when_only_docstrings_differ(self) -> None:
        a = parse_source_functions(CLAMP_NO_DOC).functions[0].node
        b_source = '''
def clamp(value, low, high):
    """Only change."""
    if value < low:
        return low
    if value > high:
        return high
    return value
'''
        b = parse_source_functions(b_source).functions[0].node
        self.assertEqual(hash_function_node(a), hash_function_node(b))

    def test_nested_class_docstring_stripped_in_outer_function_tree(self) -> None:
        """Outer function bodies that define inner classes ignore class docstrings."""
        source_a = '''
def factory():
    class Helper:
        """Class doc A."""
        def run(self):
            return 1
    return Helper
'''
        source_b = '''
def factory():
    class Helper:
        """Class doc B."""
        def run(self):
            return 1
    return Helper
'''
        fa = parse_source_functions(source_a).functions[0].node
        fb = parse_source_functions(source_b).functions[0].node
        self.assertEqual(hash_function_node(fa), hash_function_node(fb))


if __name__ == "__main__":
    unittest.main()
