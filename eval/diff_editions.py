"""Find where the two empanelment editions actually disagree.

Raw text diff is useless here -- the two files were typeset separately, so every
line differs on whitespace and page furniture. What matters for writing
version-conflict questions is narrower: sentences that say almost the same thing
in both documents but carry DIFFERENT NUMBERS. A bed count, a day limit, a
percentage that changed between editions is exactly the case where a naive RAG
system cites the superseded rule and sounds confident doing it.

Method:
  1. pull sentences containing numbers from both editions
  2. pair them up by token overlap (cheap prefilter) then difflib ratio
  3. keep pairs that are textually similar but numerically different
  4. also report numbered claims that exist in only one edition

Output: Docs/empanelment-diff.md
"""

import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

PAGES = Path("data/processed/pages.jsonl")
OUT = Path("Docs/empanelment-diff.md")

OLD = "empanelment_dec2021.pdf"
NEW = "empanelment_v2_0.pdf"

# Similar enough to be the same clause, not so similar it is the same text.
SIMILAR_ENOUGH = 0.55
NEAR_IDENTICAL = 0.995

# Numbers worth comparing. Skips bare page furniture like "Page 4 of 64".
NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)*\s*(?:%|percent|per cent)?", re.I)
SENTENCE_RE = re.compile(r"(?<=[.;:])\s+|\n(?=[A-Z0-9])")
PAGE_FURNITURE_RE = re.compile(r"^\s*page\s+\d+\s+of\s+\d+\s*$", re.I)
STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "for", "and", "or", "be", "is", "are",
    "shall", "will", "as", "at", "by", "on", "with", "that", "this", "any",
    "such", "from", "which", "has", "have", "been", "may", "not", "it", "its",
}


def load_sentences(source_file):
    """(sentence, page) for sentences that contain a digit."""
    out = []
    with PAGES.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec["source_file"] != source_file:
                continue
            text = re.sub(r"[ \t]+", " ", rec["text"])
            for raw in SENTENCE_RE.split(text):
                s = raw.strip().replace("\n", " ")
                if len(s) < 40 or len(s) > 400:
                    continue
                if PAGE_FURNITURE_RE.match(s) or not re.search(r"\d", s):
                    continue
                out.append((s, rec["page_number"]))
    return out


def numbers_in(sentence):
    """Comparable numbers, with page-reference noise stripped out."""
    cleaned = re.sub(r"\bpage\s+\d+\s+of\s+\d+\b", " ", sentence, flags=re.I)
    cleaned = re.sub(r"\b(?:section|clause|annexure|chapter)\s+[\d.]+", " ", cleaned, flags=re.I)
    found = set()
    for m in NUMBER_RE.finditer(cleaned):
        token = m.group().strip().lower().replace(" ", "")
        digits = token.rstrip("%").replace("percent", "").replace("percent", "")
        digits = digits.replace(",", "")
        if digits and digits not in {"0"}:
            found.add(token.replace("percent", "%").replace("percent", "%"))
    return found


def tokens(sentence):
    return {w for w in re.findall(r"[a-z]{3,}", sentence.lower()) if w not in STOPWORDS}


def build_index(sentences):
    """token -> indices, so we only compare sentences that share vocabulary."""
    index = defaultdict(set)
    for i, (s, _) in enumerate(sentences):
        for t in tokens(s):
            index[t].add(i)
    return index


def best_match(sentence, candidates, others):
    best, best_ratio = None, 0.0
    for j in candidates:
        ratio = SequenceMatcher(None, sentence, others[j][0]).ratio()
        if ratio > best_ratio:
            best, best_ratio = j, ratio
    return best, best_ratio


def compare(old, new):
    """Pairs that read alike but count differently, plus one-sided claims."""
    new_index = build_index(new)
    conflicts, only_old = [], []

    for old_sentence, old_page in old:
        old_tokens = tokens(old_sentence)
        if len(old_tokens) < 4:
            continue

        # Cheap prefilter: only sentences sharing several content words.
        counts = defaultdict(int)
        for t in old_tokens:
            for j in new_index.get(t, ()):
                counts[j] += 1
        candidates = [j for j, c in sorted(counts.items(), key=lambda kv: -kv[1])[:25]
                      if c >= max(3, len(old_tokens) // 4)]
        if not candidates:
            only_old.append((old_sentence, old_page))
            continue

        j, ratio = best_match(old_sentence, candidates, new)
        if j is None or ratio < SIMILAR_ENOUGH:
            only_old.append((old_sentence, old_page))
            continue
        if ratio >= NEAR_IDENTICAL:
            continue  # identical clause, nothing to ask about

        new_sentence, new_page = new[j]
        old_numbers, new_numbers = numbers_in(old_sentence), numbers_in(new_sentence)
        if old_numbers != new_numbers and (old_numbers or new_numbers):
            conflicts.append(
                {
                    "ratio": ratio,
                    "old": old_sentence, "old_page": old_page, "old_numbers": sorted(old_numbers),
                    "new": new_sentence, "new_page": new_page, "new_numbers": sorted(new_numbers),
                }
            )

    conflicts.sort(key=lambda c: -c["ratio"])
    return conflicts, only_old


def write_report(conflicts, only_old, only_new, old, new):
    lines = [
        "# Empanelment editions: where they disagree",
        "",
        "Generated by `python -m eval.diff_editions`. Raw material for writing the",
        "version-conflict questions in `eval/golden_set.csv` -- **not** a set of questions,",
        "and not a substitute for reading the pages it points at.",
        "",
        f"- `{OLD}` — 46pp, cover dated December 2021, no version number printed",
        f"- `{NEW}` — 64pp, cover states \"Version – 2.0\"",
        "",
        f"Numeric sentences compared: {len(old)} in the December 2021 edition, "
        f"{len(new)} in Version 2.0.",
        "",
        "**Which edition is currently in force is still unconfirmed.** This report shows",
        "*that* they differ and *where*; it cannot tell you which one is right. Settle that",
        "against NHA's own circulars before writing expected answers.",
        "",
        "---",
        "",
        f"## Same clause, different numbers ({len(conflicts)})",
        "",
        "The highest-value rows in this file. Each pair reads as the same provision in both",
        "editions but carries different figures — so a question about it has a different",
        "correct answer depending on which edition you trust, which is precisely what the",
        "version-conflict test cases are meant to catch.",
        "",
    ]

    if not conflicts:
        lines += ["_None found._", ""]

    for i, c in enumerate(conflicts, 1):
        lines += [
            f"### {i}. similarity {c['ratio']:.2f}",
            "",
            f"**Dec 2021, p.{c['old_page']}** — numbers: `{', '.join(c['old_numbers']) or '(none)'}`",
            "",
            f"> {c['old']}",
            "",
            f"**Version 2.0, p.{c['new_page']}** — numbers: `{', '.join(c['new_numbers']) or '(none)'}`",
            "",
            f"> {c['new']}",
            "",
        ]

    for title, rows, page_label in [
        (f"Numeric claims found only in the December 2021 edition ({len(only_old)})",
         only_old, "Dec 2021"),
        (f"Numeric claims found only in Version 2.0 ({len(only_new)})", only_new, "v2.0"),
    ]:
        lines += [
            "---",
            "",
            f"## {title}",
            "",
            "No close counterpart in the other edition. Some are genuinely new or removed",
            "provisions; some are just typesetting differences. Worth skimming for questions",
            "of the form \"was X ever required?\", where the answer depends on the edition.",
            "",
        ]
        for sentence, page in rows[:60]:
            lines.append(f"- **p.{page}** ({page_label}) — {sentence}")
        if len(rows) > 60:
            lines.append(f"- _…and {len(rows) - 60} more_")
        lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")


def main():
    if not PAGES.exists():
        raise SystemExit(f"{PAGES} not found -- run `python -m src.extract` first")

    old = load_sentences(OLD)
    new = load_sentences(NEW)
    if not old or not new:
        raise SystemExit(f"missing corpus text: {OLD}={len(old)}, {NEW}={len(new)}")

    print(f"{OLD}: {len(old)} numeric sentences")
    print(f"{NEW}: {len(new)} numeric sentences")
    print("comparing…")

    conflicts, only_old = compare(old, new)
    _, only_new = compare(new, old)

    write_report(conflicts, only_old, only_new, old, new)
    print(f"\n{len(conflicts)} same-clause-different-number pairs")
    print(f"{len(only_old)} numeric claims only in {OLD}")
    print(f"{len(only_new)} numeric claims only in {NEW}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
