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
