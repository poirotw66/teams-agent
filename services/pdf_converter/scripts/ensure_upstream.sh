#!/usr/bin/env bash
# Clone / sync poirotw66/pdf-to-markdown-converter for local Gemini Vision mode.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONVERTER_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
UPSTREAM_DIR="${PDF_CONVERTER_UPSTREAM_DIR:-${CONVERTER_DIR}/upstream}"
UPSTREAM_REPO="${PDF_CONVERTER_UPSTREAM_REPO:-https://github.com/poirotw66/pdf-to-markdown-converter.git}"
UPSTREAM_REF="${PDF_CONVERTER_UPSTREAM_REF:-main}"

log() {
  printf '[pdf-converter] %s\n' "$*" >&2
}

fail() {
  printf '[pdf-converter] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "找不到必要指令：$1"
}

require_command git
require_command uv

if [[ ! -d "${UPSTREAM_DIR}/.git" ]]; then
  log "Clone upstream converter → ${UPSTREAM_DIR}"
  rm -rf "${UPSTREAM_DIR}"
  git clone --depth 1 --branch "${UPSTREAM_REF}" "${UPSTREAM_REPO}" "${UPSTREAM_DIR}"
else
  log "Upstream checkout 已存在：${UPSTREAM_DIR}"
  if [[ "${PDF_CONVERTER_UPSTREAM_UPDATE:-false}" == "true" ]]; then
    log "更新 upstream（${UPSTREAM_REF}）…"
    git -C "${UPSTREAM_DIR}" fetch --depth 1 origin "${UPSTREAM_REF}"
    git -C "${UPSTREAM_DIR}" checkout -q FETCH_HEAD
  fi
fi

[[ -f "${UPSTREAM_DIR}/pyproject.toml" ]] || fail "upstream 缺少 pyproject.toml"
[[ -d "${UPSTREAM_DIR}/app" ]] || fail "upstream 缺少 app/"

log "uv sync upstream 依賴…"
(
  cd "${UPSTREAM_DIR}"
  if [[ -f uv.lock ]]; then
    uv sync --frozen || uv sync
  else
    uv sync
  fi
)

printf '%s\n' "${UPSTREAM_DIR}"
