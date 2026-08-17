"""Report which downloaded PDFs are text-native and which are scanned images.

Open question #1 in the brief: a scanned PDF yields near-zero extractable text
and would silently contribute nothing to the index. Run this before trusting the
corpus.
"""

from pathlib import Path

import pymupdf

RAW = Path("data/raw")

# Text-native government manuals run well over a thousand characters per page.
# Anything this low is either a scan or a cover-art-heavy document.
SCANNED_CHARS_PER_PAGE = 100


def profile(path):
    doc = pymupdf.open(path)
    try:
        chars = [len(page.get_text().strip()) for page in doc]
    finally:
        doc.close()
    pages = len(chars)
    total = sum(chars)
    return {
        "pages": pages,
        "total_chars": total,
        "chars_per_page": total / pages if pages else 0,
        "empty_pages": sum(1 for c in chars if c == 0),
    }


def main():
    pdfs = sorted(RAW.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"no PDFs in {RAW} -- run `python -m src.download` first")

    print(f"{'file':38s} {'pages':>6s} {'chars/pg':>9s} {'empty':>6s}  verdict")
    print("-" * 78)

    suspect = []
    for pdf in pdfs:
        try:
            p = profile(pdf)
        except Exception as e:
            print(f"{pdf.name:38s} {'':>6s} {'':>9s} {'':>6s}  UNREADABLE ({type(e).__name__})")
            suspect.append(pdf.name)
            continue

        scanned = p["chars_per_page"] < SCANNED_CHARS_PER_PAGE
        verdict = "SCANNED - needs OCR" if scanned else "text-native"
        if scanned:
            suspect.append(pdf.name)
        print(
            f"{pdf.name:38s} {p['pages']:6d} {p['chars_per_page']:9.0f} "
            f"{p['empty_pages']:6d}  {verdict}"
        )

    print(f"\n{len(pdfs)} PDFs, {len(suspect)} needing attention")
    if suspect:
        print("set aside rather than blocking on them: " + ", ".join(suspect))


if __name__ == "__main__":
    main()
