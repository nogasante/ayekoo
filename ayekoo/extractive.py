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

# Region-to-zone mapping, taken from the Ghana Meteorological Agency's Weather
# and Climate Manual for Agriculture (2022) — see
# corpus/text/derived-region-zone-mapping.txt for the quoted source text.
#
# This was previously recorded as an unfillable gap. It is filled now because a
# Ghanaian government source states it, not because the geography is obvious.
#
# A region can map to several zones, and most do: zones follow rainfall, not
# administrative borders. Where a region spans zones we return all of them and
# say so, rather than picking the largest and sounding more certain than the
# source.
PLACE_TO_ZONES: dict[str, tuple[str, ...]] = {
    # Stated as covering the whole region
    "upper west": ("guinea",),
    "northern region": ("guinea",),
    "greater accra": ("coastal",),
    # Stated as spanning more than one zone
    "upper east": ("guinea", "sudan"),
    "ashanti": ("transition", "forest"),
    "eastern region": ("transition", "forest"),
    "western region": ("forest",),
    "western north": ("forest",),
    "central region": ("forest", "coastal"),
    "volta": ("guinea", "transition", "forest", "coastal"),
    # Former Brong Ahafo, now Bono / Bono East / Ahafo
    "brong ahafo": ("guinea", "transition", "forest"),
    "bono east": ("guinea", "transition", "forest"),
    "ahafo": ("guinea", "transition", "forest"),
    "bono": ("guinea", "transition", "forest"),
}

# Town-to-region is NOT stated by any source in this corpus. These are included
# because a farmer types a town name, but the answer must disclose that this
# step is not sourced — only the region-to-zone step is.
TOWN_TO_REGION: dict[str, str] = {
    "tamale": "northern region",
    "bolgatanga": "upper east",
    "wa": "upper west",
    "kumasi": "ashanti",
    "accra": "greater accra",
    "tema": "greater accra",
    "koforidua": "eastern region",
    "cape coast": "central region",
    "takoradi": "western region",
    "sunyani": "bono",
    "techiman": "bono east",
    "ho": "volta",
}


MONTHS = ("january february march april may june july august september october "
          "november december").split()

# "We are in August, what can I plant?" is a calendar question that names no
# crop and asks nothing my regexes recognised, so it went to the model, which
# answered "you can plant maize in August after rains have established good soil
# moisture". Nothing in the sources says that. August is the minor season in the
# south only, and northern Ghana has no minor season at all — so the answer was
# wrong for half the country and unsupported everywhere.
MONTH_INTENT = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\b.{0,60}\b(plant|sow|grow|crop)\b"
    r"|\b(plant|sow|grow)\b.{0,40}\b(" + "|".join(MONTHS) + r")\b"
    r"|\b(this|next|which) month\b|\bright now\b|\bthis season\b",
    re.I,
)


def is_calendar_question(question: str) -> bool:
    return bool(
        (CALENDAR_INTENT.search(question) and PLANTING_TERMS.search(question))
        or MONTH_INTENT.search(question)
    )


# "I want to plant maize" is not a question, it is an intent — and it is
# probably the most common thing a farmer would type. Treated as a query it
# matches plant-anatomy prose: the first answer this system gave was "maize is a
# monoecious plant with separate male and female parts", followed by grain
# physiological maturity. True, sourced, and no use to anyone holding seed.
#
# What that farmer needs is the practical starting set: when to plant, how far
# apart, how much seed, which varieties. So we assemble it rather than retrieve
# it.
GETTING_STARTED_INTENT = re.compile(
    r"\b(i want to|i wish to|i plan to|planning to|how (do i|to|can i)|"
    r"want to start|how to start|thinking of|advice on)\b.{0,40}"
    r"\b(plant|grow|farm|cultivat\w*|start)\b"
    r"|\b(plant|grow|farm|cultivat\w*)\b.{0,20}\b(how|advice|help)\b",
    re.I,
)

# Facts worth surfacing for someone about to plant, and the shapes they take in
# the documents.
STARTER_PATTERNS = (
    ("Spacing", re.compile(r"\b\d{2,3}\s?cm\b.{0,80}\b(apart|spacing|rows?|between)\b|"
                           r"\b(spacing|space)\b.{0,60}\b\d{2,3}\s?cm\b", re.I)),
    ("Seed rate", re.compile(r"\b\d+(\.\d+)?\s?kg\s?/?\s?(acre|ha|hectare)\b", re.I)),
    ("Fertilizer", re.compile(r"\bNPK\b|\b\d+-\d+-\d+\b|\bbags?\b.{0,40}\b(acre|hectare|ha)\b", re.I)),
    ("Depth", re.compile(r"\b\d{1,2}\s?cm\b.{0,40}\bdeep\b|\bdeep\b.{0,30}\b\d{1,2}\s?cm\b", re.I)),
)


def extract_getting_started(question: str, retriever, hits) -> tuple[str, list] | None:
    """Assemble the practical basics for a crop someone wants to plant."""
    if not GETTING_STARTED_INTENT.search(question):
        return None

    low = question.lower()
    crops = [c for c in CROPS if re.search(rf"\b{c}s?\b", low)]
    if not crops:
        return None
    crop = crops[0]

    from .retrieve import Hit

    sections: dict[str, str] = {}
    used: list = []
    calendar_lines: list[str] = []

    practical = getattr(retriever, "source_doc_type", {})

    # Other things a sentence might really be about. The FAO fertilizer report is
    # tagged with all seven crops, so a cocoa yield figure passed the crop filter
    # and was offered as maize's seed rate.
    other_crops = tuple(c for c in CROPS if c != crop) + (
        "mucuna", "cowpea", "soybean", "groundnut", "cocoyam", "banana")

    def about_this_crop(sentence: str) -> bool:
        low = sentence.lower()
        # Reject anything naming another crop, even if ours appears too. The
        # sentence "plant mucuna at 60 cm x 40 cm as a pre-maize cover legume"
        # mentions maize and is about mucuna's spacing, not maize's — offering
        # it as maize spacing would send a farmer to the field with the wrong
        # numbers.
        if any(re.search(rf"\b{o}\b", low) for o in other_crops):
            return False
        return True

    # Single-crop sources first, and Ghanaian ones before regional: a maize
    # guide is a better source for maize spacing than a seven-crop fertilizer
    # survey that merely mentions maize.
    def source_rank(chunk: dict) -> tuple:
        tags = chunk.get("crops") or []
        return (len(tags), 0 if chunk.get("ghana_specific", True) else 1)

    for chunk in sorted(retriever.chunks, key=source_rank):
        sid = chunk["source_id"]
        crop_tags = chunk.get("crops") or []
        # Must be a document about THIS crop. An earlier version skipped only
        # chunks tagged with a different crop, which let untagged sources
        # through — so "I want to plant maize" answered with "perching space of
        # 15 to 20 cm should be allowed for each bird" from a poultry manual,
        # and a cocoa yield figure as the seed rate.
        if crop not in crop_tags:
            continue
        # And a document meant to be followed, not a study.
        if practical.get(sid) == "research":
            continue

        # Planting windows come from the derived calendar, quoted.
        if sid.startswith("derived-") and crop in crop_tags:
            for sentence in re.split(r"(?<=\.)\s+", chunk["text"]):
                s = " ".join(sentence.split())
                if re.match(r"^[A-Z]", s) and "plant" in s.lower() and re.search(
                    r"(january|february|march|april|may|june|july|august|september|"
                    r"october|november|december)", s, re.I):
                    if s not in calendar_lines:
                        calendar_lines.append(s)
            continue

        # Everything else: the first clean sentence matching each starter fact.
        for label, pattern in STARTER_PATTERNS:
            if label in sections:
                continue
            for sentence in re.split(r"(?<=[.;])\s+", chunk["text"]):
                s = " ".join(sentence.split())
                if len(s) < 30 or len(s) > 240 or not re.match(r"^[A-Z(]", s):
                    continue
                if pattern.search(s) and about_this_crop(s):
                    sections[label] = s
                    hit = Hit(chunk=chunk, score=0.0, dense_rank=None, lexical_rank=None)
                    if not any(h.chunk["chunk_id"] == chunk["chunk_id"] for h in used):
                        used.append(hit)
                    break

    if not calendar_lines and not sections:
        return None

    parts = [f"Here is what my sources say about planting {crop}, word for word."]
    if calendar_lines:
        parts.append("\nWhen to plant:")
        parts.extend(f"- {ln}" for ln in calendar_lines[:6])
    for label, _ in STARTER_PATTERNS:
        if label in sections:
            parts.append(f"\n{label}:\n- {sections[label]}")
    parts.append(
        "\nAsk me about varieties, pests, fertilizer or storage for more detail, "
        "and tell me your region so I can give the right planting window."
    )
    return "\n".join(parts), (used + list(hits))[:6]


def asked_zones_named(question: str) -> bool:
    """Did the farmer name a zone, region or town we can resolve?"""
    return bool(resolve_place(question)[0])


def month_in(question: str) -> str | None:
    for m in MONTHS:
        if re.search(rf"\b{m}", question, re.I):
            return m
    return None


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
    for place, zones in PLACE_TO_ZONES.items():
        if place in low:
            found.update(zones)
    return found


def resolve_place(question: str) -> tuple[set[str], str | None]:
    """Resolve a question's place name to zones, and explain how we got there.

    Returns (zones, note). The note is shown to the farmer when the resolution
    passed through an unsourced step or landed on more than one zone — both are
    things they need to know before acting on a planting date.
    """
    low = question.lower()

    zones = zones_in(question)
    if zones:
        for region, region_zones in PLACE_TO_ZONES.items():
            if region in low and len(region_zones) > 1:
                return zones, (
                    f"The {region.title()} area lies across more than one "
                    "agro-ecological zone, so more than one planting window is "
                    "shown. Check which zone your farm is in."
                )
        return zones, None

    for town, region in TOWN_TO_REGION.items():
        if re.search(rf"\b{town}\b", low):
            region_zones = PLACE_TO_ZONES.get(region, ())
            if not region_zones:
                continue
            label = region.title()
            if not label.lower().endswith("region"):
                label += " Region"
            note = (
                f"I have taken {town.title()} to be in the {label}. "
                "That step is not from my sources — only the link from region to "
                "agro-ecological zone is, and it comes from the Ghana "
                "Meteorological Agency."
            )
            if len(region_zones) > 1:
                note += (
                    " That region lies across more than one zone, so more than "
                    "one planting window is shown."
                )
            return set(region_zones), note

    return set(), None


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
# Kept deliberately wide. "What killed my chicken" was refused because the
# trigger list had "dying" and "died" but not "killed" — a farmer describing a
# dead animal in the past tense fell straight through to the generic path.
SYMPTOM_INTENT = re.compile(
    r"\b(dying|die|died|dead|killed|killing|kill|losing|lost|sick|sickness|ill|"
    r"disease|diseased|infect\w*|symptom|symptoms|signs?|pest|attack\w*|"
    r"what is wrong|what.s wrong|what could it be|why (is|are|did)|"
    r"droppings|diarrh\w*|gasping|coughing|sneez\w*|limping|"
    r"swollen|swelling|wilting|curling|yellowing|rotting|rot\b|spots?|holes?)\b",
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

    asked, place_note = resolve_place(question)
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

    # If the question also asks about varieties, quote the variety lines for the
    # same zone. "When should I plant maize in Tamale, and which varieties are
    # recommended?" previously answered only the first half: variety lines carry
    # no month, so the date filter above dropped them, and the farmer got a
    # window with no seed to put in the ground.
    if re.search(r"\b(variet|variety|varieties|seed|which maize|what maize)\b", question, re.I):
        for hit in candidates:
            chunk = hit.chunk
            if not chunk["source_id"].startswith("derived-"):
                continue
            for sentence in re.split(r"(?<=\.)\s+", chunk["text"]):
                s = " ".join(sentence.split())
                if not re.match(r"^[A-Z]", s) or ":" not in s:
                    continue
                # Variety lines name a zone and list cultivars, with no month.
                if re.search(r"(january|february|march|april|may|june|july|august|"
                             r"september|october|november|december)", s, re.I):
                    continue
                if not re.search(r"\bzones?\b", s, re.I):
                    continue
                if asked and not (zones_in(s) & asked):
                    continue
                if s not in lines:
                    lines.append(s)
                    if not any(h.chunk["chunk_id"] == chunk["chunk_id"] for h in used):
                        used.append(hit)

    if not lines:
        return None

    # If the question named a month, keep the windows that actually include it.
    # "We are in August, what can I plant?" should not print the whole calendar.
    asked_month = month_in(question)
    if asked_month:
        matching = [ln for ln in lines if re.search(rf"\b{asked_month}", ln, re.I)]
        if matching:
            lines = matching

    body = "\n".join(f"- {line}" for line in lines)
    preamble = "From the source, word for word:"
    if asked_month and not asked_zones_named(question):
        preamble = (
            f"Planting depends on your agro-ecological zone. These are the "
            f"windows my sources record that include {asked_month.title()}:"
        )

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
    elif place_note:
        preamble = f"{place_note}\n\nFrom the source, word for word:"

    return (
        f"{preamble}\n\n"
        f"{body}\n\n"
        "(Quoted exactly rather than summarised, so the planting window is not "
        "altered.)"
    ), used
