# CodeFence

Local-first tool that checks whether an outgoing Python function snippet matches code in an authorized local folder—using **exact structural AST matching**, **identifier-normalized AST matching** (Milestone 2A), and **token-based similarity** with exact Jaccard and MinHash (Milestone 2B).

## Requirements

- Python 3.10+
- Core matching (Milestones 1–2A): standard library only
- MinHash (Milestone 2B): install optional dependency `datasketch` (see `requirements.txt`)

```powershell
pip install -r requirements.txt
```

## Quick start

From the project root:

```powershell
# List indexed functions in the synthetic example repo
python -m codefence index --repo examples/synthetic_repo

# Exact structural match — exit code 1
python -m codefence match --repo examples/synthetic_repo --snippet-file examples/snippets/clamp_compact.py
echo $LASTEXITCODE   # expect 1

# Renamed copy (identifier-normalized match) — exit code 1
python -m codefence match --repo examples/synthetic_repo --snippet-file examples/snippets/clamp_renamed.py
echo $LASTEXITCODE   # expect 1

# No match — exit code 0 (not a safety guarantee)
python -m codefence match --repo examples/synthetic_repo --snippet "def add(a, b): return a + b"
echo $LASTEXITCODE   # expect 0

# Invalid snippet — exit code 2
python -m codefence match --repo examples/synthetic_repo --snippet "def broken("
echo $LASTEXITCODE   # expect 2
```

On Unix shells, use `$?` instead of `$LASTEXITCODE`.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

- Milestone 2A: `tests/test_identifier_normalization.py`
- Milestone 2B: `tests/test_token_similarity.py` (requires `datasketch` for MinHash tests)

## How it works

1. **Index** — Walk an authorized directory tree, read `.py` files as text (never execute), skip symlinks and common generated/vendor folders.
2. **Extract** — Parse with `ast` and collect every `def` / `async def`, including nested functions and class methods.
3. **Normalize (exact_ast)** — Strip docstrings, then `ast.dump(..., include_attributes=False)` and SHA-256 hash. Spacing, comments, and docstrings do not affect equality; **identifier names still matter** for this method.
4. **Normalize (identifier_normalized)** — On a separate path, rename **locally bound** identifiers to stable slots (`FUNC`, `VAR_0`, `VAR_1`, …) by binding order, then hash the same way. Functions that differ only by consistent renaming can match.
5. **Token similarity (Milestone 2B)** — Tokenize each function (no execution), build configurable **token shingles**, compute **exact Jaccard** over shingle sets and **MinHash** estimates (`num_perm=128`, seed `42`). **Exact Jaccard alone** decides review candidacy (MinHash is supporting evidence and may later help retrieve candidates in large repos).
6. **Match** — Compare the outgoing snippet against the index. Confirmed methods: `exact_ast`, `identifier_normalized`. Token methods report **`REVIEW_REQUIRED`** evidence (`token_jaccard`, `token_minhash`); they are **not** confirmed proprietary leakage.

### Token normalization (Milestone 2B)

- Uses the `tokenize` module on extracted function source (from `ast.get_source_segment`).
- **Dropped:** comments, whitespace-only tokens, indentation markers.
- **Preserved:** `NAME` (identifiers stay meaningful), `NUMBER` / `STRING` literals, operators, keywords.
- **Shingle size:** default **5** contiguous normalized tokens (`--shingle-size`).
- **Exact Jaccard:** \|A ∩ B\| / \|A ∪ B\| (empty union → 0.0).
- **MinHash:** `datasketch` with **128** permutations, fixed seed for reproducibility. MinHash estimates are validated against exact Jaccard on synthetic fixtures; MinHash is not claimed to be more accurate than exact Jaccard.

### Token review policy (conservative)

- **`REVIEW_REQUIRED`** lines use exit code **1** (potential match / manual review), same as confirmed matches, but output prefix distinguishes them.
- **Exact Jaccard** (not MinHash noise) must meet **`--review-jaccard`** (default **0.55**, experimental—not production-tuned).
- **Literal differences** are reported as **evidence** (counts/categories only—no raw literal values in output). High Jaccard with differing literals can still be `REVIEW_REQUIRED`; literals alone never prove leakage.
- **`--min-tokens`** (default 12) and **`--min-shingles`** (default 5) filter short boilerplate.
- Renamed-only copies remain the job of `identifier_normalized` (token fingerprints keep identifier names).
- Token output includes shared shingle count, literal evidence note, and review reason.
- Similarity is evidence for review, not proof of copying.

### Identifier normalization (Milestone 2A)

Bindings are normalized, not renamed blindly:

| Role | Normalized label |
| --- | --- |
| Function’s own name (including recursive calls) | `FUNC` |
| Parameters (declaration order) | `VAR_0`, `VAR_1`, … |
| Other local bindings | Next `VAR_n` in **first-assignment / binding order** in the function body |

**Preserved (not renamed):** unshadowed built-ins (`len`, `range`, …), imported module/symbol names, **attribute** names (`customer.balance` keeps `balance`), keyword-argument **labels** at call sites, and names read from outer/global scope without a local binding.

**Why binding-based normalization:** Two functions that rename `amount`→`value` and `score`→`result` together keep the same usage graph; arbitrary string equality on names would miss modified copies.

**Identifier mappings** on a match align outgoing and protected names through shared normalized slots (for example `value -> amount`). Mappings are derived from analysis; they are not guessed.

### Minimum size (`--min-nodes`, default 20)

Short functions are easy false positives under identifier normalization (for example tiny getters or `__init__` assigners). The **20-node** threshold applies **only** to `identifier_normalized` matching (node count is after docstring removal). **`exact_ast` is unaffected.**

This default is a **provisional starting point** for development—not a validated security bound. Tune it later with labeled, repository-split evaluation data. When normalization is skipped for size, stderr notes that skip; **that is not a “safe to share” claim.**

**Lowering `--min-nodes` increases false-positive risk** (unrelated short functions can look alike after renaming). Negative values are rejected with exit code **2**.

Configure:

```powershell
python -m codefence match --repo examples/synthetic_repo --snippet-file examples/snippets/clamp_renamed.py --min-nodes 20
```

### Docstring normalization

- The first string literal in a function, `async def`, or class body (PEP 257 docstring position) is removed before hashing.
- Ordinary string expressions (for example `tag = "item"`) stay in the AST and still affect matching.

### Function naming

| Location | Example qualified name |
| --- | --- |
| Module-level function | `clamp` |
| Class method | `Widget.spin` |
| Nested function | `outer_factor.inner_double` |

## `match` exit codes (fail-closed integration)

Integrations should **only allow further processing when the command exits 0**, and only after all other security checks pass.

| Code | Meaning | When |
| --- | --- | --- |
| **0** | No match | Scan completed; no structural match in the indexed repository |
| **1** | Match | Protected-code structure matched (review required) |
| **2** | Error | Invalid snippet, unreadable snippet file, incomplete repository scan, unsupported normalization scope, or unexpected failure |

Exit **2** (not 0) also applies when:

- The snippet is valid Python but contains **no analyzable function**.
- The snippet mixes a `def` / `async def` with **other top-level statements**.
- The repository has **no indexable functions**.
- The snippet uses **scoping constructs that Milestone 2A cannot normalize reliably** (for example nested `def`, lambdas, comprehensions) and there is no `exact_ast` match.
- A **multi-function snippet** where **any** function cannot undergo reliable identifier normalization, and **no** `exact_ast` or `identifier_normalized` match is found—the whole submission returns **exit 2** (conservative fail-closed behavior, not a clean no-match).

- **Exit 0 is not “safe to share.”** It only means no match was found in the files that were successfully indexed.
- Skipped protected paths are listed on stderr; incomplete scans with no match return **exit 2**.
- Error output does not include raw snippet or repository source.

## Output examples

- **Exact match (exit 1):** `MATCH (exact_ast): clamp in ...\helpers.py (snippet function: clamp)`
- **Renamed match (exit 1):** `MATCH (identifier_normalized): ...` with AST node count, threshold, `Identifier mappings: ...`, and a short explanation.
- **No match (exit 0):** message includes *this is not a guarantee that code is safe to share*
- **Size skip (stderr):** identifier-normalized matching skipped for a small outgoing function (not a safety guarantee)

## Known limitations (through Milestone 2B)

- Identifier normalization does **not** support nested functions, lambdas, comprehensions, or classes defined inside the analyzed function body; such cases error when no exact match exists.
- No MinHash, ML, decorator/type-annotation normalization, or partial snippets.
- Snippets must be function-only at module top level (no mixed assignments/imports).
- Function-level granularity; in-memory index rebuilt each run; no editor integration.
- Token similarity is sensitive to statement add/remove and reordering; thresholds require labeled tuning.
- MinHash requires `datasketch`; without it, exact Jaccard still runs but MinHash signatures are omitted.
- Similarity is evidence for review, not proof of ownership or misconduct.

## Project docs

- `AGENTS.md` — standing rules for development
- `PLAN.md` — long-term roadmap (context only)
- `PROGRESS.md` — milestone status and journal

## Privacy

Use synthetic or appropriately licensed public code in this workspace. Do not put real private repositories inside folders the agent can read.
