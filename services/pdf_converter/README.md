# PDF → Markdown Converter (Cloud Run)

Standalone service used by Knowledge Portal for BU PDF import.

Upstream capability source: [poirotw66/pdf-to-markdown-converter](https://github.com/poirotw66/pdf-to-markdown-converter)

## Modes

| Mode | How to run | Behavior |
|---|---|---|
| `gemini` (preferred) | `start.sh` when `GOOGLE_API_KEY` / `GEMINI_API_KEY` is set | Clones upstream into `upstream/` and runs **PyMuPDF + Gemini Vision** |
| `legacy` | Fallback shim in this folder | Text-PDF extraction only |
| `auto` (default in `start.sh`) | — | `gemini` if API key present, else `legacy` |
| Cloud Run upstream image | `Dockerfile.upstream` | Same Gemini Vision stack for production |

## Local run (Gemini Vision via start.sh)

`./start.sh` will:

1. Detect `GEMINI_API_KEY` / `GOOGLE_API_KEY` from `agent_service/.env`
2. Clone [poirotw66/pdf-to-markdown-converter](https://github.com/poirotw66/pdf-to-markdown-converter) into `services/pdf_converter/upstream/` (gitignored)
3. Start it on port **8095**
4. Point Portal at `KNOWLEDGE_PORTAL_PDF_CONVERTER_URL=http://127.0.0.1:8095` with `KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE=gemini_vision`

Requirements:

- `uv`, `git`, `poppler` (`brew install poppler`)
- A valid Gemini API key

Force modes:

```bash
PDF_CONVERTER_MODE=gemini ./start.sh   # require Vision stack
PDF_CONVERTER_MODE=legacy ./start.sh   # force text-only shim
```

Refresh upstream checkout:

```bash
PDF_CONVERTER_UPSTREAM_UPDATE=true ./start.sh
# or
./services/pdf_converter/scripts/ensure_upstream.sh
```

## Local run (legacy shim only)

```bash
cd services/pdf_converter
pip install -e .
PDF_CONVERTER_MODE=legacy uvicorn app.main:app --reload --port 8095
```

## Wire Knowledge Portal

```bash
export KNOWLEDGE_PORTAL_PDF_CONVERTER_URL=http://127.0.0.1:8095
export KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE=gemini_vision
export KNOWLEDGE_PORTAL_PDF_CONVERTER_TOKEN=  # optional shared bearer
export KNOWLEDGE_PORTAL_PDF_SYNC_MAX_BYTES=5242880
export KNOWLEDGE_PORTAL_PDF_SYNC_MAX_PAGES=20
```

## Cloud Run (recommended production)

1. Build upstream image:
   ```bash
   gcloud builds submit services/pdf_converter \
     --config=/dev/stdin <<'EOF'
   steps:
   - name: gcr.io/cloud-builders/docker
     args: ['build', '-f', 'Dockerfile.upstream', '-t', '$_IMAGE', '.']
   images: ['$_IMAGE']
   EOF
   ```
2. Deploy with `GOOGLE_API_KEY` secret and optional `PDF_CONVERTER_TOKEN`.
3. Set Portal env:
   - `KNOWLEDGE_PORTAL_PDF_CONVERTER_URL` → service URI
   - `KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE=gemini_vision`
4. Keep the service **internal / IAM-authenticated** when possible; do not expose publicly without a token.

## Contract

`POST /api/v1/convert-pdf` multipart:

- `file`: PDF bytes
- `prompt_template`: e.g. `slide`

JSON response (preferred):

```json
{
  "markdown": "# Title\n\n...",
  "page_count": 3,
  "warnings": [],
  "assets": [{"filename": "p01.png", "content_base64": "..."}]
}
```
