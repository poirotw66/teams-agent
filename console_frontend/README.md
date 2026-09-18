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
tests aligned. That path remains the default same-origin product UI
(`/console-v2` + `/api` on one Backoffice service).

## Independent static image (Phase G)

Multi-stage Node build + nginx serves the same Vite base (`/console-v2/`)
without packaging the Python Backoffice. Build context is the repository root:

```bash
docker build -f console_frontend/Dockerfile -t ai-ops-console:latest .
docker run --rm -p 8088:8080 ai-ops-console:latest
# http://127.0.0.1:8088/console-v2/  (health: /healthz)
```

Compose reference:

```bash
docker compose -f deploy/docker-compose.console.yml up --build
```

Cloud Build reference (does not change Backoffice release wiring):

```bash
gcloud builds submit . --config=deploy/cloudbuild-console.yaml \
  --substitutions=_IMAGE=<registry>/ai-ops-console:<tag>
```

This image is assets-only: browser `/api` calls still need same-origin
Backoffice (or a reverse proxy). It does not enable legacy shell.

## CI freshness

```bash
python3 scripts/sync_console_v2.py --check
```

CI rebuilds into a temporary directory and compares paths plus SHA-256 digests
against the committed `static/console-v2` tree. Drift fails the
`console-frontend` job.
