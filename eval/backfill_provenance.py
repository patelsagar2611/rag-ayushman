"""Backfill run provenance into results files written before it was recorded.

Why this exists. A results file is supposed to be self-describing, and for the
things the code wrote -- retriever, k, embedding model, chunk parameters -- it was.
Two facts were only ever asserted in the free-text `label`, which a human typed:

  * WHICH REVISION of the question set produced the numbers. `golden_set.csv` has
    meant three different things, and every published figure moved when the third
    landed.
  * WHETHER A PIN HELD. Two runs labelled `openrouter-...` were assumed pinned on
    the strength of that label and were in fact blended across two deployments
    mid-run (README gotcha 20).

Both are recoverable from data already inside the files, so no run has to be
repeated:

  * The question set is identified by matching each file's SAVED per-case targets
    against every revision of every question set in git history. A revision that
    matches every case is the one that scored the run. This is exact, not a guess --
    and where nothing matches, the field is left null rather than filled with the
    closest thing, because a wrong provenance record is worse than a missing one.
  * The serving deployment is already recorded per case in `gen_stats.served_by`
    (design decision 28). A set larger than one IS a blended run.

Strictly additive and idempotent: an existing value is never overwritten, so
re-running changes nothing and the script cannot rewrite history it did not create.

    python -m eval.backfill_provenance --dry-run    # report, touch nothing
    python -m eval.backfill_provenance
"""

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

from eval.run_eval import build_descriptor, build_targets, split_field

RESULTS_DIRS = [Path("eval/results"), Path("eval/results/archive-56q")]

# Every revision of every question set, newest first. Working tree first so a run
# scored by the current set is labelled with it rather than an identical ancestor.
SOURCES = [
    ("worktree", "eval/golden_set.csv"),
    ("worktree", "eval/paraphrase_set.csv"),
    ("17bd1f0", "eval/golden_set.csv"),
    ("17bd1f0", "eval/paraphrase_set.csv"),
    ("6c623ed", "eval/golden_set.csv"),
    ("0e38259", "eval/golden_set.csv"),
    ("170ae17", "eval/golden_set.csv"),
]


def read_source(rev, path):
    if rev == "worktree":
        p = Path(path)
        return p.read_bytes() if p.exists() else None
    out = subprocess.run(["git", "show", f"{rev}:{path}"],
                         capture_output=True)
    return out.stdout if out.returncode == 0 else None


def load_revisions():
    """Every question-set revision, as (sha, name, rows, {row: targets})."""
    seen, revisions = set(), []
    for rev, path in SOURCES:
        raw = read_source(rev, path)
        if raw is None:
            continue
        # Normalised the same way run_eval fingerprints it -- see
        # question_set_fingerprint. Without this, git's LF blobs and a Windows
        # working tree's CRLF give one question set two fingerprints, and the
        # backfill would invent revisions that never existed.
        sha = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()[:12]
        if sha in seen:
            continue
        seen.add(sha)
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        targets = {}
        for i, r in enumerate(rows, start=2):
            if (r.get("expected_answer") or "").strip() == "ABSTAIN":
                targets[i] = set()
            else:
                targets[i] = set(build_targets(split_field(r.get("source_file")),
                                               split_field(r.get("page")), i))
        revisions.append((sha, Path(path).name, len(rows), targets))
    return revisions


def identify(data, revisions):
    """The revision whose targets match EVERY case in this file, or None."""
    saved = {c["row"]: {tuple(t) for t in c.get("targets") or []}
             for c in data["cases"]}
    matches = [
        (sha, name, rows) for sha, name, rows, targets in revisions
        if all(row in targets and targets[row] == tg for row, tg in saved.items())
    ]
    # Several revisions can match a PARTIAL run whose rows the edits never touched.
    # Ambiguity is reported, not silently resolved by taking the first.
    return matches


def observed(data):
    names = {(c.get("gen_stats") or {}).get("served_by") for c in data["cases"]}
    return sorted(n for n in names if n) or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    revisions = load_revisions()
    print(f"question-set revisions found: {len(revisions)}")
    for sha, name, rows, _ in revisions:
        print(f"  {sha}  {name:22} {rows} rows")
    print()

    changed = skipped = ambiguous = unmatched = 0
    for directory in RESULTS_DIRS:
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if "cases" not in data or "config" not in data:
                continue
            cfg = data["config"]
            updates = {}

            if not cfg.get("question_set_sha"):
                matches = identify(data, revisions)
                if len(matches) == 1:
                    sha, name, rows = matches[0]
                    updates["question_set_sha"] = sha
                    updates["question_set_rows"] = rows
                    cfg.setdefault("question_set", name)
                elif len(matches) > 1:
                    # Report every candidate rather than picking one.
                    shas = ", ".join(m[0] for m in matches)
                    print(f"  {path.name}: AMBIGUOUS -- targets match {shas}")
                    ambiguous += 1
                else:
                    print(f"  {path.name}: NO REVISION MATCHES -- left null")
                    unmatched += 1

            if "served_by" not in cfg:
                updates["served_by"] = observed(data)

            if not updates and data.get("descriptor"):
                skipped += 1
                continue

            cfg.update(updates)
            if not data.get("descriptor") and cfg.get("question_set_sha"):
                data["descriptor"] = build_descriptor({
                    "retriever": cfg.get("retriever", "?"),
                    "retrieval_only": cfg.get("retrieval_only", not cfg.get("llm_model")),
                    "llm_model": cfg.get("llm_model"),
                    "n_questions": cfg.get("n_questions", len(data["cases"])),
                    "question_set": cfg.get("question_set", "unknown.csv"),
                    "question_set_sha": cfg["question_set_sha"],
                    "served_by": cfg.get("served_by"),
                    "only_rows": cfg.get("only_rows"),
                })
            changed += 1
            if not args.dry_run:
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                encoding="utf-8")

    verb = "would update" if args.dry_run else "updated"
    print(f"\n{verb} {changed} file(s); {skipped} already complete; "
          f"{ambiguous} ambiguous; {unmatched} unmatched")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
