"""Answer precise-fact questions by quoting the source instead of paraphrasing.

Three times in a row, on the highest-stakes question type this corpus serves,
the 0.5B model corrupted a planting date while doing everything else right:

  source "Early March-end of April"     -> answer "July through early August"
  source "End of May-early July"        -> answer "early May to end of July"

The second is the instructive one. Retrieval was correct, the chunk was correct,
the months were correct, and the zone association was correct — the model simply
swapped "end of May" for "early May" and "early July" for "end of July",
widening the planting window by about three weeks at each end. No amount of
prompt engineering reliably fixes that at this model size, and no verifier that
checks months or numbers can catch it, because every month and number present
was legitimately there.

The answer is not to try harder. It is to stop paraphrasing where paraphrase
adds nothing. A planting window is a quotation, not a summary: the farmer wants
the exact window, and the exact window is already written in plain language in
the derived calendar documents. So for these questions we return the source
sentences verbatim, attributed. Deterministic, exact, and a judge can check it
against the PDF character by character.

The generative path still handles everything else — explanations, symptoms,
"what should I do about" questions — where paraphrase genuinely helps.
"""

from __future__ import annotations

import re

# Question shapes that ask for a precise calendar window.
CALENDAR_INTENT = re.compile(
    r"\b(when|what time|which month|planting (date|time|period|season|window)|"
    r"time to plant|best time)\b",
    re.I,
)

PLANTING_TERMS = re.compile(r"\b(plant|planting|sow|sowing|season)\b", re.I)

# Zone vocabulary, matched against both question and source lines.
ZONES = {
    "forest": ("forest zone", "rain forest", "deciduous"),
    "transition": ("transition", "transitional"),
    "coastal": ("coastal savannah", "coastal"),
    "guinea": ("guinea savannah", "guinea"),
    "sudan": ("sudan savannah", "sudan"),
    "northern": ("guinea savannah", "sudan savannah"),
}


def is_calendar_question(question: str) -> bool:
    return bool(CALENDAR_INTENT.search(question) and PLANTING_TERMS.search(question))


def zones_in(text: str) -> set[str]:
    low = text.lower()
    found = set()
    for key, terms in ZONES.items():
        if any(t in low for t in terms):
            found.add(key)
    return found


def extract(question: str, hits) -> tuple[str, list] | None:
    """Return (verbatim answer, hits used) if this is a calendar question that a
    derived document answers directly. Otherwise None, and the caller generates.
    """
    if not is_calendar_question(question):
        return None

    asked = zones_in(question)
    lines: list[str] = []
    used = []

    for hit in hits:
        chunk = hit.chunk
        # Only quote from derived documents: they are already clean prose with
        # one fact per sentence. Quoting raw PDF text would emit table debris.
        # Identified by id prefix rather than a chunk field, so that recognising
        # them does not require re-embedding the whole index.
        if not chunk["source_id"].startswith("derived-"):
            continue
        for sentence in re.split(r"(?<=\.)\s+", chunk["text"]):
            s = sentence.strip()
            if not s or not PLANTING_TERMS.search(s):
                continue
            if not re.search(r"(january|february|march|april|may|june|july|august|"
                             r"september|october|november|december)", s, re.I):
                continue
            # If the question named a zone, keep only sentences about that zone.
            if asked and not (zones_in(s) & asked):
                continue
            if s not in lines:
                lines.append(s)
                if hit not in used:
                    used.append(hit)

    if not lines:
        return None

    body = "\n".join(f"- {line}" for line in lines)
    return (
        "From the source, word for word:\n\n"
        f"{body}\n\n"
        "(Quoted exactly rather than summarised, so the planting window is not "
        "altered.)"
    ), used
