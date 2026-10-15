# CodeFence — Long-Term Roadmap (Context Only)

**Scope:** Python-only version 1. Approximately 2–3 hours a day; timings are flexible and depend on testing results.

| Phase | Target weeks | Intended outcome |
| --- | --- | --- |
| 0. Setup and conversations | 1 | Development environment, version control, initial user interviews |
| 1. Python foundations and simple detector | 2–8 | Parse functions; normalized AST exact matching; token-based and MinHash baselines |
| 2. Secret detection and datasets | 9–11 | Credential scanning, licensed/synthetic examples, repository-level splits and hard negatives |
| 3. Transfer-learning experiments | 12–18 | Pretrained and fine-tuned CodeBERT/UniXcoder comparisons against baselines |
| 4. Local security service | 19–21 | Local API, warn/block/allow policy checks, tests |
| 5. Developer integration | 22–25 | VS Code extension and a *controlled* submission path with pre-send checking |
| 6. Pilot and release | 26–28 | User tests, false-positive assessment, packaging, honest documentation |

## Product goal
Build a **local-first, repository-aware source-code leak-prevention tool** for developers and small teams. Protect secrets and proprietary code before submission via CodeFence-controlled workflows.

## Technical objective
Compare normalized hashing, MinHash/token similarity, AST-aware similarity, and transfer-learning approaches. Do not assume ML is better. Prefer methods that offer acceptable recall at low false-positive rates and practical local latency.

## Non-goals for initial release
- Monitoring every application, browser, or clipboard event.
- Enterprise dashboards, billing, and fleet management.
- Claiming that similarity proves ownership or malicious intent.
- Uploading private repositories or running untrusted repository code.

**IMPORTANT:** This is the roadmap, not today's task list. Implement only the milestone specified in the current task prompt.
