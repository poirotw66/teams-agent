# Golden Judge v2

Golden Judge v2 separates retrieval quality from answer quality so one model
decision cannot silently redefine both metrics.

## Evaluation flow

1. The target runs the production workflow through
   `POST /agent/evaluation/chat`.
2. Evaluation-channel citations carry the complete set of retrieved chunks
   from each cited document. Evidence segments include stable `[chunkId=...]`
   markers. Normal user responses retain the compact citation payload.
3. Expected-source recall is calculated deterministically before the LLM Judge
   runs.
4. `google_genai:gemini-3.1-pro-preview` evaluates correctness, completeness,
   groundedness, material claims, and missing required facts.
5. Each supported claim must reference an observed evidence chunk ID.
6. PARTIAL, INCONCLUSIVE, and low-confidence results receive an independent
   second review. Disagreeing verdicts receive a third adjudication and are
   marked for human review.

## Execution pipeline

Agent execution and Judge evaluation use independent concurrency limits. The
runner defaults to 8 Agent requests and 16 Judge requests:

```bash
python scripts/run_golden_baseline.py questions.csv \
  --agent-concurrency 8 \
  --judge-concurrency 16
```

An Agent slot is released as soon as the target response is available; Judge
review, retry, and adjudication no longer block new Agent requests. Lower
`--judge-concurrency` if the Gemini project reports quota exhaustion or
throttling. The deprecated `--max-concurrency` option remains available and
sets both stages to the same value for backward compatibility.

Reports include Agent latency plus Judge queue and execution latency, making
provider latency and local pipeline saturation distinguishable on subsequent
runs.

## Deterministic retrieval scoring

Expected source names are matched against citation titles and source-path file
names after Unicode normalization. Exact matches are preferred. A deterministic
title-similarity fallback uses a threshold of `0.65`; every fallback match
records its source pair, method, and similarity score for audit.

`source_match` remains in the report for backward compatibility and now equals
deterministic expected-source recall. Matched sources, missing sources, and
match details are recorded separately. Precision is intentionally omitted
because the question bank does not exhaustively label every relevant source.

## Judge output

The v2 report adds:

- `claim_assessments`, including support status and evidence chunk IDs
- `missing_required_facts`
- deterministic `retrieval` metrics
- Judge `confidence`
- `review_status` and `secondary_verdict`
- complete primary, secondary, and adjudication assessments when applicable
- `needs_human_review`

The comparison CSV exports the same fields. The report identifies this contract
as `knowledge-answer-judge-v2` with `schemaVersion` set to
`golden-baseline-v2`.

## Evaluation capability

`/agent/evaluation/chat` is disabled unless `GOLDEN_EVALUATION_TOKEN` is
configured. It requires that token as a Bearer credential, and the token must
differ from `AGENT_SERVICE_TOKEN`. The ordinary `/agent/chat` route rejects the
reserved internal evaluation channel, so caller-controlled channel values
cannot enable full evidence.

## Reliability boundaries

- Schema and evidence-reference failures retry up to three total attempts.
- Provider transport retries remain bounded by the model adapter.
- Independent review improves consistency but does not replace calibration
  against a human-labelled set.
- Title similarity is a fallback for the current label-only question bank.
  Stable source identifiers should replace it when the bank schema supports
  source IDs.
