"""Check a generated answer against the passages it was supposed to come from.

This exists because of one observed failure. Asked when to plant maize in the
forest zone, the model wrote "July through early August". The retrieved MoFA
source says "Early March-end of April". The model did not copy the source, it
paraphrased it into something false — fluently, and with no human in the loop to
notice.

So we check mechanically. Two classes of claim are checkable without knowing any
agronomy:

  numbers  — "9kg/acre", "75cm", "2 bags". If a number is not in the sources,
             the model produced it.
  months   — "March", "August". Planting-date errors are the most likely to
             cause real harm to a farmer and the easiest to verify.

This is not a truth check. A verified answer can still misrepresent its source;
it only means every number and month in it came from the passages provided. That
is a floor, not a ceiling — but it is a floor that catches invention.
"""

from __future__ import annotations

import re

MONTHS = (
    "january february march april may june july august september october "
    "november december"
).split()

# Match numbers including decimals, ranges and units glued on: 9kg, 75cm, 15-15-15
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Numbers too common to be meaningful evidence of invention.
TRIVIAL = {"1", "2", "3", "0"}


def _numbers(text: str) -> set[str]:
    return {n for n in NUMBER_RE.findall(text.lower()) if n not in TRIVIAL}


def _months(text: str) -> set[str]:
    low = text.lower()
    return {m for m in MONTHS if re.search(rf"\b{m}", low)}


# Agro-ecological zones and regions. A date is only meaningful attached to one
# of these, and pairing a date with the wrong one is the failure this guards.
ZONE_TERMS = (
    "forest transition savannah savanna coastal guinea sudan deciduous "
    "northern southern ashanti brong volta eastern western central upper accra"
).split()


def check(answer: str, sources: str, question: str = "") -> dict:
    """Return claims in `answer` that are not supported by `sources`.

    Two levels. Presence: is this number/month anywhere in the sources at all.
    Association: if the question names an agro-ecological zone, does the month
    in the answer actually occur near that zone in the sources.

    The second exists because presence alone is not enough. Asked about the
    forest zone, the model answered "July through early August" — a date it took
    from the Guinea/Sudan savannah row of MoFA's planting table. Every month in
    that answer was "in the sources", just attached to a different zone. Tables
    extract from PDFs as interleaved fragments, so mixing rows is easy and
    invisible.
    """
    src_numbers = _numbers(sources)
    src_months = _months(sources)

    bad_numbers = sorted(n for n in _numbers(answer) if n not in src_numbers)
    bad_months = sorted(m for m in _months(answer) if m not in src_months)

    # Association check
    low_q = question.lower()
    asked_zones = [z for z in ZONE_TERMS if z in low_q]
    misassociated: list[str] = []
    if asked_zones:
        low_src = sources.lower()
        for month in _months(answer):
            near = False
            for match in re.finditer(rf"\b{month}", low_src):
                window = low_src[max(0, match.start() - 400) : match.start() + 400]
                if any(z in window for z in asked_zones):
                    near = True
                    break
            if not near:
                misassociated.append(month)

    return {
        "ok": not bad_numbers and not bad_months and not misassociated,
        "unsupported_numbers": bad_numbers,
        "unsupported_months": bad_months,
        "misassociated_months": sorted(misassociated),
        "zones_in_question": asked_zones,
    }


def warning_for(result: dict) -> str | None:
    """A plain-language warning to attach to an answer that failed the check."""
    if result["ok"]:
        return None
    bits = []
    if result["unsupported_numbers"]:
        bits.append("numbers (" + ", ".join(result["unsupported_numbers"]) + ") not in the sources")
    if result["unsupported_months"]:
        bits.append("months (" + ", ".join(result["unsupported_months"]) + ") not in the sources")
    if result.get("misassociated_months"):
        zones = ", ".join(result.get("zones_in_question") or [])
        bits.append(
            "months ("
            + ", ".join(result["misassociated_months"])
            + f") that the sources do not attach to {zones}"
        )
    return (
        "UNVERIFIED: this answer contains "
        + "; and ".join(bits)
        + ". Do not rely on it — read the sources below directly."
    )
