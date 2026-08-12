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

# Price questions get the same treatment as dates, and for the same reason.
# Asked "how much is yam selling for", the model produced correct figures and
# then looped — "has increased due to inflation rather than real gain" eight
# times over. Asked "what is the price of maize", it retrieved tomato text and
# reported a 130kg crate at GHS 700, along with maize having "high brix
# content", which is a tomato measure. A price is a figure to be quoted.
PRICE_INTENT = re.compile(
    r"\b(price|prices|cost|costs|selling for|sell for|worth|how much|"
    r"market rate|going rate)\b",
    re.I,
)

CROPS = ("maize", "cassava", "yam", "cocoyam", "plantain", "rice", "tomato",
         "sorghum", "millet", "groundnut")

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


def is_price_question(question: str) -> bool:
    return bool(PRICE_INTENT.search(question))


def extract_prices(question: str, retriever) -> tuple[str, list] | None:
    """Quote the price lines for whichever crops the question names."""
    if retriever is None or not is_price_question(question):
        return None

    low = question.lower()
    # Word boundaries matter here: "rice" is a substring of "price", so a plain
    # containment check made every price question also return the rice figure.
    wanted = [c for c in CROPS if re.search(rf"\b{c}s?\b", low)]
    if not wanted:
        return None

    from .retrieve import Hit

    lines: list[str] = []
    used: list = []
    for chunk in retriever.chunks:
        if chunk["source_id"] != "derived-market-prices":
            continue
        for sentence in re.split(r"(?<=\.)\s+", chunk["text"]):
            s = " ".join(sentence.split())
            if not re.match(r"^[A-Z]", s):
                continue
            # Only the per-crop price statements, which name a crop, a cedi
            # figure and a year.
            if not any(s.lower().startswith(c) for c in wanted):
                continue
            if "GH" not in s:
                continue
            if s not in lines:
                lines.append(s)
                hit = Hit(chunk=chunk, score=0.0, dense_rank=None, lexical_rank=None)
                if not any(h.chunk["chunk_id"] == chunk["chunk_id"] for h in used):
                    used.append(hit)

    if not lines:
        return None

    body = "\n".join(f"- {line}" for line in lines)
    return (
        "From the source, word for word:\n\n"
        f"{body}\n\n"
        "These are annual national average wholesale prices, not today's market "
        "price and not a farm-gate price. Prices vary by region and by season.\n\n"
        "(Quoted exactly rather than summarised, so the figures are not altered.)"
    ), used


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


# Symptom questions. A farmer describing sick animals or plants is asking a
# differential-diagnosis question, and that is the worst possible task for a
# 0.63B model to paraphrase.
#
# Measured on "my chickens have green droppings and are gasping", with correct
# chunks retrieved:
#   - with the refusal clause in the system prompt, the model declined outright
#   - with the clause removed, it named Newcastle disease and then merged it with
#     fowl cholera, attributing Pasteurella multocida to the same picture
#   - with diagnostic framing, it produced "coat dragging on the ground", a
#     garbled reading of drooping wings
#
# All three are unacceptable for animal health advice. So we quote: list the
# signs the sources actually record, name the diseases the sources name, and
# tell the farmer to get a veterinary officer. Ayekoo does not diagnose.
SYMPTOM_INTENT = re.compile(
    r"\b(dying|die|died|sick|sickness|disease|symptom|symptoms|signs?|"
    r"what is wrong|what could it be|droppings|diarrh|gasping|coughing|"
    r"swollen|wilting|curling|yellowing|rotting|spots?)\b",
    re.I,
)

SYMPTOM_TERMS = re.compile(
    r"\b(sign|signs|symptom|symptoms|mortality|diarrh\w*|gasping|coughing|"
    r"sneezing|paralysis|convulsion\w*|torticollis|twisted neck|lesion\w*|"
    r"swelling|swollen|discharge|drop in egg|loss of appetite|wilting|"
    r"chlorotic|necrosis|rot\b|spots?)\b",
    re.I,
)

DISEASE_NAME = re.compile(
    r"\b(newcastle|nd virus|fowl (?:cholera|pox|typhoid)|pasteurell\w+|"
    r"gumboro|infectious (?:bronchitis|coryza|laryngotracheitis)|coccidiosis|"
    r"marek\w*|avian influenza|mosaic|bacterial blight|anthracnose|"
    r"black pod|swollen shoot|sigatoka|striga|mealybug|armyworm)\b",
    re.I,
)


# Tidy the names for display. The documents abbreviate heavily, and "the sources
# above name: nd virus" reads like a glitch rather than a disease.
DISEASE_LABELS = {
    "nd virus": "Newcastle disease (ND)",
    "newcastle": "Newcastle disease (ND)",
    "pasteurella": "fowl cholera (Pasteurella)",
    "pasteurellosis": "fowl cholera (Pasteurella)",
    "mosaic": "cassava mosaic disease",
    "black pod": "black pod",
    "swollen shoot": "cocoa swollen shoot virus",
    "sigatoka": "black sigatoka",
}


def is_symptom_question(question: str) -> bool:
    return bool(SYMPTOM_INTENT.search(question))


def extract_symptoms(question: str, hits) -> tuple[str, list] | None:
    """Quote the signs and disease names the sources record, without diagnosing."""
    if not is_symptom_question(question):
        return None

    lines: list[str] = []
    used: list = []
    diseases: list[str] = []

    for hit in hits:
        for sentence in re.split(r"(?<=[.;])\s+|\n(?=[•\-])", hit.chunk["text"]):
            s = " ".join(sentence.split()).lstrip("•- ")
            if len(s) < 25 or len(s) > 300:
                continue
            if not SYMPTOM_TERMS.search(s):
                continue
            # Skip fragments that begin mid-word — chunk overlap debris.
            if not re.match(r"^[A-Z(]", s):
                continue
            if s in lines:
                continue
            lines.append(s)
            for match in DISEASE_NAME.finditer(s):
                name = DISEASE_LABELS.get(match.group(0).lower(), match.group(0))
                if name not in diseases:
                    diseases.append(name)
            if not any(h.chunk["chunk_id"] == hit.chunk["chunk_id"] for h in used):
                used.append(hit)
        if len(lines) >= 6:
            break

    if len(lines) < 2:
        return None

    header = "Here is what my sources record about signs like these, word for word:"
    body = "\n".join(f"- {_repair(line)}" for line in lines[:6])
    named = ""
    if diseases:
        named = (
            "\n\nThe sources above name: "
            + ", ".join(sorted(set(diseases)))
            + "."
        )

    # Livestock and crops need different closing advice: telling someone whose
    # cassava is sick to have "the animals" examined reads as carelessness, and
    # carelessness in a health answer undermines the rest of it.
    livestock = bool(re.search(
        r"\b(chicken|chickens|fowl|fowls|poultry|bird|birds|goat|goats|sheep|"
        r"cattle|cow|cows|animal|animals|guinea)\b", question, re.I))
    if livestock:
        closing = (
            "I am quoting my sources, not diagnosing. Several diseases share "
            "these signs, and telling them apart needs someone who can examine "
            "the animals. Contact your MoFA extension officer or a veterinary "
            "officer."
        )
    else:
        closing = (
            "I am quoting my sources, not diagnosing. Several pests and diseases "
            "share these signs, and telling them apart usually needs someone who "
            "can look at the crop. Contact your MoFA extension officer."
        )

    return f"{header}\n\n{body}{named}\n\n{closing}", used


def _repair(line: str) -> str:
    """Undo the letter-spacing PDF extraction leaves behind ("Y ou", "th e")."""
    return re.sub(r"\b([A-Za-z])\s([a-z]{1,3}\b)", r"\1\2", line)


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
