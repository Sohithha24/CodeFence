# CodeFence Progress Log

## Current milestone: 2B — Token-Based Similarity and MinHash
Status: **Complete (awaiting review)**

### Acceptance checklist (Milestone 2B)
- [x] Function-level token fingerprinting without executing code.
- [x] Configurable token shingles (default size 5).
- [x] Exact Jaccard baseline over shingle sets.
- [x] MinHash via `datasketch` (128 permutations, deterministic seed).
- [x] Distinct evidence types: `token_jaccard`, `token_minhash` as `REVIEW_REQUIRED`.
- [x] Preserve `exact_ast` and `identifier_normalized` behavior.
- [x] CLI exit codes 0 / 1 / 2 unchanged; `REVIEW_REQUIRED` prefix for token evidence.
- [x] Synthetic evaluation fixtures in `codefence/token_eval_fixtures.py`.
- [x] `tests/test_token_similarity.py` and README updates.

### Milestone 2A (complete)
See journal entries below.

### Journal
**Entry 5 — Milestone 2A pre-commit hardening**
- Scope regression tests; `--min-nodes` validation; multi-function fail-closed test.
- **Tests run:** 66 run, 65 passed, 1 skipped.

**Entry 6 — Milestone 2A merged to main**
- `main` at `ca47cea`.

**Entry 7 — Milestone 2B token similarity**
- Added `codefence/token_similarity.py`, `codefence/token_eval_fixtures.py`, `requirements.txt`.
- Extended indexer, matcher, CLI for token review candidates.
- **Tests run:** 82 run, 81 passed, 1 skipped.

**Entry 8 — Milestone 2B pre-commit hardening**
- Literal differences reported as evidence (not auto-excluded); exact Jaccard-only candidacy; richer review output.
- **Tests run:** `python -m unittest discover -s tests -v` → 87 run, 86 passed, 0 failed, 1 skipped (symlink).

**Next action:** Review and commit Milestone 2B; do not start Milestone 3 until approved.

### Known limitations (Milestone 2B)
- `--review-jaccard` default (0.55) is experimental, not production-tuned.
- Short functions may skip token review via `--min-tokens` even when literals differ.
- Renamed copies are not token candidates by design (use Milestone 2A).
- MinHash optional without `datasketch` install; used for evidence today, candidate retrieval later.

*For each session, record: what changed, which tests ran, what failed, what you learned, and the next action.*
