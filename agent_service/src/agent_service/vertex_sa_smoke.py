"""Vertex SA smoke preflight and optional live chat/embedding probe.

Requires explicit ``VERTEX_AI_PROJECT`` (or a single ``GCP_PROJECT_ID`` /
``GOOGLE_CLOUD_PROJECT``) plus ``VERTEX_AI_CHAT_LOCATION`` and
``VERTEX_AI_EMBEDDING_LOCATION``. The unapproved P0 placeholder ``global``
is rejected. Refuses when ``GEMINI_API_KEY`` or ``GOOGLE_API_KEY`` is
already in the process environment. Does not load ``.env`` so leftover
Developer API keys cannot enter the process.

Live requests go through ``build_chat_model`` / ``build_embeddings``.
Skip and fail both exit non-zero. Classified errors never include secrets.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from os import environ

from .gemini_backend import (
    GeminiApiBackend,
    GeminiBackendConfig,
    GeminiConfigurationError,
    assert_vertex_process_has_no_api_keys,
    present_developer_api_key_names,
    resolve_gemini_backend,
)
from .gemini_errors import classify_gemini_error, safe_gemini_error_text

__all__ = [
    "DEFAULT_CHAT_MODEL",
    "DEFAULT_EMBEDDING_MODEL",
    "EXIT_FAIL",
    "EXIT_OK",
    "EXIT_SKIP",
    "main",
    "preflight_vertex_sa_smoke",
    "run_live_vertex_sa_smoke",
]

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_SKIP = 2
DEFAULT_CHAT_MODEL = "google_genai:gemini-3.8-flash"
DEFAULT_EMBEDDING_MODEL = "google_genai:gemini-embedding-2"
_LIVE_CHAT_PROMPT = "Reply with the single word ok."
_LIVE_EMBED_QUERY = "ok"


def preflight_vertex_sa_smoke(
    *,
    environ_map: Mapping[str, str] | None = None,
) -> GeminiBackendConfig:
    """Validate Vertex SA process env. No dotenv load and no network I/O."""
    env = environ if environ_map is None else environ_map
    present = present_developer_api_key_names(environ_map=env)
    if present:
        raise GeminiConfigurationError(
            "VERTEX_AI refuses Gemini/Google API keys in the process environment "
            f"({', '.join(present)}). Unset them before constructing Gemini clients."
        )
    raw_backend = (env.get("GEMINI_API_BACKEND") or "").strip()
    if raw_backend and raw_backend != GeminiApiBackend.VERTEX_AI.value:
        raise GeminiConfigurationError(
            "vertex_sa_smoke requires GEMINI_API_BACKEND=VERTEX_AI or unset; "
            f"got {raw_backend!r}."
        )
    if environ_map is None:
        environ["GEMINI_API_BACKEND"] = GeminiApiBackend.VERTEX_AI.value
        assert_vertex_process_has_no_api_keys()
        return resolve_gemini_backend()

    forced = dict(environ_map)
    forced["GEMINI_API_BACKEND"] = GeminiApiBackend.VERTEX_AI.value
    assert_vertex_process_has_no_api_keys(environ_map=forced)
    return resolve_gemini_backend(environ_map=forced)


def run_live_vertex_sa_smoke(
    config: GeminiBackendConfig,
    *,
    chat_model: str = DEFAULT_CHAT_MODEL,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> None:
    """Send one chat and one embedding request through production factories."""
    from .gemini_clients import build_embeddings
    from .graph import build_chat_model

    _apply_resolved_backend_to_process(config)
    chat = build_chat_model(chat_model)
    if chat is None:
        raise GeminiConfigurationError(f"build_chat_model returned None for {chat_model}.")
    embeddings = build_embeddings(embedding_model)
    if embeddings is None:
        raise GeminiConfigurationError(
            f"build_embeddings returned None for {embedding_model}."
        )
    chat.invoke(_LIVE_CHAT_PROMPT)
    vector = embeddings.embed_query(_LIVE_EMBED_QUERY)
    if not isinstance(vector, list) or not vector:
        raise GeminiConfigurationError("Vertex embedding probe returned an empty vector.")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = preflight_vertex_sa_smoke()
    except GeminiConfigurationError as error:
        _print_classified(error, stage="preflight")
        return EXIT_SKIP
    if args.preflight_only:
        _print_preflight_ok(config)
        return EXIT_OK
    try:
        run_live_vertex_sa_smoke(
            config,
            chat_model=args.chat_model,
            embedding_model=args.embedding_model,
        )
    except Exception as error:  # noqa: BLE001 - CLI process boundary
        _print_classified(error, stage="live")
        return EXIT_FAIL
    print(
        "vertex_sa_smoke: live chat and embedding probes succeeded "
        f"project_set=true chat_location={config.chat_location} "
        f"embedding_location={config.embedding_location}"
    )
    return EXIT_OK


def _apply_resolved_backend_to_process(config: GeminiBackendConfig) -> None:
    environ["GEMINI_API_BACKEND"] = GeminiApiBackend.VERTEX_AI.value
    if config.vertex_project:
        environ["VERTEX_AI_PROJECT"] = config.vertex_project
    if config.chat_location:
        environ["VERTEX_AI_CHAT_LOCATION"] = config.chat_location
    if config.embedding_location:
        environ["VERTEX_AI_EMBEDDING_LOCATION"] = config.embedding_location


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vertex SA smoke using production Gemini factories."
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate project/locations and refuse keys; do not send a live request.",
    )
    parser.add_argument("--chat-model", default=DEFAULT_CHAT_MODEL)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    return parser.parse_args(argv)


def _print_classified(error: BaseException, *, stage: str) -> None:
    error_class = classify_gemini_error(error)
    text = (
        str(error)
        if isinstance(error, GeminiConfigurationError)
        else safe_gemini_error_text(error)
    )
    print(f"vertex_sa_smoke: {stage} {error_class.value}: {text}", file=sys.stderr)


def _print_preflight_ok(config: GeminiBackendConfig) -> None:
    print(
        "vertex_sa_smoke: preflight ok "
        f"project_set={bool(config.vertex_project)} "
        f"chat_location_set={bool(config.chat_location)} "
        f"embedding_location_set={bool(config.embedding_location)}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
