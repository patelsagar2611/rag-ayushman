# Handoff — for the next session only

**Read [README.md](../README.md) first.** It is the permanent record: results, design
decisions (36), gotchas (25), anti-goals, corpus provenance, both eval sets. This file holds
*only* what the next session needs that is not already there.

**When this session's work is stable, promote its findings to the README and rewrite this file
from scratch.** If it grows a history section, it has drifted from its purpose.

Written 2026-08-30, after the golden-set completeness review. **The next phase is deployment.**

---

## The working agreement — binding, full text in the README

[How this project is worked on](../README.md#how-this-project-is-worked-on). Summarised here
only because these are the rules most costly to miss:

1. **Explain the reasoning, not just the outcome** — what was chosen *over* what, and what
   evidence decided it.
2. **Small batches.** Put judgement calls to the owner as they arise. Never ten to twenty steps
   followed by a short summary.
3. **Ask before starting ANY run**, including single-question smoke tests.
4. **Any message sent while a run is in flight ends with a line** saying a run is in progress,
   that a system sleep will affect it, and the estimated time.
5. **The machine is not always on.** Plan runs around that.

[INTERVIEW-ANGLES.md](INTERVIEW-ANGLES.md) is a required deliverable of every session. New
findings get an entry *in the session that produced them*, in the four-part format. It now runs
to 28 entries.

**ASK BEFORE CHANGING `eval/golden_set.csv` OR `eval/paraphrase_set.csv`.** The owner edits
them; the assistant proposes rows and verifies them afterwards.

---

## State

**Tree is dirty and uncommitted** — 55 changed files on `main` at `17bd1f0`. Nothing is
half-done; it is one coherent body of work that has not been committed yet:

- `eval/golden_set.csv` — 18 of 60 answerable rows gained target pages
- `eval/paraphrase_set.csv` — 3 rows resynced to match the golden rows they pair with
- `README.md`, `Docs/INTERVIEW-ANGLES.md` — every figure re-measured, three claims retracted
- `eval/run_eval.py` — records question-set hash, `served_by`, and a derived `descriptor`
- `eval/citation_companions.py` — alignment guard rewritten
- `eval/backfill_provenance.py` — new; backfills provenance into older results files
- 47 results files — provenance backfilled (additive only); 12 new runs from this session

**Committing this is the first thing to do.** It is a large, self-consistent change and it
should not be mixed with deployment work.

**OpenRouter credit: ~$9.60. Nothing was spent this session** — every run was retrieval-only
or a re-score from saved answers, so the whole eval correction cost nothing.

**Environment.** Use `.venv\Scripts\python.exe` explicitly; system Python is 3.13 and has none
of the dependencies (gotcha 7). Set hosted-run variables per command, never in `.env`:

```powershell
$env:LLM_PROVIDER="openai"
$env:OPENAI_MODEL="google/gemini-3.1-flash-lite-20260507"
$env:OPENAI_PROVIDER="Google AI Studio"
```

**Stop putting `goldenvN` in `--label`.** The question set is now recorded as a content hash and
the label lint will warn you about it on every run. Labels are for intent ("noise-rep2"), not
for facts the file already carries.

---

## What this session settled, that changes how to work

- **The golden set was materially incomplete**, and correcting it moved every published number.
  Two rows had listed a page that does not contain the answer at all. Full write-up in the README.
- **A prediction was registered and lost**: correcting the eval was expected to shrink the
  reranking precision penalty. It widened it. The incomplete eval had been *flattering*
  reranking. Recovery-rate table in the README; journal entry 26.
- **Retrieval is byte-reproducible across days and process restarts**, so any past run can be
  re-scored against any golden version from its saved candidate lists — no re-runs needed. This
  is what made the whole correction free, and it is worth remembering before paying for anything.
- **Run identity is now data, not a typed label.** `question_set_sha`, `served_by`, `descriptor`.
  Two runs whose labels said `openrouter-...` turned out to be the unpinned ones (gotcha 20).

---

## What to do next — deployment, in phases

The eval-integrity phase is closed. Nothing is live, and a portfolio RAG project nobody can click
is materially weaker than one they can. [DEPLOYMENT.md](DEPLOYMENT.md) has the original plan;
**its steps 1–5 are already done** (Track A shipped) and three of its projections are now
measured. Read it for context, not as a task list.

### Decisions already made, so they do not get relitigated

| decision | choice | why |
|---|---|---|
| LLM backend | **Google AI Studio direct, free tier**; OpenRouter as env-var fallback | Its runs are byte-identical to the pinned OpenRouter runs, so the free path is backed by the measured numbers and spends no credit |
| Host | **Hugging Face Spaces**, CPU tier | 16 GB RAM has headroom for torch + two models; free GPU is not actually available there without PRO |
| GPU | **No** | It would only help the cross-encoder, and would make every latency number non-comparable to the CPU baseline. int8 ONNX is the cheaper fix if one is needed |
| Index delivery | **Commit `chroma/`** (16 MB) | Rebuilding costs 30–60 s on every cold start of a sleeping app |
| Quota protection | Precomputed showcase answers + global daily counter + per-session cap | **No IP blocking** — unreliable behind a proxy, unpersistable on free Spaces, and PII |
| UI framework | **Keep Streamlit** | Open WebUI / AnythingLLM would replace the *pipeline*, not the interface, and every README number would stop describing what is deployed |
| Cache keyed on reranker results | **No** | Same pages, different question, different answer — rows 2 and 58 are live counterexamples |

### D-1 — pre-flight, local, free

Four defects exist today and block a deploy:

1. **`app.py`'s `MODE_HELP` quotes goldenv1 MRRs** (0.624, 0.677, 0.795 …), all superseded. Fix
   the *class*: read them from `eval/results/*.json` at startup so the UI cannot go stale. The
   comment above the dict already predicted this failure.
2. **The error path is Ollama-specific** — a `ConnectionError` tells the user to run
   `ollama run qwen2.5:7b`, which is nonsense on a hosted deploy.
3. **`torch` is not in `requirements.txt`.** It is a manual CPU-index install today, and Spaces
   builds from `requirements.txt` alone. **This is the biggest build risk — resolve it in
   isolation, first.** Pin the build tag so resolution cannot silently fall back to the ~2.5 GB
   CUDA wheel, because `--extra-index-url` is a hint and not a constraint: pip considers both
   indexes and picks by version precedence, so a newer torch on PyPI wins and the flag does
   nothing.

   ```
   --extra-index-url https://download.pytorch.org/whl/cpu
   torch==2.x.y+cpu
   ```

   The `+cpu` local-version suffix exists only on the PyTorch index, so resolution either finds
   the CPU wheel or fails loudly. **Acceptance test, run in a clean Linux environment, not on
   Windows:**

   ```
   python -c "import torch; print(torch.__version__, torch.cuda.is_available())"   # expect False
   pip freeze | grep -Ei 'nvidia|cuda'                                             # expect nothing
   ```

   An empty second command is the real signal — NVIDIA packages in a supposedly CPU-only
   environment mean resolution did not do what was intended, whatever the first command says.
4. **The cross-encoder downloads ~90 MB lazily on first rerank.** Fetch both models at build time
   and warm them at startup, so no visitor ever pays for a download. Whether a Space wake is a
   restart (cache survives) or a rebuild (cache does not) is **unverified** — building it in
   makes the question moot.

Then: un-ignore and commit `chroma/` with a comment saying why, and verify the app runs
end-to-end with `LLM_PROVIDER=openai` against the Google endpoint.

### D-2 — create the Space, then MEASURE it

Create the Space, add secrets, push, verify cold start. Then **measure `vector` and `rerank`
end-to-end on the 2 vCPUs.** This is a measurement, not a deploy step: DEPLOYMENT.md's
"~20–30 s" for the reranker is a projection, and every downstream choice depends on the real
number. Record it in the README like any other measurement.

Two open decisions are settled by that number and by nothing else.

**OPEN DECISION 1 — what retrieval mode the demo defaults to.** `DEFAULT_MODE` is `vector`, and
design decision 22 says it stays until *generation* evidence justifies changing it. **That
condition has now been met for the deployment model**: on `flash-lite`, reranking cuts false
abstention 7.3% → 5.2% and is neutral on citation precision (+0.3). So the quality case for
`rerank` exists and only latency is unresolved. Suggested threshold: **switch the default to
`rerank` if it lands under ~5 s end to end**, above which a demo reads as broken. Whatever is
chosen, record it as a design-decision update, because it reverses a documented default.

**OPEN DECISION 2 — whether int8 ONNX quantisation is needed.** Only relevant if D-2 shows the
cross-encoder too slow. `optimum` + ONNX Runtime is typically 3–4× faster on CPU and keeps the
model that was benchmarked. **If it is adopted, re-run the four retrieval baselines afterwards** —
quantisation can shift scores, and that must be measured rather than assumed. Do not reach for a
reranker API first; it changes the model and adds a second key.

### D-3 — harden before the link is shared

- Showcase questions with **precomputed, committed answers**, so the common path costs zero tokens
- Global in-process daily counter (bounds the worst case) + per-session cap in `st.session_state`
- **429 handling in the UI.** `src/generate.py` already distinguishes a transient per-minute 429
  from the daily cap and raises `SystemExit` on the latter — correct for a CLI, wrong inside
  Streamlit, where it renders as a broken page. Catch it and say what happened.
- Visible "portfolio demo on a free tier" note

**Budget reality: the Google free tier is ~200,000 tokens/day, and at ~2,500 prompt tokens per
query that is roughly 80 questions per day for the whole world.** The daily cap appears only in a
429 body and never in a response header (gotcha 16), so it cannot be seen coming. This is why the
precomputed path matters more than the rate limits do.

### D-4 — the differentiator: "how this was measured"

The highest-value hour in the plan, and the thing that separates this from a text box over
someone else's pipeline.

**A milestone slider** (`st.select_slider`), each position reading a committed results file and
rendering hit@1 / hit@3 / hit@5 / MRR / latency with deltas against the previous position, plus a
caption on what changed and what it cost. Every results file now carries `descriptor` and
`question_set_sha`, so each position can display exactly which run and which eval version
produced its numbers — provable, not asserted.

**The one thing that must not be got wrong:** the timeline mixes two kinds of milestone, and
presenting them on one undifferentiated track would tell a visitor the system improved when it
did not.

```
system changes        Phase 1 vector  ->  +BM25  ->  +RRF hybrid  ->  +cross-encoder
measurement changes   goldenv1  ->  goldenv2 (4 rows)  ->  goldenv3 (18 rows)
```

Badge each milestone, or put measurement changes on a second track. **The regressions are the
credibility** — fusion made hit@1 worse and was kept anyway for a stated reason; a documented
reranker failure turned out to be an eval failure.

Also worth having: a **side-by-side retriever comparison** for one question, `vector` against
`rerank`, with rank movement marked per chunk and both timings shown. It shows the reranker
working, what it costs, and that it is not always an improvement.

### D-5 — analytics, with a blocker attached

Log to a **Hugging Face Dataset repo**, not Google Sheets: same platform, no extra credentials,
free, *persistent across restarts* where the Space's local disk is not, versioned, exports to
CSV/parquet, and loads straight back into the eval pipeline.

```
session_id (random uuid, NOT a user id)   timestamp   question   mode   k
latency_ms   n_citations   cited_pages   abstained   cache_hit
rating (thumbs)   sources_expanded   app_version   index_hash
```

`sources_expanded` is the interesting one — for a citation-first product, whether anyone actually
checks the citation is the real success metric. Write once per completed answer, asynchronously,
never blocking the response.

> **BLOCKER, not a nice-to-have.** This is a health-scheme assistant, and visitors will type
> things like *"my mother has kidney failure, is dialysis covered"*. That is sensitive personal
> data. Before any logging ships: a visible notice that questions are recorded, no IP or
> identifier beyond a random per-session uuid, and a scrub pass for obvious identifiers.

The payoff is the feedback loop: logged questions are **genuine user language**, which is what
open question 4 below actually needs and what the paraphrase set can only proxy. They are allowed
under the anti-goals — the prohibition is on *LLM-generated* eval questions, not on real ones.

### D-6 — semantic cache, gated on a measurement

Exact-match-after-normalisation caching ships unconditionally: free, zero risk, and it catches
more than expected because visitors paste the suggested questions.

The semantic layer — embed the query with the BGE model already loaded (**apply the query
prefix**, design decision 3), cosine-match against cached questions, serve above a threshold — is
worth having but **must not ship on a guessed threshold.** This corpus is hostile to it: 10 beds
vs 5 in aspirational districts, 3 vs 5 working days, two empanelment editions stating the same
clause with different numbers. A slightly generous threshold serves a wrong figure *with a
citation attached*, which is the worst failure this product has.

**RUN TO DO — the threshold sweep.** Free, no LLM, and the labelled data already exists:

- **True positives — `eval/paraphrase_set.csv`.** 17 pairs that *should* collide: same fact, same
  answer, mean vocabulary overlap 36.1%.
- **True negatives — the golden set's near-duplicate pairs.** The contradiction and
  version-conflict rows, where near-identical phrasing must *not* collide.

Sweep the threshold against both, report hit rate against false-collision rate, and **ship the
semantic layer only if there is a threshold with zero false collisions.** Key the cache on
`(embedding, prompt_version, retriever_mode, index_hash)` so a prompt bump or re-index invalidates
it automatically, and label cached answers in the UI so nobody misreads the latency.

---

## Two risks to resolve early

1. **The torch install on Spaces** — most likely thing to eat an afternoon. Resolve in isolation
   before anything else is touched.
2. **Chroma's sqlite store moving Windows → Linux.** Verify early rather than assume. If it does
   not travel, the index decision flips to shipping `chunks.jsonl` (1.5 MB) and rebuilding at
   startup, which changes the cold-start story.

---

## Open questions still live

1. **Which empanelment edition is in force?** Unresolved. Settle against NHA circulars, not
   filenames. `Docs/empanelment-diff.md` lists 13 same-clause-different-number pairs. The golden
   set now lists both editions on the rows where both state the rule, which makes the metrics
   honest but does **not** answer which one a user should be told.
2. **Abstention has no similarity threshold** — it is the model's judgement. Any threshold must be
   set with its false-abstention cost measured, and must be per-mode (gotcha 22).
3. **`k = 5` is untuned** and is the dominant latency parameter locally. On a hosted LLM that
   reasoning inverts: generation is ~0.5 s and reranking is ~90% of query time, so **depth and `k`
   suddenly matter in a way they did not.** Tuning against the golden set is test-set contact and
   must be disclosed.
4. **Real user questions.** Needs its own golden rows; D-5 is what makes it possible with genuine
   language rather than an LLM proxy.
5. **Does the window-homogeneity penalty appear on a frontier model?** Confirmed on two 7B models,
   absent on `flash-lite`, and it got *bigger* when the eval was corrected. Nobody knows whether
   it is a size effect or a light-model effect. ~$3 pinned to `Anthropic` would answer it. **Do
   not run it for `citation_correctness`** — that metric is saturated at 100.0% for `flash-lite` +
   `rerank` and is arithmetically incapable of moving. Run it for precision, false abstention and
   the contradiction rows.
6. **Should hybrid still be the default rerank pool?** Weaker again: a BM25-only pool now reaches
   100% recall at depth 30 while hybrid reaches 96.7%, and hybrid is the only pool that misses.
   Counterweight before acting: that is golden-set evidence, and the paraphrase set inverts it.
7. **Prompt v2** — splits what rule 2 conflates (*introduce no new fact* vs *you may compute from
   stated figures*), targeting false abstention. ~$0.15, ~40 min, and the A/B is clean because
   pinned runs are byte-identical. Deliberately deferred behind deployment: it spends money to add
   a row to the most-measured part of the project while the thing a reader notices first is that
   they cannot use it.

---

## Things not to lose

- **`--only-rows` plus saved candidate lists mean almost nothing needs re-running.** Check whether
  a question can be answered by re-scoring before paying for a run.
- **`eval/backfill_provenance.py` is idempotent and additive.** Safe to re-run after any new
  question-set revision.
- **The label lint fires at write time.** If it warns, believe it — it was built from a trap that
  cost an hour of diffing 69 answers.
