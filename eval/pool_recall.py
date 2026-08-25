"""Recall of a candidate POOL at increasing depth -- the ceiling a reranker can reach.

Separate from run_eval because it answers a different question. run_eval scores what
a retriever finally returns at k; this scores how deep you have to read before a
retriever has found the answer at all. The second number is what matters when the
retriever is feeding a reranker, because reranking can only reorder the pool it is
handed. A pool that never contains the golden page cannot be rescued downstream.

That makes this the measurement behind the choice of rerank pool. The recall table
in HANDOFF section 3d was previously computed ad hoc and could not be reproduced
from the repository; this script exists so the claim is re-derivable.

    python -m eval.pool_recall
    python -m eval.pool_recall --pools bm25,hybrid --depths 5,10,20,30

Abstain rows are skipped: they have no golden page, so recall is undefined for them.
"""

import argparse
import sys

from eval.run_eval import GOLDEN, load_golden
from src.retrieve import bm25_search, hybrid_search, vector_search

POOLS = {
    "vector": vector_search,
    "bm25": bm25_search,
    "hybrid": hybrid_search,
}

DEFAULT_DEPTHS = (5, 10, 20, 30)


def first_hit_depth(hits, targets):
    """1-based position of the first hit matching any golden target, else 0.

    Any one target counts. Rows list several pages when the same fact appears in
    several documents, and finding any of them is a successful retrieval -- scoring
    it otherwise measures the golden set's completeness, not the retriever.
    """
    for hit in hits:
        if (hit["source_file"], hit["page"]) in targets:
            return hit["rank"]
    return 0


def measure(cases, pool_names, depths):
    """Return {pool: {depth: recall}} plus the per-case depths, for both readings.

    One search per pool per question, at max(depths). Recall at every shallower
    depth is then a comparison against the rank already found, so the deeper table
    costs no extra retrieval -- and every column is guaranteed consistent with the
    others, which running each depth separately would not be.
    """
    max_depth = max(depths)
    found = {name: {} for name in pool_names}

    for case in cases:
        for name in pool_names:
            hits = POOLS[name](case.question, k=max_depth)
            found[name][case.row] = first_hit_depth(hits, case.targets)
        print(".", end="", flush=True)
    print()

    recall = {
        name: {
            d: sum(1 for r in rows.values() if 0 < r <= d) / len(rows) if rows else 0.0
            for d in depths
        }
        for name, rows in found.items()
    }
    return recall, found


def report(recall, found, cases, depths):
    width = max(len(n) for n in recall)
    header = "  ".join(f"recall@{d:<3d}" for d in depths)
    print(f"\n{'pool':<{width}}  {header}")
    for name, by_depth in recall.items():
        row = "  ".join(f"{by_depth[d]:>9.1%}" for d in depths)
        print(f"{name:<{width}}  {row}")

    # Rows no pool reaches are the hard ceiling on the whole retrieval stage: no
    # reranker, prompt or model change can recover a page that was never a
    # candidate. Naming them is more useful than the aggregate, because they are
    # the list of questions the corpus or the chunking has to answer for.
    deepest = max(depths)
    missed = [
        c for c in cases
        if all(not (0 < found[n][c.row] <= deepest) for n in recall)
    ]
    print(f"\nreached by NO pool at depth {deepest}: {len(missed)}")
    for c in missed:
        ranks = ", ".join(f"{n}={found[n][c.row] or 'miss'}" for n in recall)
        print(f"  row {c.row}: {c.question[:64]}  [{ranks}]")

    # Where the pools genuinely differ. Equal recall totals can hide this, and the
    # two shapes below are the whole case for and against fusion:
    #
    #   "<pool> ALONE"     one retriever carries a page by itself. Fusion has
    #                      nothing to corroborate it with, so it can eject it.
    #   "LOST by hybrid"   both components found a valid target and fusion returned
    #                      neither -- the failure the recall totals cannot show, and
    #                      the reason this report exists and not just the table.
    for name in recall:
        for c in cases:
            hitters = [n for n in recall if 0 < found[n][c.row] <= deepest]
            if hitters == [name]:
                ranks = ", ".join(f"{n}={found[n][c.row] or 'miss'}" for n in recall)
                print()
                print(f"found at depth {deepest} by {name} ALONE -- row {c.row}: "
                      f"{c.question[:60]}")
                print(f"    [{ranks}]")

    if "hybrid" in recall:
        components = [n for n in recall if n != "hybrid"]
        lost = [
            c for c in cases
            if not (0 < found["hybrid"][c.row] <= deepest)
            and any(0 < found[n][c.row] <= deepest for n in components)
        ]
        print()
        print(f"found by a component but LOST by hybrid at depth {deepest}: {len(lost)}")
        for c in lost:
            ranks = ", ".join(f"{n}={found[n][c.row] or 'miss'}" for n in recall)
            print(f"  row {c.row}: {c.question[:60]}")
            print(f"    [{ranks}]")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--pools", default=",".join(POOLS),
                        help=f"comma-separated, from {','.join(POOLS)}")
    parser.add_argument("--depths", default=",".join(str(d) for d in DEFAULT_DEPTHS))
    args = parser.parse_args()

    pool_names = [p.strip() for p in args.pools.split(",") if p.strip()]
    unknown = [p for p in pool_names if p not in POOLS]
    if unknown:
        raise SystemExit(f"unknown pool(s) {unknown} -- expected from {list(POOLS)}")
    depths = sorted(int(d) for d in args.depths.split(","))

    # Abstain rows have no golden page, so recall over them is undefined rather
    # than zero. Same filter run_eval uses to build its answerable set, so the
    # denominators here and there cover the same 60 questions.
    cases = [c for c in load_golden(GOLDEN) if not c.should_abstain and c.targets]

    print(f"{len(cases)} answerable questions | pools: {', '.join(pool_names)} "
          f"| depths: {depths}")
    recall, found = measure(cases, pool_names, depths)
    report(recall, found, cases, depths)


if __name__ == "__main__":
    main()
