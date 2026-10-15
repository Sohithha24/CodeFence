# CodeFence

Local-first tool that checks whether an outgoing Python function snippet **exactly matches** the normalized structure of code in an authorized local folder—ignoring spacing, comments, and **docstrings**, but not renamed variables yet.

## Requirements

- Python 3.10+ (standard library only; no pip install required)

## Quick start

From the project root:

```powershell
# List indexed functions in the synthetic example repo
python -m codefence index --repo examples/synthetic_repo

# Match (protected code found) — exit code 1
python -m codefence match --repo examples/synthetic_repo --snippet-file examples/snippets/clamp_compact.py
echo $LASTEXITCODE   # expect 1

# No match — exit code 0 (not a safety guarantee)
python -m codefence match --repo examples/synthetic_repo --snippet "def add(a, b): return a + b"
echo $LASTEXITCODE   # expect 0

# Invalid snippet — exit code 2
python -m codefence match --repo examples/synthetic_repo --snippet "def broken("
echo $LASTEXITCODE   # expect 2

# Valid Python, no function — exit code 2
python -m codefence match --repo examples/synthetic_repo --snippet "internal_token = \"x\""
echo $LASTEXITCODE   # expect 2

# Repository with no indexable functions — exit code 2
python -m codefence match --repo examples/synthetic_repo_no_functions --snippet "def add(a, b): return a + b"
echo $LASTEXITCODE   # expect 2
```

On Unix shells, use `$?` instead of `$LASTEXITCODE`.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## How it works

1. **Index** — Walk an authorized directory tree, read `.py` files as text (never execute), skip symlinks and common generated/vendor folders.
2. **Extract** — Parse with `ast` and collect every `def` / `async def`, including nested functions and class methods.
3. **Normalize** — Strip **docstrings** from functions, async functions, and classes in the function subtree; then `ast.dump(..., include_attributes=False)` and SHA-256 hash.
4. **Match** — Parse the outgoing snippet the same way; report `exact_ast` matches with file path and qualified function name.

### Docstring normalization

- The first string literal in a function, `async def`, or class body (PEP 257 docstring position) is removed before hashing.
- **Ordinary string expressions** (for example `tag = "item"`) stay in the AST and still affect matching.
- Changing or removing a docstring does **not** break an otherwise identical `exact_ast` match.

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
| **2** | Error | Invalid snippet, unreadable snippet file, incomplete repository scan, or unexpected failure |

Exit **2** (not 0) also applies when:

- The snippet is valid Python but contains **no analyzable function** (for example only `internal_token = "..."`).
- The snippet mixes a `def` / `async def` with **other top-level statements** (assignments, imports, etc.). The result is not a clean no-match or match.
- The repository scan finishes but **no protected functions** were indexed (`examples/synthetic_repo_no_functions/`).

- **Exit 0 is not “safe to share.”** It only means no match was found in the files that were successfully indexed.
- If any protected `.py` file cannot be read or parsed, skipped paths are listed on stderr. When no match is found in that situation, the command returns **exit 2**, not 0.
- Error output does not include raw snippet or repository source.

## Output examples

- **Match (exit 1):** `MATCH (exact_ast): clamp in ...\helpers.py (snippet function: clamp)`
- **No match (exit 0):** message includes *this is not a guarantee that code is safe to share*
- **Error (exit 2):** short reason on stderr; `Skipped protected file: ...` when indexing failed for specific paths

## Known limitations (through Milestone 2 prep)

- Variable renaming
- Function renaming
- Decorator changes
- Type annotation changes
- Partial code snippets (non-function fragments)
- Snippets must be function-only at module top level (no mixed assignments/imports)
- Exact executable structure only (no fuzzy or ML similarity yet)
- Function-level granularity; no persistent index file or editor integration yet
- Similarity is evidence for review, not proof of ownership or misconduct

## Project docs

- `AGENTS.md` — standing rules for development
- `PLAN.md` — long-term roadmap (context only)
- `PROGRESS.md` — milestone status and journal

## Privacy

Use synthetic or appropriately licensed public code in this workspace. Do not put real private repositories inside folders the agent can read.
