# Archived results — 56-question golden set

Every file in this folder was measured against an **older 56-question version** of
`eval/golden_set.csv` (49 answerable, 7 abstain). The set is now 69 questions
(60 answerable, 9 abstain), so **none of these numbers are comparable to anything in the
parent folder.** Kept because they are the record of how Phase 1 and the first Phase 2
measurements were actually taken.

The JSON files are unmodified — their `label` fields say nothing about the question count,
which is exactly why they live in a folder that does.

| File | Label | What it is |
|---|---|---|
| `20260819T102845Z.json` | `phase1-baseline` | Phase 1 retrieval baseline, `--retrieval-only` |
| `20260819T163840Z.json` | `phase1-baseline-full` | Phase 1 full run **— the only generation run ever recorded** |
| `20260820T114930Z.json` | `phase2-baseline-vector-retrieval` | vector, re-measured under the Phase 2 harness |
| `20260820T114834Z.json` | `phase2a-bm25-only-retrieval` | BM25 alone |
| `20260820T115208Z.json` | `phase2b-hybrid-rrf-retrieval` | RRF of vector + BM25 |
| `20260820T120042Z.json` | `phase2c-rerank-retrieval` | hybrid top-30 + cross-encoder |

Two further reasons these cannot be compared forward:

1. **`must_contain` changed meaning.** Units were stripped from the values on 2026-08-24
   (see HANDOFF design decision 8), so `must_contain_pass` in `20260819T163840Z.json` was
   measured under a stricter definition than any future run will use.
2. **`false_abstention_rate` in these files is the unconditioned form** (9/49 = 18.4%). The
   conditioned figure, 7/44 = 15.9%, was recomputed offline and is the one quoted in
   HANDOFF §3.
