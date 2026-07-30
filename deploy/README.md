# GCP Cloud Run deployment

Default target:

```text
Project: itr-aimasteryhub-lab
Region: asia-east1
Agent: teams-rag-agent (private)
Adapter: teams-agent-adapter (public)
```

Deployed on 2026-07-30:

```text
Agent URL:   https://teams-rag-agent-jt7pjdeeoa-de.a.run.app
Adapter URL: https://teams-agent-adapter-jt7pjdeeoa-de.a.run.app
```

Deploy:

```bash
./deploy/deploy-gcp.sh
```

The script:

1. Enables required APIs.
2. Creates Artifact Registry and two service accounts.
3. Copies local secret values into Secret Manager without printing them.
4. Builds both Linux images in Cloud Build.
5. Deploys the private Agent and grants only the Adapter `run.invoker`.
6. Deploys the public Teams Adapter.
7. Configures the Adapter Cloud Run URL for signed RAG images.

After deployment, set Azure Bot Messaging endpoint to:

```text
https://<teams-agent-adapter-url>/api/messages
```

Current endpoint:

```text
https://teams-agent-adapter-jt7pjdeeoa-de.a.run.app/api/messages
```

Do not commit `.env`, `agent_service/.env`, credentials, or exported secrets.
