"""Patch upstream PDFParser to honor GEMINI_API_BACKEND."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "teams-agent-gemini-backend-patch"
NEEDLE = "self.client = genai.Client(api_key=api_key_to_use.strip())"
API_KEY_GATE_NEEDLE = (
    '"API key is required. Please provide your Google Gemini API key in "'
)


def _helper_source() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        here.parents[1] / "patches" / "gemini_backend_client.py",
        here.parent / "gemini_backend_client.py",
        Path("/tmp/gemini_backend_client.py"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("gemini_backend_client.py not found next to the patch script")


def apply_patch(upstream_dir: Path) -> None:
    parser_path = upstream_dir / "src" / "utils" / "pdf_parser.py"
    if not parser_path.is_file():
        raise SystemExit(f"upstream pdf_parser.py not found: {parser_path}")

    helper_src = _helper_source()
    helper_dest = upstream_dir / "src" / "utils" / "gemini_backend_client.py"
    shutil.copy2(helper_src, helper_dest)

    text = parser_path.read_text(encoding="utf-8")
    if MARKER in text:
        _patch_convert_api_key_gate(upstream_dir)
        return
    if NEEDLE not in text:
        raise SystemExit(
            "upstream pdf_parser.py no longer constructs genai.Client(api_key=...). "
            "Update services/pdf_converter/scripts/apply_gemini_backend_patch.py."
        )

    import_line = "from src.utils.gemini_backend_client import build_genai_client  # teams-agent-gemini-backend-patch\n"
    if "from src.utils.prompts import" in text:
        text = text.replace(
            "from src.utils.prompts import",
            import_line + "from src.utils.prompts import",
            1,
        )
    else:
        text = import_line + text

    old_block = (
        "        api_key_to_use = api_key if api_key and api_key.strip() else settings.google_api_key\n"
        '        if not api_key_to_use or not api_key_to_use.strip():\n'
        '            raise ValueError("Google Gemini API key is required. Please provide api_key parameter or set GOOGLE_API_KEY in environment.")\n'
        "        self.gemini_model = resolve_gemini_model(gemini_model)\n"
        "        \n"
        "        if USE_GOOGLE_GENAI_SDK:\n"
        "            self.client = genai.Client(api_key=api_key_to_use.strip())\n"
    )
    new_block = (
        "        # teams-agent-gemini-backend-patch\n"
        "        api_key_to_use = api_key if api_key and api_key.strip() else settings.google_api_key\n"
        "        self.gemini_model = resolve_gemini_model(gemini_model)\n"
        "        \n"
        "        if USE_GOOGLE_GENAI_SDK:\n"
        "            self.client = build_genai_client(genai, fallback_api_key=api_key_to_use)\n"
    )
    if old_block in text:
        text = text.replace(old_block, new_block, 1)
    else:
        text = text.replace(
            NEEDLE,
            "self.client = build_genai_client(genai, fallback_api_key=api_key_to_use)  # teams-agent-gemini-backend-patch",
            1,
        )
        text = text.replace(
            'raise ValueError("Google Gemini API key is required. Please provide api_key parameter or set GOOGLE_API_KEY in environment.")',
            "pass  # teams-agent-gemini-backend-patch: backend factory validates credentials",
            1,
        )
    parser_path.write_text(text, encoding="utf-8")
    _patch_convert_api_key_gate(upstream_dir)


def _patch_convert_api_key_gate(upstream_dir: Path) -> None:
    """Vertex revisions must not 400 before the dual-mode parser runs."""
    api_path = upstream_dir / "app" / "api" / "pdf_convert.py"
    if not api_path.is_file():
        raise SystemExit(f"upstream pdf_convert.py not found: {api_path}")
    text = api_path.read_text(encoding="utf-8")
    if MARKER in text:
        return
    if API_KEY_GATE_NEEDLE not in text:
        raise SystemExit(
            "upstream pdf_convert.py no longer rejects a missing API key. "
            "Update services/pdf_converter/scripts/apply_gemini_backend_patch.py."
        )
    old_gate = (
        "    if not api_key_to_use:\n"
        "        service_metrics.increment(\"conversion_rejected_total\")\n"
        "        raise HTTPException(\n"
        "            status_code=400,\n"
        "            detail=(\n"
        "                \"API key is required. Please provide your Google Gemini API key in \"\n"
        "                \"the form or set GOOGLE_API_KEY in environment variables.\"\n"
        "            ),\n"
        "        )\n"
    )
    new_gate = (
        "    from src.utils.gemini_backend_client import (\n"
        "        VERTEX_AI,\n"
        "        resolve_backend,\n"
        "    )  # teams-agent-gemini-backend-patch\n"
        "    if not api_key_to_use and resolve_backend() != VERTEX_AI:\n"
        "        service_metrics.increment(\"conversion_rejected_total\")\n"
        "        raise HTTPException(\n"
        "            status_code=400,\n"
        "            detail=(\n"
        "                \"API key is required. Please provide your Google Gemini API key in \"\n"
        "                \"the form or set GOOGLE_API_KEY in environment variables.\"\n"
        "            ),\n"
        "        )\n"
    )
    if old_gate not in text:
        raise SystemExit(
            "upstream pdf_convert.py API-key gate block did not match. "
            "Update services/pdf_converter/scripts/apply_gemini_backend_patch.py."
        )
    api_path.write_text(text.replace(old_gate, new_gate, 1), encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_gemini_backend_patch.py UPSTREAM_DIR")
    apply_patch(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
