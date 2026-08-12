"""Query expansion: bridge what a farmer types to what the documents say.

The corpus is written by agronomists; questions are asked by farmers. Those are
different vocabularies, and the mismatch is a silent retrieval failure — the
right passage exists, the question never reaches it.

Measured examples from this corpus:
    "capsid"     appears  5 times   ← what Ghanaian cocoa farmers say
    "mirid"      appears 41 times   ← what the manuals say
    "army worm"  appears  1 time
    "armyworm"   appears 12 times

Rules for this file, which matter because there is no human factual audit:

1. This maps VOCABULARY ONLY. It never encodes agronomic claims — no
   treatments, rates, or dates. A wrong alias costs a retrieval miss; a wrong
   fact costs credibility.
2. Every expansion target must actually occur in the corpus. `verify()` enforces
   this and the test suite runs it, so an alias cannot quietly point at nothing.
3. Local-language terms are included only where a corpus document states them
   itself (e.g. the cocoa manual gives "kokoo kokoram" for stem canker). We do
   not invent Twi.

Expansion is applied to the BM25 side of retrieval only. The dense embedding
sees the farmer's original phrasing, which is what it is good at.
"""

from __future__ import annotations

from pathlib import Path

# farmer-facing term  ->  terms used in the documents
ALIASES: dict[str, list[str]] = {
    # ── cocoa ────────────────────────────────────────────────────────────────
    "capsid": ["mirid", "capsid"],
    "capsids": ["mirid", "mirids"],
    # UNVERIFIED KEY: "akate" is a Ghanaian term for cocoa capsid, but no corpus
    # document states it, so it is not corroborated here. Kept because a key
    # asserts nothing — if it is wrong it simply never fires — but it must not
    # be cited as evidence of local-language coverage. Remove or confirm.
    "akate": ["mirid", "capsid"],
    "kokoo kokoram": ["stem canker", "phytophthora"],
    "kokoo ananse": ["stem canker", "phytophthora"],
    "cocoa cancer": ["stem canker"],
    "black pod": ["black pod", "phytophthora"],
    "cssvd": ["swollen shoot"],
    "swollen shoot": ["swollen shoot", "cssvd", "virus"],
    # ── maize ────────────────────────────────────────────────────────────────
    "army worm": ["armyworm", "fall armyworm", "spodoptera"],
    "armyworm": ["armyworm", "fall armyworm", "spodoptera"],
    "fall army worm": ["fall armyworm", "armyworm", "spodoptera"],
    "faw": ["fall armyworm", "armyworm"],
    "stalk borer": ["stem borer", "borer"],
    "witchweed": ["striga", "witchweed"],
    "striga": ["striga", "witchweed"],
    # ── cassava ──────────────────────────────────────────────────────────────
    "cmd": ["mosaic", "cassava mosaic"],
    "cassava mosaic": ["mosaic", "cassava mosaic disease"],
    "cbb": ["bacterial blight"],
    "mealy bug": ["mealybug"],
    "mealybugs": ["mealybug"],
    # ── plantain / banana ────────────────────────────────────────────────────
    "black sigatoka": ["sigatoka"],
    "sigatoka": ["sigatoka", "leaf spot"],
    "banana weevil": ["weevil", "cosmopolites"],
    "suckers": ["sucker", "planting material"],
    # ── poultry & livestock ──────────────────────────────────────────────────
    # A farmer describes what they see: birds dying fast, with no warning. The
    # manuals call it "sudden, very high mortality" and name Newcastle disease.
    # Without this bridge, "my chickens are dying suddenly" retrieved general
    # husbandry pages and the system declined a question it could answer.
    "dying suddenly": ["sudden", "mortality", "newcastle"],
    "dying fast": ["sudden", "mortality", "newcastle"],
    "sudden death": ["sudden", "mortality", "newcastle"],
    "many died": ["mortality", "newcastle"],
    "birds dying": ["mortality", "newcastle", "disease"],
    "chickens dying": ["mortality", "newcastle", "disease"],
    "fowl disease": ["newcastle", "disease"],
    "nd": ["newcastle"],
    "not laying": ["egg production", "laying"],
    # ── general ──────────────────────────────────────────────────────────────
    "eelworm": ["nematode"],
    "eelworms": ["nematode"],
    "fertiliser": ["fertilizer"],
    "manure": ["manure", "organic fertilizer"],
    "weedicide": ["herbicide", "weed control"],
    "chemical": ["pesticide", "insecticide", "fungicide"],
    "harmattan": ["harmattan", "dry season"],
    "dry season": ["dry season", "harmattan"],
    "rainy season": ["rainy season", "major season", "wet season"],
    "planting time": ["planting date", "sowing", "planting time"],
    "spacing": ["spacing", "plant population", "planting distance"],
    "storage": ["storage", "store", "post-harvest", "postharvest"],
}


def expand(question: str) -> str:
    """Append alias terms to a question for lexical matching.

    The original wording is preserved; expansions are added, never substituted,
    so a farmer's exact phrasing still scores.
    """
    lowered = question.lower()
    extra: list[str] = []
    for term, targets in ALIASES.items():
        if term in lowered:
            extra.extend(t for t in targets if t not in lowered)
    if not extra:
        return question
    # De-duplicate while preserving order.
    seen: set[str] = set()
    ordered = [t for t in extra if not (t in seen or seen.add(t))]
    return f"{question} {' '.join(ordered)}"


def verify(corpus_dir: Path) -> list[str]:
    """Return alias targets that do not occur anywhere in the corpus.

    An alias pointing at a term no document uses is dead weight at best and a
    sign of invented vocabulary at worst. The test suite asserts this is empty.
    """
    blob = " ".join(
        p.read_text(encoding="utf-8", errors="ignore").lower()
        for p in corpus_dir.glob("*.txt")
    )
    missing: list[str] = []
    for term, targets in ALIASES.items():
        for target in targets:
            if target.lower() not in blob and target not in missing:
                missing.append(target)
    return missing
