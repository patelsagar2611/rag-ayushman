# Handoff — for the next session only

**Read [README.md](../README.md) first.** It is the permanent record: results, design
decisions, gotchas, anti-goals, corpus provenance. This file holds *only* what the next
session needs that is not already there — current state, what is in flight, what to do next.

**When this session's work is stable, promote its findings to the README and rewrite this file
from scratch.** If it has grown a history section, it has drifted from its purpose.

Written 2026-08-27.

---

## The working agreement is binding and lives in the README

[How this project is worked on](../README.md#how-this-project-is-worked-on). Five rules,
summarised here only so they cannot be missed:

1. Explain the reasoning, not just the outcome — what was chosen *over* what.
2. Small batches; put judgement calls to the owner as they arise, never a long unattended run
   of steps followed by a summary.
3. **Ask before starting ANY run**, including single-question smoke tests.
4. **Any message sent while a run is in flight ends with a line** saying so, warning that a
   system sleep will affect it, and giving an estimated time.
5. The machine is not always on. Plan around it.

The standard behind all five: this is a portfolio project, so the deliverable is a working
pipeline **its author can explain**. Speed of completion is worth nothing against that.

[Docs/INTERVIEW-ANGLES.md](INTERVIEW-ANGLES.md) is a required deliverable of every session, not
a by-product. New findings get an entry *in the session that produced them*.

---

## State of the tree

**Uncommitted.** Nothing from 2026-08-26/27 is committed. Changed or added:

- `src/generate.py` — `OPENAI_PROVIDER` pinning, `served_by` recording, connection-error retry
- `eval/run_eval.py` — citation companions, `served_by` in metrics, `--only-rows`, save-before-report
- `eval/citation_companions.py` — **new**, head-to-head recomputation with base-rate nulls
- `README.md`, `Docs/HANDOFF.md`, `Docs/INTERVIEW-ANGLES.md`
- `.env` — points at OpenRouter; `OPENAI_MODEL` is the sentinel `SET-AFTER-MODEL-LIST-STEP`

**Credit:** ~$10 on OpenRouter, roughly $0.25 spent. Auto top-up should be off.

**Results files added this session** (`eval/results/`):

- `20260826T182707Z` / `20260826T183227Z` — flash-lite pair via OpenRouter, **unpinned**
  (blended across two Google endpoints — usable, but disclose)
- `20260826T210353Z` / `20260826T210919Z` — qwen-2.5-7b pair, pinned to Phala
- `noise-rep{1,2}-{vector,rerank}-...-pinned` — the noise pairs, if that run completed

---

## What to do next, in priority order

This ordering was set after stepping back from the eval work. **The first two threaten numbers
already published in the README; the third is the only remaining change likely to improve the
product.** More model runs rank below all of them.

### 1. ~~The paraphrase experiment~~ — DONE 2026-08-27, and it inverted a headline

**BM25's lead over the embeddings is substantially an artifact of who wrote the questions.**
On 17 paired questions rewritten in lay language, BM25 fell from MRR 0.941 to **0.144** (hit@1
88.2% → 5.9%) and went from second-best retriever to last; vector went from last to second.
Reranking degraded least (−39%), as pre-registered. Everything degraded sharply. Full table and
caveats in the README.

Three follow-ups this opens, none of them started:

- **Extend the paraphrase set beyond 17 rows.** The current rows were chosen as the
  highest-overlap in the set, so they overstate the effect. A sample drawn across the overlap
  distribution would give an unbiased estimate. `eval/make_paraphrases.py` takes a row count.
- **Reconsider hybrid.** It now scores *below plain vector* on lay phrasing (0.402 vs 0.443),
  so design decision 23's quality case is weaker again. Still defensible on latency, but the
  gap between "chosen on latency" and "also fine on quality" has widened.
- **Real user questions, as a separate experiment.** The current rewrites are LLM-drafted and
  strip nearly all domain vocabulary; a real user would keep some. Public PM-JAY FAQ or forum
  questions would be actual user language — but they have different answers and target pages,
  so that is an unpaired test measuring something else, and needs its own golden rows.

`eval/paraphrase_set.csv` is now a **permanent second eval set**, run with
`--golden eval/paraphrase_set.csv`. It is a robustness check, not a baseline.

### 2. Golden-set target completeness — confirmed broken

Row 9 lists only `fraud_analytics_rfe.pdf` p.41, but **p.39 states the same 70% threshold** in
more detail. The model answered from p.39 almost verbatim, cited it, and scored as a citation
failure. **The model was right and the golden set was wrong.** Some share of the measured
"model errors" are eval errors.

Two detectors, both already run on 2026-08-25:

- *The model cited an unlisted page* — the better signal, since it surfaces pages the model
  treated as its source. **14 citation failures to review.**
- *A distinctive `must_contain` value appears on unlisted pages* — six candidates: rows 28, 29,
  38, 45, 62, 68. **Candidates only**; a number on a page does not mean the page answers the
  question. Hand-verify.

Do it in ONE edit, then re-run the four retrieval baselines and pool recall (~10 min).
**Adding targets moves numbers upward, and that is a measurement change, not an improvement** —
say so in the README, same as the `must_contain` unit-stripping.

**Ask the owner before changing `eval/golden_set.csv`.**

### 3. Prompt v2 — the only remaining change likely to improve the product

Targets the measured weakness: the model declines on yes/no and read-the-table questions where
the answer must be inferred rather than copied. The specific edit splits what rule 2 conflates:

- *Do not introduce any fact not present in the sources* — keep, strictly. This is the
  anti-hallucination rule and it is doing real work.
- *You may combine or compute from figures the sources state* — add explicitly. Rule 2 as
  written reads as a ban on arithmetic over stated values.

A/B against v1 with nothing else changed, via `PMJAY_PROMPTS` (design decision 20). **Bump the
version field.**

**This is where the noise band earns its keep** — see below. Without it you cannot tell whether
v2 beat v1 or simply wobbled.

### 4. Deployment

Nothing is live. A portfolio RAG project nobody can click is materially weaker. See
[DEPLOYMENT.md](DEPLOYMENT.md). Before any public demo: hard monthly spend cap in the provider
dashboard, per-session query limit in `st.session_state`, `max_tokens` capped server-side, key
in Hugging Face Spaces secrets, and log query volume to distinguish interest from abuse.

### 5. Optional — opus-5 for the multi-model table

~$3, both arms, pinned to `Anthropic`. **Run it for precision, false abstention, and
contradiction-handling — not for `citation_correctness`**, which is retrieval-capped at ~95%
hit@5 with flash-lite already at 94.2%. Framed as "does the expensive model score higher" it
will look like wasted money.

Note `anthropic/claude-opus-5` is an **alias** for `anthropic/claude-opus-5-20260723`, and has
**9 endpoints across 5 providers at two price points** — unpinned, even the cost is
nondeterministic. A strict pin costs nothing when it fails: the router returns 404 before any
inference, so nothing is billed.

### 6. CI

`--retrieval-only` needs no LLM and is the natural CI target (design decision 10).

---

## Reproducibility — MEASURED 2026-08-27, and better than expected

Two identical pinned `flash-lite` pairs were run to establish a noise band. **There is no noise
band: the runs were byte-identical**, 0 of 69 answers different, in both arms. Pinned to Google
AI Studio, `temperature: 0` is genuinely deterministic, and the pinned OpenRouter run reproduces
the earlier direct-Google-endpoint run to the digit.

The variance seen earlier came from **provider blending**, not from floating-point
nondeterminism: an unpinned run of the same model differs from the pinned one on 19 of 69
answers. See README gotcha 16 for the full table, including that `qwen-2.5-7b` on **Phala** is
*not* deterministic (~2 pts drift between identical runs) — **so reproducibility is a property
of the provider, not of hosted inference in general. Pin, then verify by repeating.**

**Consequence for prompt v2 (item 3).** The A/B is cleaner than expected: on a deterministic
provider, any difference between v1 and v2 is real, with no error bar to argue about. Run the
v1 baseline and the v2 arm pinned to the same provider, and diff the answers first to confirm
determinism still holds before reading the metrics.

**Consequence for the published deltas.** `flash-lite` precision +0.2 is now an exact
measurement rather than a noise-bounded one. Since +0.2 pts over 52 questions is a fraction of
one question, the conclusion is unchanged and is now stated more strongly: **reranking produced
no measurable precision gain on the hosted model.** The −0.8 previously reported came from the
unpinned blended run and should not be quoted.

---

## Open questions still live

1. **Which empanelment edition is in force?** Unresolved. Settle against NHA circulars, not
   filenames — inferring from filenames produced the false pair in README gotcha 3.
   `Docs/empanelment-diff.md` lists 13 same-clause-different-number pairs. Row 41 shows the
   reranker confidently preferring the wrong edition, so this is a measured failure.
2. **Abstention has no similarity threshold** — it is the model's judgement. Observed top scores
   ~0.79 in-corpus vs ~0.53 out-of-corpus. A threshold looks learnable but must be set with its
   false-abstention cost measured, and after Phase 2 the score is mode-dependent (gotcha 20), so
   any threshold must be per mode.
3. **`k = 5` is untuned** and is the dominant latency parameter. Reranking makes a smaller `k`
   plausible for the first time: hit@3 was 73.5% in Phase 1 and is 85.0% after reranking.
   Dropping 5→3 cuts roughly a third of query time. Worth measuring; tuning it against the
   golden set is test-set contact and must be disclosed.
4. **Rerank depth 30 is inherited, not derived.** Depth 25 gives the same union-pool ceiling as
   30. The `batch_size=32` boundary matters more than depth itself (gotcha 21). Untested for the
   hybrid pool.
5. **Does the window-homogeneity penalty appear on a frontier model?** Confirmed on two 7B
   models and absent on light-hosted. Untested above that — this is what item 5 above would
   answer.

---

## Three disclosures the README still owes

Required by design decision 13 and the anti-goals:

1. The **depth-25 choice was made by reading golden-set recall** — the mild form of test-set
   contact, but it is contact.
2. The **union pool arm was post-hoc**, suggested by failure analysis rather than pre-registered.
3. The **golden-set vocabulary bias** in item 1 above.
