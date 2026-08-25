# Handoff — PM-JAY RAG

Context for a fresh session picking this project up. Read this before touching code.
The project brief is [PMJAY-RAG-PROJECT.md](PMJAY-RAG-PROJECT.md); this file records what
was actually built, what was discovered along the way, and what is next.

**Where things stand (updated 2026-08-25):** Phase 1 is complete and measured. Phase 2's
**retrieval** work is finished, measured, and the candidate-pool question is settled (§3e).
Its **generation** work is still unmeasured on the current golden set — the first full
generation run was started 2026-08-25 and its result is not in this document yet. CI/CD is
deferred until after Phase 2.

Phase 2 retrieval through commit `0e38259` is committed. The work described in §3c.1
(mode threading, LLM recording, citation stripping, the pool comparison) is **written and
verified but NOT yet committed** — check `git status` before assuming.

---

# 0. START HERE — session handoff, 2026-08-26

## The headline finding

**Whether better retrieval produces better answers depends on the model.** Same golden set,
same prompt v1, same questions; retrieval the only variable within each pair:

| head-to-head (questions BOTH arms answered) | vector | rerank | delta |
|---|---|---|---|
| local `qwen2.5:7b` — 46 q | **80.4%** | 73.9% | **−6.5 pts** |
| hosted `gemini-3.1-flash-lite` — 52 q | 90.4% | **94.2%** | **+3.8 pts** |

Retrieval improved identically in both rows (MRR 0.624 → 0.795). The answers moved in
opposite directions. On the local model the cause is **window homogeneity** — reranking
returns five near-duplicate chunks and the model loses track of which it used. On the hosted
model that never happened: only two questions changed, both `miss` → rank 2–3.

Working hypothesis: a model that already attributes well converts a retrieval gain into an
answer gain; a model that struggles with attribution is confused by the same change.
**Untested on a genuinely strong model** — that is the top open question.

Three methodological notes that make this trustworthy:
- Aggregates are useless here — the arms decline different numbers of questions, so **always
  restrict to questions both arms answered** before comparing.
- The local pair ran on golden set v1 and the hosted on v2. The local answers were re-scored
  against v2 before comparing; the fix moved both arms by exactly one row, so the golden set
  is not the cause. The models are.
- An earlier version of the README claimed "better retrieval does not produce better answers"
  from the local pair alone. That was too strong and is corrected in place, not deleted.

## State of the tree

Committed through `6c623ed`. **Uncommitted:** `README.md`, `src/generate.py`, and three
untracked results files. Commit before doing anything else.

Results files worth knowing (`eval/results/`):
- `phase2-{vector,bm25,hybrid,rerank}-retrieval-69q` — the four retrieval baselines
- `phase2-rerank-{hybrid,bm25,union}-pool-69q` — the pool comparison (§3e)
- `phase1-vector-` / `phase2-rerank-generation-69q-local-qwen2.5-7b` — the local pair
- `hosted-phase{1,2}-...-gemini-3.1-flash-lite` — the hosted pair
- `FAILED-RUN-DO-NOT-USE-...gemini-3.5-flash` — 52 of 69 errored, kept deliberately as the
  run that looked fine and was not. Metrics cover 17 questions.

**All the 69-question runs before the golden-set fix used goldenv1.** Four rows gained target
pages (9, 28, 62, 68). Re-score rather than re-run where possible: the answers are saved.

## Free tiers were the bottleneck. Pay instead.

Four separate rate-limit behaviours were hit across two providers, and each cost hours:

| provider | limit | how it was found |
|---|---|---|
| Groq `gpt-oss-120b` | **200k tokens/DAY** | only ever stated in a 429 body, never a header |
| Groq | every retry is a billed request | retries drained the request bucket, driving `retry-after` from 15 s to 1,700 s |
| Gemini `3.5-flash` | **20 requests/DAY** | `quotaId: GenerateRequestsPerDayPerProjectPerModel` |
| Gemini | no rate-limit headers at all, retry hint only as prose in the body | header-based pacing is blind against it |

**A full 69-question run is a few cents.** Measured token use: ~2,400 input per question and a
**median 25–32 output tokens** (max 427; only one answer ever reached the 512 cap). So a run
is roughly 0.17M input + 0.003M output. At any budget-tier rate that is **under $0.05**.

Put $10–20 on a card and this entire class of problem disappears. That is the single highest
-value action available and it should happen before any further benchmarking.

## Next steps, in order

1. **Commit the tree.**
2. **Buy credit and re-run the pair on a capable model.** The open question is whether the
   local model's window-homogeneity penalty is a weak-model failure mode. `flash-lite` is
   light; the hypothesis needs a strong model to be tested properly.
3. **Multi-model comparison table for the README.** Now that a run costs pennies, run the same
   golden set across 3–4 models and publish: cost/run, latency p50, citation correctness,
   false abstention rate, `must_contain` pass. This converts "I picked a model" into "I
   measured four models against a hand-built eval set." Very few portfolio projects do this,
   and it is ~$1 of compute.
4. **Batch APIs** offer ~50% off and the eval is offline — a natural fit. Keep the synchronous
   path for the demo.
5. Then the outstanding Phase 2 / Phase 3 work below (§7): empanelment version conflict,
   prompt v2, paraphrase experiment, CI, deployment.

### Choosing a model — use the method, not a name

Model names and prices move faster than any document. **Do not trust a model name from a
document, including this one.** The procedure that worked, in order, before committing to any
model for a benchmark:

1. `GET {base_url}/models` — list what the key can actually reach.
2. **Reject `-latest` aliases and `preview` builds.** They change underneath a benchmark and
   break comparability (design decision 19). Pin one stable, versioned id.
3. Send **one real corpus prompt** through `config/prompts.yaml` and check three things:
   citations parse (`parse_citations`), the abstain string matches byte-for-byte, and
   `must_contain` still matches. This step has caught a failure **twice**: CJK bracket
   citations `【1】`, and a dagger form `【2†L1-L3】`. Both would have reported
   `citation_correctness` near zero with nothing explaining why. A model's output shape is
   **prompt-dependent** — sampling three calls is not enough.
4. Deliberately trigger a 429 and read the body. It is the only place daily quotas appear.

OpenRouter is a reasonable way to compare many models behind one key and one balance, then
move to a direct API once chosen — the adapter already supports this via `OPENAI_BASE_URL`
and `OPENAI_MODEL`, so switching is configuration, not code.

### Before any public demo

- Hard monthly spend cap in the provider dashboard
- Per-session query limit in `st.session_state`
- `max_tokens` capped server-side
- Key in Hugging Face Spaces secrets, never the repo
- Log query volume to distinguish interest from abuse

## Corrections to external cost advice

Guidance received from another assistant contained errors specific to this project. Recorded
so they are not re-imported:

- **"56 questions"** — the golden set is **69**.
- **"most answers hit the 512-token cap, cut to ~200"** — false. Median output is **25–32
  tokens**; exactly one answer in five runs reached 512. Output length is not a cost lever
  here and shortening it would not improve citation correctness by that route.
- **"the 72.5% citation baseline"** — stale. That is the archived 56-question Phase 1 figure.
  Current values are 80.4% (local vector) and 90.4% (hosted vector), on goldenv2.
- Model names and per-token prices in that advice could not be verified and have a short
  shelf life. Use the procedure above instead.

Its central claim is nonetheless **correct and worth acting on**: the amounts are trivial,
and fighting free-tier quotas has already cost far more than the money would have.

---

**Read [§3c](#3c-phase-2-status--read-this-before-continuing) first if you are resuming
Phase 2.** It lists exactly what is finished, what is half-finished, and the one gap that
matters most.

---

## 1. Environment — read this first

Windows 11, PowerShell. The single most common failure is running the wrong Python.

```powershell
# system `python` is 3.13 and has NONE of the dependencies
.venv\Scripts\Activate.ps1        # prompt must show (.venv)
python -m eval.run_eval

# or skip activation entirely
.venv\Scripts\python.exe -m eval.run_eval
```

`ModuleNotFoundError: No module named 'chromadb'` always means the venv is not active.

- Python **3.12** in `.venv` (3.13 is installed system-wide — not the one to use)
- `torch` is the **CPU** build (`2.13.0+cpu`); never let pip resolve torch from PyPI or it
  pulls a ~2.5 GB CUDA wheel as a `sentence-transformers` dependency
- Ollama runs `qwen2.5:7b` at `http://localhost:11434`; check with `curl .../api/ps`
- `HF_HUB_DISABLE_SYMLINKS_WARNING=1` silences cosmetic noise
- `truststore` is required — see gotcha 2 below
- Phase 2 added `pyyaml` to `requirements.txt`. `rank-bm25` and `sentence-transformers`
  were already there; the cross-encoder (~90 MB) downloads on first rerank call.

## 2. Pipeline

```powershell
python -m src.download          # 11 PDFs -> data/raw/   (gitignored)
python -m src.inspect_corpus    # text-native vs scanned triage
python -m src.extract           # -> data/processed/pages.jsonl
python -m src.chunk             # -> data/processed/chunks.jsonl
python -m src.index             # -> chroma/  (persistent; skips already-indexed)
streamlit run app.py
```

Corpus: **11 PDFs, 629 pages, 872 chunks.** All text-native, no OCR needed at document level
(but see gotcha 5).

Retrieval has **six** modes, selected by `--mode` on both CLIs and `--retriever` in the eval.
The last three differ only in which candidate pool the cross-encoder is handed:

```powershell
python -m src.retrieve "hospital empanelment criteria"        # vector (default)
python -m src.retrieve --mode bm25 "PAN card"
python -m src.retrieve --mode hybrid "empanelment renewal"
python -m src.retrieve --mode rerank "annual cover per family"        # hybrid pool
python -m src.retrieve --mode rerank-bm25 "annual cover per family"   # bm25 pool
python -m src.retrieve --mode rerank-union "annual cover per family"  # union pool

python -m src.generate --mode rerank "your question"   # same flag, same position
python -m eval.pool_recall                             # pool ceilings, no LLM, no reranker
```

`--mode` reaches generation as of 2026-08-25 (§3c). Before that the four Phase 2 retrievers
were reachable only from the eval harness, and the app was still Phase 1.

## 3. Baseline — Phase 1, recorded 2026-08-19  *(56-question set — HISTORICAL)*

> **These numbers are on the old 56-question golden set and are NOT comparable to anything
> below.** The set is now 69 questions. Retrieval has been re-baselined (§3d); the
> **generation** figures here have not, so there is currently no generation baseline on the
> current golden set. Re-running it is ~2.5 h locally or ~10 min against a hosted LLM, which
> is the strongest argument for doing the hosted swap next.

`eval/results/archive-56q/20260819T102845Z.json`, 56 questions (49 answerable, 7 abstain):

| Metric | Value |
|---|---|
| `hit_rate@1` | 51.0% |
| `hit_rate@3` | 73.5% |
| `hit_rate@5` | 89.8% |
| `mrr` | 0.641 |
| retrieve p50 / p95 | 127 ms / 260 ms |

Full run (`eval/results/archive-56q/20260819T163840Z.json`, same 56 questions, k=5):

| Metric | Value |
|---|---|
| `abstention_recall` | 100% (7/7) |
| `false_abstention_rate` | **15.9% (7/44)** — corrected, see below |
| `citation_correctness` | 72.5% |
| `must_contain_pass` | 74.1% (of 27 checked) |
| `uncited_answers` | 1 |
| generate p50 / p95 | 126.9 s / 169.5 s |

> **The false abstention figure in that results file says 18.4% (9/49).** That is the old,
> unconditioned definition. The corrected figure was recomputed offline from the same file:
> 7 of the 9 abstentions had the golden page retrieved, 2 did not. See §3a.1.

## 3a. Groundwork — DONE

Both items the previous handoff demanded before Phase 2 are complete.

**1. `false_abstention_rate` is now conditioned on the target having been retrieved.**
Denominator is answerable questions where `first_hit_rank > 0`. Baseline moves from
18.4% (9/49) to **15.9% (7/44)**.

The point is attribution, not the number. Unconditioned, the metric moves whenever
*retrieval* changes: a reranker that recovers a missed page shifts that question out of the
"rightly declined" bucket and into the denominator, so the rate moves for a reason unrelated
to abstention behaviour. `false_abstention_rate_unconditioned` and
`abstained_on_retrieval_miss` are both still recorded so older results stay comparable.

Validated by recomputing from the saved Phase 1 JSON rather than by re-running — the file
already carried `first_hit_rank` and the answer text.

**2. Ollama's latency breakdown is captured.** `src/generate.parse_stats` reads
`prompt_eval_duration`, `prompt_eval_count`, `eval_duration`, `eval_count` and
`load_duration`, and the eval records p50s and aggregate tokens/sec.

**The finding is decisive:**

| Sample | prompt eval (prefill) | generation (decode) | load |
|---|---|---|---|
| 1 (cold) | **162.9 s** · 2,456 tok · 15.1 tok/s | 7.6 s · 30 tok · 3.9 tok/s | 10.0 s |
| 2 (warm) | **161.3 s** · 2,547 tok · 15.8 tok/s | 9.1 s · 36 tok · 3.9 tok/s | 0.9 s |

**~95% of generation time is prompt prefill, not token generation.** Capping `num_predict`
would save nothing. The lever is fewer or smaller chunks — which makes **`k` the primary
latency parameter**, not just a quality one. Prefill is actually *faster* per token
(15 vs 3.9 tok/s); it dominates because there are ~80× more prompt tokens than answer
tokens.

Six further cold samples (the gotcha 19 experiment) put prefill at a consistent
**18–21 tok/s**, slightly better than the two figures above, so treat ~20 tok/s as the
working number and the 15 tok/s samples as mildly contended. The conclusion is unchanged:
at 20 tok/s a 2,349-token prompt costs ~117 s against ~14 s of decode, still **~90% prefill**.

Two details worth knowing:
- **Abstaining does not save time.** The out-of-corpus question still paid 130 s of prefill —
  retrieval hands over five chunks regardless, and the model reads all of them before
  declining. Only decode is short (10 tokens).
- `load_ms` was 0.0 s on every timed question, confirming the warmup call absorbs the model
  load exactly as intended (gotcha 9).

Caveat: the eval-wide p50 split still needs a full generation run, which has not happened.

**Still outstanding from the original §3a list:** the golden set is not finalised (see open
questions 2 and 5), and no fast-iteration subset exists.

## 3b. Known behaviour worth reviewing by hand

- **7 of 9 false abstentions had the evidence retrieved**, 4 of them at rank 1. The pattern is
  yes/no and read-the-table questions (rows 33, 35, 40) plus negation (row 53) — the model
  declines when the answer must be *inferred* rather than copied. This is prompt strictness,
  not retrieval, and now that prompts are versioned it is A/B-testable as prompt v2.
- **Golden rows 36 and 67 are further instances of the same failure**, deliberately kept.
  Row 67's page states "a duration of 3 (three) years... extension... up to a maximum of two
  (2) additional years"; the answer, 5 years, requires adding two stated figures. That is
  reading a compound fact, not inventing one, and a system that cannot do it is a search box
  rather than an assistant. Their `must_contain` values are legitimately absent from the
  target page — the only two rows for which that is true, and by design.
- **5 questions failed retrieval but only 2 abstained.** The other 3 answered with no golden
  chunk retrieved — hallucination candidates, worth reading manually.
- **Glossary pages are systematically hard to retrieve** (§3d). An abbreviations table
  mentions a term once, in a list, with no context, and both retrievers prefer pages that
  *use* the term over the page that *defines* it. Rows 61 and 62 are the only two questions
  whose golden page never enters the candidate pool at all.
- **Use `--no-save` for exploratory runs** rather than saving unlabelled results. Always pass
  `--label` on runs worth keeping; unlabelled files become archaeology.

## 3c. Phase 2 status — READ THIS BEFORE CONTINUING

### What is done

| Change | Code | Retrieval measured | Generation measured |
|---|---|---|---|
| a. BM25 via `rank-bm25` | done | done | **no** |
| b. Reciprocal rank fusion | done | done | **no** |
| c. Cross-encoder reranking | done | done | **no** |
| d. `config/prompts.yaml` v1 | done | n/a | **no** |
| e. Empanelment version conflict | **not started** | | |
| f. Retrieval `mode` reachable from the product | done | n/a | n/a |
| g. LLM recorded in results `config` | done | n/a | n/a |
| h. Citation markers stripped before `must_contain` | done | n/a | n/a |
| i. Candidate-pool comparison (open q5) | done | done | n/a |

Four retrieval-only results files are saved and labelled:
`phase2-baseline-vector-retrieval`, `phase2a-bm25-only-retrieval`,
`phase2b-hybrid-rrf-retrieval`, `phase2c-rerank-retrieval`.

### The gap that mattered most — CLOSED 2026-08-25

*Kept because the reasoning still applies to any future harness/product split.*

**`src/generate.answer()` took no retrieval mode**, so it always used `DEFAULT_MODE`
(`vector`):

```python
def answer(question, k=DEFAULT_K):
    hits = search(question, k=k)          # <- no mode argument
```

Consequence: **the Streamlit app and `python -m src.generate` still use Phase 1 retrieval.**
The four new modes are reachable *only* from the eval harness, which calls `search(...)`
directly. The measurement uses Phase 2; the product does not.

**Fixed.** `answer(question, k, mode=DEFAULT_MODE)` now threads `mode` into `search()`;
`python -m src.generate --mode MODE "..."` parses the flag exactly as `src.retrieve` does;
and `app.py` has a sidebar mode selector. Verified by asserting that `answer(mode=X)` calls
`search(mode=X)` for every mode, and that a full retrieval-only run still reproduces §3d
exactly (MRR 0.624 for vector), which is what proves nothing in retrieval moved.

`DEFAULT_MODE` deliberately stays `"vector"` — design decision 21 holds until the generation
evidence exists. **The 2026-08-25 generation run is that evidence**; if `rerank` holds up,
flip `DEFAULT_MODE` to `"rerank"` then, and the app default follows it automatically.

Three things surfaced while doing this and are worth knowing:

- **`hit["score"]` means something different per mode** (gotcha 15), which only became a
  user-visible problem once modes were selectable. `SCORE_LABELS` in `src/retrieve.py` is
  now the single definition, read by the two CLIs and the app so the three cannot drift.
  A bare "score" of `0.86` (cosine), `7.73` (bm25) and `0.032` (RRF) invites a comparison
  that is meaningless.
- **Both CLIs crashed on cp1252** when a chunk contained a private-use PDF glyph (gotcha 11).
  Fixed with the `eval/find.py` remedy, but applied *inside* `main()` — these modules are
  imported by `app.py` and the eval, and reconfiguring their stdout from an import would be
  a side effect neither asked for.
- **`src.retrieve`'s CLI prints only `hit["text"][:400]`** of a chunk that runs to ~2,400
  characters. This makes correct retrieval look wrong: a question about "Arogya Shiksha"
  returned the right chunk at rank 1 from both retrievers, and the term sits at character
  451 — 51 characters past the preview. **Not yet fixed.** Print the chunk length and the
  region around the query terms instead of the head.

### Generation — the first Phase 2 run is IN FLIGHT

**Started 2026-08-25**, hybrid pool, local `qwen2.5:7b`:

```powershell
python -m eval.run_eval --retriever rerank --label "phase2-rerank-generation-69q-local-qwen2.5-7b"
```

Expect **~3 hours**, not the 2.5 h quoted elsewhere in this file: the 2026-08-24 smoke test
measured generate p50 at 161.5 s, and 69 × 161.5 s ≈ 3.1 h. **If that results file exists,
it is the first generation run on the 69-question golden set and the first ever to carry
`prompt_version`, `llm_model` and `gen_stats`.** If it does not exist, the run did not
finish — check for a sleep (gotcha 17) before trusting anything partial.

Read it against these, from the 3-question smoke test on 2026-08-24 (n=3, so watch for the
pattern, do not quote the numbers):

- **Citation correctness was 33.3% while hit@1 was 100%.** All three answers were factually
  right and the golden page was at rank 1 every time, yet two cited `[4]` and `[2]` instead.
  The model answers from a chunk other than the golden one — plausibly the same fact on
  several pages, which is row 25's situation generalised. If that holds at 69 questions,
  `citation_correctness` is partly measuring golden-set completeness rather than the model.
- **Row 67 succeeded at the inference it is documented as failing.** §3b keeps rows 36 and 67
  as cases where the answer must be *inferred* (3 + 2 = 5 years). Under prompt **v1**, with
  rerank retrieval, the model produced it correctly and showed its working. That complicates
  the motivation for prompt v2 (§7.7) — if it holds up, part of the problem v2 targets may
  already be a retrieval problem rather than a prompt one.
- Prefill was **152.0 s / 2,608 tok / 17.6 tok/s** against 7.4 s of decode — ~95% prefill,
  inside gotcha 19's cold 18–21 tok/s band, and Ollama was confirmed empty beforehand so
  these are not gotcha 18 cache hits.

Every generation metric on record BEFORE that run — citation correctness, abstention,
`must_contain`, latency — is **Phase 1 code with Phase 1 retrieval**. A full local run was
started and deliberately stopped after ~15 minutes. Nothing was saved.

`prompt_version` and `gen_stats` have therefore never been written to a *saved* results file.

**Smoke-tested 2026-08-22.** Three questions (one `must_contain`, one ABSTAIN, one plain)
were run through `evaluate -> summarise -> report` in `rerank` mode with generation enabled,
and the save block was replicated to confirm serialisation. **The path works**: every new
metric key is produced (`n_false_abstention_denom`, `abstained_on_retrieval_miss`,
`false_abstention_rate_unconditioned`, `prompt_eval_ms_p50`, `eval_tps`, `n_timed`,
`n_model_reloads`) and the payload serialises cleanly. No crash risk at the end of a long
run.

Run twice (the first run's machine slept mid-way). Between the two runs the code path behaved
identically, but **the generation metrics did not** — see gotchas 17, 18 and 19, which came
out of comparing them. Those three are the most consequential things learned this session and
they all bear on how the overnight run must be done and read.

Cosmetic nit, still unfixed (deliberately left out of the 2026-08-25 changes to keep that
diff to its three items): the `report()` line for `abstained_on_retrieval_miss` prints as
`...also declined on a  0  retrieval miss (correctly)`, which reads badly. Reword it.

### Golden set went 56 -> 69 on 2026-08-24

All four retrieval baselines were re-run on the new set and §3d reflects it. What has **not**
been redone is the **generation** baseline: the only one on record is the 2026-08-19 run over
56 questions, which is not comparable to anything current.

So the state is: retrieval is measured on 69 questions, generation is measured on 56, and the
two cannot be put in the same table. Fixing that is ~2.5 h locally or ~10 min hosted.

Also changed in that edit: `must_contain` values had their units stripped (design decision 8),
so `must_contain_pass` from the 2026-08-19 run is not comparable to any future value either —
it was measured under the old, stricter definition.

## 3d. Phase 2 retrieval results — 69 questions, k=5

Re-run 2026-08-24 on the current golden set (60 answerable, 9 abstain). Measured one change
at a time. Results files are labelled `phase2-{vector,bm25,hybrid,rerank}-retrieval-69q`.

| Retriever | hit@1 | hit@3 | hit@5 | MRR | Δ MRR | p50 |
|---|---|---|---|---|---|---|
| `vector` (Phase 1 baseline) | 48.3% | 71.7% | 90.0% | 0.624 | — | 26 ms |
| `bm25` | 58.3% | 78.3% | 81.7% | 0.677 | +0.053 | 2 ms |
| `hybrid` (RRF) | 51.7% | 81.7% | 86.7% | 0.671 | −0.006 | 29 ms |
| `rerank` | **71.7%** | **85.0%** | **95.0%** | **0.795** | **+0.124** | 3,269 ms |
| **vs baseline** | +23.4 | +13.3 | +5.0 | **+0.171** | | 126× |

Candidate-pool recall — the ceiling a reranker of that pool can reach:

| Pool | recall@5 | recall@10 | recall@20 | recall@30 |
|---|---|---|---|---|
| `vector` | 90.0% | 90.0% | 95.0% | 96.7% |
| `bm25` | 81.7% | 86.7% | 95.0% | **98.3%** |
| `hybrid` | 86.7% | 95.0% | 96.7% | 96.7% |

### What changed against the 56-question set, and what it means

The shape of the result survived: BM25 still beats the embeddings on hit@1 and MRR, RRF still
costs hit@1 while buying hit@3, and reranking is still where the gain is. But three claims
that held at 56 questions do **not** hold at 69, and two of them were load-bearing.

**1. `hit@5 = 100%` is gone — it is now 95.0%.** Three golden pages are missing from the final
top 5. The perfect score was an artefact of the smaller set, and its disappearance is a useful
correction: it was always the number most likely to be flattering.

**2. Hybrid is no longer the best candidate pool — BM25 alone is.** At depth 30 BM25 reaches
98.3% against hybrid's 96.7%. On the old set they tied at 100%, and hybrid was chosen on a
margin argument. **That argument has now reversed**, and open question 5 is no longer
hypothetical — it is the single most likely improvement available.

**3. RRF can push a chunk out of the candidate pool entirely, not merely demote it.** Row 61
("What do mean by DDO?") is the clean case:

```
vector  NOT IN TOP 30
bm25    rank 17          <- the only retriever that finds it
hybrid  NOT IN TOP 30    <- RRF drops it below 30 chunks both retrievers agreed on
```

This is the row-39 mechanism with a fatal outcome. A demotion inside the pool is recoverable
by the reranker; being pushed out of the pool is not. Fusion is discarding exactly the
find that BM25 was added to contribute.

### The new failure mode: glossary pages

Rows 61 and 62 are the only two questions whose golden page is absent from the hybrid pool
altogether, and they are the same kind of question — acronym lookups answered by an
abbreviations table.

- `DDO` appears on **exactly one page of the corpus** (`operation_manual.pdf` p.3, the
  glossary) and still is not retrieved by embeddings at all. BM25 gets it to rank 17.
- `CSC` appears on 15 pages and the question lists **five** valid golden pages. Measured
  separately, **both retrievers find one** — vector reaches `operation_manual.pdf` p.3 at
  rank 23, BM25 reaches `grievance_redressal.pdf` p.22 at rank 26. They are different valid
  pages, so neither is corroborated, each gets a single RRF contribution, and **fusion drops
  both.** Two right answers went in and nothing came out.

  This generalises into a rule worth remembering: **RRF is hostile to questions with several
  valid answers.** The more valid targets a question has, the more likely the two retrievers
  land on different ones, and the more likely fusion discards all of them for lack of
  agreement.

**A glossary page mentions a term exactly once, in a list, with no explanatory context.** Both
retrievers systematically prefer pages that discuss a term over the page that defines it. This
is a real corpus-level weakness worth stating in the README failure analysis, and it is
unlikely to be fixed by reranking — the cross-encoder never sees the page.

### Reranker regressions still present

Row 58 entered the pool at rank 3 and the cross-encoder pushed it below the top 5. The
edition-confusion and adjacent-page-crowding failures recorded previously still stand.

### Latency note

`rerank` p50 is **3,269 ms** here against 6,075 ms on the 56-question run. Same depth, same
model. The earlier figure was measured on a machine that was doing other things; this one was
measured idle. Treat ~3.3 s as the real cost and see gotcha 21 — batch padding makes it vary
with chunk length regardless.

## 3e. The candidate-pool question — SETTLED 2026-08-25

This is open question 5, and it is now answered with measurements rather than argument.
All three arms are k=5, depth 30, same cross-encoder, same 69 questions, retrieval-only.

| arm | pool | hit@1 | hit@3 | hit@5 | MRR | p50 | k=5 misses |
|---|---|---|---|---|---|---|---|
| `rerank` | hybrid (RRF, cut to 30) | 71.7% | 85.0% | 95.0% | 0.795 | 2,012 ms | 58, 61, 62 |
| `rerank-bm25` | bm25 top 30 | **73.3%** | 86.7% | 95.0% | **0.808** | 3,732 ms | 58, 62, 66 |
| `rerank-union` | both lists, deduped (~50) | 71.7% | 86.7% | **98.3%** | 0.806 | 6,741 ms | **58** |

Results files: `phase2-rerank-hybrid-pool-69q`, `phase2-rerank-bm25-pool-69q`,
`phase2-rerank-union-pool-69q-measured-not-adopted`.

**The hybrid arm reproduced the saved `phase2-rerank-retrieval-69q` baseline exactly**
(0.795 / 71.7 / 85.0 / 95.0), which is what proves making the pool a parameter changed
nothing about the existing measurement.

### Decision: hybrid stays, chosen on latency, NOT on quality

Recorded plainly because the numbers say the opposite of what "we kept hybrid" implies:
**hybrid loses the coverage comparison** (95.0% vs the union's 98.3% hit@5) and wins the
latency one. The target is a public demo on free hosting, where §4 of DEPLOYMENT.md projects
the cross-encoder running ~4× slower than locally. Do not read this table as hybrid winning.

### Why pool recall did not decide it

`eval/pool_recall.py` (new; the §3d recall table was previously ad hoc and could not be
reproduced from the repo) reports pool ceilings at depth 30:

| pool | recall@30 | misses |
|---|---|---|
| vector | 96.7% | rows 39, 61 |
| bm25 | 98.3% | row 66 |
| hybrid | 96.7% | rows 61, 62 |
| **union** | **100.0%** | none |

BM25's recall lead over hybrid is **+2 questions and −1 question**, not a strict improvement:
the pools are not nested. And the net +1 converted to net 0 in the reranked result, because
**a pool gain is optional while a pool loss is mandatory**. Row 61 was in the BM25 pool at 17
and the cross-encoder promoted it to rank 1; row 62 was in the same pool at 26 and the
cross-encoder declined to promote it at all; row 66 was absent and therefore unrecoverable.
Two soft gains and one hard loss cancel.

**Recall is a ceiling, not a score.** Comparing pools by the recall scalar assumes the extra
recall converts and the missing recall does not matter. Here both assumptions failed, in
opposite directions.

### Why the union is the better pool, and what it costs

RRF is a ranking **and truncation** step: it merges up to 60 distinct chunks and cuts back to
30, and that cut is the only place a page can be lost. `rerank()` then re-sorts entirely by
cross-encoder score, **discarding RRF's ordering completely**. So in a reranking pipeline
fusion contributes nothing downstream while its truncation still costs pages — it keeps only
its downside. Fusion earns its keep when its output *is* the answer.

The union recovered rows 61 and 62 (miss → ranks 2 and 3) and cost only two one-rank
demotions, rows 4 (3→4) and 24 (4→5), both still inside the window. **The distractor-pressure
risk did not materialise**: hit@1 was identical to hybrid despite ~20 more candidates. That
is worth knowing — it was the main argument against a union.

Its single remaining miss, row 58, **is not a retrieval failure**: the page is in the pool and
the cross-encoder demotes it (the §3d regression), and the question sits on gotcha 4's
self-contradiction. After a union, retrieval stops being what loses answers anywhere.

The cost is structural, not incidental. `CrossEncoder.predict` uses `batch_size=32`
(gotcha 14), so hybrid and bm25 at depth 30 fit **one** batch by construction while the
union's ~50 needs **two**, the second mostly padding. That is why 1.66× the candidates costs
3.3× the time.

### Depth, if the union is ever revisited

Measured union pool recall by per-retriever depth:

| depth | union size | CE batches | pool recall |
|---|---|---|---|
| 5–16 | 8–26 | **1** | 96.7% |
| 20 | 33.2 | 2 | 98.3% |
| **25** | **41.4** | 2 | **100.0%** |
| 30 (current) | 49.9 | 2 | 100.0% |

Two conclusions. **Depth 25 is free** — same 100% ceiling as 30 with ~17% fewer candidates.
And **you cannot have the union's recall and a single batch**: rows 61 and 62 sit at ranks 17
and 23/26, so reaching them requires depth ≥ 26, which puts the pool over 32. Every one-batch
configuration falls back to 96.7% — losing exactly what the union exists to recover.

Note that choosing depth 25 by reading golden-set recall **is** test-set contact under design
decision 12. It is the mild form — the smallest depth preserving an already-measured ceiling,
not tuning for a score — but it is disclosed, and it must reach the README.

If int8 ONNX quantisation (DEPLOYMENT §4) makes reranking cheap enough, revisit this. Rough
arithmetic, stacked estimates and not measurements: union at depth 25 ≈ 5.8–6.1 s local,
÷3–4 for int8 ≈ 1.5–2.0 s, ×4 for a weak free-tier vCPU ≈ 6–8 s, plus ~2 s of hosted LLM.

## 4. Design decisions — do not silently reverse these

Phase 1:

1. **Chunks never span a page boundary.** Every chunk carries exactly one page number, so a
   citation always points at a page that genuinely contains the text. Costs cross-page
   context; bought guaranteed citation accuracy. Revisit only with evidence from the eval.
2. **The BGE query prefix is applied query-side only**, in `src.index.embed_query`.
   Applying it to documents too, or omitting it from queries, degrades retrieval *silently*.
   `retrieve.py` imports from `index.py` so the two sides cannot drift.
3. **Embeddings are L2-normalised and the Chroma space is cosine.** Chroma defaults to `l2`;
   mismatching them changes ranking with no error.
4. **Page numbers are physical position in the file** (`i + 1`), matching a PDF viewer's page
   counter — not the number printed on the page.
5. **No orchestration framework.** The retrieval loop is plain Python on purpose.
6. ~~Prompts are inline in `src/generate.py`.~~ **Superseded in Phase 2** — see 17.
7. **The golden set is anchored to `(source_file, page)`, never chunk IDs.** This is what lets
   the eval survive re-chunking, re-embedding and model swaps — without it, no Phase 2 number
   could be compared to the Phase 1 baseline.
8. **`must_contain` holds the smallest string that carries the fact — normally a bare
   number — and is matched against the model's answer, not against the page.**

   It exists to catch exactly one failure: *the right page was retrieved and the model stated
   the wrong figure.* It is deliberately **not** a test of phrasing, completeness or style.

   That is why units are stripped. `48` passes on "48 hrs", "48 hours" and "forty-eight
   hours"; `48 hrs` fails all but one of them. `136` passes on both "136 percent" and "136%".
   The number is the claim; the unit wording is presentation, and the source's own wording is
   not the only correct wording. Keeping the value bare also needs no matcher changes — it is
   still a plain substring check.

   A phrase is right only when the phrase **is** the fact: acronym expansions such as
   `Deputy District Officer`, or proper nouns like `Aadhaar`. A model writing "District
   Deputy Officer" is genuinely wrong, so the words carry the claim there.

   Leave the field **blank** for yes/no, definitional and descriptive questions. There is no
   load-bearing value to check, and a phrase would only manufacture false failures.
   `citation_correctness` and the abstention metrics still cover those rows.

   **`must_contain_pass` is a floor, never a target.** Optimising the prompt to raise it would
   push the model toward reciting source text verbatim, which is worse product behaviour, not
   better. If it ever rises because answers got more literal, that is a regression wearing a
   metric's clothing.
9. **Retrieval metrics need no LLM** (`--retrieval-only`). Deliberate, and what makes CI
   possible later.
10. **Errored questions are excluded from generation metrics**, not counted as wrong. A
    network blip must never look like a quality regression.

Phase 2:

11. **Fusion merges ranks, never scores.** A cosine similarity (~0.69) and a BM25 score
    (~12.55) are different scales; combining them numerically needs a normalisation step that
    is itself a tuned parameter. Positions are comparable without one.
12. **`RRF_K = 60` and `FUSION_DEPTH = 30` are left at their published/brief defaults, not
    tuned.** Tuning either against the 69 evaluation questions would be fitting a constant to
    the test set and reporting the fit as a measurement. If you ever tune them, say so in the
    README.
13. **The BM25 index is built from the Chroma collection, not from `chunks.jsonl`.** This makes
    it structurally impossible for the lexical and dense sides to search different corpora.
    Re-chunk without re-indexing and the alternative would silently diverge.
14. **The BM25 tokenizer keeps Indian-format numbers whole.** `\d[\d.,]*\d` before
    `[a-z0-9]+`, so `5,00,000` survives as one high-IDF token instead of becoming
    `5`/`00`/`000`. Hyphens deliberately split, so "PM JAY" matches "PM-JAY".
15. **Tokenisation symmetry is per-retriever and opposite.** BM25 applies `tokenize()` to
    *both* query and corpus; BGE applies its prefix to the *query only*. Two adjacent
    retrievers with opposite rules — each is enforced inside one function so they cannot drift.
16. **Every ranking breaks ties on `chunk_id`.** BM25, RRF and reranking all sort by
    `(-score, chunk_id)`. Without it, equal scores resolve by whatever order the data arrived
    in and two runs of identical code can report different numbers.
17. **Prompts live in `config/prompts.yaml` with a `version` field**, recorded in every
    generation results file. v1 was verified **byte-identical** to the `phase-1` git tag
    (872 chars), which is what keeps the Phase 2 generation run comparable to the baseline.
    The decline string is defined once and substituted into rule 3 via `{abstain}` so the
    instruction and the string the eval matches cannot diverge. **Bump `version` on every
    edit.**
18. **`false_abstention_rate` is conditioned on the golden page having been retrieved.**
    See §3a.1. Do not revert to the unconditioned form as the headline number.
19. **One build reaches every phase, by flag — do not create per-phase branches or builds.**
    `--retriever vector` reproduces Phase 1 retrieval exactly, and prompts v1 is byte-identical
    to the phase-1 prompt, so today's code scores Phase 1 and Phase 2 with the *same harness*.
    Separate builds would be scored by different harness versions and the numbers would not be
    comparable — the same trap the unconditioned FAR was.
    **This property has to be actively preserved.** It holds today because `retriever` and `k`
    are parameters. It does *not* automatically extend to prompts v2 (use the `PMJAY_PROMPTS`
    env var to point at a second file), and it cannot extend to re-chunking or an embedding
    model swap, which need a re-index. Anything that changes the index breaks the property and
    forces a full re-baseline.
20. **Results from a superseded golden set move to `eval/results/archive-56q/`, never
    deleted.** The JSON `label` fields do not record the question count, so the folder does
    it instead, with a README naming what changed. Any future golden-set change gets the same
    treatment: a new `archive-<n>q/` folder and a manifest. Deleting them would destroy the
    record of how each phase was actually measured; leaving them loose in `eval/results/`
    would invite someone to put incomparable numbers in the same table.
21. **`DEFAULT_MODE` stays `"vector"` until generation evidence exists.** Retrieval improved,
    but nothing yet shows that better ranking produces better *answers*. Switching the default
    before measuring would make the product's behaviour change for unmeasured reasons.

Added 2026-08-25:

22. **The rerank candidate pool is a parameter, and `hybrid` was chosen on LATENCY, not
    quality.** See §3e. The union pool measures strictly better on evidence coverage
    (98.3% vs 95.0% hit@5) and reduces retrieval to a single failing question; hybrid was
    kept because the target is a public demo on free hosting where the cross-encoder is
    projected to run ~4× slower. **Anyone reversing this should reverse it on latency
    evidence, not because they think hybrid retrieves better — it does not.**
23. **Losing arms stay reachable by flag, never deleted.** `rerank-bm25` and `rerank-union`
    both lost and both remain modes. This is design decision 19 applied to experiments: the
    results files that justify the choice name a `config.retriever`, and a results file
    naming a mode that no longer exists is unreproducible archaeology. Keeping the code is
    cheaper than losing the evidence.
24. **`hit["score"]` is labelled with what it actually is, from one definition.**
    `SCORE_LABELS` in `src/retrieve.py` maps mode to `cosine` / `bm25` / `rrf` / `ce logit`,
    and both CLIs plus the app read it. Gotcha 15 was a latent trap while modes were only
    reachable from the eval; it became a user-visible one the moment the app got a selector.
    A bare "score" of 0.86, 7.73 and 0.032 invites a comparison that means nothing.
25. **Citation markers are stripped before the `must_contain` comparison, and only there.**
    After `parse_citations`, which needs them; substituting a SPACE rather than nothing, so
    "the fee [3] is 48" cannot fuse into one token. The raw answer is still what gets saved
    to the results file — the strip is a comparison detail, not an edit to the record.
26. **The results `config` block records the LLM, and records `null` for it on
    retrieval-only runs.** Naming a model that had no influence on the numbers would be
    worse than naming none. `llm_provider` exists with one possible value today so that the
    field predates the second provider rather than arriving with it — a field that appears
    late leaves every earlier file ambiguous about something it never stated.

## 5. Gotchas discovered the hard way

1. **The brief's `nha.gov.in` URLs are dead.** The portal became a single-page app; those
   paths return the app shell as `HTTP 200 text/html`. Search engines still index them. The
   `%PDF` magic-byte check in `src/download.py` is what caught it. Documents were re-sourced
   from government mirrors and Wayback — provenance is recorded per-entry in `download.py`.
2. **TLS:** `nha.gov.in` presents a chain Windows trusts but `certifi` does not
   (`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`). Fixed with
   `truststore`, which uses the OS trust store — **not** `verify=False`.
3. **The brief's "two conflicting empanelment editions" are byte-identical.**
   `Hospital-Empanelment-Guidelines-21-12-22.pdf` and
   `Revised-Empanelment-and-De-empanelment-Guideline.pdf` share one sha256
   (`9B61270B...`, 1,481,305 bytes) — one document under two filenames. The real version pair
   is `empanelment_dec2021.pdf` (46pp) vs `empanelment_v2_0.pdf` (64pp, cover states
   "Version - 2.0"), the latter found on the Kerala SHA mirror. Do not re-add the duplicate.
4. **`empanelment_v2_0.pdf` contradicts itself** — show-cause response time is 5 working days
   on p.29 and 3 working days on p.34. Genuine test material.
5. **Some values live inside images.** Four questions were written, verified, then moved to
   `eval/known_gaps.csv` because the answer is not in the extracted text at all — e.g. the
   word "helpline" extracts from `operation_manual.pdf` p.30 but `14255` appears nowhere in
   the file. `src/inspect_corpus.py` cleared all 11 PDFs as text-native because it measures
   **average characters per page**, which cannot see an image table on a text-heavy page.
   Document-level triage is not content-level coverage.
6. **Ollama evicts an idle model after 5 minutes.** Mid-eval that meant a ~2.5 min cold CPU
   reload that blew a 300s timeout and killed a whole run. Fixed with `keep_alive: "30m"`.
   `gen_stats["load_ms"]` now exposes this — a non-zero load after warmup means an eviction
   happened mid-run, and `n_model_reloads` counts it.
7. **Ollama's default `num_ctx` is 4096** — too small for 5 chunks, and it truncates from the
   front, silently dropping the sources. Set to 8192.
8. **`num_predict: 512`** caps answer length. Uncapped, one enumerating answer can run for
   minutes on CPU and dominate a whole eval run. Note the latency finding in §3a.2: this cap
   is *not* where the time goes.
9. **Latency must be measured after a warmup call to both stages**, or the embedding-model
   load (~5s) and Ollama's model load land entirely on question 1 and distort p50/p95.
10. **CSV values containing commas must be quoted** (`"4,500"`). One unquoted value shifted a
    whole row and put the filename in the `page` column. `must_contain` therefore splits on
    `;` only.
11. **Windows console is cp1252** and crashes on non-encodable characters; `eval/find.py`
    reconfigures stdout with `errors="replace"`.
12. **`grep` buffers when piping to a file**, so a backgrounded run appears to produce no
    output. Use `--line-buffered`, or `python -u`, or run it in a terminal and watch the
    progress marks (`.` hit, `x` miss, `E` generation error).

Phase 2:

13. **The cross-encoder's input window is 512 tokens and chunks target ~600.**
    **299 of 872 chunks (34.3%) are truncated** before scoring, so a chunk whose only relevant
    sentence sits in its tail can be scored as irrelevant. Not the cause of any regression
    observed so far — row 24's chunk is 358 tokens — but a live risk. Re-chunking to fit would
    change the indexing the Phase 1 baseline was measured against.
14. **`CrossEncoder.predict` defaults to `batch_size=32`.** Depth ≤32 is a single batch; depth
    33–63 costs two batches, and the second is mostly padding. If you raise `FUSION_DEPTH`,
    go to 64, not 40. Also: batches pad to the *longest* sequence present, so one 512-token
    chunk makes every chunk in that batch cost 512 tokens.
15. **In `hybrid` and `rerank` modes, `hit["score"]` is no longer a similarity.** It is an RRF
    score (~0.03) or a cross-encoder logit (unbounded, often negative). Anything that
    thresholds or compares `score` across modes will break silently. Nothing does today —
    abstention is the model's judgement, not a threshold — but see open question 3.
16. **`chroma/` and `data/processed/` are gitignored**, and `chroma/` is 16 MB. Nothing
    deployable exists in the repo today; the index has to be committed or rebuilt on the host.
    See [DEPLOYMENT.md](DEPLOYMENT.md).
17. **A machine that sleeps mid-run silently corrupts the latency numbers.** Ollama reports
    wall-clock elapsed time, so a suspend inflates whatever phase it slept through. In the
    2026-08-22 smoke test one question logged **3,051 s of prompt eval for 2,317 tokens —
    0.76 tok/s against the usual ~15** — purely because the machine slept. It dragged
    `generate_ms_p95` to 47 minutes.
    The tell is that **only one phase inflates**: that same question's decode ran at
    4.03 tok/s, exactly normal, and `load_ms` stayed at 0.7 s with `n_model_reloads` at 0.
    Genuine CPU contention would slow *both* phases; an Ollama eviction (gotcha 6) would show
    in `load_ms`. Neither happened.
    **Disable sleep and screen-lock before the overnight run** — `powercfg /change
    standby-timeout-ac 0` — and sanity-check p95 against p50 afterwards. One suspended
    question makes the whole latency table meaningless.
18. **Re-running the same questions gives fake prefill numbers — Ollama caches prompts.**
    The clean rerun of the same three questions reported prompt eval of **0.2 s for 2,349
    tokens, i.e. 10,392 tok/s**, against the true ~15 tok/s. That is a KV-cache hit, not a
    measurement: llama.cpp keeps per-slot prompt caches, retrieval is deterministic, so the
    second run sent byte-identical prompts and paid nothing to ingest them.
    Consequences: **prefill numbers from any repeat run are worthless**, and a `prompt_eval_tps`
    in the thousands is the signature to look for. A first run over 69 distinct questions is
    genuinely cold and unaffected. If you need to re-measure latency, restart Ollama first.
    (The two diagnostic samples in §3a.2 were both first-time questions on a freshly loaded
    model, so those numbers stand.)
19. **Generation IS reproducible — but only from a cold model. Unload before any run you
    will compare.** *Settled 2026-08-22.*

    Two smoke runs of the same three questions produced different answers
    (`citation_correctness` 50% → 100%, `must_contain_pass` 0% → 100%), which raised the
    question of whether `temperature: 0` was reproducible at all. It is. The cause was the
    prompt cache in gotcha 18, not the CPU backend.

    The experiment: unload the model, run three fixed questions, unload, run them again.
    **All three answers were byte-identical across both cold passes** — 53 / 10 / 374 answer
    tokens both times, and identical retrieved chunks. Prefill ran at 18–21 tok/s in both
    passes, confirming the unload really did clear the cache and the test was valid.

    So the rule is a protocol one, and it is simple:

    > **Unload the model before any run whose numbers will be compared to another run.**
    > `POST /api/generate` with `{"model": ..., "prompt": "", "keep_alive": 0}`, then poll
    > `/api/ps` until empty.

    Follow it and generation metrics stay single-number and comparable — no repeats, no
    variance reporting needed. Skip it and a re-run silently reports different quality
    numbers for the same configuration. Note that the *first* run after a fresh Ollama start
    is already cold, so the overnight run needs nothing special beyond not being a repeat.

    The comment in `src/generate.py` calling `temperature: 0` "deterministic, so eval runs
    are comparable" is now accurate, but should say *"deterministic from a cold model"* —
    the qualifier is the whole finding.

20. **A single-digit `must_contain` can pass on a citation marker.** *FIXED 2026-08-25 —
    see design decision 25. Kept because the reasoning explains why the fix is safe.* The check runs against
    the raw answer, which contains `[1]`–`[5]` citations at k=5. So `must_contain: 5` matches
    an answer that cites `[5]` while never stating the figure — a silent false pass. Seven
    rows currently carry a single digit (5, 7, 20, 32, 44, 58, 67) and five of those are
    values ≤ 5.
    **Fixed** by stripping `CITATION_RE` matches from the answer before the `must_contain`
    comparison. Citations are metadata, not content, so removing them is unambiguously
    correct and does not reintroduce any sensitivity to phrasing. Retrieval-only runs are
    unaffected, so no retrieval baseline was invalidated.

    Verified both directions: `must_contain: 5` against "described in the guidelines [5]"
    now fails (it previously passed), while "the cover is 5 lakh per family [3]" still
    passes. The seven bare-digit rows are 5, 7, 20, 32, 44, 58 and 67; five carry values
    ≤ 5 and were therefore reachable as citation markers at k=5.

    The change can only LOWER `must_contain_pass`, never raise it. Per design decision 8
    that metric is a floor rather than a target, so a lower honest number is the correct
    outcome. It landed before the first generation run on the 69-question set, which is the
    point — fixing it afterwards would have meant either discarding that baseline or
    carrying a known-inflated number forward indefinitely.
21. **Reranking latency varies with chunk length, not just candidate count.** The batch pads
    to the longest sequence in it (gotcha 14), so a pool of short chunks is cheaper than a
    pool containing one 512-token chunk. The smoke test saw retrieve p50 of 2.6 s against the
    full eval's 6.1 s for the same depth, purely from shorter candidates. Do not treat
    reranking latency as a constant.

22. **`src.retrieve`'s CLI shows only the first 400 characters of a ~2,400-character chunk,
    which makes correct retrieval look wrong.** A question about "Arogya Shiksha" returned
    the right chunk at rank 1 from *both* retrievers (`{'vector': 1, 'bm25': 1}`) and the
    preview cut off at character 400 — the term sits at character 451. The reviewer's
    reasonable conclusion was that chunking had gone wrong. It had not.
    **Not yet fixed.** Print the chunk length, and the region around the query terms rather
    than the head. `app.py` is unaffected — it renders the whole chunk.

## 6. Open questions

1. **Which empanelment edition is currently in force?** Unresolved. Version 2.0 declares its
   version; the other is dated December 2021. Settle against NHA circulars, not filenames —
   inferring from filenames is what produced the false pair in gotcha 3.
   `Docs/empanelment-diff.md` lists 13 same-clause-different-number pairs. Row 41 shows the
   reranker confidently preferring the wrong edition, so this is now a measured failure, not
   a hypothetical one.
2. ~~**Golden set row 25 is incomplete.**~~ **CLOSED.** All seven target pages were added to
   the CSV on 2026-08-24 at 07:27Z, four minutes before the four retrieval baselines ran at
   07:31Z — every results file records `n_targets: 7` for that row, so **§3d already includes
   the fix** and no re-run was needed.
   Row 25 is now the corpus's strongest multi-target question, and it behaves exactly as the
   RRF analysis predicts: vector, bm25 and rerank all hit it at rank 1 while **hybrid alone
   demotes it to rank 2** — a third instance of fusion penalising questions with several
   valid answers, alongside rows 61 and 62.
3. **Abstention is the model's judgement, with no similarity threshold.** Observed top scores:
   ~0.79 in-corpus vs ~0.53 out-of-corpus. A threshold looks learnable, but must be set from
   the eval set with its false-abstention cost measured — not guessed from two examples. Note
   that after Phase 2 the score is mode-dependent (gotcha 15), so any threshold must be
   defined per mode.
4. **`k = 5` is untuned**, and it is now known to be the dominant latency parameter (§3a.2).
   Reranking makes a smaller `k` plausible for the first time: hit@3 was 73.5% in Phase 1 and
   is 89.8% after reranking. Dropping k=5→3 would cut roughly a third of query time at a cost
   of ~5 questions in 49 losing their evidence. Worth measuring.
5. ~~**Is the hybrid pool actually WORSE than a BM25-only pool for reranking?**~~
   **ANSWERED 2026-08-25 — see §3e.** Short version: BM25's higher pool recall did not
   convert (net +1 question of recall became net 0 of result), the *union* pool is the one
   that measures better (98.3% vs 95.0% hit@5, and it reduces retrieval to a single failing
   question), and **hybrid was nonetheless kept — on latency for the public demo, not on
   quality.** The original text is preserved below because its reasoning was sound and its
   prediction about row 61 was exactly right.

   *Original entry:*
   On the 69-question set BM25 alone reaches **98.3% recall@30** against hybrid's **96.7%**.
   On the old 56-question set they tied at 100% and hybrid was kept on a margin argument;
   that argument has reversed. Row 61 shows the mechanism concretely — BM25 finds the page at
   rank 17 and RRF pushes it out of the top 30 entirely (§3d).
   The experiment is a `bm25 → rerank` mode compared against `hybrid → rerank` on the same
   questions. Three outcomes: bm25 wins (drop the vector retriever from the pool, simpler and
   faster), tie (drop it anyway), hybrid wins despite lower recall (its distractors are
   better — worth knowing and worth writing down). Recall is necessary but not sufficient:
   two pools can have identical recall and still hand the cross-encoder different wrong
   answers to be tempted by.
6. **Rerank depth 30 is inherited from the brief, not derived.** *Partially measured
   2026-08-25 — §3e has union pool recall by depth, and the finding is that depth 25 gives
   the same 100% ceiling as 30. The `CrossEncoder` batch_size=32 boundary matters more than
   depth itself: hybrid at 30 fits one batch, a union does not. Untested for the hybrid pool.* On the 69-question set the
   pool no longer saturates — hybrid recall is 96.7% at both 20 and 30, and BM25 is still
   climbing at 30 (98.3%), so a *deeper* pool may now be the right move rather than a
   shallower one. That reverses the earlier reading. Saves ~2 s of ~133 s, so it is not worth the test-set
   contact today; it becomes worth doing once generation is fast (§7), where reranking would
   be ~75% of query time instead of 4%.
7. **Does better retrieval actually produce better answers?** Completely unmeasured, and not
   obvious: 7 of 9 false abstentions already had the evidence at rank 1–5, so the failure is
   the model declining to use what it was given, not the retriever failing to find it.
   Reranking may move citation correctness very little.

## 7. What remains in Phase 2

In order. Items 1–3 are prerequisites for any benchmark being trustworthy.

1. ~~**Finish the golden set**, re-run all four retrieval modes.~~ **DONE** — 69 questions,
   §3d. Row 25 closed (open question 2).
2. ~~**Thread retrieval `mode` through `src/generate.answer()`** and expose it in `app.py`.~~
   **DONE 2026-08-25** — §3c.
3. ~~**Record the LLM model in the results `config` block.**~~ **DONE 2026-08-25** —
   `llm_provider` and `llm_model`, null on retrieval-only runs. Design decision 26.
3b. ~~**Settle the rerank candidate pool** (open question 5).~~ **DONE 2026-08-25** — §3e.
   Hybrid kept, on latency.
3c. **Commit the above.** Nothing from this session is committed. `eval/pool_recall.py` is
   untracked.
3d. **The README still owes three disclosures**: the depth-25 test-set contact note (§3e);
   the fact that the union arm was post-hoc, suggested by failure analysis rather than
   pre-registered; and the golden-set vocabulary bias below. Design decision 12 and the
   anti-goals require the first two.

3e. **The paraphrase experiment -- the biggest open threat to every retrieval number here.**
   The golden set was written by someone reading the documents, so the questions reuse the
   documents' own vocabulary ("cover amount on family floater basis" rather than "how much
   money do I get for an operation"). **Lexical overlap between question and document is
   exactly what BM25 scores**, so BM25's win over the embeddings may be partly an artefact of
   authorship rather than a property of the corpus. Every retrieval figure in §3d and §3e
   inherits that bias.

   Cheap to test: 15-20 questions phrased the way a real user would, re-run all four
   retrievers (~10 min, no LLM). If BM25's lead shrinks, the evaluation has a real
   limitation. If it holds, the finding is much stronger and can be claimed as such.

   **The phrasings must not come from anyone who has read the corpus** -- which rules out the
   project author, and is the whole difficulty. In preference order: (1) real public PM-JAY
   FAQ and forum questions, which are actual user language and involve no LLM; (2) a person
   given the topic but not the documents; (3) LLM paraphrase of existing verified questions,
   which does NOT breach the anti-goal (there is no LLM judge, and the fact plus target pages
   stay human-verified) but is a proxy for user language rather than user language, and must
   be disclosed as one.

3f. **Golden-set target completeness -- confirmed incomplete in at least one row.**
   Row 9 ("What is cut-off in technical evaluation for bidder?") lists only
   `fraud_analytics_rfe.pdf` p.41, but **p.39 states the same 70% threshold** in more detail,
   and the model answered from p.39 almost verbatim and cited it. It scored as a citation
   failure. **The model was right and the golden set was wrong.**

   Two detectors for the rest, both run 2026-08-25:
   - *The model cited an unlisted page.* Better signal -- it surfaces pages the model treated
     as its source. 14 citation failures to review.
   - *A distinctive `must_contain` value appears on unlisted pages.* Six candidates: rows 28,
     29, 38, 45, 62, 68. **Candidates only** -- a number on a page does not mean the page
     answers the question. Hand-verify, per the project's own rule.

   Do this in ONE edit, after the local generation pair finishes, then re-run the four
   retrieval baselines and pool recall (~10 min) plus the hosted generation pair (~5 min).
   **Adding targets moves numbers upward, and that is a measurement change, not an
   improvement** -- the same trap as the `must_contain` unit-stripping. Say so in the README.
4. **Swap in a hosted-LLM backend** — see [DEPLOYMENT.md](DEPLOYMENT.md). This turns a 2.5 h
   generation run into ~10 minutes and unblocks everything below.
5. **Generation runs**: hosted `--retriever vector` (Phase 1 baseline) and hosted
   `--retriever rerank` (Phase 2). That pair is the answer to "what did Phase 2 buy?"
   Optionally a local Phase 2 run overnight to complete the local grid.
6. **Handle the empanelment version conflict** — metadata field vs separate collections.
   Open question 1 gates the expected answers, not the retrieval work.
7. **Prompt v2**, targeting the inference-vs-copying weakness in §3b, A/B'd against v1 with
   nothing else changed. The specific edit is to split what rule 2 currently conflates:

   - *Do not introduce any fact not present in the sources* — keep, strictly. This is the
     anti-hallucination rule and it is doing real work.
   - *You may combine or compute from figures the sources state* — add, explicitly. Rule 2 as
     written ("do not infer beyond what is written") reads as a ban on arithmetic over stated
     values, which is not what it is for.

   Rows 36 and 67 plus the four rank-1 false abstentions in §3b are the measurement for
   whether v2 worked. Watch `abstention_recall` at the same time: the risk of loosening rule 2
   is that the model starts answering questions it should decline, so a gain in
   `false_abstention_rate` that comes with a drop in `abstention_recall` is not a win.

Then CI/CD: `--retrieval-only --min-hit-rate` runs on the runner (no Ollama available);
generation metrics run locally and are committed as a results file CI verifies. Retrieval
enforced by execution, generation by attestation, tradeoff stated honestly in the README.

**On honesty about results:** hybrid retrieval and reranking produced a large *retrieval*
gain. That says nothing yet about answers. If the generation numbers show no improvement,
report that — the brief is explicit that a measured null result is more credible than an
assumed win. Do not tune until the numbers look good.

## 8. Anti-goals — from the brief

- **Do not generate eval questions with an LLM.** The golden set is hand-written and
  hand-verified. Scoring LLM-written questions with an LLM judge measures the model agreeing
  with itself.
- Do not add hybrid retrieval or reranking without recording the baseline first (done).
- Do not adopt a heavy orchestration framework.
- Do not drop page-number tracking anywhere in the pipeline.
- Do not start the multilingual work until English is measured and working.
- **Do not tune hyperparameters against the golden set** without saying so. `RRF_K`, fusion
  depth and `k` are all currently untuned, which is a claim worth being able to make.
