"""Split extracted source text into retrievable chunks that carry their provenance.

Every chunk knows which document it came from, how to cite it, whether that
document is Ghana-specific, and any caveat attached to it. That metadata is not
decoration: with no human factual audit in the loop, the citation *is* the
correctness mechanism, so it has to survive all the way to the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

# Chunks are kept small because the generation model has a 4096-token context
# and a 0.5B model degrades quickly when the prompt is padded with marginally
# relevant text. Small chunks + low top-k beats large chunks + high top-k here.
TARGET_CHARS = 800
OVERLAP_CHARS = 150
MIN_CHARS = 120

# Hard ceiling. bge-small-en-v1.5 truncates at 512 tokens (roughly 2000 chars),
# so anything longer is silently discarded at embed time — the text stays in the
# chunk and gets shown to the model, but the part past the cut never influences
# whether the chunk is retrieved at all. Tables and figure captions in the MoFA
# PDFs extract as one enormous "paragraph" with no sentence punctuation, which
# is exactly how a 9000-character chunk got through.
MAX_CHARS = 1600


@dataclass
class Chunk:
    chunk_id: str
    source_id: str
    text: str
    attribution: str
    ghana_specific: bool
    caveat: str | None
    crops: list[str]
    topics: list[str]
    section: str | None

    def as_dict(self) -> dict:
        return asdict(self)


def parse_header(raw: str) -> tuple[dict, str]:
    """Split the `# key: value` provenance header from the body text."""
    meta: dict[str, str] = {}
    lines = raw.splitlines()
    i = 0
    for i, line in enumerate(lines):
        if not line.startswith("#"):
            break
        stripped = line.lstrip("#").strip()
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            meta[key.strip().lower()] = value.strip()
    return meta, "\n".join(lines[i:]).strip()


def clean(text: str) -> str:
    """Repair the usual PDF-extraction damage."""
    # Hyphenation across line breaks: "fertil-\nizer" -> "fertilizer"
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    # The MoFA guides use the Unicode replacement char where quotes were.
    text = text.replace("�", "'")
    # Collapse runs of whitespace but keep paragraph breaks meaningful.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Front matter retrieves well and answers nothing. A table of contents is dense
# with exactly the words a farmer's question contains ("maize", "planting",
# "pests") attached to page numbers instead of facts — so it competes directly
# with the passages that do hold the answer. Observed: a question about maize
# varieties retrieved the variety catalogue's contents page.
BOILERPLATE_MARKERS = (
    "acknowledgement",
    "acknowledgements",
    "foreword",
    "acronyms",
    "table of contents",
    "all rights reserved",
    "isbn",
    "for resale or other commercial purposes",
    "the designations employed and the presentation",
    "bibliographic",
    "cataloguing-in-publication",
)


def is_boilerplate(text: str) -> bool:
    """Front matter, copyright pages and contents listings — retrievable noise."""
    low = text.lower()
    if sum(1 for m in BOILERPLATE_MARKERS if m in low) >= 2:
        return True
    # A contents listing: many lines ending in a page number, little prose.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 4:
        numbered = sum(1 for ln in lines if re.search(r"[.\s]\d{1,3}\s*$", ln))
        if numbered / len(lines) > 0.6:
            return True
    # Mostly digits and dots (index/page tables).
    alpha = sum(c.isalpha() for c in text)
    if alpha and alpha / max(len(text), 1) < 0.45:
        return True
    return False


def looks_like_heading(line: str) -> bool:
    """Detect section headings so chunks can be labelled with their section."""
    s = line.strip()
    if not (3 < len(s) < 90):
        return False
    # "3.2 LAND PREPARATION" or "LAND PREPARATION"
    if re.match(r"^\d+(\.\d+)*\s+[A-Z][A-Za-z &/'-]+$", s):
        return True
    if s.isupper() and sum(c.isalpha() for c in s) >= 4:
        return True
    return False


def split_paragraphs(body: str) -> list[tuple[str, str | None]]:
    """Yield (paragraph, current_section) pairs."""
    out: list[tuple[str, str | None]] = []
    section: str | None = None
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        first = block.splitlines()[0]
        if looks_like_heading(first):
            section = first.strip()
            rest = "\n".join(block.splitlines()[1:]).strip()
            if rest:
                out.append((rest, section))
            continue
        out.append((block, section))
    return out


def _hard_wrap(piece: str, limit: int = TARGET_CHARS) -> list[str]:
    """Break a piece with no sentence punctuation on whitespace instead.

    Without this, an extracted table arrives as a single multi-thousand
    character 'sentence' and sails past every other boundary check.
    """
    if len(piece) <= limit:
        return [piece]
    out: list[str] = []
    words = piece.split(" ")
    buf: list[str] = []
    size = 0
    for word in words:
        if size + len(word) + 1 > limit and buf:
            out.append(" ".join(buf))
            buf, size = [], 0
        buf.append(word)
        size += len(word) + 1
    if buf:
        out.append(" ".join(buf))
    return out


def chunk_document(source_id: str, raw: str, src_meta: dict) -> list[Chunk]:
    header, body = parse_header(raw)
    body = clean(body)

    attribution = src_meta.get("attribution") or header.get("attribution") or source_id
    ghana = bool(src_meta.get("ghana_specific", True))
    caveat = src_meta.get("caveat")
    crops = list(src_meta.get("crops") or [])
    topics = list(src_meta.get("topics") or [])

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_len = 0
    buf_section: str | None = None

    def flush() -> None:
        nonlocal buf, buf_len, buf_section
        text = "\n".join(buf).strip()
        # Belt and braces: whatever the upstream splitting did, never emit a
        # chunk longer than the embedder's window.
        for part in _hard_wrap(text, MAX_CHARS) if len(text) > MAX_CHARS else [text]:
            if len(part) < MIN_CHARS or is_boilerplate(part):
                continue
            chunks.append(
                Chunk(
                    chunk_id=f"{source_id}#{len(chunks):04d}",
                    source_id=source_id,
                    text=part,
                    attribution=attribution,
                    ghana_specific=ghana,
                    caveat=caveat,
                    crops=crops,
                    topics=topics,
                    section=buf_section,
                )
            )
        # Carry a tail of the previous chunk so a fact split across a boundary
        # is still retrievable from at least one side of it.
        if OVERLAP_CHARS and text:
            tail = text[-OVERLAP_CHARS:]
            buf = [tail]
            buf_len = len(tail)
        else:
            buf, buf_len = [], 0

    for para, section in split_paragraphs(body):
        if buf_section is None:
            buf_section = section
        # A very long paragraph gets hard-split on sentence boundaries, then —
        # for text with no sentence punctuation at all, like extracted tables —
        # on whitespace, so nothing can exceed the embedder's window.
        pieces = [para] if len(para) <= TARGET_CHARS else re.split(r"(?<=[.!?])\s+", para)
        pieces = [p for piece in pieces for p in _hard_wrap(piece)]
        for piece in pieces:
            if buf_len + len(piece) > TARGET_CHARS and buf_len:
                flush()
                buf_section = section
            buf.append(piece)
            buf_len += len(piece)
    flush()

    # flush() seeds the next buffer with an overlap tail; if nothing followed,
    # that tail became a trailing duplicate chunk. Drop it.
    if len(chunks) > 1 and chunks[-1].text in chunks[-2].text:
        chunks.pop()

    return chunks


def build_all(text_dir: Path, sources: list[dict]) -> list[Chunk]:
    by_id = {s["id"]: s for s in sources}
    out: list[Chunk] = []
    for path in sorted(text_dir.glob("*.txt")):
        sid = path.stem
        meta = by_id.get(sid, {})
        out.extend(chunk_document(sid, path.read_text(encoding="utf-8"), meta))
    return out
