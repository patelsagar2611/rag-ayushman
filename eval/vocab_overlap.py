"""Measure how much each golden question's wording is borrowed from its target page.

The concern this quantifies: the golden set was written by someone reading the
documents, so questions tend to reuse the documents' own phrasing ("cover amount on
family floater basis" rather than "how much money do I get for an operation").
**BM25 scores exactly that lexical overlap**, so BM25's measured lead over the
embeddings may be a property of who wrote the questions rather than of the corpus.

Two jobs:

1. Turn "the questions probably reuse document vocabulary" into a number, so the
   claim in the README is measured rather than asserted.
2. Select rows to paraphrase by an objective rule -- highest overlap first, where
   the bias bites hardest -- rather than by picking ones that look convenient.

Deliberately uses `src.retrieve.tokenize`, the SAME tokenizer BM25 uses, rather than
a second one. The number is meant to be what BM25 sees, and a private tokenizer here
would measure something adjacent to it instead.

Stopwords are removed before scoring: "what is the" overlaps with every page in the
corpus and would swamp the signal. The list is deliberately short and generic -- a
longer, tuned one would be fitting the measurement to the answer.

    python -m eval.vocab_overlap [N]      # N rows to list, default 20
"""

import sys
from collections import defaultdict
from pathlib import Path
import json

from eval.run_eval import GOLDEN, PAGES, load_golden
from src.retrieve import tokenize

# Short and generic on purpose -- see module docstring.
STOP = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
    "do", "does", "did", "can", "could", "should", "would", "will", "shall",
    "of", "in", "on", "at", "to", "for", "from", "by", "with", "as", "and",
    "or", "but", "if", "than", "that", "this", "these", "those", "it", "its",
    "there", "have", "has", "had", "not", "no", "any", "all", "much", "many",
}


def page_text():
    """(source_file, page_number) -> text, from the extraction output."""
    out = {}
    with PAGES.open(encoding="utf-8") as handle:
        for line in handle:
            rec = json.loads(line)
            out[(rec["source_file"], rec["page_number"])] = rec["text"]
    return out


def overlap(question, pages, targets):
    """Fraction of the question's content tokens that appear on ANY target page.

    ANY rather than all: a question with two target pages is answered by either, so
    borrowing vocabulary from one of them is the same contamination as borrowing
    from both. Taking the union is also the generous reading -- it can only make the
    measured overlap higher, so it cannot understate the problem being tested for.
    """
    q = [t for t in tokenize(question) if t not in STOP]
    if not q:
        return None, [], []
    corpus = set()
    for target in targets:
        corpus.update(tokenize(pages.get(target, "")))
    hit = [t for t in q if t in corpus]
    miss = [t for t in q if t not in corpus]
    return len(hit) / len(q), hit, miss


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    pages = page_text()
    rows = []
    for case in load_golden(GOLDEN):
        if not case.targets:          # abstain questions have no target page
            continue
        score, hit, miss = overlap(case.question, pages, case.targets)
        if score is not None:
            rows.append((score, case, hit, miss))

    rows.sort(key=lambda r: -r[0])
    scores = [r[0] for r in rows]
    print(f"{len(rows)} answerable questions scored against {PAGES}\n")
    print(f"  mean overlap   {sum(scores)/len(scores):6.1%}")
    print(f"  median         {sorted(scores)[len(scores)//2]:6.1%}")
    print(f"  >= 90%         {sum(1 for s in scores if s >= 0.9):3d} questions")
    print(f"  100%           {sum(1 for s in scores if s >= 1.0):3d} questions "
          "(every content word appears on the target page)")
    print(f"  <= 50%         {sum(1 for s in scores if s <= 0.5):3d} questions\n")

    print(f"top {limit} by overlap -- the rows a paraphrase test should target:\n")
    for score, case, hit, miss in rows[:limit]:
        print(f"  row {case.row:3d}  {score:5.1%}  {case.question[:66]}")
        if miss:
            print(f"           words NOT on the page: {', '.join(miss[:8])}")


if __name__ == "__main__":
    main()
