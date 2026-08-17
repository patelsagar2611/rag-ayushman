"""Extract text from data/raw/*.pdf, one record per page.

Page numbers are captured here and carried by every downstream stage. Citations
are the point of this project, so no stage is allowed to drop them.

Output: data/processed/pages.jsonl -- {text, source_file, page_number}
"""

import json
from pathlib import Path

import pymupdf

RAW = Path("data/raw")
OUT = Path("data/processed/pages.jsonl")


def extract_pdf(path):
    """Yield one record per page that contains extractable text.

    page_number is 1-based so it matches what a PDF viewer displays -- a reader
    following a citation should be able to type it straight into the page box.
    """
    doc = pymupdf.open(path)
    try:
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            if not text:
                continue
            yield {"text": text, "source_file": path.name, "page_number": i + 1}
    finally:
        doc.close()


def main():
    pdfs = sorted(RAW.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"no PDFs in {RAW} -- run `python -m src.download` first")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with OUT.open("w", encoding="utf-8") as f:
        for pdf in pdfs:
            n = 0
            for record in extract_pdf(pdf):
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                n += 1
            total += n
            print(f"{pdf.name:38s} {n:4d} pages with text")

    print(f"\n{total} pages -> {OUT}")


if __name__ == "__main__":
    main()
