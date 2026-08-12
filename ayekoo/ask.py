"""Ask Ayekoo a question and get a grounded, cited answer.

    python -m ayekoo.ask "When should I plant maize in the Northern Region?"

The whole design point: the model is not the source of truth, the corpus is.
The model's only job is to read retrieved passages and say what they contain,
in plain language, with the source named. If retrieval finds nothing relevant,
we do not ask the model at all — we say so. A 0.5B model asked an unsupported
question will confidently invent an answer, and with no human fact-checking in
the loop, an admitted gap is worth more than a fluent fabrication.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from . import extractive, verify
from .retrieve import Retriever

SERVER = "http://127.0.0.1:8080"

# Refusal gate. This MUST be absolute similarity, not the fused RRF score.
#
# RRF is built from ranks, and there is always a rank-0 document, so a fused
# score says which chunk matched best but nothing about whether anything matched
# at all. Measured on this corpus:
#
#     "How much fertilizer for yam?"           RRF 0.0358   cosine 0.84
#     "When should I plant maize up north?"    RRF 0.0349   cosine 0.76
#     "What is the capital city of Mongolia?"  RRF 0.0357   cosine 0.51
#
# The Mongolia question outranked a real farming question on RRF. Gating on it
# would have handed unsupported questions to a 0.5B model to improvise on —
# the exact failure mode the refusal path exists to prevent.
#
# Cosine separates in-scope (0.75+) from out-of-scope (0.51-0.59) cleanly.
# 0.65 sits in the empty band between them. Retune on day 9-10 against real
# questions; it is the single most safety-relevant number in the system.
MIN_COSINE = 0.65

# Note what this prompt does NOT ask for: citations.
#
# Instructing a 0.5B model to "put [1] after each fact" reliably collapses it
# into copying — it emits a numbered list of source fragments and then loops
# ("[4] 5.5-6.5cm" eleven times, observed). Attribution is therefore produced by
# the system, from the chunks we actually retrieved, which is both more reliable
# and more honest: a model citing [2] for a fact from [1] is false attribution,
# and false attribution is worse than none when nobody is checking.
SYSTEM_PROMPT = """You are Ayekoo, an assistant for farmers in Ghana.

Answer only from the sources given to you. Write your own short sentences —
never copy the source text, headings, or page numbers.

Copy numbers, dates and months exactly as the sources write them. Never change,
round, or convert them. Add nothing that is not in the sources.

If the sources do not answer the question, reply exactly:
My sources do not cover this."""

REFUSAL = (
    "My sources do not cover this. Ayekoo only answers from a fixed set of "
    "Ghanaian agricultural documents, and nothing in them addresses this question."
)


def build_prompt(question: str, hits) -> str:
    blocks = []
    for n, hit in enumerate(hits, 1):
        c = hit.chunk
        label = c["attribution"]
        if not c.get("ghana_specific", True):
            label += " [regional source, not Ghana-specific]"
        blocks.append(f"[{n}] {label}\n{c['text']}")
    sources = "\n\n".join(blocks)
    # Question first, sources second, an explicit `ANSWER:` cue last.
    #
    # Measured against the alternatives on this model: sources-first makes it
    # continue the source text instead of answering, and a few-shot example makes
    # it worse still — it copies the numbers out of the example ("28 kg/ha" for a
    # seed-rate question, a figure from nowhere). This ordering is what produced
    # clean prose: "open-pollinated maize is planted at 9kg/acre, hybrid maize at
    # 10kg/acre."
    return (
        f"QUESTION: {question}\n\n"
        f"SOURCES\n{sources}\n\n"
        "Write 2-4 short sentences answering the question, using only the sources "
        "above. Do not copy the sources. Keep every number and month exactly as "
        "written.\n\nANSWER:"
    )


_INPROC = None  # lazily-loaded in-process generation model


def _generate_in_process(system: str, user: str, max_tokens: int, temperature: float) -> str:
    """Run generation through the llama-cpp-python bindings, no server needed.

    The HTTP path is the primary one — llama-server keeps the model resident, so
    repeated questions do not pay the load cost. But requiring a separately
    compiled llama-server binary means `pip install -r requirements.txt` is not
    enough to run this repo, which is a poor experience for anyone evaluating it.
    Same llama.cpp underneath either way.
    """
    global _INPROC
    if _INPROC is None:
        from llama_cpp import Llama

        from .index import ROOT

        gen_model = ROOT / "model" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        if not gen_model.exists():
            sys.exit(f"generation model missing: {gen_model}\nrun: bash download_model.sh")
        _INPROC = Llama(
            model_path=str(gen_model),
            n_ctx=4096,
            n_threads=4,
            verbose=False,
            seed=42,
        )
    out = _INPROC.create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return out["choices"][0]["message"]["content"].strip()


def call_model(system: str, user: str, max_tokens: int = 320, temperature: float = 0.2) -> str:
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        # Low but not zero: greedy decoding on a 0.5B model tends to loop.
        "temperature": temperature,
        "cache_prompt": True,
    }
    req = urllib.request.Request(
        f"{SERVER}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.load(resp)
    except urllib.error.URLError:
        # No server running — fall back to loading the model in this process.
        return _generate_in_process(system, user, max_tokens, temperature)
    return body["choices"][0]["message"]["content"].strip()


def answer(question: str, top_k: int = 4, show_sources: bool = True) -> dict:
    from .index import embed_query, load_embedder

    retriever = Retriever()
    llm = load_embedder()
    qvec = embed_query(llm, question)
    hits = retriever.search(question, qvec, top_k=top_k)

    # Absolute semantic similarity of the best-matching chunk in the whole index,
    # independent of ranking. This is what decides whether we answer at all.
    best_cosine = float((retriever.vectors @ qvec).max()) if len(retriever.chunks) else 0.0

    if not hits or best_cosine < MIN_COSINE:
        return {
            "question": question,
            "answer": REFUSAL,
            "grounded": False,
            "hits": [],
            "best_cosine": round(best_cosine, 4),
            "top_score": hits[0].score if hits else 0.0,
        }

    # Precise-calendar questions are answered by quotation, not paraphrase.
    # See ayekoo/extractive.py: at this model size, paraphrasing a planting
    # window corrupts it ("End of May-early July" became "early May to end of
    # July"), and no verifier can catch that because every month present is
    # legitimately there.
    extracted = extractive.extract(question, hits, retriever)
    if extracted is not None:
        text, used = extracted
        return {
            "question": question,
            "answer": text,
            "mode": "extractive",
            "warning": None,
            "grounded": True,
            "top_score": hits[0].score,
            "best_cosine": round(best_cosine, 4),
            "hits": _hit_dicts(used),
        }

    prompt = build_prompt(question, hits)
    text = call_model(SYSTEM_PROMPT, prompt)

    # Every number and month in the answer must appear in the passages it was
    # generated from. This catches paraphrase-into-falsehood — the model once
    # turned "Early March-end of April" into "July through early August".
    retrieved_text = "\n".join(h.chunk["text"] for h in hits)
    verification = verify.check(text, retrieved_text, question)
    warning = verify.warning_for(verification)

    return {
        "question": question,
        "answer": text,
        "warning": warning,
        "verification": verification,
        "grounded": True,
        "top_score": hits[0].score,
        "best_cosine": round(best_cosine, 4),
        "hits": _hit_dicts(hits),
    }


def _hit_dicts(hits) -> list[dict]:
    return [
        {
            "n": n,
            "attribution": h.attribution,
            "source_id": h.chunk["source_id"],
            "ghana_specific": h.chunk.get("ghana_specific", True),
            "section": h.chunk.get("section"),
            "caveat": h.chunk.get("caveat"),
            "score": round(h.score, 5),
            "dense_rank": h.dense_rank,
            "lexical_rank": h.lexical_rank,
        }
        for n, h in enumerate(hits, 1)
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask Ayekoo a Ghanaian farming question.")
    ap.add_argument("question", nargs="+")
    ap.add_argument("--top-k", type=int, default=4)
    ap.add_argument("--json", action="store_true", help="emit the raw result as JSON")
    args = ap.parse_args()

    result = answer(" ".join(args.question), top_k=args.top_k)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"\nQ: {result['question']}\n")
    print(result["answer"])
    if result["hits"]:
        print("\nSources:")
        for h in result["hits"]:
            flag = "" if h["ghana_specific"] else "  (regional, not Ghana-specific)"
            print(f"  [{h['n']}] {h['attribution']}{flag}")
            if h["caveat"]:
                print(f"        caveat: {h['caveat'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
