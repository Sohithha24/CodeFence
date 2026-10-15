"""Edge-case regression tests before Milestone 2."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from codefence.cli import EXIT_ERROR, EXIT_MATCH, EXIT_NO_MATCH
from codefence.matcher import match_snippet_against_repo

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "examples" / "synthetic_repo"
REPO_NO_FUNCTIONS = ROOT / "examples" / "synthetic_repo_no_functions"

ASSIGNMENT_ONLY = 'internal_token = "example-sensitive-value"\n'

MIXED_SNIPPET = '''
def add(a, b):
    return a + b
internal_token = "example-sensitive-value"
'''


def run_match_cli(repo: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "codefence", "match", "--repo", str(repo), *extra_args]
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class TestValidPythonWithoutFunction(unittest.TestCase):
    def test_assignment_only_is_error_not_no_match(self) -> None:
        report = match_snippet_against_repo(REPO, ASSIGNMENT_ONLY)
        self.assertEqual(report.status, "error")
        self.assertNotIn("not a guarantee", (report.message or "").lower())

    def test_assignment_only_cli_exit_error(self) -> None:
        result = run_match_cli(REPO, "--snippet", ASSIGNMENT_ONLY)
        self.assertEqual(result.returncode, EXIT_ERROR)
        self.assertNotIn("example-sensitive-value", result.stdout)
        self.assertNotIn("example-sensitive-value", result.stderr)
        self.assertNotIn("not a guarantee", result.stdout.lower())


class TestRepositoryWithoutIndexableFunctions(unittest.TestCase):
    def test_empty_function_index_is_error(self) -> None:
        report = match_snippet_against_repo(
            REPO_NO_FUNCTIONS,
            "def add(a, b):\n    return a + b\n",
        )
        self.assertEqual(report.status, "error")
        self.assertIn("No protected functions", report.message or "")

    def test_empty_function_index_cli_exit_error(self) -> None:
        result = run_match_cli(
            REPO_NO_FUNCTIONS,
            "--snippet",
            "def add(a, b):\n    return a + b\n",
        )
        self.assertEqual(result.returncode, EXIT_ERROR)
        self.assertNotIn("not a guarantee", result.stdout.lower())


class TestFunctionPlusLooseCode(unittest.TestCase):
    def test_mixed_snippet_is_error_even_if_function_unrelated(self) -> None:
        report = match_snippet_against_repo(REPO, MIXED_SNIPPET)
        self.assertEqual(report.status, "error")
        self.assertIn("outside supported", (report.message or "").lower())

    def test_mixed_snippet_errors_even_when_function_would_match(self) -> None:
        mixed_match = '''
def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value
internal_token = "example-sensitive-value"
'''
        report = match_snippet_against_repo(REPO, mixed_match)
        self.assertEqual(report.status, "error")
        result = run_match_cli(REPO, "--snippet", mixed_match)
        self.assertEqual(result.returncode, EXIT_ERROR)
        self.assertNotEqual(result.returncode, EXIT_MATCH)

    def test_mixed_snippet_cli_exit_error(self) -> None:
        result = run_match_cli(REPO, "--snippet", MIXED_SNIPPET)
        self.assertEqual(result.returncode, EXIT_ERROR)
        self.assertIn("outside supported", result.stderr.lower())
        self.assertNotIn("not a guarantee", result.stdout.lower())

    def test_function_only_still_allows_no_match(self) -> None:
        report = match_snippet_against_repo(REPO, "def add(a, b):\n    return a + b\n")
        self.assertEqual(report.status, "no_match")
        result = run_match_cli(REPO, "--snippet", "def add(a, b):\n    return a + b\n")
        self.assertEqual(result.returncode, EXIT_NO_MATCH)


if __name__ == "__main__":
    unittest.main()
