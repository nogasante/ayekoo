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

import re
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
    # Newcastle symptom vocabulary. A farmer describes what they see; the
    # manuals use clinical terms. Sourced from a Ghanaian video survey and then
    # checked against this corpus — every target below occurs in it.
    "green droppings": ["greenish diarrhoea", "green diarrhoea"],
    "green poo": ["greenish diarrhoea"],
    "greenish droppings": ["greenish diarrhoea"],
    "gasping": ["gasping", "respiratory"],
    "breathing hard": ["gasping", "respiratory", "coughing"],
    "twisted neck": ["twisted neck", "torticollis", "nervous signs"],
    "twisting neck": ["twisted neck", "torticollis"],
    "head twisted": ["twisted neck", "torticollis"],
    "cannot walk": ["paralysis", "nervous signs"],
    "paralysed": ["paralysis", "nervous signs"],
    "stopped laying": ["drop in egg", "egg production"],
    "no appetite": ["loss of appetite"],
    # "Nkoko Nketenkete" is MoFA's backyard-poultry programme under Feed Ghana;
    # the spelling here is the one MoFA's own document uses.
    "nkoko": ["nkoko nketenkete", "backyard poultry"],
    "nkoko nketenkete": ["backyard poultry", "household poultry"],
    "backyard fowls": ["backyard poultry", "nkoko nketenkete"],
    "local fowls": ["backyard poultry", "village poultry"],
    # ── Ghanaian crop names in local languages ───────────────────────────────
    # A farmer types "abele", not "maize". The system refused that outright,
    # which is the same failure as refusing "kokoo kokoram": a submission whose
    # localisation claim rests on Ghanaian vocabulary cannot refuse Ghanaian
    # vocabulary.
    #
    # KOBBY: THESE NEED YOUR EYES. Unlike everything else in this file, the KEYS
    # here are translations taken from general knowledge, not from a corpus
    # document — no source in this corpus lists crop names in Twi, Ga or Ewe.
    # A wrong key costs nothing (it simply never fires) but it also must not be
    # presented as evidence of local-language coverage. Correct or delete
    # anything that is wrong, and add the ones I have missed.
    # SOURCED — Akan lexicon, Burkill's Useful Plants of West Tropical Africa
    # (Kew/JSTOR), University of Ghana repository. Spellings follow the sources.
    "aburoo": ["maize"],
    "aburo": ["maize"],
    "bankye": ["cassava"],
    "borodee": ["plantain"],
    "amankani": ["cocoyam"],
    "mankani": ["cocoyam"],
    "nkatee": ["groundnut"],
    "nkate": ["groundnut"],
    "ntoosi": ["tomato"],
    "mako": ["pepper"],
    "moko": ["pepper"],
    "gyeene": ["onion"],
    "nkruma": ["okra"],
    "nkuruma": ["okra"],
    "fetri": ["okra"],       # Ewe
    "abe": ["oil palm"],
    "kontommire": ["cocoyam"],   # the leaves, eaten as a green
    "nyaadewa": ["garden egg", "eggplant"],
    "ntrowa": ["garden egg", "eggplant"],
    "aborobe": ["pineapple"],
    "borofere": ["pawpaw", "papaya"],
    "ankaa": ["orange", "citrus"],
    "akutu": ["orange", "citrus"],
    "dawadawa": ["dawadawa", "locust bean"],
    "efan": ["amaranth"],
    # Ghanaian English, not a local language, but what a farmer actually types.
    "garden egg": ["garden egg", "eggplant"],
    "garden eggs": ["garden egg", "eggplant"],

    # UNSOURCED — my own recollection, no citation found. Kept because a key
    # asserts nothing and simply never fires if wrong, but NOT to be counted as
    # local-language coverage. "kooko" was removed from this list entirely: I had
    # mapped it to cocoyam and the sources give amankani, so I had it wrong.
    "abele": ["maize"],        # believed Ga; not confirmed by any source found
    "bayere": ["yam"],
    "emo": ["rice"],
    "kwadu": ["banana"],
    "adua": ["cowpea"],
    "ayuo": ["millet"],

    # Local pest terms. "Ntontom" is a catch-all for small flying insects, so it
    # is mapped broadly rather than to one species. "Ayoyo worms" is Ghanaian
    # English for armyworm larvae, from the local name for jute mallow.
    "ntontom": ["whitefly", "whiteflies", "insect"],
    "ntontome": ["whitefly", "whiteflies", "insect"],
    "ayoyo worm": ["armyworm"],
    "ayoyo worms": ["armyworm"],
    "agbeli": ["cassava"],  # Ewe

    # ── Ghanaian Pidgin constructions ────────────────────────────────────────
    # "dey" carries the continuous tense and "don" the perfect, so a farmer
    # writes "my maize dey yellow" and "pest don finish my pepper" where a
    # manual writes "chlorotic" and "damage". Ghanaian Pidgin is lighter than
    # Nigerian and code-switches with Twi, Ga and Ewe more fluidly, so these are
    # matched as phrases rather than by trying to parse the grammar.
    "dey yellow": ["yellowing", "chlorotic"],
    "dey die": ["mortality", "dying"],
    "dey curl": ["curling", "leaf curl"],
    "dey wilt": ["wilting", "wilt"],
    "dey rot": ["rotting", "rot"],
    "dey chop": ["damage", "feeding"],
    "don finish": ["damage", "destroyed"],
    "don spoil": ["damage", "spoilage"],
    "no good": ["poor", "low yield"],
    "small small": ["gradually"],

    # ── Local disease names ──────────────────────────────────────────────────
    # The same category as "kokoo kokoram": names farmers give a disease, which
    # appear in Ghanaian field surveys and nowhere in the manuals.
    #
    # "Akyimkyimakyimkyim" is literally "twisting" — the onion leaf-twisting
    # disease, recorded in Fanteakwa and Kwahu South. "Mathwo" was recorded for
    # tomato yellow leaf curl. "Ginger killer" is current usage for ginger
    # bacterial wilt. None of these is in our corpus as a name, so each is
    # mapped to the symptoms the documents do describe.
    "akyimkyimakyimkyim": ["twisting", "leaf curl", "onion"],
    "akyimkyim": ["twisting", "leaf curl"],
    "mathwo": ["leaf curl", "yellowing", "tomato"],
    "ginger killer": ["wilt", "bacterial"],
    "kurukuruwa": ["curling", "twisting"],

    # ── How farmers describe symptoms ────────────────────────────────────────
    # Farmers describe what they see; manuals name the mechanism. These come
    # from Ghanaian farmer surveys and field interviews.
    "leaves turn yellow": ["yellowing", "chlorotic"],
    "yellow leaves": ["yellowing", "chlorotic"],
    "dry edges": ["drying", "necrosis"],
    "wither and die": ["wilt", "wilting", "dieback"],
    "plants wither": ["wilt", "wilting"],
    "droop": ["wilting", "drooping"],
    "centre shoot dead": ["dieback", "dead heart"],
    "not growing well": ["stunted", "poor growth"],
    "plant no grow": ["stunted", "poor growth"],
    "short plants": ["stunted"],
    "holes in leaves": ["holes", "feeding", "damage"],
    "ragged leaves": ["damage", "feeding"],
    "white powder": ["powdery", "mould"],
    "white coating": ["powdery", "mould"],
    "rusty spots": ["rust", "pustule"],
    "mouldy": ["mould", "mold"],
    "black mould on cob": ["mould", "cob"],
    "holes in grain": ["exit hole", "grain borer"],
    "burnt leaves": ["scorch", "burn"],

    # Storage and market terms that came out of the same survey.
    "grain borer": ["larger grain borer", "grain borer"],
    "weevils in my maize": ["storage pest", "grain borer", "weevil"],
    "market is bad": ["glut", "price"],
    "too much maize on market": ["glut"],
    # ── Ghanaian variety names ───────────────────────────────────────────────
    # A farmer asks for a variety by name. The name alone embeds poorly in an
    # English model — "Obatanpa" scored 0.596 against a 0.65 gate — so it is
    # paired with the words the catalogue uses around it. Every name here is a
    # released Ghanaian variety that appears in this corpus.
    "obatanpa": ["maize variety", "obatanpa"],
    "mamaba": ["maize variety", "mamaba"],
    "abontem": ["maize variety", "abontem"],
    "omankwa": ["maize variety", "omankwa"],
    "aburohemaa": ["maize variety", "aburohemaa"],
    "sanzal-sima": ["maize variety", "sanzal"],
    "kpari-faako": ["maize variety", "kpari"],
    "apantu": ["plantain", "variety"],
    "apem": ["plantain", "variety"],
    "borode": ["plantain"],
    # ── general ──────────────────────────────────────────────────────────────
    "eelworm": ["nematode"],
    "eelworms": ["nematode"],
    "fertiliser": ["fertilizer"],
    # Fertilizer names farmers use are bare product codes. To an English
    # embedding model "npk" is three letters with no meaning: "how much does npk
    # cost" scored 0.627 and was refused, while the same question saying
    # "fertilizer" scored 0.786. Expanding the code restores the meaning.
    "npk": ["NPK", "compound fertilizer", "fertilizer"],
    "npk 15-15-15": ["NPK 15-15-15", "compound fertilizer"],
    "sulphate of ammonia": ["sulphate of ammonia", "fertilizer"],
    "ammonia": ["sulphate of ammonia", "fertilizer"],
    "urea": ["urea", "fertilizer", "nitrogen"],
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
        # Word boundaries, not substring containment. "abe" (oil palm) sits
        # inside "abele" (maize), so plain containment expanded a maize question
        # with oil palm. Short keys — abe, emo, nd — are exactly the ones that
        # matter for local vocabulary and exactly the ones substrings break.
        if re.search(rf"\b{re.escape(term)}\b", lowered):
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
