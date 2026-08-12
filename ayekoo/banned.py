"""Block pesticides that are banned in Ghana from reaching a farmer.

This exists because of a real finding, not a hypothetical one.

Cross-checking the corpus against Ghana EPA's *Revised Register of Pesticides,
December 2023* turned up two banned substances being recommended by documents in
our own corpus:

  chlordecone     IITA plantain manual, in a dosage table: "chlordecone 1"
                  gram per plant, for banana weevil control
  methyl bromide  FAO yam post-harvest guide, for fumigation

Chlordecone is a persistent organic pollutant, banned under the Stockholm
Convention and in Ghana; it caused a long-running public health disaster in the
French Antilles. The same IITA table also lists HCH, likewise banned.

Neither document is wrong about what was recommended when it was written — the
plantain manual is from 1990. They are simply older than the regulations. That
is precisely the danger of a corpus built from durable agronomy: the agronomy
lasts, the chemical registrations do not.

So this is a hard block rather than a caveat. A passage naming a banned
substance is not shown as guidance; the answer says the substance is banned in
Ghana and points at the current register. Getting this wrong has consequences a
farmer cannot undo.

Source: Ghana Environmental Protection Agency, Chemicals Control and Management
Centre, Revised Register of Pesticides, December 2023.
https://epa.gov.gh/new/wp-content/uploads/2024/08/Revised-Register-Of-Pesticides-December-2023-1.pdf
"""

from __future__ import annotations

import re

# Banned in Ghana, transcribed from section (C) "Banned Pesticides" of the EPA
# register. Spelling variants are included because the corpus documents predate
# current usage.
BANNED = {
    "2,4,5-t",
    "aldrin",
    "binapacryl",
    "captafol",
    "chlordane",
    "chlordimeform",
    "chlorobenzilate",
    "chlordecone",
    "ddt",
    "dichlorodiphenyltrichloroethane",
    "dieldrin",
    "dinoseb",
    "dnoc",
    "dinitro-ortho-cresol",
    "endrin",
    "hch",
    "hexachlorocyclohexane",
    "lindane",
    "heptachlor",
    "hexachlorobenzene",
    "parathion",
    "methyl-parathion",
    "methyl parathion",
    "methamidophos",
    "pentachlorophenol",
    "pentachlorobenzene",
    "toxaphene",
    "mirex",
    "methyl bromide",
    "methyl-bromide",
}

_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(b) for b in sorted(BANNED, key=len, reverse=True)) + r")\b",
    re.I,
)

WARNING = (
    "WARNING: the source text here names {names}, which Ghana's Environmental "
    "Protection Agency lists as BANNED. Do not buy or use it. These documents "
    "are older than the current regulations. Check the EPA Revised Register of "
    "Pesticides (December 2023) or ask your MoFA extension officer for a "
    "product that is registered today."
)


def find(text: str) -> list[str]:
    """Return the banned substances named in a piece of text."""
    seen: list[str] = []
    for match in _PATTERN.finditer(text or ""):
        name = match.group(0).lower()
        if name not in seen:
            seen.append(name)
    return seen


def warning_for(names: list[str]) -> str | None:
    if not names:
        return None
    return WARNING.format(names=", ".join(sorted(set(names))))


def scrub_passages(hits) -> tuple[list, list[str]]:
    """Drop retrieved passages that name a banned substance.

    Returns (kept_hits, banned_names_found). Dropping rather than annotating is
    deliberate: a dosage table for a banned chemical has no safe use here, and
    leaving it in the model's context invites it to repeat the dose.
    """
    kept = []
    found: list[str] = []
    for hit in hits:
        names = find(hit.chunk.get("text", ""))
        if names:
            for n in names:
                if n not in found:
                    found.append(n)
            continue
        kept.append(hit)
    return kept, found
