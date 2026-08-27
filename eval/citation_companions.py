"""Recompute citation metrics from SAVED results files, head-to-head across two arms.

Why this is a script in the repo rather than a number pasted into a document: the
same reason eval/pool_recall.py exists. The recall table in HANDOFF 3d was originally
computed ad hoc and could not be reproduced from the repo, which made it impossible
to check. Any number that reaches the README has to be regenerable by running
something.

What it does that reading `metrics` out of the results file does not:

1. **Re-scores against the CURRENT golden set, not the saved targets.** Four rows
   gained target pages when the golden set went v1 -> v2 (9, 28, 62, 68). Runs saved
   before that carry v1 targets, so their stored `citation_correct` is v1-scored.
   Comparing a v1-scored arm to a v2-scored arm attributes a golden-set edit to the
   retriever. Answers are saved, so re-scoring is exact and does not need a re-run.

2. **Restricts to questions BOTH arms answered.** The arms decline different
   questions, so a whole-file aggregate compares two different question sets and
   calls the difference a retrieval effect. HANDOFF section 0 is explicit about this.

3. **Reports the companions beside the any-match rate.** citation_correctness passes
   if ANY cited page is golden, so it rewards citing broadly. Reranking measurably
   increases citations per answer, which means the rerank arm gets a tailwind the
   vector arm does not -- and that tailwind is invisible unless the citation count
   is reported next to the rate it inflates.

Usage:
    python -m eval.citation_companions                 # all known pairs
    python -m eval.citation_companions <fileA> <fileB> # one ad-hoc pair
"""

import json
import sys
from pathlib import Path

import yaml

from eval.run_eval import load_golden

RESULTS_DIR = Path("eval/results")
GOLDEN = Path("eval/golden_set.csv")

# Read from the same file the answerer reads, never re-typed here. A copy of this
# string that drifts from config/prompts.yaml would silently reclassify every
# abstention as a wrong answer -- the failure the prompts file warns about.
ABSTAIN = yaml.safe_load(GOLDEN.parent.parent.joinpath("config/prompts.yaml")
                         .read_text(encoding="utf-8"))["abstain"].strip()


def golden_targets():
    """saved `row` value -> set of (source_file, page), via run_eval's own loader.

    Deliberately NOT a second parser. The golden set's `source_file` and `page`
    columns are `;`-separated lists paired POSITIONALLY -- which is what the
    version-conflict rows need, since the same clause sits on a different page in
    each edition -- with a lone filename broadcasting across several pages. A
    reimplementation of that here got it wrong on 9 of 69 rows on the first attempt
    and reported a citation correctness of ~2% with nothing else looking broken.

    Reusing load_golden() means this file cannot drift from what the eval scored,
    and inherits the `start=2` row numbering (row 1 is the CSV header) for free.
    """
    return {case.row: set(case.targets) for case in load_golden(GOLDEN)}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_targets(data, targets, path):
    """Compare this file's SAVED targets against the current golden set.

    Two jobs. It catches an alignment bug -- an off-by-one in the row mapping makes
    nearly every row disagree, which is loud, where the resulting metrics are merely
    wrong-looking. And it reports which rows the golden set actually changed, so the
    v1 -> v2 re-scoring is visible rather than asserted: HANDOFF section 0 records
    exactly four rows gaining target pages (9, 28, 62, 68).
    """
    changed = []
    for case in data["cases"]:
        saved = {tuple(t) for t in case.get("targets") or []}
        if saved != targets.get(case["row"], set()):
            changed.append(case["row"])
    if len(changed) > 6:
        raise SystemExit(
            f"{Path(path).name}: {len(changed)} of {len(data['cases'])} rows disagree "
            "with the current golden set. That is an alignment bug, not a golden-set "
            "edit -- check the row offset in golden_targets()."
        )
    return changed


# --- the two null strategies, FIXED IN ADVANCE ---------------------------------
#
# Written down before the numbers were computed, deliberately. Three plausible nulls
# exist and whichever produces the most striking result would be tempting to adopt
# afterwards -- which is choosing a framing to fit an answer. Same discipline as
# design decision 12, which refuses to tune constants against the golden set.
# BOTH are reported, always, so there is no selection to make later.
#
#   NULL A -- "cite at random from the window."
#       base = (golden chunks in the top-k) / k.
#       The honest floor. No real model behaves this way, but it is the score for
#       doing nothing, and it MOVES BETWEEN ARMS: reranking changes how many golden
#       pages are in the window, not only where they rank. Row 25 of the README is
#       the clean case -- 1 of 5 golden under vector, 4 of 5 under rerank. A model
#       guessing blindly scores 20% in one and 80% in the other, having improved
#       nothing. This is the confound that precision alone does not remove.
#
#   NULL B -- "always cite [1]."
#       base = 1 if the rank-1 chunk is golden else 0.
#       A strategy a real system might actually ship, so the lift over it reads as
#       "what does the MODEL add over trusting the retriever?" Aggregated, this is
#       hit@1 over the scored subset.
#
# Interpretation warning for NULL B: if reranking puts the right chunk at rank 1,
# a model citing rank 1 is being CORRECT, not lazy. A shrinking lift over Null B
# can mean the baseline got good rather than the model got worse. Report it; do not
# read it as a quality score on its own.
#
# `lift` is a plain difference. `normalised` is (observed - base) / (1 - base):
# "of the improvement actually available, how much was captured?" -- which matters
# because a high base rate leaves less room. Undefined at base = 1.


def score(case, targets):
    """Per-case citation numbers, re-scored against `targets`. None if not scored.

    Not scored means an error or an abstention -- excluded for different reasons.
    An error is an infrastructure event (design decision 10); an abstention is a
    deliberate refusal, which is correct behaviour rather than a failed citation.
    """
    if case.get("error") or not case.get("answer"):
        return None
    if case["answer"].strip() == ABSTAIN:
        return None

    retrieved = case.get("retrieved") or []
    by_rank = {i + 1: tuple(r[:2]) for i, r in enumerate(retrieved)}
    cites = case.get("cited_ranks") or []
    golden = [rk for rk in cites if by_rank.get(rk) in targets]

    n_golden_in_window = sum(1 for v in by_rank.values() if v in targets)
    return {
        "any_match": bool(golden),
        # Precision is undefined with no citations rather than 0.0: "cited the wrong
        # page" and "cited nothing" are different failures, counted separately.
        "precision": (len(golden) / len(cites)) if cites else None,
        "n_cites": len(cites),
        "base_a": (n_golden_in_window / len(retrieved)) if retrieved else None,
        "base_b": 1.0 if by_rank.get(1) in targets else 0.0,
        "n_golden_in_window": n_golden_in_window,
        "k": len(retrieved),
    }


def compare(path_a, path_b, targets):
    a, b = load(path_a), load(path_b)
    for data, path in ((a, path_a), (b, path_b)):
        rescored = verify_targets(data, targets, path)
        if rescored:
            print(f"  re-scored {Path(path).name}: golden set changed rows {rescored}")
    by_row_a = {c["row"]: c for c in a["cases"]}
    by_row_b = {c["row"]: c for c in b["cases"]}

    rows = []
    for row in sorted(set(by_row_a) & set(by_row_b)):
        sa = score(by_row_a[row], targets.get(row, set()))
        sb = score(by_row_b[row], targets.get(row, set()))
        if sa and sb:                          # the restriction that makes this valid
            rows.append((sa, sb))

    def mean(values):
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    def agg(side):
        hits = [r[side] for r in rows]
        # Base rates are averaged over the SAME subset precision is averaged over --
        # answers that cited something. A base rate computed over a different set of
        # questions than the score it is subtracted from is not a floor for it.
        cited = [h for h in hits if h["n_cites"]]
        observed = mean(h["precision"] for h in cited)
        out = {
            "any_match": mean(float(h["any_match"]) for h in hits),
            "precision": observed,
            "cites": mean(h["n_cites"] for h in cited),
            "golden_in_window": mean(h["n_golden_in_window"] for h in hits),
            "base_a": mean(h["base_a"] for h in cited),
            "base_b": mean(h["base_b"] for h in cited),
        }
        for null in ("a", "b"):
            base = out[f"base_{null}"]
            if base is None or observed is None:
                out[f"lift_{null}"] = out[f"norm_{null}"] = None
                continue
            out[f"lift_{null}"] = observed - base
            # Undefined at base = 1: no headroom exists, so "share of headroom
            # captured" has no meaning. None rather than a divide-by-zero or a
            # fabricated 0.0, either of which would read as a real measurement.
            out[f"norm_{null}"] = (
                (observed - base) / (1 - base) if base < 1 else None
            )
        return out

    return a.get("label", "?"), b.get("label", "?"), len(rows), agg(0), agg(1)


# (vector arm, rerank arm). Only these two pairs exist: the gpt-oss-120b run has no
# rerank partner, and the FAILED-RUN file covers 17 questions and is excluded by name.
PAIRS = [
    ("20260825T063427Z.json", "20260825T002752Z.json"),   # local qwen2.5:7b
    ("20260825T193407Z.json", "20260825T193932Z.json"),   # hosted gemini-3.1-flash-lite
]


def main():
    targets = golden_targets()
    pairs = [tuple(sys.argv[1:3])] if len(sys.argv) >= 3 else [
        (RESULTS_DIR / x, RESULTS_DIR / y) for x, y in PAIRS
    ]

    print(f"re-scored against {GOLDEN} ({len(targets)} rows), "
          "restricted to questions BOTH arms answered\n")
    # Width 10, not 9. Several header names ("any-match", "precision", "cites/ans")
    # are exactly 9 characters, so a 9-wide column leaves no gap between them and
    # the header row reads as one word.
    def pct(value):
        return f"{'n/a':>10}" if value is None else f"{value:10.1%}"

    def pts(hi, lo):
        return f"{'n/a':>10}" if hi is None or lo is None else f"{(hi - lo) * 100:+10.1f}"

    for path_a, path_b in pairs:
        label_a, label_b, n, arm_a, arm_b = compare(path_a, path_b, targets)
        print(f"n = {n} questions both arms answered\n")

        head = ("any-match", "precision", "cites/ans", "gold/win",
                "baseA", "liftA", "normA", "baseB", "liftB", "normB")
        print("  " + " " * 46 + "".join(f"{h:>10}" for h in head))
        for label, arm in ((label_a, arm_a), (label_b, arm_b)):
            print(f"  {label[:44]:46}"
                  f"{pct(arm['any_match'])}{pct(arm['precision'])}"
                  f"{arm['cites']:10.2f}{arm['golden_in_window']:10.2f}"
                  f"{pct(arm['base_a'])}{pct(arm['lift_a'])}{pct(arm['norm_a'])}"
                  f"{pct(arm['base_b'])}{pct(arm['lift_b'])}{pct(arm['norm_b'])}")
        # Deltas in PERCENTAGE POINTS, not percent: these are differences between
        # two rates, and "+3.8%" would read as a relative change of the first rate.
        print(f"  {'DELTA (pts)':46}"
              f"{pts(arm_b['any_match'], arm_a['any_match'])}"
              f"{pts(arm_b['precision'], arm_a['precision'])}"
              f"{arm_b['cites']-arm_a['cites']:+10.2f}"
              f"{arm_b['golden_in_window']-arm_a['golden_in_window']:+10.2f}"
              f"{pts(arm_b['base_a'], arm_a['base_a'])}{pts(arm_b['lift_a'], arm_a['lift_a'])}"
              f"{pts(arm_b['norm_a'], arm_a['norm_a'])}"
              f"{pts(arm_b['base_b'], arm_a['base_b'])}{pts(arm_b['lift_b'], arm_a['lift_b'])}"
              f"{pts(arm_b['norm_b'], arm_a['norm_b'])}")
        print()
        print("  gold/win = golden pages present in the k retrieved chunks. If this "
              "MOVES between\n  arms, precision is not comparable between them "
              "unadjusted -- that is the whole point.")
        print("  baseA = cite at random from the window.  baseB = always cite [1].")
        print("  lift  = observed precision - base.  norm = share of available "
              "headroom captured.\n")


if __name__ == "__main__":
    main()
