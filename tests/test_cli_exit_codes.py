"""CLI ``match`` exit codes and subprocess integration tests."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from codefence.cli import EXIT_ERROR, EXIT_MATCH, EXIT_NO_MATCH

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "examples" / "synthetic_repo"
SNIPPET_MATCH = ROOT / "examples" / "snippets" / "clamp_compact.py"


def run_match_cli(*extra_args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "codefence", "match", "--repo", str(REPO), *extra_args]
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


class TestMatchCliExitCodes(unittest.TestCase):
    def test_exact_copy_exit_match(self) -> None:
        result = run_match_cli("--snippet-file", str(SNIPPET_MATCH))
        self.assertEqual(result.returncode, EXIT_MATCH)
        self.assertIn("MATCH (exact_ast)", result.stdout)
        self.assertNotIn("def clamp", result.stdout)
        self.assertNotIn("def clamp", result.stderr)

    def test_removed_docstring_exit_match(self) -> None:
        snippet = '''
def clamp(value, low, high):
    """Removed or present should not matter."""
    if value < low:
        return low
    if value > high:
        return high
    return value
'''
        result = run_match_cli("--snippet", snippet)
        self.assertEqual(result.returncode, EXIT_MATCH)

    def test_modified_docstring_exit_match(self) -> None:
        snippet = '''
def clamp(value, low, high):
    """Modified prose."""
    if value < low:
        return low
    if value > high:
        return high
    return value
'''
        result = run_match_cli("--snippet", snippet)
        self.assertEqual(result.returncode, EXIT_MATCH)

    def test_unrelated_function_exit_no_match(self) -> None:
        result = run_match_cli("--snippet", "def add(a, b):\n    return a + b\n")
        self.assertEqual(result.returncode, EXIT_NO_MATCH)
        self.assertIn("not a guarantee", result.stdout.lower())

    def test_invalid_snippet_exit_error(self) -> None:
        result = run_match_cli("--snippet", "def broken(")
        self.assertEqual(result.returncode, EXIT_ERROR)
        self.assertIn("Syntax error", result.stderr)

    def test_missing_snippet_file_exit_error(self) -> None:
        missing = ROOT / "examples" / "snippets" / "does_not_exist.py"
        result = run_match_cli("--snippet-file", str(missing))
        self.assertEqual(result.returncode, EXIT_ERROR)
        self.assertIn("Snippet file", result.stderr)

    def test_incomplete_repo_scan_no_match_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "good.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
            (repo / "bad.py").write_text("def broken(\n", encoding="utf-8")
            cmd = [
                sys.executable,
                "-m",
                "codefence",
                "match",
                "--repo",
                str(repo),
                "--snippet",
                "def add(a, b):\n    return a + b\n",
            ]
            result = subprocess.run(
                cmd,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, EXIT_ERROR)
            self.assertIn("Skipped protected file", result.stderr)
            self.assertIn("bad.py", result.stderr)
            self.assertIn("incomplete", result.stderr.lower())

    def test_unexpected_scanner_failure_exit_error(self) -> None:
        from codefence.cli import build_parser, cmd_match

        parser = build_parser()
        args = parser.parse_args(
            [
                "match",
                "--repo",
                str(REPO),
                "--snippet",
                "def ok():\n    return 1\n",
            ]
        )
        err = io.StringIO()
        with mock.patch(
            "codefence.cli.match_snippet_against_repo",
            side_effect=RuntimeError("boom"),
        ):
            with redirect_stderr(err):
                code = cmd_match(args)
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("Unexpected scanner failure", err.getvalue())


if __name__ == "__main__":
    unittest.main()
