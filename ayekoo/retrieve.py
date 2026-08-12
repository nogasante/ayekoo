"""Hybrid retrieval over the Ayekoo index: dense embeddings + BM25.

Why both. Dense embeddings handle the way a farmer actually phrases a question
("my cassava leaves are curling") against the way a manual writes it ("cassava
mosaic disease symptoms include leaf distortion"). BM25 handles the opposite
failure: exact tokens that embeddings blur — variety names like "Obatanpa",
fertilizer codes like "NPK 15-15-15", spacings like "75cm". Agronomy answers
live or die on those exact strings, so a purely semantic index would be a
mistake here.

Scores are combined with Reciprocal Rank Fusion, which needs no score
calibration between the two very different scales.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .aliases import expand

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "index"

RRF_K = 60  # standard RRF damping constant
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9./-]*")


SUBTOKEN_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?")


def tokenize(text: str) -> list[str]:
    """Lowercase tokens, emitting compound agronomic strings *and* their parts.

    The corpus is full of tokens like `9kg/acre`, `75cm` and `15-15-15`. Kept
    whole, they are invisible to a farmer asking about "acre" or "cm" — which
    is a real miss we hit: the MoFA maize guide states "Plant 9kg/acre for OPV's"
    and a question about seed rate per acre did not retrieve it, because
    `9kg/acre` and `acre` were different tokens with nothing in common.

    So we emit both: the compound (so exact queries still score highly) and its
    alphabetic/numeric parts (so ordinary words reach it).
    """
    out: list[str] = []
    for token in TOKEN_RE.findall(text.lower()):
        out.append(token)
        parts = SUBTOKEN_RE.findall(token)
        if len(parts) > 1:
            out.extend(parts)
    return out


@dataclass
class Hit:
    chunk: dict
    score: float
    dense_rank: int | None
    lexical_rank: int | None

    @property
    def attribution(self) -> str:
        return self.chunk["attribution"]


# Subjects a question can be *about*. A source that declares one of these and a
# question that names a different one are talking past each other.
SUBJECT_TERMS = {
    "poultry": ("chicken", "chickens", "poultry", "fowl", "cockerel", "hen", "hens", "layer", "broiler"),
    "goat": ("goat", "goats"),
    "sheep": ("sheep", "ram", "ewe", "lamb"),
    "cattle": ("cattle", "cow", "cows", "bull", "calf"),
    "maize": ("maize", "corn"),
    "cassava": ("cassava",),
    "yam": ("yam", "yams"),
    "cocoa": ("cocoa",),
    "tomato": ("tomato", "tomatoes"),
    "plantain": ("plantain", "plantains"),
    "rice": ("rice",),
}


def subjects_in(text: str) -> set[str]:
    low = f" {text.lower()} "
    found = set()
    for subject, terms in SUBJECT_TERMS.items():
        if any(f" {t} " in low or f" {t}," in low or f" {t}." in low for t in terms):
            found.add(subject)
    return found


class Retriever:
    def __init__(self) -> None:
        chunks_path = INDEX / "chunks.jsonl"
        if not chunks_path.exists():
            raise FileNotFoundError(
                f"no index at {INDEX} — run: python -m ayekoo.index"
            )
        self.chunks: list[dict] = [
            json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line
        ]
        self.vectors: np.ndarray = np.load(INDEX / "vectors.npy")
        if len(self.chunks) != self.vectors.shape[0]:
            raise ValueError(
                f"index is inconsistent: {len(self.chunks)} chunks vs "
                f"{self.vectors.shape[0]} vectors — rebuild it"
            )
        self._build_bm25()
        self._load_source_subjects()

    def _load_source_subjects(self) -> None:
        """Map each source id to the crops/livestock it declares in sources.yaml.

        Read at query time rather than baked into the chunks, so that changing
        it does not require re-embedding 5,900 chunks.
        """
        import yaml

        path = ROOT / "corpus" / "sources.yaml"
        self.source_subjects: dict[str, set[str]] = {}
        if not path.exists():
            return
        for src in yaml.safe_load(path.read_text(encoding="utf-8"))["sources"]:
            subjects = set(src.get("crops") or []) | set(src.get("livestock") or [])
            if subjects:
                self.source_subjects[src["id"]] = subjects

    # ── BM25 ──────────────────────────────────────────────────────────────────

    def _build_bm25(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.doc_tokens = [tokenize(c["text"]) for c in self.chunks]
        self.doc_len = np.array([len(t) for t in self.doc_tokens], dtype=np.float32)
        self.avg_len = float(self.doc_len.mean()) if len(self.doc_len) else 0.0
        self.tf: list[Counter] = [Counter(t) for t in self.doc_tokens]
        df: Counter = Counter()
        for toks in self.doc_tokens:
            df.update(set(toks))
        n = len(self.chunks)
        self.idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()
        }

    def _bm25_scores(self, query: str) -> np.ndarray:
        scores = np.zeros(len(self.chunks), dtype=np.float32)
        for term in tokenize(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.tf):
                freq = tf.get(term)
                if not freq:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * self.doc_len[i] / self.avg_len)
                scores[i] += idf * (freq * (self.k1 + 1)) / denom
        return scores

    # ── fusion ────────────────────────────────────────────────────────────────

    def search(
        self,
        question: str,
        query_vector: np.ndarray | None,
        top_k: int = 4,
        # How deep each ranker is consulted before fusion. Was 20, which was too
        # shallow: the passage naming Newcastle disease as the cause of "very
        # sudden, very high mortality" sat at dense rank 32 and never entered
        # the fusion at all, so a poultry question the corpus answers well came
        # back as "my sources do not cover this". Both rankers are already
        # computed over every chunk, so widening the window costs only a sort.
        candidates: int = 80,
        prefer_ghana: bool = True,
        max_per_source: int = 2,
    ) -> list[Hit]:
        # Expand only the lexical query: BM25 needs the document's vocabulary,
        # while the dense side is better served by the farmer's own phrasing.
        lex = self._bm25_scores(expand(question))
        lex_order = np.argsort(-lex)[:candidates]
        lex_rank = {int(idx): r for r, idx in enumerate(lex_order) if lex[idx] > 0}

        dense_rank: dict[int, int] = {}
        if query_vector is not None:
            sims = self.vectors @ query_vector
            for r, idx in enumerate(np.argsort(-sims)[:candidates]):
                dense_rank[int(idx)] = r

        fused: dict[int, float] = {}
        for idx, r in dense_rank.items():
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + r + 1)
        for idx, r in lex_rank.items():
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + r + 1)

        # Subject match. Without this, "my goat is sick" returned four chunks
        # from the village chicken manual and no goat content at all: the corpus
        # holds roughly ten times more poultry text than goat text, and RRF
        # rewards a document that appears mid-rank in BOTH rankers over one that
        # ranks first in only one. So a question naming an animal or crop lifts
        # sources about that subject and pushes down sources about a different
        # one. Sources that declare no subject (general agronomy, weather) are
        # left alone — they are often exactly what a broad question needs.
        asked_subjects = subjects_in(question)
        if asked_subjects:
            for idx in list(fused):
                declared = self.source_subjects.get(self.chunks[idx]["source_id"])
                if not declared:
                    continue
                if declared & asked_subjects:
                    fused[idx] *= 1.6
                else:
                    fused[idx] *= 0.4

        if prefer_ghana:
            # A mild nudge, not an override. Where a Ghanaian and a regional
            # source both match, the Ghanaian one should surface first — that is
            # the rule recorded in sources.yaml. Too large a bonus would bury
            # good agronomy that only exists in the regional manuals.
            for idx in list(fused):
                if self.chunks[idx].get("ghana_specific", True):
                    fused[idx] *= 1.15

        # Cap how many chunks any single document may contribute.
        #
        # "My chickens are dying suddenly" returned four chunks from the village
        # chicken manual — two of them noise, including a decision-tree table
        # that extracts as "yes yes No No" — while the Newcastle disease guide,
        # which is precisely about sudden poultry deaths, never appeared. The
        # manual is five times larger, so it simply has more chances to rank.
        # Spreading across documents gives the model corroboration from
        # independent sources instead of four views of one page.
        ordered: list[tuple[int, float]] = []
        per_source: Counter = Counter()
        for idx, score in sorted(fused.items(), key=lambda kv: -kv[1]):
            source = self.chunks[idx]["source_id"]
            if per_source[source] >= max_per_source:
                continue
            per_source[source] += 1
            ordered.append((idx, score))
            if len(ordered) >= top_k:
                break
        return [
            Hit(
                chunk=self.chunks[idx],
                score=score,
                dense_rank=dense_rank.get(idx),
                lexical_rank=lex_rank.get(idx),
            )
            for idx, score in ordered
        ]
