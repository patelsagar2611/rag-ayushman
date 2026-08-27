"""Draft lay-language paraphrases of the highest-overlap golden questions.

Tests whether BM25's measured lead over the embeddings is a property of the corpus
or of who wrote the questions. See eval/vocab_overlap.py for the bias itself:
mean overlap 78.1%, and 15 of 60 questions reuse EVERY content word from their
target page.

The design constraint, and the whole difficulty: whoever rewrites a question must
know what is being asked without reproducing how the document says it.

  * The model is given the QUESTION and the human-written EXPECTED ANSWER, and
    **never any page text**. Those two fields are the project author's words, not the
    corpus's, so the rewriter cannot borrow phrasing it is being tested for avoiding.
    The expected answer is included because without it a question like "Who is NGNO?"
    cannot be rephrased at all -- you cannot ask for something in plain words if you
    do not know what it is.
  * It is NOT asked to invent questions. It rewrites verified ones, and the fact,
    the target pages and the must_contain value all stay exactly as the human wrote
    them. That is what keeps this inside the project's anti-goal on LLM-authored eval
    questions: there is no LLM judge, and nothing about correctness is delegated.
  * Output is reviewed by hand before the experiment runs. An LLM draft that a human
    accepts is a different thing from an LLM-generated eval set.

Pinned to one provider, so the paraphrase set itself is reproducible (README gotcha
16) -- a question set that changed between runs would undermine the comparison it
exists to support.

    python -m eval.make_paraphrases [N]     # N highest-overlap rows, default 20
"""

import csv
import sys
from pathlib import Path

from eval.run_eval import GOLDEN, load_golden
from eval.vocab_overlap import overlap, page_text
from src.generate import call_llm, LLM_MODEL, LLM_PROVIDER

OUT = Path("eval/paraphrase_set.csv")

# Rejected at hand review 2026-08-27, and kept named here rather than silently
# filtered so the exclusion is auditable.
#
#   15, 68  the rewriter expanded a domain acronym into the WRONG domain --
#           EHCP (Empanelled Health Care Provider) became a UK "Education, Health
#           and Care Plan", and NHA (National Health Authority) became a housing
#           authority. Different question, so no longer paired.
#   31      drifted from a system-level threshold ("10% or less of grievances
#           escalating") to an individual's complaint count.
#
# Dropping these is the CONSERVATIVE direction, which is why it is the right one:
# 15 and 68 are the most jargon-dense rows in the set, so they are where BM25's
# lexical advantage is largest and where a correct paraphrase would cost it most.
# Excluding them makes the vocabulary effect HARDER to detect, not easier.
#
# The failures are themselves a small result: two questions were so bound to
# document vocabulary that their MEANING was unrecoverable without the corpus.
REJECTED = {15, 68, 31}

# No corpus text reaches this prompt -- see the module docstring. "Same information
# need" is the load-bearing instruction: a paraphrase that drifts to a different
# question would be answered by a different page, and the test would no longer be
# paired.
PROMPT = """Rewrite this question the way an ordinary member of the public would ask it.

They have no knowledge of government administrative vocabulary, scheme documents, \
official job titles or acronyms. They know only their own situation and what they \
want to find out.

Rules:
- Keep the SAME information need. The same answer must satisfy it.
- Replace administrative jargon and acronyms with everyday words.
- Do not copy distinctive phrasing from the original question.
- Do not add detail that is not in the original.
- Return ONLY the rewritten question, one line, no quotes or preamble.

Original question: {question}
The answer is: {answer}"""


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    print(f"paraphrasing with {LLM_PROVIDER}/{LLM_MODEL}\n")

    pages = page_text()
    scored = []
    for case in load_golden(GOLDEN):
        if not case.targets:
            continue
        score, _, _ = overlap(case.question, pages, case.targets)
        if score is not None:
            scored.append((score, case))
    scored.sort(key=lambda r: (-r[0], r[1].row))

    rows = []
    for score, case in scored[:limit]:
        if case.row in REJECTED:
            print(f"row {case.row:3d}   SKIPPED at review -- see REJECTED\n")
            continue
        text, _ = call_llm(PROMPT.format(
            question=case.question, answer=case.expected_answer))
        new = " ".join(text.strip().splitlines()[0].strip().strip('"').split())
        after, _, _ = overlap(new, pages, case.targets)
        rows.append((case, new, score, after))
        print(f"row {case.row:3d}   overlap {score:5.1%} -> {after:5.1%}")
        print(f"  was: {case.question}")
        print(f"  now: {new}\n")

        # `page` and `source_file` are written back in the SAME ';'-joined form the
        # golden set uses, paired positionally -- run_eval.build_targets reads both
        # files with one parser, so a different convention here would silently
        # retarget questions.
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["question", "expected_answer", "source_file", "page",
                         "must_contain", "notes"])
        for case, new, before, after in rows:
            writer.writerow([
                new,
                case.expected_answer,
                ";".join(f for f, _ in case.targets),
                ";".join(str(p) for _, p in case.targets),
                ";".join(case.must_contain),
                f"paraphrase of golden row {case.row}; overlap {before:.0%}->{after:.0%}; "
                f"drafted by {LLM_MODEL}, human-reviewed",
            ])

    moved = [a - b for _, _, b, a in rows]
    print(f"wrote {OUT} ({len(rows)} questions)")
    print(f"mean overlap {sum(b for _,_,b,_ in rows)/len(rows):.1%} -> "
          f"{sum(a for _,_,_,a in rows)/len(rows):.1%}  "
          f"(mean change {sum(moved)/len(moved):+.1%})")
    print("\nREVIEW THESE BY HAND before running the experiment. A paraphrase that")
    print("drifted to a different information need is answered by a different page,")
    print("and the comparison stops being paired.")


if __name__ == "__main__":
    main()
