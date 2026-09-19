# Target package layout (docs/0919-arch.md)

This monorepo is converging toward an explicit uv workspace. Until packages
are physically moved, workspace members are:

- `.` — Teams Adapter (`teams-agent-backend`)
- `agent_service/` — Agent Runtime + AI Ops API + Knowledge Portal (still one
  wheel; Dockerfiles now install runtime-scoped extras only)

Intended end state (same Git repo, separate installable packages):

```text
packages/
  platform-kernel/
  operations-core/
  knowledge-core/

apps/
  agent-runtime/
  ai-ops-api/
  knowledge-portal/
  teams-adapter/
  console/
```

Do not split into multiple Git repositories.

In-tree shared libraries already exist under `agent_service/src/`:

- `platform_kernel/`
- `operations_core/`
- `knowledge_core/`
- `composition/`

Adapter-side Asset Gateway extraction: `src/citation_asset_gateway/`
(with `teams_agent` shims for stable imports).
