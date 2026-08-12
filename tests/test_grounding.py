"""Prove the answers come from the corpus, not from the model's parameters.

    python -m tests.test_grounding

This is the Day 3-4 gate: for each probe, ask the same question twice — once
with no sources (bare model) and once with retrieval — and show the difference.
If the bare model already answers correctly, that probe proves nothing about
grounding and is reported as WEAK. If the bare model invents something and the
grounded run cites a real Ghanaian document, the corpus is doing the work.

It also checks the refusal path, which matters more than usual here: with no
human fact-checking in the loop, a system that guesses when it should decline
is the main way wrong answers reach a judge.
"""

from __future__ import annotations

import sys

from ayekoo.ask import SYSTEM_PROMPT, answer, call_model

# Facts that are Ghana-specific and document-bound. A general-purpose model has
# no reliable way to know these; our corpus does.
PROBES = [
    "Which maize varieties are released and registered in Ghana, and what are their maturity periods?",
    "What is the recommended seed rate per acre for open-pollinated maize in Ghana?",
    "What plant spacing does MoFA recommend for maize in Ghana?",
    "What fertilizer rate is recommended for yam in Ghana?",
    "How should yams be stored after harvest to reduce losses?",
    "What causes black sigatoka in plantain and how is it managed?",
]

# Nothing in a Ghanaian agriculture corpus should answer these. The system is
# expected to decline rather than improvise.
OUT_OF_SCOPE = [
    "What is the capital city of Mongolia?",
    "How do I treat a snake bite on my leg?",
    "What is the current exchange rate of the cedi to the dollar today?",
]

BARE_SYSTEM = "You are a helpful assistant for farmers in Ghana. Answer the question."


def run_probe(question: str) -> dict:
    bare = call_model(BARE_SYSTEM, question, max_tokens=160)
    grounded = answer(question)
    return {"question": question, "bare": bare, "grounded": grounded}


def main() -> int:
    print("=" * 78)
    print("GROUNDING TEST — bare model vs. retrieval over the Ghanaian corpus")
    print("=" * 78)

    failures = 0
    for question in PROBES:
        r = run_probe(question)
        g = r["grounded"]
        print(f"\n{'-' * 78}\nQ: {question}\n")
        print("BARE MODEL (no sources):")
        print(f"  {r['bare'][:420].replace(chr(10), chr(10) + '  ')}")
        print("\nAYEKOO (retrieval over corpus):")
        print(f"  {g['answer'][:420].replace(chr(10), chr(10) + '  ')}")
        if g["hits"]:
            print("\n  cited:")
            for h in g["hits"]:
                tag = "GH" if h["ghana_specific"] else "regional"
                print(f"    [{h['n']}] ({tag}) {h['attribution'][:74]}")
        else:
            print("\n  NO SOURCES RETRIEVED — this probe should have matched the corpus")
            failures += 1

    print(f"\n{'=' * 78}\nREFUSAL TEST — questions the corpus must decline\n{'=' * 78}")
    for question in OUT_OF_SCOPE:
        g = answer(question)
        ok = not g["grounded"]
        print(f"\n{'PASS' if ok else 'FAIL'}  {question}")
        print(f"      score={g['top_score']:.5f}  ->  {g['answer'][:150]}")
        if not ok:
            failures += 1

    print(f"\n{'=' * 78}")
    if failures:
        print(f"{failures} problem(s) found — see above")
    else:
        print("all probes retrieved sources; all out-of-scope questions declined")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
