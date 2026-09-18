# Generated API types

TypeScript schema types generated from the canonical Backoffice OpenAPI document.

**Do not edit files in this directory by hand.**

## Regenerate

```bash
PYTHONPATH=agent_service/src uv run python scripts/snapshot_openapi.py --write
PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --write
```

## CI freshness check

```bash
PYTHONPATH=agent_service/src uv run python scripts/generate_openapi_ts.py --check
```

Import example:

```ts
import type { WorkItemsResponse } from './generated/backoffice-schemas';
```
