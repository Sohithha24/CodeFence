# CodeFence Progress Log

## Current milestone: 1 — Normalized AST Exact Matching
Status: **Complete (pre–Milestone 2 edge cases verified)**

### Acceptance checklist (Milestone 1)
- [x] Reads `.py` files from a specified local folder without executing them.
- [x] Extracts top-level and nested Python functions using `ast` (methods: `ClassName.method_name`; nested: `outer.inner`).
- [x] Accepts an outgoing snippet via file or pasted text.
- [x] Detects function matches after AST normalization, ignoring formatting, comments, and docstrings.
- [x] Reports file path, function name, match type (`exact_ast`), and clear 'no match' output.
- [x] Reports invalid or partial Python snippets clearly without crashing.
- [x] Includes an exact-copy test, spacing/comments test, unrelated-code test, and invalid-input test.
- [x] Test suite runs successfully on the developer's machine.
- [x] README updated with real usage commands and honest limitations.

### Pre–Milestone 2 fixes
- [x] Docstrings stripped from `def`, `async def`, and `class` nodes before hashing.
- [x] `match` exit codes: 0 = no match, 1 = match, 2 = error.
- [x] Incomplete repository scan + no match → error (not exit 0).
- [x] Skipped protected files listed on stderr (paths only, no source).
- [x] Regression tests for docstrings and CLI exit codes.
- [x] Valid Python without a function → error (exit 2), not no-match.
- [x] Repository with no indexable functions → error (exit 2).
- [x] Function plus loose top-level code → error (exit 2), including when the function would otherwise match.

### Journal
**Entry 0 — Starter files created**
- Project instructions, roadmap, and first prompt prepared.

**Entry 1 — Milestone 1 implemented**
- Core `codefence` package, synthetic examples, and unittest suite.

**Entry 2 — Milestone 1 hardening (docstrings + exit codes)**
- Docstring stripping, CLI exit codes, Windows `skipped_paths` fix.
- **Tests run:** 24 run, 23 passed, 1 skipped.

**Entry 3 — Pre–Milestone 2 edge cases**
- `ast_util.py`: `unsupported_scope` for non-def/class top-level statements.
- `matcher.py`: reject empty function index before reporting no-match.
- Added `examples/synthetic_repo_no_functions/` and `tests/test_edge_cases_pre_m2.py`.
- **Tests run:** `python -m unittest discover -s tests -v` → 32 run, 31 passed, 0 failed, 1 skipped (symlink test).

**Next action:** Begin Milestone 2 only after review.

### Remaining limitations (explicit for Milestone 2)
- Variable renaming
- Function renaming
- Decorator modifications
- Type annotation modifications
- Partial code snippets (body fragments without a `def` header)
- Module snippets must not mix functions with other top-level statements
- No fuzzy/ML matching; function-level only; in-memory index rebuilt each run

*For each session, record: what changed, which tests ran, what failed, what you learned, and the next action.*
