# Console Frontend (React `/console-v2`)

Source for the AI Ops Workflow Console. Production assets are built into:

`agent_service/src/ai_ops_backoffice/static/console-v2/`

Do not edit that static directory by hand.

## Develop

```bash
cd console_frontend
npm ci
npm test
npm run dev
```

Vite proxies `/api` to the local Backoffice BFF (`http://127.0.0.1:8092`).

## Production build / sync

From the repository root:

```bash
python3 scripts/sync_console_v2.py --write
```

This runs `npm run build` (TypeScript + Vite) and refreshes hashed assets under
`static/console-v2/`. Commit those files with the frontend source change when
the Backoffice image or non-Docker local serve path needs an updated bundle.

`Dockerfile.backoffice` also rebuilds from `console_frontend/` and copies the
fresh artifacts into the image; the committed bundle keeps non-Docker runs and
tests aligned.

## CI freshness

```bash
python3 scripts/sync_console_v2.py --check
```

CI rebuilds into a temporary directory and compares paths plus SHA-256 digests
against the committed `static/console-v2` tree. Drift fails the
`console-frontend` job.
