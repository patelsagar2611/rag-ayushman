"""Precompute the showcase answers that the demo serves without calling anything.

WHY. The deployed demo runs on a free tier of ~200,000 tokens/day, and each query
costs ~2,600 prompt tokens -- roughly 80 questions per DAY for the entire world.
One enthusiastic visitor can drain it. Most visitors click a suggested question
rather than composing one, so serving those from disk removes the common path from
the budget entirely.

It also removes them from the LATENCY budget: the retrieved chunks are stored
alongside the answer, so a showcase question costs neither an LLM call nor a
retrieval pass. That matters most for `rerank`, which is ~3.5-5 s of cross-encoder
work on the deployed hardware.

WHAT IS STORED, AND WHY IT IS HONEST. These are real answers from a real run, not
hand-written text: same prompt, same retriever, same model as a live query. The UI
labels them as precomputed so nobody reads the instant response as system speed.
The provenance block records what produced them, so a stale file is detectable
rather than silently wrong -- if the prompt version or the model changes, the
answers no longer describe the deployed system and should be regenerated.

The questions are golden-set rows, deliberately. They are hand-verified, their
answers are known, and using them lets the demo say the suggestions come from the
same 69-question set every published number is measured on.

Usage:
    python -m eval.make_showcase                 # both modes
    python -m eval.make_showcase --modes vector  # one mode
    python -m eval.make_showcase --dry-run       # show what would be asked
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.generate import (
    LLM_BACKEND,
    LLM_MODEL,
    LLM_PROVIDER,
    PROMPT_VERSION,
    answer_from_hits,
)
from src.retrieve import DEFAULT_K, search

OUT = Path("config/showcase.json")

# Golden-set questions, chosen to show a different behaviour each. The comment on
# each is what it demonstrates -- a showcase that only shows easy wins is an advert,
# not a demo.
SHOWCASE = [
    # The headline fact of the scheme, and the question every visitor asks first.
    "What is cover amount under PM JAY for family floater basis?",
    # A concrete eligibility number, answered from a paragraph rather than a table.
    "What is the minimum number of inpatient beds required for a hospital to be empanelled under PM-JAY?",
    # Practical, and the answer appears in several documents.
    "What is primary identity document for family member under PM-JAY?",
    # A timeline a real user would need.
    "If any party to a grievance is not satisfied, then how many days it has to appeal that decision?",
    # A tariff, and the same figure appears across two policy versions.
    "What is per day price for bed if patient is admitted to ICU with ventilator support?",
    # The corpus CONTRADICTS ITSELF here -- 48 hrs on one page, 7 days on another.
    "By what timeline, mortality report section 5.1 and 5.2 has to be filled by the hospital and sent?",
    # Extracted from a table rather than prose.
    "How much incentive will hospital receive with full NABH accreditation?",
    # ABSTENTION. A plausible, in-domain question the corpus simply does not answer.
    # A visitor learns more from this than from an obviously off-topic question,
    # because it shows the system declining something it might have been expected
    # to know rather than something nobody would ask.
    "What should be minimum revenue of hospital to be eligible for empanelment application?",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modes", default="vector,rerank",
                    help="comma-separated retrieval modes to precompute")
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    total = len(SHOWCASE) * len(modes)
    print(f"{len(SHOWCASE)} questions x {len(modes)} modes = {total} LLM calls "
          f"(~{total * 2600:,} prompt tokens)")
    if args.dry_run:
        for q in SHOWCASE:
            print(f"  {q}")
        return

    entries = []
    for mode in modes:
        for i, question in enumerate(SHOWCASE, start=1):
            print(f"[{mode} {i}/{len(SHOWCASE)}] {question[:60]}...", flush=True)
            hits = search(question, k=args.k, mode=mode)
            text, stats = answer_from_hits(question, hits)
            entries.append({
                "question": question,
                "mode": mode,
                "k": args.k,
                "answer": text,
                # Stored so the UI can render the evidence panel without running
                # retrieval again -- which is the whole point on rerank.
                "hits": [
                    {
                        "rank": h["rank"],
                        "source_file": h["source_file"],
                        "page": h["page"],
                        "score": h["score"],
                        "chunk_id": h["chunk_id"],
                        "text": h["text"],
                        "pre_rerank_rank": h.get("pre_rerank_rank"),
                    }
                    for h in hits
                ],
                "stats": stats,
            })

    payload = {
        # Provenance, so a stale file is detectable rather than silently wrong.
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt_version": PROMPT_VERSION,
        "llm_provider": LLM_PROVIDER,
        "llm_backend": LLM_BACKEND,
        "llm_model": LLM_MODEL,
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {OUT} -- {len(entries)} entries, "
          f"{OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
