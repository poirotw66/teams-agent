# Cloud Run RAG pressure-test matrix (Phase-2)

Formal concurrency decisions require longer runs than current ad-hoc samples.

## Matrix

| Concurrency | Min requests | Duration |
|---:|---:|---:|
| 1 | 200 | ≥5 min |
| 4 | 400 | ≥5 min |
| 8 | 800 | ≥10 min |
| 16 | 1,600 | ≥10 min |
| 32 | 3,200 | ≥10 min |

## Record per run

- instance count, CPU, memory, cold starts
- timeout / error rate
- TTFT (when streaming enabled) and full-response P50/P95/P99
- embedding / provider throttling signals
- cache hit rate split by repeated vs unique queries
- query-tier distribution and relevance LLM call / flip rates
- release ID, model, region

## Notes

- Do not use this matrix to pick Cloud Run concurrency until error rate and P99 are stable across the full duration.
- Keep unique-query and repeated-query workloads as separate passes so cache hit rate is interpretable.
- Prefer production-like region and model settings; label every report with git SHA and release ID.
