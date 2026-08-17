"""Score the pipeline against the hand-written golden set.

Retrieval metrics need no LLM at all -- they only ask whether the chunk you named
in the golden set came back in the top k. That is what --retrieval-only exposes,
and it is what makes CI possible: GitHub Actions cannot run Ollama, but it can
run this, and it is still measuring the half of the system most likely to break.

Usage:
    python -m eval.run_eval                      # retrieval + generation
    python -m eval.run_eval --retrieval-only     # no Ollama needed
    python -m eval.run_eval --k 10
    python -m eval.run_eval --min-hit-rate 0.7   # exit 1 below threshold (CI)
"""

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.chunk import OVERLAP_CHARS, TARGET_CHARS
from src.index import EMBED_MODEL
from src.retrieve import DEFAULT_K, search

GOLDEN = Path("eval/golden_set.csv")
RESULTS_DIR = Path("eval/results")
PAGES = Path("data/processed/pages.jsonl")

# The literal token used in expected_answer to mark a question the corpus should
# not be able to answer.
ABSTAIN_MARKER = "ABSTAIN"

# Matches "[2]" and "[2, 4]" in a generated answer.
CITATION_RE = re.compile(r"\[([\d,\s]+)\]")

HIT_RATE_CUTOFFS = (1, 3, 5)


@dataclass
class Case:
    row: int
    question: str
    expected_answer: str
    targets: list  # [(source_file, page), ...] -- any one counts as a hit
    notes: str

    @property
    def should_abstain(self):
        return self.expected_answer.strip().upper() == ABSTAIN_MARKER


@dataclass
class Outcome:
    case: Case
    hits: list = field(default_factory=list)
    first_hit_rank: int = 0  # 0 = target never retrieved
    answer: str = ""
    cited_ranks: list = field(default_factory=list)
    citation_correct: bool = False
    retrieve_ms: float = 0.0
    generate_ms: float = 0.0


def load_golden(path):
    """Parse the golden set.

    source_file and page may each hold a comma-separated list, paired by
    position, so one question can legitimately point at several pages -- which
    the version-conflict questions need, since the answer lives in two documents.
    """
    if not path.exists():
        raise SystemExit(f"{path} not found")

    cases = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for i, raw in enumerate(csv.DictReader(f), start=2):  # row 1 is the header
            question = (raw.get("question") or "").strip()
            if not question:
                continue

            files = [s.strip() for s in (raw.get("source_file") or "").split(",") if s.strip()]
            pages = [s.strip() for s in (raw.get("page") or "").split(",") if s.strip()]

            targets = []
            if len(files) != len(pages):
                print(f"  row {i}: {len(files)} source_file(s) but {len(pages)} page(s) -- skipping targets")
            else:
                for fname, page in zip(files, pages):
                    try:
                        targets.append((fname, int(page)))
                    except ValueError:
                        print(f"  row {i}: page '{page}' is not an integer")

            cases.append(
                Case(
                    row=i,
                    question=question,
                    expected_answer=(raw.get("expected_answer") or "").strip(),
                    targets=targets,
                    notes=(raw.get("notes") or "").strip(),
                )
            )
    return cases


def validate(cases):
    """Catch typos in the golden set before they show up as fake misses.

    A (file, page) that is not in pages.jsonl can never be retrieved, so a
    mistyped page number looks exactly like a retrieval failure. Worth separating.
    """
    if not PAGES.exists():
        print(f"  {PAGES} missing -- skipping validation (run `python -m src.extract`)")
        return 0

    valid = set()
    with PAGES.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            valid.add((rec["source_file"], rec["page_number"]))
    known_files = {fname for fname, _ in valid}

    problems = 0
    for case in cases:
        if case.should_abstain:
            if case.targets:
                print(f"  row {case.row}: ABSTAIN case should have no source_file/page")
                problems += 1
            continue
        if not case.targets:
            print(f"  row {case.row}: no source_file/page -- cannot score retrieval")
            problems += 1
            continue
        for fname, page in case.targets:
            if fname not in known_files:
                print(f"  row {case.row}: '{fname}' is not in the corpus")
                problems += 1
            elif (fname, page) not in valid:
                print(f"  row {case.row}: {fname} p.{page} has no extractable text")
                problems += 1
    return problems


def parse_citations(answer):
    """Rank numbers the model cited, e.g. '[2, 4]' -> [2, 4]."""
    ranks = []
    for group in CITATION_RE.findall(answer):
        for part in group.split(","):
            part = part.strip()
            if part.isdigit():
                ranks.append(int(part))
    return sorted(set(ranks))


def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def evaluate(cases, k, retrieval_only):
    if not retrieval_only:
        from src.generate import answer_from_hits

    # Warm up before timing anything. Both stages pay a large one-off cost on
    # first call -- ~5s to load the embedding model, and far more for Ollama to
    # load a 7B model into RAM. Left unwarmed, both land entirely on question 1
    # and drag the reported p50/p95 far away from real per-query latency.
    print("warming up… ", end="", flush=True)
    warm_hits = search("warmup", k=1)
    if not retrieval_only:
        answer_from_hits("warmup", warm_hits)
    print("done")

    outcomes = []
    for case in cases:
        outcome = Outcome(case=case)

        t0 = time.perf_counter()
        hits = search(case.question, k=k)
        outcome.retrieve_ms = (time.perf_counter() - t0) * 1000
        outcome.hits = hits

        # Rank of the first retrieved chunk matching any golden target.
        for hit in hits:
            if (hit["source_file"], hit["page"]) in case.targets:
                outcome.first_hit_rank = hit["rank"]
                break

        if not retrieval_only:
            t0 = time.perf_counter()
            text = answer_from_hits(case.question, hits)
            outcome.generate_ms = (time.perf_counter() - t0) * 1000
            outcome.answer = text
            outcome.cited_ranks = parse_citations(text)

            # A citation is correct if some chunk the model cited is a golden target.
            by_rank = {h["rank"]: h for h in hits}
            for rank in outcome.cited_ranks:
                hit = by_rank.get(rank)
                if hit and (hit["source_file"], hit["page"]) in case.targets:
                    outcome.citation_correct = True
                    break

        outcomes.append(outcome)
        mark = "." if (outcome.first_hit_rank or case.should_abstain) else "x"
        print(mark, end="", flush=True)

    print()
    return outcomes


def summarise(outcomes, k, retrieval_only):
    answerable = [o for o in outcomes if not o.case.should_abstain and o.case.targets]
    abstain_cases = [o for o in outcomes if o.case.should_abstain]

    metrics = {"n_total": len(outcomes), "n_answerable": len(answerable), "n_abstain": len(abstain_cases)}

    # --- Retrieval ---
    for cutoff in [c for c in HIT_RATE_CUTOFFS if c <= k] + ([k] if k not in HIT_RATE_CUTOFFS else []):
        got = sum(1 for o in answerable if 0 < o.first_hit_rank <= cutoff)
        metrics[f"hit_rate@{cutoff}"] = got / len(answerable) if answerable else 0.0

    # Mean reciprocal rank: rewards ranking the right chunk 1st over 5th, which
    # plain hit rate cannot see. This is the number the Phase 2 reranker targets.
    rr = [1 / o.first_hit_rank if o.first_hit_rank else 0.0 for o in answerable]
    metrics["mrr"] = sum(rr) / len(rr) if rr else 0.0

    metrics["retrieve_ms_p50"] = percentile([o.retrieve_ms for o in outcomes], 0.50)
    metrics["retrieve_ms_p95"] = percentile([o.retrieve_ms for o in outcomes], 0.95)

    if not retrieval_only:
        from src.generate import ABSTAIN

        def abstained(o):
            return o.answer.strip() == ABSTAIN.strip()

        correct_abstentions = sum(1 for o in abstain_cases if abstained(o))
        false_abstentions = sum(1 for o in answerable if abstained(o))

        metrics["abstention_recall"] = (
            correct_abstentions / len(abstain_cases) if abstain_cases else None
        )
        metrics["false_abstention_rate"] = (
            false_abstentions / len(answerable) if answerable else None
        )
        answered = [o for o in answerable if not abstained(o)]
        metrics["citation_correctness"] = (
            sum(1 for o in answered if o.citation_correct) / len(answered) if answered else 0.0
        )
        metrics["uncited_answers"] = sum(1 for o in answered if not o.cited_ranks)
        metrics["generate_ms_p50"] = percentile([o.generate_ms for o in outcomes], 0.50)
        metrics["generate_ms_p95"] = percentile([o.generate_ms for o in outcomes], 0.95)

    return metrics


def report(metrics, retrieval_only):
    print("\n" + "=" * 62)
    print(f"{metrics['n_total']} questions "
          f"({metrics['n_answerable']} answerable, {metrics['n_abstain']} should abstain)")
    print("=" * 62)

    print("\nRETRIEVAL  (no LLM involved)")
    for key in sorted(k for k in metrics if k.startswith("hit_rate@")):
        print(f"  {key:<26s} {metrics[key]:6.1%}")
    print(f"  {'mrr':<26s} {metrics['mrr']:6.3f}")
    print(f"  {'retrieve p50 / p95 (ms)':<26s} "
          f"{metrics['retrieve_ms_p50']:6.0f} / {metrics['retrieve_ms_p95']:.0f}")

    if not retrieval_only:
        print("\nGENERATION")
        for key, label in [
            ("abstention_recall", "abstained when it should"),
            ("false_abstention_rate", "refused when it should not"),
            ("citation_correctness", "cited a golden page"),
        ]:
            value = metrics.get(key)
            print(f"  {label:<26s} " + ("   n/a" if value is None else f"{value:6.1%}"))
        print(f"  {'answers with no citation':<26s} {metrics['uncited_answers']:6d}")
        print(f"  {'generate p50 / p95 (ms)':<26s} "
              f"{metrics['generate_ms_p50']:6.0f} / {metrics['generate_ms_p95']:.0f}")

    print("\nFaithfulness is NOT measured here -- it needs a judge, and an LLM judge")
    print("scoring an LLM's answers largely measures the model agreeing with itself.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--retrieval-only", action="store_true",
                        help="skip generation; needs no Ollama, safe for CI")
    parser.add_argument("--min-hit-rate", type=float, default=None,
                        help="exit 1 if hit_rate@k falls below this")
    parser.add_argument("--label", default="", help="tag recorded in the results file")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    cases = load_golden(GOLDEN)
    if not cases:
        raise SystemExit(f"{GOLDEN} has no questions")

    print(f"loaded {len(cases)} questions from {GOLDEN}")
    problems = validate(cases)
    print(f"validation: {problems} problem(s)\n")

    if len(cases) < 60:
        print(f"NOTE: {len(cases)} questions is below the 60-80 the brief calls for.")
        print("      Numbers from a set this small are not yet meaningful.\n")

    outcomes = evaluate(cases, args.k, args.retrieval_only)
    metrics = summarise(outcomes, args.k, args.retrieval_only)
    report(metrics, args.retrieval_only)

    if not args.no_save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = RESULTS_DIR / f"{stamp}.json"
        dest.write_text(
            json.dumps(
                {
                    "timestamp": stamp,
                    "label": args.label,
                    # Config is recorded so a results file is self-describing --
                    # a metrics table is meaningless without knowing what produced it.
                    "config": {
                        "k": args.k,
                        "retrieval_only": args.retrieval_only,
                        "embed_model": EMBED_MODEL,
                        "chunk_target_chars": TARGET_CHARS,
                        "chunk_overlap_chars": OVERLAP_CHARS,
                        "n_questions": len(cases),
                    },
                    "metrics": metrics,
                    "cases": [
                        {
                            "row": o.case.row,
                            "question": o.case.question,
                            "targets": [list(t) for t in o.case.targets],
                            "first_hit_rank": o.first_hit_rank,
                            "retrieved": [[h["source_file"], h["page"], round(h["score"], 4)]
                                          for h in o.hits],
                            "answer": o.answer,
                            "cited_ranks": o.cited_ranks,
                            "citation_correct": o.citation_correct,
                        }
                        for o in outcomes
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {dest}")

    if args.min_hit_rate is not None:
        actual = metrics.get(f"hit_rate@{args.k}", 0.0)
        if actual < args.min_hit_rate:
            print(f"\nFAIL hit_rate@{args.k} {actual:.1%} < threshold {args.min_hit_rate:.1%}")
            sys.exit(1)
        print(f"\nPASS hit_rate@{args.k} {actual:.1%} >= threshold {args.min_hit_rate:.1%}")


if __name__ == "__main__":
    main()
