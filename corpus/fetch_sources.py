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


def fetch(url: str, dest: Path, want: str = "pdf") -> tuple[bool, str]:
    """Download url to dest. `want` is 'pdf' or 'html'. Returns (ok, message)."""
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
    if want == "pdf" and not body.startswith(b"%PDF"):
        return False, f"not a PDF (content-type={ctype!r}, {len(body):,} bytes)"
    if want == "html" and body.startswith(b"%PDF"):
        return False, "declared html but served a PDF — fix `format` in sources.yaml"

    dest.write_bytes(body)
    return True, f"downloaded ({len(body):,} bytes)"


def extract_html(path: Path, src: dict, dest: Path) -> tuple[bool, str]:
    """Pull readable prose out of an HTML page, dropping chrome and scripts."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_bytes(), "lxml")

    # Navigation, scripts and styles are noise that would otherwise be indexed
    # and retrieved as if it were agronomic content.
    for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript"]):
        tag.decompose()

    # Prefer the page's main content region when it declares one.
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = main.get_text("\n", strip=True)

    # Collapse the run of near-empty lines that get_text tends to leave behind.
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)

    if len(text) < MIN_CHARS:
        return False, f"only {len(text):,} chars of text — page may be JS-rendered or paywalled"

    dest.write_text(_header(src, f"{len(text.splitlines())} lines") + text, encoding="utf-8")
    return True, f"{len(text):,} chars of HTML text"


def _header(src: dict, extent: str) -> str:
    caveat = src.get("caveat")
    lines = [
        f"# {src['title']}",
        f"# publisher: {src['publisher']}",
        f"# year: {src.get('year') or 'unknown'}",
        f"# url: {src['url']}",
        f"# attribution: {src['attribution']}",
        f"# ghana_specific: {src.get('ghana_specific', True)}",
        f"# extent: {extent}",
    ]
    if caveat:
        lines.append(f"# CAVEAT: {caveat}")
    lines += [
        "#",
        "# Extracted text follows. Provenance above travels with every chunk",
        "# derived from this document.",
        "",
        "",
    ]
    return "\n".join(lines)


def extract(pdf: Path, src: dict, dest: Path) -> tuple[bool, str]:
    try:
        reader = PdfReader(pdf)
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception as exc:  # pypdf raises a variety of things on damaged files
        return False, f"extract failed: {exc}"

    text = "\n".join(pages).strip()
    if len(text) < MIN_CHARS:
        return False, f"only {len(text):,} chars from {len(pages)} pages — likely a scanned PDF, needs OCR"

    dest.write_text(_header(src, f"{len(pages)} pages") + text, encoding="utf-8")
    return True, f"{len(text):,} chars from {len(pages)} pages"


def main() -> int:
    manifest = yaml.safe_load((HERE / "sources.yaml").read_text(encoding="utf-8"))
    RAW.mkdir(exist_ok=True)
    TEXT.mkdir(exist_ok=True)

    report = []
    for src in manifest["sources"]:
        if src.get("status") == "dead":
            continue
        if src.get("derived"):
            # Derived documents are hand-restructured from a source already in
            # the corpus. Their `url` points at that original for verification,
            # so fetching it would overwrite the derived text with the raw PDF.
            txt = TEXT / f"{src['id']}.txt"
            ok = txt.exists()
            print(f"{'ok' if ok else 'MISSING':7} {src['id']:28} derived from {src.get('derived_from')}")
            report.append({"id": src["id"], "ok": ok, "message": "derived", "url": src["url"]})
            continue
        sid = src["id"]
        fmt = src.get("format", "pdf")
        raw = RAW / f"{sid}.{fmt}"
        txt = TEXT / f"{sid}.txt"

        ok, msg = fetch(src["url"], raw, want=fmt)
        if ok:
            ok, msg = (extract_html if fmt == "html" else extract)(raw, src, txt)

        status = "ok" if ok else "FAILED"
        print(f"{status:7} {sid:28} {msg}")
        report.append({"id": sid, "ok": ok, "message": msg, "url": src["url"]})

    (HERE / "fetch_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    good = sum(1 for r in report if r["ok"])
    print(f"\n{good}/{len(report)} sources usable")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
