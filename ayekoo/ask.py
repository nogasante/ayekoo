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
import re
import sys
import urllib.error
import urllib.request

from . import banned, extractive, verify
from .retrieve import INDEX, Retriever

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

# The gate had an English-language bias, and fixing it took two attempts worth
# recording.
#
# "What is kokoo kokoram?" — the Twi name for cocoa stem canker — scored cosine
# 0.594 against this 0.65 gate and was refused, even though the chunk naming
# kokoo kokoram was rank 0 of 8,169. The embedding model is bge-small-en; a Twi
# phrase has no meaningful English embedding. A submission whose localisation
# claim rests on Ghanaian vocabulary must not refuse Ghanaian vocabulary.
#
# First attempt: also admit a question containing a rare word that occurs in the
# corpus. That failed on measurement. "Write me a Python function" scored cosine
# 0.595 and idf 8.09, against kokoo kokoram's 0.594 and 8.60 — indistinguishable.
# "Who won the world cup" scored a HIGHER cosine than the Twi query. No
# threshold on those two signals separates them.
#
# What works is translating the vernacular before embedding, using the same
# corpus-verified alias map that already serves BM25. Expanded, "kokoo kokoram"
# embeds at 0.784 because it now carries "stem canker" and "phytophthora" —
# terms the corpus actually uses. "Python function" and "Mongolia" contain no
# alias keys, are left untouched, and stay refused.

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

# Questions whose answer changes daily. A fixed set of documents cannot answer
# these however well retrieval scores, and the 2005 FAO fertilizer report does
# contain cedi-dollar figures, so retrieval scores them well: the exchange-rate
# question cleared the gate at 0.67 and the model produced "18" from nowhere.
LIVE_DATA = re.compile(
    r"\b(exchange rate|forex|interest rate|cedi to (the )?(dollar|usd|euro|pound)"
    r"|dollar rate|rate of the (cedi|dollar))\b", re.I
)


def coverage_line() -> str:
    """Describe what the corpus actually holds, read from the built index.

    Derived rather than declared, so it cannot advertise coverage the corpus
    does not have: drop a crop's sources and it stops being listed on the next
    build.
    """
    import json
    from collections import Counter

    crops: Counter = Counter()
    livestock = set()
    for line in (INDEX / "chunks.jsonl").open(encoding="utf-8"):
        d = json.loads(line)
        for c in d.get("crops") or []:
            crops[c] += 1
        sid = d.get("source_id", "")
        if "poultry" in sid or "chicken" in sid:
            livestock.add("poultry")
        if "sheep" in sid or "goat" in sid:
            livestock.add("sheep and goats")
    # Only advertise crops with enough material behind them to answer from.
    named = [c for c, n in crops.most_common() if n >= 40] + sorted(livestock)
    return ", ".join(named)


def refusal_text() -> str:
    """The refusal, plus a way in.

    Anything that is not a farming question lands here — greetings, "what can
    you do", questions about other countries. That is the whole set of ways a
    person can miss, and it is one place, so there is no list of phrasings to
    keep up to date. Saying only "my sources do not cover this" to someone who
    typed "hello" is correct and useless; it leaves them with no next move.
    """
    return (
        f"{REFUSAL}\n\n"
        f"Ayekoo answers from Ghanaian agricultural documents - MoFA and CSIR guides,\n"
        f"FAO manuals, Ghanaian research - and cites the source of every answer.\n\n"
        f"Covered: {coverage_line()}.\n"
        "Planting calendars, pests and diseases, varieties, soil and fertiliser,\n"
        "harvest and storage, input costs in cedis, weather by agro-ecological zone.\n\n"
        "Try:\n"
        "  When should I plant maize in Tamale, and which varieties are recommended?\n"
        "  My cassava leaves are curling and yellow - what is wrong?\n\n"
        "Local names work: kokoo kokoram, abele, akyimkyimakyimkyim."
    )


def _tidy(text: str) -> str:
    """Drop a leading part-sentence so the model is not handed broken text.

    Chunks carry an overlap tail from the previous chunk, so many begin
    mid-word: "irds affected, and the severity...", "us, the survival rates
    were...". Given four passages that all start like that, the model concluded
    the sources were unusable and refused a poultry question it had perfectly
    good material to answer. Nothing is lost by trimming — the overlap exists
    precisely so the full sentence survives in the neighbouring chunk.
    """
    stripped = text.lstrip()
    if not stripped or stripped[0].isupper() or stripped[0] in "•-—(":
        return text
    # Cut to the first sentence boundary or bullet, if there is one.
    match = re.search(r"(?:(?<=[.!?])\s+|\n)(?=[A-Z•(])", stripped)
    trimmed = stripped[match.end():] if match else stripped
    # If trimming would leave almost nothing, keep the original.
    return trimmed if len(trimmed) > 120 else text


def build_prompt(question: str, hits) -> str:
    # Deliberately no attribution labels in the prompt.
    #
    # They used to be included, and the model read them as content: asked about
    # kokoo kokoram it answered "consult the manual for Yam Diseases: Research
    # Guide No. 39 (1992)" — turning a citation label from a neighbouring
    # passage into advice, complete with a document number it had no business
    # recommending. Since the model is not asked to cite (attribution is emitted
    # by the system from the chunks actually retrieved), the labels bought
    # nothing and cost that.
    # Cap how much text goes in. Prompt processing is the other half of the
    # wait, and it scales with length: four full chunks is ~3,800 characters,
    # which on a loaded laptop costs more than twenty seconds before a single
    # token comes out. Three passages of 700 characters carry the answer in
    # nearly every case and cut that sharply.
    blocks = [
        f"[{n}]\n{_tidy(hit.chunk['text'])[:700]}"
        for n, hit in enumerate(hits[:3], 1)
    ]
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


# Generation length is the single biggest lever on how long a farmer waits.
# Every token costs the same wall-clock time, and on a busy four-core laptop
# that is roughly a third of a second each. Answers here are 2-4 sentences by
# design, so 160 tokens is enough — and it roughly halves the wait against the
# 320 this started with. Truncation is not a risk: _stop_repeating already cuts
# these answers short more often than the limit does.
def call_model(system: str, user: str, max_tokens: int = 160, temperature: float = 0.2) -> str:
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
        return _stop_repeating(_generate_in_process(system, user, max_tokens, temperature))
    return _stop_repeating(body["choices"][0]["message"]["content"].strip())


def _stop_repeating(text: str) -> str:
    """Cut a generated answer at the point it starts repeating itself.

    Small models loop. Asked "how much is yam selling for", this one produced
    correct figures and then wrote "has increased due to inflation rather than
    real gain" eight times over. The information was right; the answer was
    unusable. Truncating at the first repeated sentence keeps the good part and
    drops the loop, rather than showing a farmer a wall of duplicated text.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    seen: set[str] = set()
    kept: list[str] = []
    for sentence in sentences:
        key = re.sub(r"[^a-z0-9 ]", "", sentence.lower())
        # Short fragments repeat harmlessly; only guard substantial sentences.
        if len(key) > 25 and key in seen:
            break
        seen.add(key)
        kept.append(sentence)
    return " ".join(kept)


def answer(question: str, top_k: int = 4, show_sources: bool = True,
           _retriever=None, _llm=None) -> dict:
    if LIVE_DATA.search(question):
        return {
            "question": question,
            "answer": (
                "Ayekoo cannot answer this. Exchange and interest rates change daily, "
                "and this system is offline and reads a fixed set of documents. Any "
                "figure it gave you would be out of date or invented.\n\n"
                "Crop prices it can give are 2024 annual national averages, and it "
                "says so when it does."
            ),
            "grounded": False,
            "hits": [],
            "best_cosine": 0.0,
            "top_score": 0.0,
        }

    from .index import embed_query, load_embedder

    from .aliases import expand

    # Reuse already-loaded models when the caller has them (the REPL does).
    # Loading both models costs about twenty seconds, which is fine once and
    # unacceptable per question.
    retriever = _retriever if _retriever is not None else Retriever()
    llm = _llm if _llm is not None else load_embedder()
    # Embed the alias-expanded question, so vernacular and abbreviations reach
    # the corpus's own vocabulary. See the note on MIN_COSINE above.
    qvec = embed_query(llm, expand(question))
    hits = retriever.search(question, qvec, top_k=top_k)

    # Absolute semantic similarity of the best-matching chunk in the whole index,
    # independent of ranking. This is what decides whether we answer at all.
    best_cosine = float((retriever.vectors @ qvec).max()) if len(retriever.chunks) else 0.0

    if not hits or best_cosine < MIN_COSINE:
        return {
            "question": question,
            "answer": refusal_text(),
            "grounded": False,
            "hits": [],
            "best_cosine": round(best_cosine, 4),
            "top_score": hits[0].score if hits else 0.0,
        }

    # Remove any passage naming a pesticide Ghana has banned, before it reaches
    # either the extractive paths or the model. Our own corpus recommends
    # chlordecone and methyl bromide — both banned — because the documents
    # predate the regulations. See ayekoo/banned.py.
    hits, banned_found = banned.scrub_passages(hits)
    banned_warning = banned.warning_for(banned_found)
    if not hits:
        return {
            "question": question,
            "answer": (banned_warning or REFUSAL)
            + ("\n\nI have no other source for this question." if banned_warning else ""),
            "grounded": False,
            "banned_substances": banned_found,
            "hits": [],
            "best_cosine": round(best_cosine, 4),
            "top_score": 0.0,
        }

    # Precise-calendar questions are answered by quotation, not paraphrase.
    # See ayekoo/extractive.py: at this model size, paraphrasing a planting
    # window corrupts it ("End of May-early July" became "early May to end of
    # July"), and no verifier can catch that because every month present is
    # legitimately there.
    extracted = (
        extractive.extract_prices(question, retriever)
        or extractive.extract_getting_started(question, retriever, hits)
        or extractive.extract(question, hits, retriever)
        or extractive.extract_symptoms(question, hits)
    )
    if extracted is not None:
        text, used = extracted
        if banned_warning:
            text = f"{banned_warning}\n\n{text}"
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
    # A separate check: does the answer read a described practice as advice?
    caution = verify.practice_caution(text, question)
    if caution:
        warning = f"{warning}\n\n{caution}" if warning else caution

    if banned_warning:
        text = f"{banned_warning}\n\n{text}"

    return {
        "question": question,
        "answer": text,
        "banned_substances": banned_found,
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


def repl() -> int:
    """Interactive session: load the models once, answer many questions.

    The one-shot CLI reloads both models on every invocation, which costs about
    twenty seconds a question. That is fine for scripting and wrong for anything
    a person sits in front of — and it makes a live demo look broken.
    """
    print("Ayekoo — offline farming assistant for Ghana")
    print("loading…", flush=True)

    from .index import embed_query, load_embedder

    retriever = Retriever()
    llm = load_embedder()
    # Warm the generation model too, so the first question is not the slow one.
    call_model("You are a helpful assistant.", "Say OK.", max_tokens=4)

    print(f"ready — {len(retriever.chunks):,} passages from Ghanaian agricultural sources")
    print("ask a question, or Ctrl-C to quit\n")

    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nayekoo.")
            return 0
        if not question:
            continue
        if question.lower() in {"quit", "exit"}:
            print("ayekoo.")
            return 0

        # A generative answer takes fifteen to twenty seconds on a four-core
        # laptop. Silence for that long reads as a hang, so show the clock.
        import threading
        import time as _time

        done = threading.Event()

        # Only when attached to a real terminal: `\r` cannot overwrite a pipe,
        # so piped output would fill with one line per tick.
        interactive = sys.stdout.isatty()

        def tick() -> None:
            start = _time.time()
            while not done.wait(0.25):
                print(f"\r  thinking… {_time.time() - start:4.1f}s", end="", flush=True)

        spinner = threading.Thread(target=tick, daemon=True)
        if interactive:
            spinner.start()
        try:
            result = answer(question, _retriever=retriever, _llm=llm)
        finally:
            done.set()
            if interactive:
                spinner.join(timeout=1)
                print("\r" + " " * 30 + "\r", end="")

        print()
        print(result["answer"])
        if result.get("warning"):
            print(f"\n{result['warning']}")
        print_sources(result["hits"])
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask Ayekoo a Ghanaian farming question.")
    ap.add_argument("question", nargs="*")
    ap.add_argument("--repl", action="store_true",
                    help="interactive session; loads the models once")
    ap.add_argument("--top-k", type=int, default=4)
    ap.add_argument("--json", action="store_true", help="emit the raw result as JSON")
    args = ap.parse_args()

    if args.repl or not args.question:
        return repl()

    result = answer(" ".join(args.question), top_k=args.top_k)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"\nQ: {result['question']}\n")
    print(result["answer"])
    if result.get("warning"):
        print(f"\n{result['warning']}")
    print_sources(result["hits"])
    return 0


def print_sources(hits: list[dict]) -> None:
    """List the documents an answer drew on, once each.

    Several quoted passages usually come from the same document — three chunks
    of MoFA's planting table, say — and printing the attribution and its caveat
    once per chunk made a correct answer look like a wall of repetition. The
    farmer needs to know which documents this came from, not how many passages
    of each.
    """
    if not hits:
        return
    top = hits[0].get("score") or 0.0
    print("\nSources:")
    seen: set[str] = set()
    for h in hits:
        # Skip passages that scored well below the best one: they were in the
        # model's context but contributed little, and listing them reads as
        # careless attribution.
        if top and (h.get("score") or 0.0) < top * 0.75:
            continue
        if h["attribution"] in seen:
            continue
        seen.add(h["attribution"])
        flag = "" if h["ghana_specific"] else "  (regional, not Ghana-specific)"
        print(f"  - {h['attribution']}{flag}")
        if h["caveat"]:
            print(f"      caveat: {h['caveat'][:110]}")


if __name__ == "__main__":
    sys.exit(main())
