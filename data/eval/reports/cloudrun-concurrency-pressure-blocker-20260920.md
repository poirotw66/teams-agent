# Cloud Run concurrency pressure — 2026-09-20

## Target

- Service: `teams-rag-agent`
- Revision: `teams-rag-agent-00042-npc`
- URL: `https://teams-rag-agent-jt7pjdeeoa-de.a.run.app`
- Endpoint: `POST /agent/chat`
- Container concurrency setting: **8**
- Requests per level: **8**
- Query: `FortiClient VPN 連不上怎麼辦`

## Results

| Concurrency | OK | Errors | P50 (ms) | P95 (ms) | Throughput (rps) |
|---|---:|---:|---:|---:|---:|
| 1 | 8 | 0 | 6067 | 8583 | 0.18 |
| 4 | 8 | 0 | 2744 | 5992 | 0.80 |
| 8 | 8 | 0 | 2936 | 10139 | 0.67 |
| 16 | 8 | 0 | 3586 | 4912 | 1.55 |

Artifact: `data/eval/reports/cloudrun-concurrency-pressure-20260920.json`

## Notes

- Warm request succeeded (≈10.5s, likely cold path).
- Zero HTTP errors through concurrency 16 even though the service template caps container concurrency at 8 (Cloud Run scales instances).
- This is a short burst (8 requests/level), not a sustained soak. Use for capacity signal, not SLA certification.
