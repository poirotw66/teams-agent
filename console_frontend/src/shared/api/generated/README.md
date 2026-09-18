# Generated API types and client

TypeScript schema types and a typed HTTP client generated from the canonical Backoffice OpenAPI document.

**Do not edit files in this directory by hand.**

## Artifacts

- `backoffice-schemas.ts` — component schema types
- `backoffice-client.ts` — `backofficeClient` path/operation wrappers over `apiClient`

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
import { backofficeClient } from './generated/backoffice-client';
import type { WorkItemsResponse } from './generated/backoffice-schemas';

const res: WorkItemsResponse =
  await backofficeClient.list_work_items_api_console_work_items_get({
    query: { bucket: 'all', limit: 25 },
  });
```
