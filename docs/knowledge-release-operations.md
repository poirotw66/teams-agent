# Knowledge release operations

Knowledge releases are independent from application images. Do not copy
`data/index`, `data/releases`, source documents, or embeddings into a Cloud Run
image.

## Production contract

The Portal builds an immutable directory:

```text
knowledge-releases/
  tenants/{tenantId}/releases/{releaseId}/
    manifest.json
    index/chunks.json
    sources/
    assets/
    original/
```

`manifest.json` records the release and tenant IDs, release purpose
(`PRODUCTION`, `E2E`, or `SHADOW`), plus the index SHA-256, byte size, chunk
count, vector count, embedding model, and dimensions. The Portal uploads every
object with the GCS `if_generation_match=0` precondition. An existing release
ID therefore cannot be overwritten.

The Firestore `knowledge_releases/{releaseId}` document stores the bucket,
object prefix, manifest generation, index generation, release status, document
manifest, ACL metadata, publisher, and timestamps. The
`knowledge_portal_config/active_release` document is the only active pointer.

The Agent resolves that pointer at startup, downloads the recorded generations
to its disposable cache, verifies the manifest and SHA-256, and then loads the
index into memory. Terraform enables strict checks: a release with zero chunks,
missing vectors, inconsistent dimensions, or a mismatched model/hash cannot
become ready. Production Portal and Agent processes both fail closed unless the
Firestore record and immutable manifest identify the release purpose as
`PRODUCTION`; legacy releases without purpose metadata are treated as
`UNKNOWN`.

## Initial migration order

1. Apply Terraform to create the private release bucket and grant the Agent
   `roles/storage.objectViewer`. Configure the Portal service account in
   `knowledge_release_writer_members`; it receives
   `roles/storage.objectCreator`, not object-admin.
2. Deploy the Portal with `KNOWLEDGE_PORTAL_RELEASE_GCS_BUCKET` and publish or
   reindex the complete corpus. Verify the Firestore release record contains
   non-null generations and the expected chunk/vector counts.
3. Deploy the Agent with `KNOWLEDGE_RELEASE_STORE_MODE=GCS`. Its `/readyz`
   response must report the expected release ID, `knowledgeIndexVerified=true`,
   equal chunk/vector counts, dimensions `3072`, and a non-null SHA-256.
4. Retry Portal-to-Agent synchronization if the first publish occurred before
   the GCS-capable Agent was deployed.
5. Remove any E2E release from the production Firestore active pointer. E2E
   artifacts may remain for tests, but are never included in image build
   context or selected by production configuration.

Rollback changes only the Firestore active pointer to a previously
Agent-verified immutable release with complete GCS generation, hash, and vector
metadata, then asks the Agent to reload it. GCS remains the rollback snapshot.

## Application releases

`deploy/release-gcp.sh` detects affected components or accepts an explicit
comma-separated `RELEASE_COMPONENTS` value (`agent`, `adapter`, `backoffice`,
`portal`). It submits one source context to Cloud Build. Selected images build
in parallel with registry-backed cache images, resolve to digests, and create
Cloud Run revisions in parallel. Smoke checks run after revisions are ready.

Knowledge-only changes should use the Portal publication flow and must not run
the application release script.

## MongoDB Atlas shadow evaluation

MongoDB is an optional spike and is not wired into production runtime.

```bash
cd agent_service
uv sync --extra mongodb-spike

MONGODB_URI='mongodb+srv://...' \
  .venv/bin/python ../scripts/mongodb_vector_spike.py \
  --index ../data/index/chunks.json \
  --tenant-id default \
  --release-id release-example \
  --print-index-definition

MONGODB_URI='mongodb+srv://...' \
  .venv/bin/python ../scripts/mongodb_vector_spike.py \
  --index ../data/index/chunks.json \
  --tenant-id default \
  --release-id release-example

MONGODB_URI='mongodb+srv://...' \
MONGODB_VECTOR_RELEASE_ID='release-example' \
  .venv/bin/python ../scripts/retrieval_ab_test.py \
  --backends hybrid,firestore,mongodb \
  --backend-monthly-cost-usd hybrid=0 \
  --backend-monthly-cost-usd mongodb=57 \
  --monthly-query-volume 100000
```

The same evaluation cases report recall, ACL accuracy, P95 latency, and
measured model/API query cost when a backend exposes it. Fixed backend
infrastructure cost is supplied explicitly from the current Atlas and Cloud Run
quotes; the result records both the monthly assumption and its amortized
per-query value. Omit an unknown cost instead of estimating it silently.
Firestore is reported as skipped for the current 3,072-dimensional vectors
because its supported dimension is lower; the harness does not fabricate a
comparison. Atlas queries are constrained by tenant, release, shadow status,
and ACL tokens. Start with shadow traffic; do not cut over until the recorded
quality, latency, and cost thresholds pass.
