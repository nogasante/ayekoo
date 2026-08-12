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


def check(answer: str, sources: str) -> dict:
    """Return the claims in `answer` that are not supported by `sources`."""
    src_numbers = _numbers(sources)
    src_months = _months(sources)

    bad_numbers = sorted(n for n in _numbers(answer) if n not in src_numbers)
    bad_months = sorted(m for m in _months(answer) if m not in src_months)

    return {
        "ok": not bad_numbers and not bad_months,
        "unsupported_numbers": bad_numbers,
        "unsupported_months": bad_months,
    }


def warning_for(result: dict) -> str | None:
    """A plain-language warning to attach to an answer that failed the check."""
    if result["ok"]:
        return None
    bits = []
    if result["unsupported_numbers"]:
        bits.append("numbers " + ", ".join(result["unsupported_numbers"]))
    if result["unsupported_months"]:
        bits.append("months " + ", ".join(result["unsupported_months"]))
    return (
        "UNVERIFIED: this answer contains "
        + " and ".join(bits)
        + " that do not appear in the sources below. Treat it with caution and "
        "read the sources directly."
    )
