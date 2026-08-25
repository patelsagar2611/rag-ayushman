"""Score the pipeline against the hand-written golden set.

Retrieval metrics need no LLM at all -- they only ask whether the chunk you named
in the golden set came back in the top k. That is what --retrieval-only exposes,
and it is what makes CI possible: GitHub Actions cannot run Ollama, but it can
run this, and it is still measuring the half of the system most likely to break.

Usage:
    python -m eval.run_eval                      # retrieval + generation
    python -m eval.run_eval --retrieval-only     # no Ollama needed
    python -m eval.run_eval --k 10
    python -m eval.run_eval --retriever bm25 --retrieval-only
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
from src.retrieve import DEFAULT_K, DEFAULT_MODE, MODES, search

GOLDEN = Path("eval/golden_set.csv")
RESULTS_DIR = Path("eval/results")
PAGES = Path("data/processed/pages.jsonl")

# The literal token used in expected_answer to mark a question the corpus should
# not be able to answer.
ABSTAIN_MARKER = "ABSTAIN"

# Matches "[2]" and "[2, 4]" in a generated answer, in either bracket glyph.
#
# ASCII [n] is what the prompt asks for and what every local qwen2.5:7b answer
# used. Some hosted models cite with the CJK brackets U+3010/U+3011 instead --
# and openai/gpt-oss-120b does it on SOME prompts and not others, so it cannot be
# screened out by checking one answer. The failure it causes is silent and total:
# every answer parses as uncited, citation_correctness reads 0%, and nothing says
# why.
#
# Accepting both is the right fix rather than rewriting the model's output. The
# model is citing correctly; the glyph is presentation, the rank is the claim --
# the same reasoning as design decision 8. Widening is also safe for existing
# results: no [n]-only answer can match differently, so no recorded number moves.
CITATION_RE = re.compile(r"[\[【]\s*([\d,\s]+)(?:†[^\]】]*)?[\]】]")

# source_file and page accept either separator, since a semicolon is the natural
# thing to reach for and silently dropping the row would look like a miss.
LIST_SEP_RE = re.compile(r"[;,]")

# must_contain splits on SEMICOLON ONLY -- the values are things like "5,00,000",
# which contain commas of their own.
MUST_CONTAIN_SEP = ";"

HIT_RATE_CUTOFFS = (1, 3, 5)


@dataclass
class Case:
    row: int
    question: str
    expected_answer: str
    targets: list  # [(source_file, page), ...] -- any one counts as a hit
    must_contain: list
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
    missing_substrings: list = field(default_factory=list)
    error: str = ""
    retrieve_ms: float = 0.0
    generate_ms: float = 0.0
    # Ollama's own breakdown of generate_ms -- see src.generate.parse_stats.
    gen_stats: dict = field(default_factory=dict)


def normalise(text):
    """Collapse whitespace and case, so PDF line breaks do not defeat matching."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def split_field(value):
    return [s.strip() for s in LIST_SEP_RE.split(value or "") if s.strip()]


def build_targets(files, pages, row):
    """Pair filenames with page numbers.

    One file with several pages is the common case -- a fact spanning pages 5 and
    6 of a single document -- so a lone filename broadcasts across every page
    rather than forcing you to repeat it. Equal-length lists pair positionally,
    which is what the version-conflict questions need, since their answer lives
    on a different page of each edition.
    """
    numbers = []
    for p in pages:
        try:
            numbers.append(int(p))
        except ValueError:
            print(f"  row {row}: page '{p}' is not an integer")

    if not files or not numbers:
        return []
    if len(files) == 1:
        return [(files[0], p) for p in numbers]
    if len(numbers) == 1:
        return [(f, numbers[0]) for f in files]
    if len(files) == len(numbers):
        return list(zip(files, numbers))

    print(f"  row {row}: {len(files)} file(s) cannot be paired with {len(numbers)} page(s)")
    return []


def load_golden(path):
    if not path.exists():
        raise SystemExit(f"{path} not found")

    cases = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for i, raw in enumerate(csv.DictReader(f), start=2):  # row 1 is the header
            question = (raw.get("question") or "").strip()
            if not question:
                continue

            cases.append(
                Case(
                    row=i,
                    question=question,
                    expected_answer=(raw.get("expected_answer") or "").strip(),
                    targets=build_targets(
                        split_field(raw.get("source_file")),
                        split_field(raw.get("page")),
                        i,
                    ),
                    must_contain=[
                        s.strip()
                        for s in (raw.get("must_contain") or "").split(MUST_CONTAIN_SEP)
                        if s.strip()
                    ],
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
            print(f"  row {case.row}: no usable source_file/page -- cannot score retrieval")
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


def evaluate(cases, k, retrieval_only, mode=DEFAULT_MODE):
    if not retrieval_only:
        from src.generate import answer_from_hits

    # Warm up before timing anything. Both stages pay a large one-off cost on
    # first call -- ~5s to load the embedding model, and far more for Ollama to
    # load a 7B model into RAM. Left unwarmed, both land entirely on question 1
    # and drag the reported p50/p95 far away from real per-query latency.
    print("warming up… ", end="", flush=True)
    warm_hits = search("warmup", k=1, mode=mode)
    if not retrieval_only:
        answer_from_hits("warmup", warm_hits)
    print("done")

    outcomes = []
    for case in cases:
        outcome = Outcome(case=case)

        t0 = time.perf_counter()
        hits = search(case.question, k=k, mode=mode)
        outcome.retrieve_ms = (time.perf_counter() - t0) * 1000
        outcome.hits = hits

        # Rank of the first retrieved chunk matching any golden target.
        for hit in hits:
            if (hit["source_file"], hit["page"]) in case.targets:
                outcome.first_hit_rank = hit["rank"]
                break

        if not retrieval_only:
            t0 = time.perf_counter()
            try:
                text, gen_stats = answer_from_hits(case.question, hits)
            except Exception as e:
                # A single timeout or dropped connection used to abort the whole
                # run and lose every question before it. Record and carry on --
                # errored questions are excluded from generation metrics rather
                # than silently counted as wrong answers.
                outcome.error = f"{type(e).__name__}: {e}"
                outcome.generate_ms = (time.perf_counter() - t0) * 1000
                outcomes.append(outcome)
                print("E", end="", flush=True)
                continue
            outcome.generate_ms = (time.perf_counter() - t0) * 1000
            outcome.gen_stats = gen_stats
            outcome.answer = text
            outcome.cited_ranks = parse_citations(text)

            # A citation is correct if some chunk the model cited is a golden target.
            by_rank = {h["rank"]: h for h in hits}
            for rank in outcome.cited_ranks:
                hit = by_rank.get(rank)
                if hit and (hit["source_file"], hit["page"]) in case.targets:
                    outcome.citation_correct = True
                    break

            # Plain substring check, no judge involved. Catches the failure that
            # matters most on numeric questions: right page found, wrong figure stated.
            #
            # Citation markers are stripped FIRST, because they are metadata rather
            # than content and leaving them in lets a must_contain pass on a citation
            # instead of on the answer. `must_contain: 5` matched "...as set out in
            # [5]" while the answer never stated the figure -- a silent false pass.
            # Seven rows carry a bare digit and five of those values are <= k, so the
            # bug was reachable by a third of the checked rows.
            #
            # Two details are load-bearing. This runs AFTER parse_citations above,
            # which needs the markers intact. And the substitution is a SPACE, not an
            # empty string, so "the fee [3] is 48" cannot collapse into "is48" once
            # normalise() squeezes the whitespace and manufacture a different false
            # result in the other direction.
            normalised = normalise(CITATION_RE.sub(" ", text))
            outcome.missing_substrings = [
                s for s in case.must_contain if normalise(s) not in normalised
            ]

        outcomes.append(outcome)
        mark = "." if (outcome.first_hit_rank or case.should_abstain) else "x"
        print(mark, end="", flush=True)

    print()
    return outcomes


def summarise(outcomes, k, retrieval_only):
    answerable = [o for o in outcomes if not o.case.should_abstain and o.case.targets]
    abstain_cases = [o for o in outcomes if o.case.should_abstain]

    metrics = {
        "n_total": len(outcomes),
        "n_answerable": len(answerable),
        "n_abstain": len(abstain_cases),
    }

    # --- Retrieval ---
    cutoffs = [c for c in HIT_RATE_CUTOFFS if c <= k]
    if k not in cutoffs:
        cutoffs.append(k)
    for cutoff in cutoffs:
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

        errored = [o for o in outcomes if o.error]
        metrics["n_generation_errors"] = len(errored)
        abstain_cases = [o for o in abstain_cases if not o.error]
        answerable = [o for o in answerable if not o.error]

        correct_abstentions = sum(1 for o in abstain_cases if abstained(o))
        metrics["abstention_recall"] = (
            correct_abstentions / len(abstain_cases) if abstain_cases else None
        )

        # An abstention is only the model's fault when the evidence was actually in
        # front of it. Where retrieval missed the golden page there was nothing to
        # answer from, and declining was the CORRECT behaviour -- so those cases are
        # conditioned out of the denominator here.
        #
        # The reason is attribution, not the absolute number. Unconditioned, the
        # metric moves whenever RETRIEVAL changes: a reranker that recovers a missed
        # page shifts that question out of the "rightly declined" bucket and into
        # this denominator, so false_abstention_rate shifts for a reason that has
        # nothing to do with abstention behaviour -- crediting or blaming the prompt
        # for something the retriever did. Conditioning keeps the two separable.
        with_evidence = [o for o in answerable if o.first_hit_rank]
        false_abstentions = sum(1 for o in with_evidence if abstained(o))
        metrics["n_false_abstention_denom"] = len(with_evidence)
        metrics["false_abstention_rate"] = (
            false_abstentions / len(with_evidence) if with_evidence else None
        )

        # Retained only so results recorded before this change stay comparable.
        # It is the number the conditioning above exists to replace -- do not quote it.
        all_abstentions = sum(1 for o in answerable if abstained(o))
        metrics["false_abstention_rate_unconditioned"] = (
            all_abstentions / len(answerable) if answerable else None
        )
        metrics["abstained_on_retrieval_miss"] = all_abstentions - false_abstentions

        answered = [o for o in answerable if not abstained(o)]
        metrics["citation_correctness"] = (
            sum(1 for o in answered if o.citation_correct) / len(answered) if answered else 0.0
        )
        metrics["uncited_answers"] = sum(1 for o in answered if not o.cited_ranks)

        checked = [o for o in answered if o.case.must_contain]
        metrics["n_must_contain"] = len(checked)
        metrics["must_contain_pass"] = (
            sum(1 for o in checked if not o.missing_substrings) / len(checked)
            if checked
            else None
        )

        metrics["generate_ms_p50"] = percentile([o.generate_ms for o in outcomes], 0.50)
        metrics["generate_ms_p95"] = percentile([o.generate_ms for o in outcomes], 0.95)

        # Split that wall-clock figure into its two halves. Which one dominates
        # decides the fix -- fewer/smaller chunks if the prompt does, a tighter
        # num_predict or a smaller model if generation does -- and the total on
        # its own cannot distinguish them. Measure before tuning either.
        timed = [o for o in outcomes if o.gen_stats]
        metrics["n_timed"] = len(timed)
        if timed:
            for half in ("prompt_eval", "eval", "load"):
                metrics[f"{half}_ms_p50"] = percentile([o.gen_stats[f"{half}_ms"] for o in timed], 0.50)
            for half in ("prompt_eval", "eval"):
                metrics[f"{half}_tokens_p50"] = percentile(
                    [o.gen_stats[f"{half}_tokens"] for o in timed], 0.50)
                # Aggregate throughput -- total tokens over total seconds, not a
                # mean of per-question rates, which short answers would skew.
                total_tok = sum(o.gen_stats[f"{half}_tokens"] for o in timed)
                total_ms = sum(o.gen_stats[f"{half}_ms"] for o in timed)
                metrics[f"{half}_tps"] = total_tok / (total_ms / 1000) if total_ms else 0.0
            # A non-zero load time after warmup means Ollama evicted the model
            # mid-run (gotcha 6) and some question wore a cold reload.
            metrics["n_model_reloads"] = sum(1 for o in timed if o.gen_stats["load_ms"] > 1000)

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
            ("false_abstention_rate", "refused despite evidence"),
            ("citation_correctness", "cited a golden page"),
            ("must_contain_pass", "stated the required text"),
        ]:
            value = metrics.get(key)
            suffix = ""
            if key == "false_abstention_rate":
                suffix = f"   (of {metrics.get('n_false_abstention_denom', 0)} retrieved)"
            if key == "must_contain_pass":
                suffix = f"   (of {metrics.get('n_must_contain', 0)} checked)"
            print(f"  {label:<26s} " + ("   n/a" if value is None else f"{value:6.1%}") + suffix)
        # Shown separately because they are correct behaviour, not a failure:
        # the model declined a question whose evidence retrieval never surfaced.
        print(f"  {'  ...also declined on a':<26s} {metrics.get('abstained_on_retrieval_miss', 0):6d}"
              "   retrieval miss (correctly)")
        print(f"  {'answers with no citation':<26s} {metrics['uncited_answers']:6d}")
        if metrics.get("n_generation_errors"):
            print(f"  {'GENERATION ERRORS':<26s} {metrics['n_generation_errors']:6d}"
                  "   (excluded from the rates above)")
        print(f"  {'generate p50 / p95 (ms)':<26s} "
              f"{metrics['generate_ms_p50']:6.0f} / {metrics['generate_ms_p95']:.0f}")

        if metrics.get("n_timed"):
            print("\n  where that time goes (Ollama's own split, p50)")
            print(f"    {'prompt eval':<24s} {metrics['prompt_eval_ms_p50'] / 1000:6.1f}s  "
                  f"{metrics['prompt_eval_tokens_p50']:5.0f} tok  "
                  f"{metrics['prompt_eval_tps']:6.1f} tok/s")
            print(f"    {'generation':<24s} {metrics['eval_ms_p50'] / 1000:6.1f}s  "
                  f"{metrics['eval_tokens_p50']:5.0f} tok  "
                  f"{metrics['eval_tps']:6.1f} tok/s")
            if metrics.get("n_model_reloads"):
                print(f"    {'MODEL RELOADS mid-run':<24s} {metrics['n_model_reloads']:6d}"
                      "   (cold load inflated those questions)")

    print("\nFaithfulness is NOT measured here -- it needs a judge, and an LLM judge")
    print("scoring an LLM's answers largely measures the model agreeing with itself.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--retriever", choices=MODES, default=DEFAULT_MODE,
                        help="which retrieval mode to score")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="skip generation; needs no Ollama, safe for CI")
    parser.add_argument("--min-hit-rate", type=float, default=None,
                        help="exit 1 if hit_rate@k falls below this")
    parser.add_argument("--label", default="", help="tag recorded in the results file")
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()

    # Recorded so a results file identifies the prompt AND the model behind its
    # numbers. Only meaningful for generation runs -- a retrieval-only run builds no
    # prompt and calls no LLM, so these stay null there rather than naming a model
    # that had no influence on the metrics.
    #
    # The LLM was previously not recorded at all: config named embed_model but never
    # the generator. That was survivable while exactly one model existed and fatal
    # the moment a second one did, since every existing file would then be ambiguous
    # about which produced it. Recorded before the hosted backend lands, not after.
    prompt_version = None
    llm_provider = None
    llm_model = None
    if not args.retrieval_only:
        from src.generate import LLM_MODEL, LLM_PROVIDER, PROMPT_VERSION

        prompt_version = PROMPT_VERSION
        llm_provider = LLM_PROVIDER
        # LLM_MODEL, not OLLAMA_MODEL -- the latter would mislabel every hosted run
        # with the name of a model that never saw the prompt.
        llm_model = LLM_MODEL

    cases = load_golden(GOLDEN)
    if not cases:
        raise SystemExit(f"{GOLDEN} has no questions")

    print(f"loaded {len(cases)} questions from {GOLDEN}")
    problems = validate(cases)
    print(f"validation: {problems} problem(s)\n")

    if len(cases) < 60:
        print(f"NOTE: {len(cases)} questions is below the 60-80 the brief calls for.")
        print("      Numbers from a set this small are not yet meaningful.\n")

    print(f"retriever: {args.retriever}")
    outcomes = evaluate(cases, args.k, args.retrieval_only, mode=args.retriever)
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
                        "retriever": args.retriever,
                        "prompt_version": prompt_version,
                        "llm_provider": llm_provider,
                        "llm_model": llm_model,
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
                            "missing_substrings": o.missing_substrings,
                            "gen_stats": o.gen_stats,
                            "error": o.error,
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
