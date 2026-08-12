"""Build the retrieval index: chunk the corpus, embed it, write it to disk.

    python -m ayekoo.index

Embeddings run through llama.cpp (via llama-cpp-python bindings) using
bge-small-en-v1.5. llama.cpp is the only inference runtime in this submission —
no second stack — which keeps the "llama.cpp only" rule unambiguous and avoids
installing multi-gigabyte frameworks on an 8 GB machine.

Writes to index/:
    chunks.jsonl    chunk text + provenance, one JSON object per line
    vectors.npy     float32 [n_chunks, dim], L2-normalised, row i <-> line i
    manifest.json   what built it, so a stale index is detectable
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import yaml

from .chunker import build_all

ROOT = Path(__file__).resolve().parent.parent
CORPUS_TEXT = ROOT / "corpus" / "text"
SOURCES = ROOT / "corpus" / "sources.yaml"
INDEX = ROOT / "index"
EMBED_MODEL = ROOT / "model" / "bge-small-en-v1.5-f16.gguf"

# bge asks for an instruction prefix on queries but not on passages. Getting
# this backwards quietly costs retrieval quality, so both live here together.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
BATCH = 16


def load_embedder():
    from llama_cpp import Llama

    if not EMBED_MODEL.exists():
        sys.exit(f"embedding model missing: {EMBED_MODEL}\nrun: bash download_model.sh")
    return Llama(
        model_path=str(EMBED_MODEL),
        embedding=True,
        n_ctx=512,
        n_threads=4,
        verbose=False,
    )


def embed_texts(llm, texts: list[str]) -> np.ndarray:
    """Embed a list of texts, L2-normalised so dot product == cosine."""
    vecs: list[np.ndarray] = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start : start + BATCH]
        out = llm.create_embedding(batch)
        for row in out["data"]:
            emb = np.asarray(row["embedding"], dtype=np.float32)
            # llama.cpp returns token-level embeddings for some models; mean-pool
            # when that happens so we always end up with one vector per text.
            if emb.ndim == 2:
                emb = emb.mean(axis=0)
            norm = np.linalg.norm(emb)
            vecs.append(emb / norm if norm > 0 else emb)
        print(f"  embedded {min(start + BATCH, len(texts))}/{len(texts)}", end="\r")
    print()
    return np.vstack(vecs)


def embed_query(llm, question: str) -> np.ndarray:
    return embed_texts(llm, [QUERY_PREFIX + question])[0]


def main() -> int:
    sources = yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["sources"]
    chunks = build_all(CORPUS_TEXT, sources)
    if not chunks:
        sys.exit("no chunks produced — is corpus/text/ populated? run corpus/fetch_sources.py")

    print(f"chunked {len(set(c.source_id for c in chunks))} documents into {len(chunks)} chunks")
    lengths = [len(c.text) for c in chunks]
    print(f"  chunk chars: min {min(lengths)}, median {int(np.median(lengths))}, max {max(lengths)}")
    ghana = sum(1 for c in chunks if c.ghana_specific)
    print(f"  {ghana}/{len(chunks)} chunks from Ghana-specific sources")

    llm = load_embedder()
    vectors = embed_texts(llm, [c.text for c in chunks])

    INDEX.mkdir(exist_ok=True)
    with (INDEX / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c.as_dict(), ensure_ascii=False) + "\n")
    np.save(INDEX / "vectors.npy", vectors)
    (INDEX / "manifest.json").write_text(
        json.dumps(
            {
                "n_chunks": len(chunks),
                "dim": int(vectors.shape[1]),
                "embed_model": EMBED_MODEL.name,
                "query_prefix": QUERY_PREFIX,
                "sources": sorted({c.source_id for c in chunks}),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote index/: {len(chunks)} chunks, dim {vectors.shape[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
