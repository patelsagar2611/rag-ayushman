# Handoff — for the next session only

**Read [README.md](../README.md) first.** It is the permanent record: results, design
decisions (36), gotchas (25), anti-goals, corpus provenance, both eval sets. This file holds
*only* what the next session needs that is not already there.

**When this session's work is stable, promote its findings to the README and rewrite this file
from scratch.** If it grows a history section, it has drifted from its purpose.

Written 2026-09-01. **The app is deployed and live.** The next phase is the measurement tab
(D-4) and the remaining hardening.

---

## The working agreement — binding, full text in the README

[How this project is worked on](../README.md#how-this-project-is-worked-on). Summarised here
because these are the rules most costly to miss:

1. **Explain the reasoning, not just the outcome** — what was chosen *over* what, and what
   evidence decided it.
2. **Small batches.** Put judgement calls to the owner as they arise. Never ten to twenty steps
   followed by a short summary.
3. **Ask before starting ANY run**, including single-question smoke tests.
4. **Any message sent while a run is in flight ends with a line** saying a run is in progress,
   that a system sleep will affect it, and the estimated time.
5. **The machine is not always on.** Plan runs around that.

Four additions the owner asked for after 2026-09-01, and they exist because ignoring them cost
most of a session:

6. **State the one outcome that would make the session a success, before starting**, and flag
   immediately when work drifts away from it.
7. **Before any plan that depends on a third-party platform's features, pricing or limits,
   verify against the live API or current pricing page.** Say explicitly which parts remain
   unverified. See journal entry 31: three rounds of platform assumptions were wrong, and the
   owner had correctly identified the problem in his first message about it.
8. **If the owner reports what a screen actually shows, that outranks documentation.**
9. **Give estimates as best case / likely / what would blow it up**, and distinguish "written"
   from "verified working end to end".

**The owner has said that much of the technical discussion goes over his head and that he is
sometimes agreeing because he cannot counter it.** That is not consent and the working
agreement does not function on it. Present every decision with a plain-language *"what breaks
if this is wrong"* so consequences can be judged without the internals.

[INTERVIEW-ANGLES.md](INTERVIEW-ANGLES.md) is a required deliverable of every session. It now
runs to **34 entries**, and it is also the owner's study material for defending this project.

**ASK BEFORE CHANGING `eval/golden_set.csv` OR `eval/paraphrase_set.csv`.**

---

## State: LIVE

**Deployed on Streamlit Community Cloud**, free tier, from the public GitHub repo. Deploying is
`git push` — Community Cloud rebuilds on it. There is no second repo and no sync step.

**Hugging Face Spaces is not available on a free tier.** The Hub API accepts only
`gradio|docker|static` as SDKs — `streamlit` was removed — and Docker or Gradio on free
`cpu-basic` returns `402 Payment Required`. `Dockerfile`, `.dockerignore`, `deploy_space.py`
and `Docs/SPACE_README.md` are kept as the paid fallback. **The Dockerfile earns its place
regardless**: it is a reproducible local build of the deployed environment and it is what made
every measurement below possible.

### Configuration, and where each setting lives

| setting | where | why there |
|---|---|---|
| `GOOGLE_API_KEY` | Community Cloud **Secrets** | the only manual setting on the host |
| `LLM_PROVIDER`, `LLM_BACKEND`, `GOOGLE_BASE_URL`, `GOOGLE_MODEL` | Community Cloud Secrets | no ENV mechanism there; `app.py` bridges `st.secrets` into `os.environ` |
| `PMJAY_TORCH_THREADS` (default 2) | `app.py` | worth ~48% of reranked latency |
| `PMJAY_RERANK_BATCH` (default 8 in the app, **unset in the pipeline**) | `app.py` | 32 gets OOM-killed under 768 MB; unset in `src/` so the eval reproduces committed numbers |

**`app.py`'s boot order is load-bearing** — secrets bridge, then thread and batch defaults, then
`src` imports, because those read settings at import time and one pulls torch. Moving an import
above that block disables the settings silently.

**The Chroma index is committed and hidden from git with `skip-worktree`**, because merely
*opening* it rewrites the sqlite file. To commit a genuine re-index, un-hide first —
`python -m src.index` prints the exact commands on completion.

---

## What this session settled, that changes how to work

- **Deployed ≡ measured, demonstrated rather than argued.** The live app returns cross-encoder
  logits bit-identical to the local container (`5.128, 3.253, 2.719, 2.281, 1.176`, same pages),
  and the `vector` path reproduces the local smoke test token for token.
- **The dependency drift is immaterial.** Four transitive packages resolve differently on Linux
  than on the Windows venv every number was measured on; all four retrievers reproduce to
  **0.000000**.
- **Two settings are worth ~50% each**, and neither was in any plan: thread count (7,615 →
  3,974 ms) and cross-encoder batch size (1,186 → 876 MB peak). Batch size is *free* — scores are
  bit-identical at 32/16/8/4.
- **Hosted generation is ~1–2 s, not the ~0.5 s the README claimed for months.** That figure was
  never supported by any results file. Corrected in place with the original visible.
- **A UI label that says "total" must measure the total.** The caption reported only the LLM call,
  which made reranking look 20× faster than dense retrieval on the deployed app.

---

## What to do next

### Immediate

1. **Decide `DEFAULT_MODE`.** The owner is testing questions in both modes. Evidence so far:
   `vector` is far cheaper (~0.04 s and ~700 MB against ~5 s and ~870 MB) and `rerank` gave a
   visibly richer answer on the one live question compared (5 sources and both phrasings of the
   figure, against 2 and one). **This reverses a documented default (decision 22), so whatever is
   chosen is recorded as a design-decision update with its evidence.**
2. **Push the D-3 work** if it is not already live, and check the showcase selector appears.

### D-4 — the measurement tab. The differentiator, and the next real piece of work.

Tabs: **Ask** (today's page) · **How this was measured** · **About**.

A `st.select_slider` across project milestones; each position reads a committed results file and
renders hit@1 / hit@3 / hit@5 / MRR / latency with deltas against the previous position, plus a
caption on what changed and what it cost.

**The one thing that must not be got wrong.** The timeline mixes two kinds of milestone, and one
undifferentiated track would tell a visitor the system improved when it did not:

```
system changes        Phase 1 vector -> +BM25 -> +RRF hybrid -> +cross-encoder
measurement changes   goldenv1 -> goldenv2 (4 rows) -> goldenv3 (18 rows)
```

Badge each, or use two tracks. Every results file carries `descriptor` and `question_set_sha`, so
each position can name the exact run and eval version behind it.

**The regressions are the credibility.** Fusion made hit@1 *worse* and was kept anyway for a
stated reason; a documented reranker failure turned out to be an eval failure. Most dashboards
show a line going up.

Also worth building: a **side-by-side retriever comparison** for one question, `vector` against
`rerank`, with rank movement per chunk and both timings — now that the timings are honest.

**Estimate: best case half a day, likely a full day. What would blow it up** is the milestone
manifest — deciding which of the 41 results files represents which milestone defines the story
the tab tells, and that is a judgement call for the owner, not a guess.

### D-5 — analytics, with a blocker attached

Log to a Hugging Face **Dataset repo** (free, persistent, versioned, loads back into the eval).
Fields: random session uuid, timestamp, question, mode, k, latency, n_citations, cited_pages,
abstained, cache_hit, rating, `sources_expanded`, app_version, index_hash.

`sources_expanded` is the interesting one: for a citation-first product, whether anyone actually
checks the citation is the real success metric.

> **BLOCKER.** This is a health-scheme assistant and visitors will type personal medical detail.
> Before any logging ships: a visible notice that questions are recorded, no identifier beyond a
> random per-session uuid, and a scrub pass for obvious identifiers.

The payoff is real user language, which is what open question 4 needs and what the paraphrase set
can only proxy.

### D-6 — semantic cache, gated on a measurement

Exact-match-after-normalisation caching ships unconditionally: free and zero risk.

The semantic layer must **not** ship on a guessed threshold. This corpus is hostile to it: 10 beds
vs 5 in aspirational districts, 3 vs 5 working days, two empanelment editions stating the same
clause with different numbers. A generous threshold serves a wrong figure *with a citation
attached*.

**The sweep is free and the labelled data exists.** True positives: `eval/paraphrase_set.csv`
(17 pairs that should collide). True negatives: the golden set's contradiction and
version-conflict rows (near-identical phrasing that must not collide). Ship only if a threshold
exists with **zero** false collisions. Key on
`(embedding, prompt_version, retriever_mode, index_hash)`.

---

## Open questions still live

1. **Which empanelment edition is in force?** Unresolved. Settle against NHA circulars, not
   filenames.
2. **Is Google direct slower than OpenRouter?** The committed runs say yes and by a lot
   (p50 2,185/3,978 ms and p95 5,048/7,251 ms, against OpenRouter-pinned 1,112–1,231 p50 and
   1,465–1,778 p95, same model). A three-question spot check on 2026-09-01 did **not** reproduce
   the gap. Unresolved, and it matters for the demo's p95.
3. **Abstention has no similarity threshold** — it is the model's judgement.
4. **`k = 5` is untuned**, and on a hosted LLM retrieval dominates, so depth and `k` now matter in
   a way they did not locally.
5. **Real user questions.** D-5 is what makes this possible with genuine language.
6. **Does the window-homogeneity penalty appear on a frontier model?** Confirmed on two 7B models,
   absent on `flash-lite`. ~$3 pinned to Anthropic would answer it. Run it for precision and false
   abstention, **not** `citation_correctness`, which is saturated.
7. **Should hybrid still be the rerank pool?** A BM25-only pool reaches 100% recall at depth 30
   where hybrid reaches 96.7% — but that is golden-set evidence and the paraphrase set inverts it.
8. **Prompt v2** — splits what rule 2 conflates, targeting false abstention. ~$0.15, ~40 min, and
   the A/B is clean because pinned runs are byte-identical.

---

## Things not to lose

- **Check whether a question can be answered by re-scoring saved runs before paying for one.**
  Retrieval is byte-reproducible and every results file saves its candidate lists. This is what
  made the entire eval correction cost nothing.
- **`config/showcase.json` is generated, not written.** Regenerate with
  `python -m eval.make_showcase` if the prompt version or model changes — its provenance block
  records what produced it, so a stale file is detectable.
- **The showcase set includes a deliberate abstention row** and it works in both modes. Do not
  "fix" it.
- **The contradiction-flagging behaviour is a retrieval property, not a model virtue.** It appears
  only when both conflicting pages land in the same window. The mortality-report showcase row
  answers "48 hrs" cleanly without mentioning the conflicting page, and that is expected.
- **The daily and per-session caps are in-process** and reset on restart. They bound the common
  case; they are not a guarantee, and the code says so.
- **The label lint fires at write time.** If it warns, believe it.
- **Do not put `goldenvN` in `--label`.** The question set is recorded as a content hash.
