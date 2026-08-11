"""Fetch every source in sources.yaml, verify it is really a PDF, extract text.

Run from the repo root:
    python corpus/fetch_sources.py

Writes:
    corpus/raw/<id>.pdf        the original download (gitignored, large)
    corpus/text/<id>.txt       extracted text with a provenance header
    corpus/fetch_report.json   what worked, what didn't, and why

Deliberately conservative: a source that returns HTML instead of a PDF, or
whose text extraction yields almost nothing (i.e. a scanned image PDF), is
reported as a failure rather than silently producing an empty document.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
TEXT = HERE / "text"

# A PDF whose extracted text is shorter than this is almost certainly scanned
# images rather than embedded text, and needs OCR we are not doing.
MIN_CHARS = 2000

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def fetch(url: str, dest: Path) -> tuple[bool, str]:
    """Download url to dest. Returns (ok, message)."""
    if dest.exists() and dest.stat().st_size > 0:
        return True, f"cached ({dest.stat().st_size:,} bytes)"
    # Percent-encode the path so URLs with literal spaces or parentheses work,
    # while leaving an already-encoded URL untouched.
    parts = urllib.parse.urlsplit(url)
    safe = urllib.parse.urlunsplit(
        parts._replace(path=urllib.parse.quote(parts.path, safe="/%()&"))
    )
    req = urllib.request.Request(safe, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            body = resp.read()
    except Exception as exc:  # never let one bad source abort the whole run
        return False, f"fetch failed: {type(exc).__name__}: {exc}"

    # Trust the magic bytes over the Content-Type header; some servers lie.
    if not body.startswith(b"%PDF"):
        return False, f"not a PDF (content-type={ctype!r}, {len(body):,} bytes)"

    dest.write_bytes(body)
    return True, f"downloaded ({len(body):,} bytes)"


def extract(pdf: Path, src: dict, dest: Path) -> tuple[bool, str]:
    try:
        reader = PdfReader(pdf)
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as exc:  # pypdf raises a variety of things on damaged files
        return False, f"extract failed: {exc}"

    text = "\n".join(pages).strip()
    if len(text) < MIN_CHARS:
        return False, f"only {len(text):,} chars from {len(pages)} pages — likely a scanned PDF, needs OCR"

    header = (
        f"# {src['title']}\n"
        f"# publisher: {src['publisher']}\n"
        f"# year: {src.get('year') or 'unknown'}\n"
        f"# url: {src['url']}\n"
        f"# attribution: {src['attribution']}\n"
        f"# pages: {len(pages)}\n"
        f"#\n"
        f"# Extracted text follows. Provenance above travels with every chunk\n"
        f"# derived from this document.\n\n"
    )
    dest.write_text(header + text, encoding="utf-8")
    return True, f"{len(text):,} chars from {len(pages)} pages"


def main() -> int:
    manifest = yaml.safe_load((HERE / "sources.yaml").read_text(encoding="utf-8"))
    RAW.mkdir(exist_ok=True)
    TEXT.mkdir(exist_ok=True)

    report = []
    for src in manifest["sources"]:
        if src.get("status") == "dead":
            continue
        sid = src["id"]
        pdf = RAW / f"{sid}.pdf"
        txt = TEXT / f"{sid}.txt"

        ok, msg = fetch(src["url"], pdf)
        if ok:
            ok, msg = extract(pdf, src, txt)

        status = "ok" if ok else "FAILED"
        print(f"{status:7} {sid:28} {msg}")
        report.append({"id": sid, "ok": ok, "message": msg, "url": src["url"]})

    (HERE / "fetch_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    good = sum(1 for r in report if r["ok"])
    print(f"\n{good}/{len(report)} sources usable")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
