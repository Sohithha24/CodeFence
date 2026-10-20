# CodeFence Progress Log

## Current milestone: 2A — AST-Based Identifier Normalization
Status: **Complete (awaiting review)**

### Acceptance checklist (Milestone 2A)
- [x] Preserve existing `exact_ast` matching unchanged in behavior for Milestone 1 scenarios.
- [x] Add separate `identifier_normalized` matching with binding-based renaming (`FUNC`, `VAR_n`).
- [x] Preserve built-ins, imports, attributes, keyword labels, and non-local/global reads.
- [x] Configurable minimum AST node threshold (default 20) for identifier-normalized matches only.
- [x] Record size-based skips without claiming safety.
- [x] Explainable matches: method, paths, node count, threshold, mappings, explanation.
- [x] Report all identifier-normalized matches when multiple protected functions align.
- [x] Fail-closed on unsupported normalization scope when no exact match exists.
- [x] CLI exit codes 0 / 1 / 2 preserved; `--min-nodes` flag added.
- [x] `tests/test_identifier_normalization.py` with required scenarios and boilerplate fixtures.
- [x] README updated with algorithm, limitations, and test instructions.

### Milestone 1 (complete)
See journal entries below; all Milestone 1 acceptance items remain satisfied.

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

**Entry 4 — Milestone 2A identifier normalization**
- Added `codefence/id_normalize.py` (binding-aware rename, node counting, unsupported-scope detection).
- Extended indexer with identifier-normalized hashes and binding maps; extended matcher and CLI output.
- Added `tests/test_identifier_normalization.py`, `examples/snippets/clamp_renamed.py`.
- **Tests run:** `python -m unittest discover -s tests -v` → 59 run, 58 passed, 0 failed, 1 skipped (symlink test).

**Entry 5 — Milestone 2A pre-commit hardening**
- Scope regression tests (implicit/explicit global, shadowed built-ins, full clamp mappings).
- `--min-nodes` validation (reject negative); multi-function fail-closed test; README/PROGRESS updates.
- **Tests run:** `python -m unittest discover -s tests -v` → 66 run, 65 passed, 0 failed, 1 skipped (symlink test).

**Next action:** Commit Milestone 2A after approval; do not start Milestone 2B until approved.

### Known limitations (Milestone 2A)
- Identifier normalization supports single-function bodies only; nested defs, lambdas, comprehensions, and inner classes are rejected for that method.
- No MinHash, ML, decorator/type normalization, or persistent index.
- `MIN_NODES = 20` is provisional—not tuned on labeled data yet.
- Module snippets must not mix functions with other top-level statements.
- Similarity is evidence for review, not proof of ownership.

*For each session, record: what changed, which tests ran, what failed, what you learned, and the next action.*
