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

# Ayekoo needs two GGUF models, both run through llama.cpp:
#   1. the generation model, which writes the answer
#   2. a small embedding model, which finds the corpus passages to answer from
# Retrieval is not optional here — without the embedding model the assistant has
# nothing to ground answers in — so both are fetched by this script.

GEN_NAME="qwen2.5-0.5b-instruct-q4_k_m.gguf"
GEN_URL="https://huggingface.co/nogasante/ayekoo-gguf/resolve/main/$GEN_NAME"
GEN_SHA256="74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"
GEN_BYTES=491400032

EMB_NAME="bge-small-en-v1.5-f16.gguf"
EMB_URL="https://huggingface.co/nogasante/ayekoo-gguf/resolve/main/$EMB_NAME"
# Upstream fallback, used only if the primary mirror is unavailable.
EMB_URL_FALLBACK="https://huggingface.co/CompendiumLabs/bge-small-en-v1.5-gguf/resolve/main/$EMB_NAME"
EMB_SHA256="f0b2fef971e8366438bfd2d9aefea1b0115919389448806d290237f638bae999"
EMB_BYTES=67308128

# Kept for backwards compatibility with the single-model layout.
MODEL_NAME="$GEN_NAME"
MODEL_FILE="$MODEL_DIR/$GEN_NAME"

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


download_to() {
  local url="$1" dest="$2"
  if command -v curl > /dev/null 2>&1; then
    # -C - resumes a partial file rather than restarting from zero, which
    # matters on an unreliable connection; --retry-delay backs off between
    # attempts.
    curl -L --fail --retry 8 --retry-delay 3 --retry-all-errors -C - --progress-bar \
      -o "$dest" "$url"
  elif command -v wget > /dev/null 2>&1; then
    wget --tries=8 --continue --show-progress -O "$dest" "$url"
  else
    echo "error: neither curl nor wget found" >&2
    return 1
  fi
}

# fetch <name> <url> <fallback-url|-> <sha256> <bytes> <human-size>
fetch() {
  local name="$1" url="$2" fallback="$3" want_sha="$4" want_bytes="$5" human="$6"
  local dest="$MODEL_DIR/$name"

  if [[ -f "$dest" ]]; then
    if [[ "$(sha256_of "$dest")" == "$want_sha" ]]; then
      echo "already present and verified: $name"
      return 0
    fi
    echo "$name failed checksum — re-downloading" >&2
    rm -f "$dest"
  fi

  mkdir -p "$MODEL_DIR"
  echo "downloading $name ($human) …"
  if ! download_to "$url" "$dest.partial"; then
    if [[ "$fallback" != "-" ]]; then
      echo "primary source failed, trying upstream fallback …" >&2
      rm -f "$dest.partial"
      download_to "$fallback" "$dest.partial" || return 1
    else
      return 1
    fi
  fi

  local got_bytes got_sha
  got_bytes="$(size_of "$dest.partial")"
  if [[ "$got_bytes" != "$want_bytes" ]]; then
    rm -f "$dest.partial"
    echo "error: $name size mismatch — got $got_bytes, expected $want_bytes" >&2
    return 1
  fi

  got_sha="$(sha256_of "$dest.partial")"
  if [[ "$got_sha" != "$want_sha" ]]; then
    rm -f "$dest.partial"
    echo "error: $name checksum mismatch" >&2
    echo "  expected $want_sha" >&2
    echo "  got      $got_sha" >&2
    return 1
  fi

  mv "$dest.partial" "$dest"
  echo "done: $name (sha256 verified)"
}

fetch "$GEN_NAME" "$GEN_URL" "-"                 "$GEN_SHA256" "$GEN_BYTES" "469 MiB"
fetch "$EMB_NAME" "$EMB_URL" "$EMB_URL_FALLBACK" "$EMB_SHA256" "$EMB_BYTES" "64 MiB"

echo
echo "all models present in $MODEL_DIR"
