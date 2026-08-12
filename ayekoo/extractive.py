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
}

# What a farmer actually types, mapped to a zone key.
#
# Only entries corroborated by a document in this corpus appear here. The FAO
# fertilizer report states that the Sudan Savannah Zone includes districts in
# the Upper East Region; that is the one region-to-zone statement we have.
#
# Everything else a farmer might say — "Tamale", "Kumasi", "Ashanti" — is
# deliberately ABSENT, because filling it in would mean writing Ghanaian
# geography from general knowledge into a system whose whole claim is that its
# facts are traceable. When no zone can be resolved, we say so and show the
# whole calendar rather than guess which row applies.
PLACE_TO_ZONE: dict[str, str] = {
    "upper east": "sudan",
}


def is_calendar_question(question: str) -> bool:
    return bool(CALENDAR_INTENT.search(question) and PLANTING_TERMS.search(question))


def zones_in(text: str) -> set[str]:
    low = text.lower()
    found = set()
    for key, terms in ZONES.items():
        if any(t in low for t in terms):
            found.add(key)
    for place, zone in PLACE_TO_ZONE.items():
        if place in low:
            found.add(zone)
    return found


# A place name we recognise as Ghanaian but cannot map to a zone. Used to tell
# the farmer *why* we are showing the whole calendar instead of one row.
UNMAPPED_PLACE = re.compile(
    r"\b(tamale|kumasi|accra|bolgatanga|sunyani|techiman|takoradi|navrongo|ho|wa|"
    r"cape coast|koforidua|tarkwa|obuasi|ashanti|brong|ahafo|volta|eastern|western|"
    r"central|greater accra|northern|upper west|savannah region|oti|bono)\b",
    re.I,
)


def extract(question: str, hits, retriever=None) -> tuple[str, list] | None:
    """Return (verbatim answer, hits used) if this is a calendar question that a
    derived document answers directly. Otherwise None, and the caller generates.
    """
    if not is_calendar_question(question):
        return None

    asked = zones_in(question)
    lines: list[str] = []
    used = []

    candidates = list(hits)

    # If ordinary retrieval did not surface a derived calendar, consult it
    # anyway. A question like "when should I plant maize in Tamale?" ranks
    # against general maize prose and never reaches the calendar, so it used to
    # come back with soil-preparation advice instead of a date. The derived
    # documents are a handful of chunks, so scanning them directly is cheap and
    # makes calendar coverage deterministic rather than dependent on ranking.
    # Note this runs even when a derived chunk is already present: retrieval may
    # have surfaced the *varieties* chunk of the calendar rather than the one
    # holding the planting windows. Observed on "when should I plant maize in the
    # Upper East region?", which retrieved the calendar document, found no date
    # lines in that particular chunk, fell through to generation, and produced
    # "August through the end of September" against a source that says
    # "End of May to early July".
    if retriever is not None:
        from .retrieve import Hit

        have = {h.chunk["chunk_id"] for h in candidates}

        q_words = set(re.findall(r"[a-z]+", question.lower()))
        crop_named = {c for c in ("maize", "cassava", "yam", "cocoa", "tomato",
                                  "plantain", "rice") if c in q_words}
        for chunk in retriever.chunks:
            if not chunk["source_id"].startswith("derived-"):
                continue
            if chunk["chunk_id"] in have:
                continue
            crops = chunk.get("crops") or []
            # If the question names a crop, use that crop's calendar only. The
            # FAO zone document carries no crop tag and describes rainy seasons
            # rather than planting windows, so it must not displace the crop
            # calendar when one applies.
            if crop_named and not (set(crops) & crop_named):
                continue
            candidates.append(Hit(chunk=chunk, score=0.0, dense_rank=None, lexical_rank=None))

    for hit in candidates:
        chunk = hit.chunk
        # Only quote from derived documents: they are already clean prose with
        # one fact per sentence. Quoting raw PDF text would emit table debris.
        # Identified by id prefix rather than a chunk field, so that recognising
        # them does not require re-embedding the whole index.
        if not chunk["source_id"].startswith("derived-"):
            continue
        for sentence in re.split(r"(?<=\.)\s+", chunk["text"]):
            s = " ".join(sentence.split())  # normalise the line breaks inside it
            if not s or not PLANTING_TERMS.search(s):
                continue
            # Chunks carry an overlap tail from the previous chunk, so the first
            # "sentence" can start mid-word — that is where "- t zone: major
            # rainy season..." came from, a truncated "Transitional zone". A
            # quoted answer must never show a fragment, so require a sentence to
            # begin like a real one.
            if not re.match(r"^[A-Z(]", s):
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
    preamble = "From the source, word for word:"

    # The farmer named a place we recognise but cannot resolve to an
    # agro-ecological zone. Say that plainly and show every zone, rather than
    # picking one and hoping. Planting dates differ by up to two months between
    # zones, so a wrong guess here is worse than an unfiltered answer.
    if not asked and UNMAPPED_PLACE.search(question):
        preamble = (
            "Planting dates in Ghana depend on the agro-ecological zone, and my "
            "sources do not record which zone that place is in. Here is the full "
            "calendar — find your zone:"
        )

    return (
        f"{preamble}\n\n"
        f"{body}\n\n"
        "(Quoted exactly rather than summarised, so the planting window is not "
        "altered.)"
    ), used
