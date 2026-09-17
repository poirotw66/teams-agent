# Golden Baseline Evaluation History

This document records accepted Agentic RAG baseline versions and their
reproducibility metadata.

## Baseline #01

- Status: Accepted as the initial engineering baseline
- Executed: 2026-09-17 14:19:57–14:23:10 (UTC+8)
- Question count: 100
- Target: Local production-contract `POST /agent/chat`
- Judge: `google_genai:gemini-3.1-pro-preview`
- Judge rubric: `knowledge-answer-judge-v1`
- Concurrency: 8 asynchronous workers
- Result persistence: Atomic checkpoint after every completed case

### Results

- PASS: 33
- PARTIAL: 24
- FAIL: 43
- INCONCLUSIVE: 0
- Strict pass rate: 33.00%
- Acceptable rate (`PASS + PARTIAL`): 57.00%
- Mean correctness: 0.5440
- Mean target latency: 5,165.27 ms
- P95 target latency: 9,732.22 ms

### Artifacts

- Detailed report: `outputs/golden-baseline-100.json`
- Comparison report: `outputs/golden-baseline-100-comparison.csv`
- Question bank SHA-256:
  `f192c97378339feac2e8f62b04027856adadbf80924afdc5c29c8f932154af1a`
- Detailed report SHA-256:
  `54ef0b7b614929c6d16ee08755d919eed88230b49b2354144c70152764426b82`
- Comparison report SHA-256:
  `81da82ec001371cf495f90db8626396052eec7a114a89183594eacff4d47a856`

The files under `outputs/` are local generated artifacts and are excluded from
Git by the repository ignore rules. The hashes above identify the exact
artifacts used for this baseline.

### Amendment 1 — QB-029 Judge recovery

- Recorded: 2026-09-17 14:55:58 (UTC+8)
- Scope: Judge-only retry using the originally cached Agent answer and
  citations; the Agent was not executed again.
- Previous verdict: INCONCLUSIVE
- Replacement verdict: FAIL
- Replacement scores: correctness 0.0, completeness 0.0, groundedness 1.0,
  source match 0.0
- Reason: The answer correctly avoided inventing missing visual-flow details,
  but did not provide the required SSLVPN Portal, CRM bookmark, and
  second-layer login steps because retrieval evidence was insufficient.
- Original detailed report SHA-256:
  `9b1b1c767c52b4be8e58da01ee4b34420a37d8c2ec1e9bcd49e2adc034cfdbd2`
- Original comparison report SHA-256:
  `01a893fe28ca4e0796dc1ec1e7626fcd62f2e8482d9e0841e34c42924e638ba4`

The detailed JSON report also preserves the previous and replacement Judge
objects in its `amendments` audit trail.

### Known limitations

- The Judge has not yet been calibrated against a human-labelled validation
  set.
- The target used the local production HTTP contract and local knowledge
  release; it was not executed against the deployed production environment.
- This is a single run and does not measure repeated-run variance.
- Baseline #01 is suitable for engineering comparison, but not yet approved as
  a release quality gate.

## Baseline #02

- Status: Accepted as the first `golden-baseline-v2` engineering baseline
- Agent execution: 2026-09-17 15:37:51–15:44:13 (UTC+8)
- Judge recovery completed: 2026-09-17 15:54:17 (UTC+8)
- Question count: 100
- Target: Secured local production workflow via `POST /agent/evaluation/chat`
- Knowledge release: `release-4052b21ce2c2`
- Judge: `google_genai:gemini-3.1-pro-preview`
- Judge rubric: `knowledge-answer-judge-v2`
- Concurrency: 8 asynchronous workers
- Result persistence: Atomic checkpoint after every completed case

### Results

- PASS: 35
- PARTIAL: 27
- FAIL: 38
- INCONCLUSIVE: 0
- Strict pass rate: 35.00%
- Acceptable rate (`PASS + PARTIAL`): 62.00%
- Mean correctness: 0.6000
- Mean completeness: 0.5580
- Mean groundedness: 0.7506
- Mean expected-source recall: 0.4117
- Mean target latency: 5,242.00 ms
- P95 target latency: 8,371.29 ms
- Independent review outcomes: 70 single pass, 24 confirmed, 6 adjudicated
- Cases requiring human review: 9

Compared with Baseline #01, strict pass rate increased by 2 percentage points
and acceptable rate increased by 5 percentage points. The values are not a
pure model-quality delta because Judge v2 uses complete retrieval evidence,
claim-level assessment, deterministic source recall, and independent review.

### Artifacts

- Detailed report: `outputs/golden-baseline-02.json`
- Comparison report: `outputs/golden-baseline-02-comparison.csv`
- Question bank SHA-256:
  `f192c97378339feac2e8f62b04027856adadbf80924afdc5c29c8f932154af1a`
- Detailed report SHA-256:
  `dafc425835ed0e4dbd7175e50e73d2a708a9bacb3542a64415a0f05bfecc5b9f`
- Comparison report SHA-256:
  `809c1a7442e62157617220e047a6cd801f8166de95eb1ea5df904af31ea425b0`

These hashes and the release ID freeze Baseline #02. Future suite changes must
not rewrite either artifact.

### Suite membership for future comparisons

- `All-100`: all original cases, preserving direct comparison with #02.
- `Helpdesk-96`: all cases except `QB-010`, `QB-090`, `QB-099`, and `QB-100`.
- `AI-Ops-4`: `QB-010`, `QB-090`, `QB-099`, and `QB-100`.

Suite membership is metadata only. The four AI Ops cases remain in the
historical question bank and `All-100` report.

### Judge recovery amendment

The initial Judge pass left 10 cases inconclusive because the claim-reference
validator rejected unsupported claims that cited contradictory evidence. Judge
v2 was corrected to permit those auditable references and to return the exact
validation failure and allowed chunk IDs on schema retry.

The 10 affected cases (`QB-007`, `QB-011`, `QB-020`, `QB-043`, `QB-061`,
`QB-070`, `QB-077`, `QB-081`, `QB-086`, and `QB-094`) were rejudged using
their cached Agent answers and citations. The Agent was not executed again.
Every replacement and previous Judge object is retained in the report
`amendments` trail.

### Known limitations

- The Judge has not yet been calibrated against a human-labelled validation
  set.
- The target used the local production workflow and local knowledge release;
  it was not executed against the deployed production environment.
- This remains a single Agent run and does not measure repeated-run variance.
- Baseline #02 is suitable for engineering comparison, but not yet approved as
  a release quality gate.

## Baseline #03 — RAG Remediation Candidate

- Completed: 2026-09-17
- Agent target: local production workflow via `/agent/evaluation/chat`
- Knowledge release: `release-b9438e33c0f6` (explicitly pinned)
- Evaluation audience groups: `grp_public`
- Judge: `google_genai:gemini-3.1-pro-preview`
- Pipeline concurrency: Agent 8, Judge 16
- Question bank SHA-256:
  `f192c97378339feac2e8f62b04027856adadbf80924afdc5c29c8f932154af1a`
- Release manifest SHA-256:
  `ecb0cdcd4912a34c81b0ce7faf973f46e331854721303239ff0cf6f4d7fb0dc0`
- Release index SHA-256:
  `6e4fbf8d5a25365715da6f67a75807d33f5d5940d40af476498afc82cbb1b37f`

### Results

- `All-100`: 42 PASS, 29 PARTIAL, 29 FAIL; strict pass 42.00%,
  acceptable 71.00%, expected-source recall 46.17%.
- `Helpdesk-96`: 42 PASS, 29 PARTIAL, 25 FAIL; strict pass 43.75%,
  acceptable 73.96%, expected-source recall 48.09%.
- `AI-Ops-4`: 0 PASS, 0 PARTIAL, 4 FAIL. These cases remain outside the
  Helpdesk product-quality suite.
- Mean target latency: 7,325.30 ms; P95 target latency: 11,512.77 ms.
- Cases requiring human review: 4.

Compared with Baseline #02, `All-100` strict pass increased by 7 percentage
points, acceptable rate increased by 9 percentage points, and expected-source
recall increased by 5 percentage points. P95 latency increased by 37.5%, which
exceeds the remediation acceptance budget of 15%; this candidate therefore
must not be treated as a passed release gate.

### Artifacts

- Detailed report: `outputs/golden-baseline-03.json`
- Comparison report: `outputs/golden-baseline-03-comparison.csv`
- Detailed report SHA-256:
  `70033a848b60718609645807e32dca40bed4886a9f9ceac81c0316d55e703e8b`
- Comparison report SHA-256:
  `10cf1bf6c2a231db2b3fe98962cf46b1a9262e4f51a065049888b0d651e41c23`

The report contains all three suite summaries from the same Agent/Judge run,
so suite comparisons are not affected by separate model samples. This remains
a single run; repeated targeted runs are still required before release
approval.
