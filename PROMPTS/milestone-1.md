Read `AGENTS.md`, `PLAN.md` (context only), and `PROGRESS.md`. Build **Milestone 1 only**:

1. Read `.py` files from an authorized local folder without executing them.
2. Extract functions with Python's built-in `ast` module.
3. Accept an outgoing Python snippet from a file or pasted text.
4. Normalize parsed function code using AST representations that ignore formatting and comments, and hash the normalized structure for exact matching. Do not normalize renamed variables yet.
5. Return the matched file path, function name, and match type, or clearly report no match.
6. If input is unparseable or is an unsupported partial function, report that clearly; never crash.
7. Provide a small command-line demo, safe synthetic example files, and automated tests for: exact copy, spacing/comments changes, unrelated code, and unparseable input.
8. Avoid dependencies not needed for this first milestone. Keep the implementation small and understandable.

Do **not** build later-phase ML, FastAPI, or editor features. Do not add empty future-facing modules.

When done, run the tests and show the **real commands and output**. Summarize key design choices, limitations, and next steps. Update `README.md` and `PROGRESS.md`. Stop after this milestone for review.
