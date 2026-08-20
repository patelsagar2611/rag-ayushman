"""Find which file and page contains a phrase, for filling in the golden set.

Plain keyword search over the extracted text -- deliberately NOT vector search.
Using the system's own retrieval to decide which page an answer is on would be
circular: you would be grading the system against its own output, and it would
score perfectly by construction. Deterministic string matching keeps the golden
set independent of the thing it is measuring.

Usage:
    python -m eval.find "inpatient beds"
    python -m eval.find "show-cause notice" --file empanelment_v2_0.pdf
    python -m eval.find "\\d+ working days" --regex
    python -m eval.find "penalty" --context 200
"""

import argparse
import json
import re
import sys
from pathlib import Path

PAGES = Path("data/processed/pages.jsonl")

# The Windows console defaults to cp1252, which cannot encode the ellipsis or
# the stray characters PDF extraction leaves behind -- printing one crashed the
# tool mid-search. Replace rather than raise: a garbled character in a snippet
# is fine, losing the page number is not.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_pages(only_file=None):
    if not PAGES.exists():
        raise SystemExit(f"{PAGES} not found -- run `python -m src.extract` first")

    pages = []
    with PAGES.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if only_file and only_file.lower() not in rec["source_file"].lower():
                continue
            # Collapse whitespace: PDF extraction litters sentences with newlines,
            # so "10 inpatient beds" is often stored as "10 inpatient\nbeds" and a
            # naive search would miss it.
            pages.append(
                (rec["source_file"], rec["page_number"], re.sub(r"\s+", " ", rec["text"]))
            )
    return pages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phrase")
    parser.add_argument("--file", default=None, help="restrict to filenames containing this")
    parser.add_argument("--regex", action="store_true", help="treat phrase as a regex")
    parser.add_argument("--context", type=int, default=120, help="characters of context")
    parser.add_argument("--max", type=int, default=40, help="maximum matches to show")
    args = parser.parse_args()

    pattern = re.compile(args.phrase if args.regex else re.escape(args.phrase), re.I)
    pages = load_pages(args.file)

    total = 0
    per_file = {}
    for source_file, page, text in pages:
        for m in pattern.finditer(text):
            total += 1
            per_file[source_file] = per_file.get(source_file, 0) + 1
            if total <= args.max:
                start = max(0, m.start() - args.context // 2)
                end = min(len(text), m.end() + args.context // 2)
                snippet = text[start:end].strip()
                prefix = "…" if start > 0 else ""
                suffix = "…" if end < len(text) else ""
                print(f"\n{source_file}  p.{page}")
                print(f"  {prefix}{snippet}{suffix}")

    if not total:
        print(f"no match for {args.phrase!r}"
              + (f" in files matching {args.file!r}" if args.file else ""))
        print("try fewer words, or --regex for a looser pattern")
        return

    print(f"\n{'=' * 60}")
    print(f"{total} match(es)" + (f", showing first {args.max}" if total > args.max else ""))
    for name in sorted(per_file, key=lambda n: -per_file[n]):
        print(f"  {per_file[name]:4d}  {name}")
    print("\nPage numbers above are what goes in the golden set's `page` column.")


if __name__ == "__main__":
    main()
