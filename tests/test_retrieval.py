"""Retrieval-quality checks that do not need the generation model.

    python -m tests.test_retrieval

Separated from the grounding test on purpose: this runs in seconds, so
retrieval can be tuned without waiting on a 0.5B model to write prose. Most
bad answers in a RAG system are bad retrievals wearing a disguise, and this is
where you see that directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ayekoo.aliases import ALIASES, expand, verify
from ayekoo.index import embed_query, load_embedder
from ayekoo.retrieve import Retriever

ROOT = Path(__file__).resolve().parent.parent

# (question, terms we expect to see in at least one retrieved passage)
# The expectations are deliberately about vocabulary, not about correctness of
# the agronomy — asserting the latter would mean encoding facts here, which is
# exactly what we do not do without a human audit.
CASES: list[tuple[str, list[str]]] = [
    ("When should I plant maize in the Northern Region?", ["plant", "maize"]),
    ("What spacing for maize?", ["spacing", "cm"]),
    ("capsid is destroying my cocoa", ["mirid", "capsid"]),
    ("army worm dey chop my maize", ["armyworm"]),
    ("what is kokoo kokoram", ["canker"]),
    ("how do I store yam after harvest", ["yam", "stor"]),
    ("my cassava leaves are curling and yellow", ["mosaic", "cassava"]),
    ("black sigatoka on my plantain", ["sigatoka"]),
    ("which maize variety should I plant in Ghana", ["variety", "maize"]),
    ("how much fertilizer for yam", ["fertiliz", "yam"]),
]


def main() -> int:
    problems = 0

    missing = verify(ROOT / "corpus" / "text")
    print(f"alias map: {len(ALIASES)} entries, uncorroborated targets: {missing or 'none'}")
    if missing:
        problems += 1

    retriever = Retriever()
    print(f"index: {len(retriever.chunks)} chunks\n")
    llm = load_embedder()

    for question, expected in CASES:
        hits = retriever.search(question, embed_query(llm, question), top_k=4)
        blob = " ".join(h.chunk["text"].lower() for h in hits)
        found = [t for t in expected if t.lower() in blob]
        ok = len(found) == len(expected)
        status = "PASS" if ok else "MISS"
        if not ok:
            problems += 1

        top = hits[0] if hits else None
        print(f"{status}  {question}")
        if top:
            gh = "GH" if top.chunk.get("ghana_specific", True) else "reg"
            print(
                f"      score={top.score:.4f} [{gh}] {top.chunk['attribution'][:62]}"
                f"  (dense={top.dense_rank}, bm25={top.lexical_rank})"
            )
        if not ok:
            print(f"      expected terms not retrieved: {set(expected) - set(found)}")
            exp = expand(question)
            if exp != question:
                print(f"      expanded query was: {exp[:110]}")
        print()

    print("=" * 70)
    print("all retrieval checks passed" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
