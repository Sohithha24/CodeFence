"""Milestone 2B: token shingles, exact Jaccard, MinHash, and review candidates."""

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
from codefence.indexer import index_repository
from codefence.matcher import (
    DEFAULT_REVIEW_JACCARD_THRESHOLD,
    match_snippet_against_index,
    match_snippet_against_repo,
    validate_review_jaccard_threshold,
    validate_shingle_size,
)
from codefence.token_eval_fixtures import EVAL_PAIRS
from codefence.token_similarity import (
    DEFAULT_MINHASH_PERM,
    DEFAULT_SHINGLE_SIZE,
    build_shingles,
    exact_jaccard,
    fingerprint_function_tokens,
    minhash_from_shingles,
    minhash_jaccard_estimate,
    normalize_token_strings,
    passes_token_candidate_filters,
)

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_REPO = ROOT / "examples" / "synthetic_repo"

try:
    import datasketch  # noqa: F401

    HAS_DATASKETCH = True
except ImportError:
    HAS_DATASKETCH = False


def _first_function_node(source: str) -> ast.AST:
    outcome = parse_source_functions(source)
    assert outcome.kind == "ok" and outcome.functions
    return outcome.functions[0].node


def _write_repo(*files: tuple[str, str]) -> Path:
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    for name, content in files:
        (root / name).write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    return root


@unittest.skipUnless(HAS_DATASKETCH, "datasketch not installed (pip install -r requirements.txt)")
class TestTokenNormalizationAndShingles(unittest.TestCase):
    def test_token_extraction_preserves_literals_and_operators(self) -> None:
        src = "def f(x):\n    return x + 1\n"
        tokens = normalize_token_strings(src)
        self.assertIsNotNone(tokens)
        assert tokens is not None
        joined = " ".join(tokens)
        self.assertIn("NAME:x", joined)
        self.assertIn("OP:+", joined)
        self.assertIn("NUMBER:1", joined)

    def test_comments_and_whitespace_ignored(self) -> None:
        plain = "def f():\n    return 1\n"
        noisy = "def f():\n    # comment\n    return 1  # trailing\n"
        self.assertEqual(normalize_token_strings(plain), normalize_token_strings(noisy))

    def test_shingle_creation(self) -> None:
        tokens = ("A", "B", "C", "D", "E")
        shingles = build_shingles(tokens, shingle_size=3)
        self.assertEqual(len(shingles), 3)

    def test_empty_shingles_for_short_sequences(self) -> None:
        self.assertEqual(build_shingles(("A", "B"), shingle_size=3), frozenset())


@unittest.skipUnless(HAS_DATASKETCH, "datasketch not installed")
class TestJaccardAndMinHash(unittest.TestCase):
    def test_exact_jaccard_empty_sets(self) -> None:
        self.assertEqual(exact_jaccard(frozenset(), frozenset()), 0.0)
        self.assertEqual(exact_jaccard(frozenset({"a"}), frozenset()), 0.0)

    def test_exact_jaccard_identical(self) -> None:
        shingles = frozenset({"x", "y"})
        self.assertEqual(exact_jaccard(shingles, shingles), 1.0)

    def test_minhash_reproducible(self) -> None:
        shingles = frozenset({"tok\x1fone", "tok\x1ftwo"})
        first = minhash_from_shingles(shingles)
        second = minhash_from_shingles(shingles)
        self.assertEqual(first, second)
        self.assertEqual(len(first), DEFAULT_MINHASH_PERM)

    def test_minhash_estimate_near_exact_for_identical(self) -> None:
        shingles = build_shingles(("A", "B", "C", "D", "E", "F", "G"), shingle_size=3)
        sig = minhash_from_shingles(shingles)
        estimate = minhash_jaccard_estimate(sig, sig)
        self.assertAlmostEqual(estimate, 1.0, places=2)

    def test_minhash_estimate_tracks_exact_jaccard_on_fixture(self) -> None:
        pair = next(item for item in EVAL_PAIRS if item.name == "added_log_line")
        protected = textwrap.dedent(pair.protected).strip()
        outgoing = textwrap.dedent(pair.outgoing).strip()
        p_node = _first_function_node(protected)
        o_node = _first_function_node(outgoing)
        p_fp = fingerprint_function_tokens(protected, p_node)
        o_fp = fingerprint_function_tokens(outgoing, o_node)
        exact = exact_jaccard(p_fp.shingles, o_fp.shingles)
        estimate = minhash_jaccard_estimate(p_fp.minhash_hashvalues, o_fp.minhash_hashvalues)
        self.assertGreater(exact, 0.0)
        self.assertGreater(estimate, 0.0)
        self.assertLessEqual(abs(exact - estimate), 0.25)


@unittest.skipUnless(HAS_DATASKETCH, "datasketch not installed")
class TestEvaluationFixtures(unittest.TestCase):
    def test_synthetic_evaluation_pairs(self) -> None:
        for pair in EVAL_PAIRS:
            protected = textwrap.dedent(pair.protected).strip()
            outgoing = textwrap.dedent(pair.outgoing).strip()
            p_node = _first_function_node(protected)
            o_node = _first_function_node(outgoing)
            p_fp = fingerprint_function_tokens(protected, p_node)
            o_fp = fingerprint_function_tokens(outgoing, o_node)
            self.assertTrue(p_fp.ok, msg=pair.name)
            self.assertTrue(o_fp.ok, msg=pair.name)
            jaccard = exact_jaccard(p_fp.shingles, o_fp.shingles)
            minhash_est = minhash_jaccard_estimate(
                p_fp.minhash_hashvalues,
                o_fp.minhash_hashvalues,
            )
            candidate = (
                passes_token_candidate_filters(
                    token_count=len(o_fp.normalized_tokens),
                    shingle_count=len(o_fp.shingles),
                    min_tokens=12,
                    min_shingles=5,
                )
                and passes_token_candidate_filters(
                    token_count=len(p_fp.normalized_tokens),
                    shingle_count=len(p_fp.shingles),
                    min_tokens=12,
                    min_shingles=5,
                )
                and jaccard >= DEFAULT_REVIEW_JACCARD_THRESHOLD
            )
            self.assertEqual(
                candidate,
                pair.expect_candidate,
                msg=(
                    f"{pair.name}: jaccard={jaccard:.3f}, minhash={minhash_est:.3f}, "
                    f"expected candidate={pair.expect_candidate}"
                ),
            )


@unittest.skipUnless(HAS_DATASKETCH, "datasketch not installed")
class TestMatcherTokenReview(unittest.TestCase):
    def test_added_statement_triggers_review_not_confirmed_leak(self) -> None:
        pair = next(item for item in EVAL_PAIRS if item.name == "added_log_line")
        repo = _write_repo(("protected.py", pair.protected))
        report = match_snippet_against_repo(repo, textwrap.dedent(pair.outgoing).strip())
        self.assertEqual(report.status, "match")
        reviews = [m for m in report.matches if m.evidence_kind == "review_required"]
        self.assertTrue(reviews)
        self.assertTrue(any(m.match_type == "token_jaccard" for m in reviews))
        self.assertTrue(any(m.match_type == "token_minhash" for m in reviews))
        self.assertTrue(all(m.match_type != "exact_ast" for m in reviews))

    def test_unrelated_functions_no_review_by_default(self) -> None:
        pair = next(item for item in EVAL_PAIRS if item.name == "utility_add_hard_negative")
        repo = _write_repo(("protected.py", pair.protected))
        report = match_snippet_against_repo(repo, textwrap.dedent(pair.outgoing).strip())
        self.assertEqual(report.status, "no_match")

    def test_exact_ast_unchanged_and_skips_token_when_confirmed(self) -> None:
        pair = next(item for item in EVAL_PAIRS if item.name == "exact_clamp")
        repo = _write_repo(("protected.py", pair.protected))
        report = match_snippet_against_repo(repo, textwrap.dedent(pair.outgoing).strip())
        self.assertEqual(report.status, "match")
        self.assertTrue(any(m.match_type == "exact_ast" for m in report.matches))
        self.assertFalse(any(m.evidence_kind == "review_required" for m in report.matches))

    def test_invalid_review_threshold_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_review_jaccard_threshold(1.5)
        with self.assertRaises(ValueError):
            validate_shingle_size(0)
        repo = _write_repo(("p.py", "def f():\n    return 1\n"))
        index = index_repository(repo)
        with self.assertRaises(ValueError):
            match_snippet_against_index(
                index,
                "def g():\n    return 2\n",
                review_jaccard_threshold=-0.1,
            )


@unittest.skipUnless(HAS_DATASKETCH, "datasketch not installed")
class TestLiteralDifferencePolicy(unittest.TestCase):
    def test_one_modified_numeric_constant_triggers_review_with_literal_evidence(self) -> None:
        snippet = '''
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value + 1
'''
        report = match_snippet_against_repo(SYNTHETIC_REPO, snippet.strip())
        self.assertEqual(report.status, "match")
        reviews = [m for m in report.matches if m.match_type == "token_jaccard"]
        self.assertTrue(reviews)
        self.assertTrue(reviews[0].literals_differ)
        self.assertIn("Literal token multiset differs", reviews[0].literal_evidence_note or "")

    def test_multiple_modified_numeric_constants(self) -> None:
        protected = """
def mix(base, step):
    if base < 0:
        return 0
    total = base * step + 2 + 3
    return total
"""
        outgoing = """
def mix(base, step):
    if base < 0:
        return 0
    total = base * step + 9 + 8
    return total
"""
        repo = _write_repo(("protected.py", protected))
        report = match_snippet_against_repo(repo, textwrap.dedent(outgoing).strip())
        reviews = [m for m in report.matches if m.match_type == "token_jaccard"]
        self.assertTrue(reviews)
        self.assertTrue(reviews[0].literals_differ)

    def test_unrelated_arithmetic_stays_no_match(self) -> None:
        pair = next(item for item in EVAL_PAIRS if item.name == "similar_arithmetic_negative")
        repo = _write_repo(("protected.py", pair.protected))
        report = match_snippet_against_repo(repo, textwrap.dedent(pair.outgoing).strip())
        self.assertEqual(report.status, "no_match")

    def test_boilerplate_getter_not_flagged(self) -> None:
        pair = next(item for item in EVAL_PAIRS if item.name == "boilerplate_getter_negative")
        repo = _write_repo(("protected.py", pair.protected))
        report = match_snippet_against_repo(repo, textwrap.dedent(pair.outgoing).strip())
        self.assertEqual(report.status, "no_match")

    def test_minhash_alone_does_not_trigger_review(self) -> None:
        protected = "def f():\n    return 1\n"
        outgoing = "def f():\n    return 2\n"
        p_node = _first_function_node(protected)
        o_node = _first_function_node(outgoing)
        p_fp = fingerprint_function_tokens(protected, p_node)
        o_fp = fingerprint_function_tokens(outgoing, o_node)
        jaccard = exact_jaccard(p_fp.shingles, o_fp.shingles)
        minhash_est = minhash_jaccard_estimate(p_fp.minhash_hashvalues, o_fp.minhash_hashvalues)
        self.assertLess(jaccard, DEFAULT_REVIEW_JACCARD_THRESHOLD)
        repo = _write_repo(("protected.py", protected))
        report = match_snippet_against_repo(repo, outgoing)
        self.assertEqual(report.status, "no_match")
        self.assertGreaterEqual(minhash_est, 0.0)


class TestTokenCliCompatibility(unittest.TestCase):
    @unittest.skipUnless(HAS_DATASKETCH, "datashetch not installed")
    def test_review_required_printed_with_exit_match(self) -> None:
        pair = next(item for item in EVAL_PAIRS if item.name == "added_log_line")
        repo = _write_repo(("protected.py", pair.protected))
        cmd = [
            sys.executable,
            "-m",
            "codefence",
            "match",
            "--repo",
            str(repo),
            "--snippet",
            textwrap.dedent(pair.outgoing).strip(),
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, EXIT_MATCH)
        self.assertIn("REVIEW_REQUIRED", result.stdout)
        self.assertIn("token_jaccard", result.stdout)

    def test_invalid_review_jaccard_cli_exit_error(self) -> None:
        cmd = [
            sys.executable,
            "-m",
            "codefence",
            "match",
            "--repo",
            str(ROOT / "examples" / "synthetic_repo"),
            "--snippet",
            "def ok():\n    return 1\n",
            "--review-jaccard",
            "2.0",
        ]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, EXIT_ERROR)


if __name__ == "__main__":
    unittest.main()
