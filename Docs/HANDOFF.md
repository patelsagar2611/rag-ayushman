# Handoff — for the next session only

**Read [README.md](../README.md) first.** It is the permanent record: results, design
decisions (39), gotchas (28), anti-goals, corpus provenance, both eval sets, deployment
measurements. This file holds *only* what the next session needs that is not already there.

**When this session's work is stable, promote its findings to the README and rewrite this file
from scratch.** If it grows a history section, it has drifted from its purpose.

Written 2026-09-06. **The app is live and the D-4 measurement tab is shipped and verified.**
The next phase is measuring the *host* (not the development machine), then metadata-only
analytics.

---

## Start here

**Five items are outstanding and the owner has not chosen an order.** Read this file, then
[README.md](../README.md), then:

1. **Propose an order** across the five items in [What to do next](#what-to-do-next), with
   best case / likely / what-would-blow-it-up for each, and a plain-language *"what breaks if
   this is wrong"*.
2. **State the ONE outcome that would make the session a success.**
3. **Stop and wait for confirmation.** Do not start work, and do not run anything, until the
   owner picks.

Working agreement rule 6 was missed last session — the stated goal was the D-4 tab and most of
the session went into a timing bug instead. The bug was real and worth fixing, but the drift
should have been named hours before the owner asked about it. **Name drift the moment it
happens.**

---

## How to run things here

| | |
|---|---|
| **Interpreter** | `.venv\Scripts\python.exe`, called by path. System python is 3.13 and has none of the dependencies. **Never activate the venv.** |
| **Hosted LLM** | `LLM_PROVIDER` + `LLM_BACKEND` per command; each backend configured by `<NAME>_BASE_URL` / `<NAME>_API_KEY` / `<NAME>_MODEL` in `.env`. Adding a vendor is three lines and no code change. |
| **Cost** | Google direct is free at ~200k tokens/day. **The daily cap appears ONLY in a 429 body, never in a header**, so it cannot be paced against — and every retry is a billed request. OpenRouter costs credit (~$9.60 left). |
| **The index** | `chroma/` is committed and hidden with `skip-worktree`, because merely *opening* it rewrites the file. `python -m src.index` prints the un-hide steps when a genuine re-index needs committing. |
| **Run labels** | Do **not** put `goldenvN` in `--label`. The question set is recorded as a content hash. |

**Before paying for anything:** retrieval is byte-reproducible and every results file saves its
returned top-k window, so most questions can be answered by re-scoring saved runs rather than
re-running them. Pool recall at depth 30 is the one exception — that genuinely needs a re-run.

**Anti-goals live in the README**, and two are recent enough to repeat here because they were
decided in conversation rather than at the start:

- **Do not log question or answer text.** Metadata-only was a deliberate decision — see item 2.
- **Do not tell the model which empanelment edition to prefer.** Surface the disagreement
  instead; neither edition in the corpus is current.

---

## The working agreement — binding, full text in the README

[How this project is worked on](../README.md#how-this-project-is-worked-on). Summarised here
because these are the rules most costly to miss:

1. **Explain the reasoning, not just the outcome** — what was chosen *over* what, and what
   evidence decided it.
2. **Small batches.** Put judgement calls to the owner as they arise.
3. **Ask before starting ANY run**, including single-question smoke tests.
4. **Any message sent while a run is in flight ends by saying so**, that a system sleep will
   affect it, and the estimated time.
5. **The machine is not always on.** Plan runs around that.
6. **State the ONE outcome that would make the session a success before starting**, and say so
   the moment work drifts from it. *This was missed last session: the stated goal was the D-4
   tab and most of the session went into a timing bug. The bug was real and worth fixing, but
   the drift should have been named hours earlier.*
7. **Verify third-party platform features, pricing and limits against the live API or pricing
   page** before planning around them. Say what remains unverified.
8. **If the owner reports what a screen actually shows, that outranks documentation.** This rule
   earned itself again on 2026-09-06 — see the empanelment note below.
9. **Estimates as best case / likely / what would blow it up.** Distinguish "written" from
   "verified working end to end".
10. **Much of the technical detail goes over the owner's head, and agreement is not consent.**
    Give a plain-language *"what breaks if this is wrong"* with every decision.

[INTERVIEW-ANGLES.md](INTERVIEW-ANGLES.md) is a required deliverable of every session. It now
runs to **38 entries** and is also the owner's study material.

**ASK BEFORE CHANGING `eval/golden_set.csv` OR `eval/paraphrase_set.csv`.**

---

## State

**Live on Streamlit Community Cloud**, free tier, from the public GitHub repo. Deploying is
`git push`. Three tabs: **Ask**, **How this was measured**, **About**.

**`app.py` is verified rather than asserted.** 17 headless cases via
`streamlit.testing.v1.AppTest` (boot, all six retrieval modes, precomputed and live answers,
non-default `k`, live and precomputed abstention, quota caps, old-format `showcase.json`), plus
10 more for the D-4 tab. The scratch harnesses were session-local and were not committed —
**if you touch `app.py`, rewrite them; the pattern is `AppTest.from_file(<absolute path>)`,
drive the real widgets, assert on `at.caption` / `at.markdown` / `at.metric`.**

### Settled last session, with evidence

- **`DEFAULT_MODE` is `vector`, decided rather than deferred** (design decision 22, rewritten).
  Reranking buys no citation-precision gain on any of three models, costs ~470 MB peak RSS, and
  the latency argument is unusable because host *generation* was seen swinging 1.9–10.4 s, which
  is larger than the whole retrieval difference. `rerank` stays one click away.
- **Retrieval latency spans ~1.7× on one machine in one session** (gotcha 26). Two `rerank` runs
  from the *same day* report identical MRR and p50s of 2,012 ms and 3,269 ms. A 2 s idle gap
  between queries makes retrieval ~32% *faster* (CPU boost recovery). Question mix and cache
  eviction were measured and are not the cause.
- **The D-4 tab shows no speed figure on purpose**, and says why (design decision 39).
- **Google direct is deterministic across days** — regenerating `config/showcase.json` a day
  later reproduced all 16 answers and all 16 retrieval windows byte-for-byte. Gotcha 16 had only
  ever established this for OpenRouter-pinned.

### The empanelment question is answered, and the answer is worse than the question

**Of the two editions in the corpus, `empanelment_dec2021.pdf` is the later one** — confirmed
from NHA's live site, and the *opposite* of what "Version – 2.0" implies. Open question 1 from
every previous handoff is closed.

**But NHA now publishes an edition newer than either file, and it is not in the corpus.** So
every empanelment answer this system gives is drawn from superseded guidance, however correctly
it cites. The Ask tab's demo notice and the About tab now say so explicitly, because *a correct
citation to an outdated rule is more convincing than a wrong answer and no easier to catch.*

Fetching the new edition changes retrieval, invalidates the empanelment rows of the golden set,
and forces a re-baseline of every published figure. **It is a phase of work, not an errand.**

The agreed product behaviour meanwhile: **surface the disagreement, never pick a winner.** Name
the edition beside each citation and state both values when they differ. Telling the model to
prefer an edition would produce a confident, well-cited, outdated figure on a health-scheme
entitlement.

---

## What to do next

### 1. Host measurement, behind a secret token — the owner's own idea, and the top item

Everything in gotcha 26 was measured on the development machine. **Community Cloud is shared
vCPUs and the spread there is likely wider, and nobody has measured it.** The owner asked the
right question: why characterise latency on a laptop nobody visits?

Design agreed with the owner:

- **Gated by a secret token in the URL** (`?dev=<token>` checked against `st.secrets`), not a
  visible button, so it does not exist for visitors.
- **Retrieval only, no LLM calls** — costs no quota and cannot drain the demo.
- **Runs the corrected experiment design**: conditions repeated with rotated order. A single
  pass would return one point sample from a range we already know is ~1.7× wide.
- **Output is an on-screen table plus `st.download_button`.** This matters: Community Cloud's
  filesystem is **ephemeral**, so the app cannot save the result anywhere retrievable. The owner
  downloads the JSON from the browser and it gets committed.

Then commit the host figures and let the D-4 latency panel cite the *host* rather than a laptop.

### 2. Analytics — metadata only, and that decision is deliberate

**Do not log question text.** The owner and the assistant agreed to metadata only:
random session uuid, timestamp, mode, k, latency, n_citations, abstained, cache_hit,
`sources_expanded`, app_version, index_hash. **No question, no answer.**

`sources_expanded` is the one that matters: for a citation-first product, whether anyone actually
opens a citation is the real success metric.

This needs a one-line visible notice and **no scrubbing pass, because there is nothing sensitive
to scrub** — which is the entire reason for the choice. Logging question text is the more
valuable half (it is the only real fix for the golden set's authorship bias) and it is the half
that needs consent, scrubbing and care. **It is a deliberate later step, and explicitly not to be
done in the same week the link is shared publicly.**

Storage target: a Hugging Face **Dataset** repo — free, persistent, versioned, loads back into
the eval.

### 3. Two small pieces of plumbing, neither blocking

- **`timing_env` in `run_eval.py`** — record thread count and CPU in each results file, exactly
  as `eval/make_showcase.py` now does. ~20 minutes, changes no published number, and directly
  prevents a repeat of the confusion that cost most of a session.
- **`eval/rescore.py`** — re-score a saved run against a different golden set from its stored
  top-k window, without re-running it. Not needed for D-4 (runs at both eval versions happened to
  exist) but **it matters the next time the golden set changes**: generation numbers re-score
  themselves and retrieval numbers do not (gotcha 19).

### 4. Prompt v2 — cheap, clean, small payoff

Targets false refusals: the model declining when the evidence *was* retrieved, measured at
**7.3%** on the deployed configuration. Rule 2 of the current prompt conflates two instructions
and splitting them is the hypothesis. ~$0.15, ~40 minutes, and the A/B is unusually clean because
pinned runs are byte-identical, so any difference is the prompt rather than noise. Honest
expectation: a couple of points. Nice-to-have, not a headline.

### 5. Corpus refresh — the big one, and NOT a side task

NHA publishes an empanelment edition newer than anything in the corpus, so every empanelment
answer the system gives is correctly-cited superseded guidance (see above).

**This is a phase of work, not an errand.** Fetching it changes retrieval, invalidates the
empanelment rows of `eval/golden_set.csv`, and forces a re-baseline of **every published figure
in the README** — all four retrievers, both eval sets, and the generation comparisons that are
scored against those target pages. Plan it with the owner in stages first, and say what must be
re-run and what that costs before touching anything.

Note the sequencing trap: the golden set is anchored to `(source_file, page)` precisely so it
survives re-chunking and model swaps (design decision 8) — but it does **not** survive the
underlying document changing, because the page numbers move. That is the part that cannot be
automated away.

### Paused by the owner

**D-6, the semantic cache.** Nothing is lost. The exact-match-after-normalisation layer is free
and zero-risk whenever wanted. The semantic layer stays blocked on a threshold sweep — true
positives are `eval/paraphrase_set.csv`, true negatives are the contradiction and version-conflict
rows — and **ships only if a threshold exists with zero false collisions.** This corpus is hostile
to it: 10 beds vs 5, 3 vs 5 working days, two editions stating the same clause with different
numbers.

---

## Open questions still live

1. ~~Which empanelment edition is in force?~~ **Closed** — see above. Replaced by a larger one:
   the corpus predates NHA's current edition entirely.
2. **Is Google direct slower than OpenRouter?** Committed runs say yes (p50 2,185/3,978 ms and
   p95 5,048/7,251 ms against OpenRouter-pinned 1,112–1,231 / 1,465–1,778). Spot checks have not
   reproduced it, and last session's host observations showed generation swinging 1.9–10.4 s,
   which suggests the variance is large enough that neither result is settled.
3. **Abstention has no similarity threshold** — it is the model's judgement.
4. **`k = 5` is untuned**, and on a hosted LLM retrieval no longer dominates, so depth and `k`
   matter differently than they did locally.
5. **Real user questions.** Metadata-only analytics will not produce these. Getting them needs
   the question-text decision revisited deliberately.
6. **Does the window-homogeneity penalty appear on a frontier model?** Confirmed on two 7B
   models, absent on `flash-lite`. ~$3 pinned to Anthropic would answer it. Run it for precision
   and false abstention, **not** `citation_correctness`, which is saturated.
7. **Should hybrid still be the rerank pool?** A BM25-only pool reaches 100% recall at depth 30
   where hybrid reaches 96.7% — but that is golden-set evidence and the paraphrase set inverts it.

---

## Things not to lose

- **Check whether a question can be answered by re-scoring saved runs before paying for one.**
  Retrieval is byte-reproducible and every results file saves its returned window. *Note the
  precision: files save the top-5 window, not the depth-30 candidate pool, so hit@k and MRR can
  be recomputed but pool recall cannot.*
- **`@st.cache_data` means a regenerated `config/showcase.json` is not picked up until the process
  restarts** (gotcha 28). Harmless on Community Cloud because `git push` restarts the app — but a
  test that overwrites that file and re-runs the app is testing the cache, not the file. One did.
- **A test needs a control.** The old-format `showcase.json` case only worked once it asserted the
  field is *present* with the new file and *absent* with the old one. Written the natural way —
  "it does not crash" — it would have passed while executing none of the code it existed to cover.
- **`config/showcase.json` is generated, not written.** Regenerate with
  `python -m eval.make_showcase` if the prompt version or model changes. It saves after every
  answer, so a rate limit costs the remaining questions rather than the whole run.
- **The showcase set includes a deliberate abstention row** and it works in both modes. Do not
  "fix" it.
- **The D-4 tab hardcodes nothing**, including which eval versions it compares: "current" is
  whichever question-set hash is live, "earlier" is whichever appeared first. A hardcoded hash is
  a number that goes stale, which is the failure the tab exists to explain.
- **`st.tabs` renders every tab in one pass, and `st.stop()` halts the script rather than the
  tab.** The static tabs are rendered *before* the Ask flow so a quota-blocked visitor still gets
  a complete site. Do not reorder those blocks.
- **The tab CSS targets `data-baseweb` attributes**, which are Streamlit internals. It degrades
  safely — if a future version renames them the tabs revert to the default style and still work.
  The emoji in the tab labels are the fallback signal and are in the labels for that reason.
- **The daily and per-session caps are in-process** and reset on restart. They bound the common
  case; they are not a guarantee, and the code says so.
- **Do not put `goldenvN` in `--label`.** The question set is recorded as a content hash.
- **Windows console is cp1252** and dies on emoji. Project entry points reconfigure stdout;
  ad-hoc one-liners do not, and this cost time twice last session (gotcha 8).
