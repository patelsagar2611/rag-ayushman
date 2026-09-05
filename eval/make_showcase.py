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
import time
from datetime import datetime, timezone
from pathlib import Path

from src.generate import (
    LLM_BACKEND,
    LLM_MODEL,
    LLM_PROVIDER,
    PROMPT_VERSION,
    answer_from_hits,
)
from src.retrieve import DEFAULT_K, RERANK_BATCH, search

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


def write(entries, complete):
    """Write the file as it currently stands.

    `complete=False` marks a run still in progress, so a file left behind by a
    crashed or rate-limited run is self-describing rather than looking like a
    finished one that is quietly missing half its questions.

    Nothing currently reads that flag -- the app treats a short file as a short
    file and falls through to a live call for anything absent, which is correct
    either way. It is recorded because the alternative is a file that cannot be
    distinguished from a complete one after the fact, and `git diff` on a
    half-written showcase is otherwise indistinguishable from a deliberate cut.
    """
    payload = {
        # Provenance, so a stale file is detectable rather than silently wrong.
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "complete": complete,
        "prompt_version": PROMPT_VERSION,
        "llm_provider": LLM_PROVIDER,
        "llm_backend": LLM_BACKEND,
        "llm_model": LLM_MODEL,
        # The timing environment, recorded because the file now carries TIMINGS
        # and a latency figure without the machine that produced it is not a
        # measurement. Both of these are worth ~50% of reranked latency on their
        # own (design decisions 32 and 34), and both are set by app.py in the
        # deployment while this script runs at the library defaults -- so these
        # numbers describe the development machine, NOT the deployed host, and
        # anything rendering them has to say so.
        "timing_env": timing_env(),
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def timing_env():
    """What was in effect when the timings were taken."""
    import platform

    import torch

    return {
        "machine": platform.system(),
        "torch_threads": torch.get_num_threads(),
        # None means the library default of 32 -- which is what every committed
        # eval number was measured under, and therefore what makes these timings
        # comparable to eval/results/.
        "rerank_batch": RERANK_BATCH,
        "note": "development machine, library defaults -- not the deployed host",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--modes", default="vector,rerank",
                    help="comma-separated retrieval modes to precompute")
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    total = len(SHOWCASE) * len(modes) + len(modes)  # +1 warmup per mode
    print(f"{len(SHOWCASE)} questions x {len(modes)} modes "
          f"+ {len(modes)} warmup = {total} LLM calls "
          f"(~{total * 2600:,} prompt tokens)")
    if args.dry_run:
        for q in SHOWCASE:
            print(f"  {q}")
        return

    entries = []
    for mode in modes:
        # WARM UP BEFORE TIMING ANYTHING. Constructing a model is not warming it:
        # torch pays kernel setup on the first real forward pass, Chroma loads its
        # HNSW segment on the first QUERY, and BM25 builds its index on the first
        # lexical search -- and every one of those costs lands on question 1 of a
        # mode. Unwarmed, question 1 is wrong by SECONDS while questions 2-8 are
        # correct, which is worse than a uniform offset: it looks like a property
        # of that question and sends you hunting for one that does not exist.
        #
        # This is what eval/run_eval.py does before its own timing loop (gotcha
        # 11), and matching it is not optional here -- these timings are meant to
        # be comparable with the committed eval results, and a differently-measured
        # number is not comparable at all.
        #
        # Warmed per MODE, not once overall: a `vector` warmup exercises the
        # embedder and Chroma but never touches the cross-encoder or the BM25
        # index, so `rerank` would still pay both on its first question.
        #
        # The warmup answer is generated and thrown away. It costs one LLM call
        # per mode and warms the HTTP connection and TLS handshake, which the
        # provider bills into its own reported generation time on a first call.
        print(f"[{mode}] warming up...", flush=True)
        warm_hits = search("warmup", k=1, mode=mode)
        answer_from_hits("warmup", warm_hits)

        for i, question in enumerate(SHOWCASE, start=1):
            print(f"[{mode} {i}/{len(SHOWCASE)}] {question[:60]}...", flush=True)
            # Retrieval timed DIRECTLY, exactly as run_eval.py times it -- not
            # derived by subtracting the model's self-reported time from a wall
            # clock. A subtracted figure silently absorbs anything else in the
            # window and prints it under the word "retrieval".
            t0 = time.perf_counter()
            hits = search(question, k=args.k, mode=mode)
            retrieve_ms = (time.perf_counter() - t0) * 1000
            text, stats = answer_from_hits(question, hits)
            entries.append({
                "question": question,
                "mode": mode,
                "k": args.k,
                "answer": text,
                # Generation time is in stats["total_ms"], reported by the provider.
                # Retrieval has never been recorded here at all, which left the UI
                # with nothing honest to show for the half of the system where the
                # modes actually differ.
                "retrieve_ms": retrieve_ms,
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
            # SAVE AFTER EVERY ANSWER, not once at the end.
            #
            # Design decision 29: results are written before anything else can
            # fail, because a formatting bug once destroyed two completed,
            # paid-for 69-question runs. This script predates that rule and broke
            # it -- it accumulated all 16 entries in memory and wrote once at the
            # end, so a failure on entry 15 threw away 14 paid answers.
            #
            # That is not hypothetical here. The free tier's DAILY token cap
            # appears only in a 429 body and never in a response header, so it
            # cannot be paced against and arrives without warning mid-run.
            write(entries, complete=False)

    write(entries, complete=True)
    print(f"\nwrote {OUT} -- {len(entries)} entries, "
          f"{OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
