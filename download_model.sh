#!/usr/bin/env bash
# Ayekoo — download the model weights.
#
# Rules (per the ADTC submission template):
#   - Idempotent: safe to run multiple times.
#   - No credentials: the source repo is public.
#   - Output path matches `_runtime.model_path` in metadata.json.
#
# This script verifies SHA256 after downloading. A truncated download that
# still "succeeds" is a real failure mode — we hit it during development — and
# a silently corrupt GGUF would fail at profiling time instead of here.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$HERE/model"
MODEL_NAME="qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_FILE="$MODEL_DIR/$MODEL_NAME"

MODEL_URL="https://huggingface.co/nogasante/ayekoo-gguf/resolve/main/$MODEL_NAME"
EXPECTED_SHA256="74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
EXPECTED_BYTES=491400032

# ── helpers ───────────────────────────────────────────────────────────────────

sha256_of() {
  if command -v sha256sum > /dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum > /dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    echo "error: neither sha256sum nor shasum found" >&2
    exit 1
  fi
}

size_of() {
  # stat is not portable between GNU and BSD; try both.
  stat -c %s "$1" 2> /dev/null || stat -f %z "$1"
}

# ── idempotency: a valid file already on disk is a no-op ──────────────────────

if [[ -f "$MODEL_FILE" ]]; then
  if [[ "$(sha256_of "$MODEL_FILE")" == "$EXPECTED_SHA256" ]]; then
    echo "model already present and verified: $MODEL_FILE"
    exit 0
  fi
  echo "existing file failed checksum — re-downloading" >&2
  rm -f "$MODEL_FILE"
fi

# ── download ──────────────────────────────────────────────────────────────────

mkdir -p "$MODEL_DIR"
echo "downloading $MODEL_NAME (469 MiB) …"

if command -v curl > /dev/null 2>&1; then
  # -C - resumes a partial file rather than restarting from zero, which matters
  # on an unreliable connection; --retry-delay backs off between attempts.
  curl -L --fail --retry 8 --retry-delay 3 --retry-all-errors -C - --progress-bar \
    -o "$MODEL_FILE.partial" "$MODEL_URL"
elif command -v wget > /dev/null 2>&1; then
  wget --tries=8 --continue --show-progress -O "$MODEL_FILE.partial" "$MODEL_URL"
else
  echo "error: neither curl nor wget found" >&2
  exit 1
fi

# ── verify before promoting the .partial file into place ──────────────────────

ACTUAL_BYTES="$(size_of "$MODEL_FILE.partial")"
if [[ "$ACTUAL_BYTES" != "$EXPECTED_BYTES" ]]; then
  rm -f "$MODEL_FILE.partial"
  echo "error: size mismatch — got $ACTUAL_BYTES bytes, expected $EXPECTED_BYTES" >&2
  exit 1
fi

ACTUAL_SHA256="$(sha256_of "$MODEL_FILE.partial")"
if [[ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]]; then
  rm -f "$MODEL_FILE.partial"
  echo "error: checksum mismatch" >&2
  echo "  expected $EXPECTED_SHA256" >&2
  echo "  got      $ACTUAL_SHA256" >&2
  exit 1
fi

mv "$MODEL_FILE.partial" "$MODEL_FILE"
echo "done: $MODEL_FILE"
echo "sha256 verified: $EXPECTED_SHA256"
