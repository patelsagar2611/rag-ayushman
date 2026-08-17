"""Chunk pages into ~600-token windows with ~100 tokens of overlap.

A chunk never spans a page boundary, so every chunk carries exactly one page
number and a citation always points at a page that genuinely contains the text.
The cost is real and worth stating: a short page yields a short chunk, and a
paragraph running across a page break is split in the index too. Revisit this if
the eval shows answers being cut in half at page boundaries.

Output: data/processed/chunks.jsonl -- {chunk_id, text, source_file, page, char_start}
"""

import json
import re
from pathlib import Path

PAGES = Path("data/processed/pages.jsonl")
OUT = Path("data/processed/chunks.jsonl")

# ~600 tokens of target size and ~100 tokens of overlap, at the usual English
# approximation of 4 characters per token.
TARGET_CHARS = 2400
OVERLAP_CHARS = 400

_PARA_BREAK = re.compile(r"\n\s*\n")


def paragraph_starts(text):
    """Character offsets where a blank-line-separated block begins."""
    starts = [0]
    for m in _PARA_BREAK.finditer(text):
        starts.append(m.end())
    return starts


def split_page(text):
    """Yield (chunk_text, char_start) windows covering one page's text.

    Cuts land on a paragraph boundary where one is available in the back half of
    the window, and fall back to a hard character cut where none is -- government
    PDFs contain long tables that carry no blank lines at all.
    """
    n = len(text)
    if n <= TARGET_CHARS:
        yield text, 0
        return

    starts = paragraph_starts(text)
    start = 0
    while start < n:
        end = start + TARGET_CHARS
        if end >= n:
            yield text[start:], start
            return

        midpoint = start + TARGET_CHARS // 2
        cut = max((s for s in starts if midpoint < s <= end), default=end)
        yield text[start:cut], start

        # Carry the tail forward so a boundary mid-sentence does not destroy
        # context on both sides. max() guards against a cut so close to start
        # that the window would fail to advance.
        start = max(cut - OVERLAP_CHARS, start + 1)


def main():
    if not PAGES.exists():
        raise SystemExit(f"{PAGES} not found -- run `python -m src.extract` first")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    per_file = {}
    total = 0

    with PAGES.open(encoding="utf-8") as fin, OUT.open("w", encoding="utf-8") as fout:
        for line in fin:
            page = json.loads(line)
            stem = Path(page["source_file"]).stem
            for i, (text, char_start) in enumerate(split_page(page["text"])):
                chunk = {
                    "chunk_id": f"{stem}_p{page['page_number']:04d}_{i:02d}",
                    "text": text,
                    "source_file": page["source_file"],
                    "page": page["page_number"],
                    "char_start": char_start,
                }
                fout.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                per_file[page["source_file"]] = per_file.get(page["source_file"], 0) + 1
                total += 1

    for name in sorted(per_file):
        print(f"{name:38s} {per_file[name]:5d} chunks")
    print(f"\n{total} chunks -> {OUT}")


if __name__ == "__main__":
    main()
