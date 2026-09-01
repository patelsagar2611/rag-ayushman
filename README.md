# PM-JAY RAG

Retrieval Augmented Generation over the National Health Authority's Ayushman Bharat
(PM-JAY) corpus. Answers carry a filename and page number for every claim, and the
system declines to answer when the retrieved evidence does not support one.

Zero-cost stack: PyMuPDF, BGE embeddings, Chroma, Streamlit, and either a local Ollama model
or any OpenAI-compatible hosted endpoint.

**Status:** Phase 1 complete. Phase 2 retrieval complete and measured; Phase 2 generation
measured on a local model. 11 documents, 629 pages, 872 chunks, 69 hand-written evaluation
questions.

**The headline result: a large retrieval gain bought almost no answer gain.** Reranking
improved retrieval by 26% in MRR (0.699 → 0.879). It reduced false refusals on every model tested — and
improved citation *precision* on none, while actively harming it on a local 7B model. An
earlier version of this README reported a +3.8 point attribution gain on a hosted model; that
turned out to be an artifact of a metric that passes when *any* citation is correct, rewarding
the fact that reranking makes models cite more sources. See
[Generation results](#generation-results--did-better-retrieval-produce-better-answers), which
keeps the superseded claim visible alongside the correction.

### Which document is which

| doc | scope | lifetime |
|---|---|---|
| **README.md** (this file) | **The permanent record.** Results, design decisions, gotchas, anti-goals, corpus provenance. Everything durable lives here and nowhere else. | Whole project |
| [Docs/HANDOFF.md](Docs/HANDOFF.md) | **The next session only.** Current state, what is in flight, what to do next. Nothing that belongs in the README. | Replaced each session |
| [Docs/INTERVIEW-ANGLES.md](Docs/INTERVIEW-ANGLES.md) | The engineering journal — each problem with its reasoning and how to defend it. May overlap the README by design. | Whole project |
| [Docs/PMJAY-RAG-PROJECT.md](Docs/PMJAY-RAG-PROJECT.md) | The original brief. | Fixed |
| [Docs/DEPLOYMENT.md](Docs/DEPLOYMENT.md) | Hosting plan. | Whole project |

**Start every session by reading this README, then the handoff.** When a session's work is
stable, its findings are promoted here and the handoff is rewritten from scratch for the next
one. A handoff that has grown a history section has drifted from its purpose.

---

## How this project is worked on

Parts of this project were built with an AI assistant. The rules below are binding on every
working session and are recorded here rather than left implicit, because they shaped what
got built. The full version is [§00 of the handoff](Docs/HANDOFF.md).

1. **Explain the reasoning, not just the outcome.** Every decision is recorded with what it
   was chosen *over* and what evidence decided it. A decision without its alternative is an
   assertion, and it cannot be defended later by someone who was not present when it was made.
2. **Small batches, with the reasoning surfaced as it happens** — never a long unattended
   run of steps followed by a summary. Judgement calls are put to the owner at the point
   they arise, with the trade-offs, because reviewing them afterwards is not the same as
   making them.
3. **Nothing is executed without asking first** — including single-question smoke tests, not
   only full evaluation runs.
4. **Any message sent while a run is in progress ends by saying so**, warning that a system
   sleep will corrupt it, and giving an estimated duration. See gotcha 17: a suspended
   machine silently invalidates timing numbers, and on hosted models it leaves no detectable
   signature afterwards.
5. **The development machine is not always on.** Runs are planned around that.

The underlying standard: this is a portfolio project, so the deliverable is not a working
pipeline but a working pipeline its author can **explain**. Speed of completion is worth
nothing against that, and pursuing it destroys the thing being built.

### IMPORTANT — the engineering journal is a required deliverable

**[Docs/INTERVIEW-ANGLES.md](Docs/INTERVIEW-ANGLES.md) is not optional documentation and not a
by-product. It is a deliverable of every working session, on the same footing as the code.**

**The motive.** Findings are lost at the moment they are made, not later. The reasoning behind
a decision is vivid while it is being made and gone within days, leaving only the outcome —
and an outcome without its reasoning cannot be defended by anyone, including the person who
chose it. This project's value is the judgement it demonstrates, and judgement is only visible
in the *rejected* alternatives. Capturing those as they happen is the only time it is cheap.

**The process, binding on every session.** Whenever a problem is hit, a trap avoided, a
metric found wanting, or a decision made where a reasonable engineer could have gone the other
way — **it gets an entry, in that session, before the work is called done.** Not at the end of
the phase, not before an interview. A finding that survives only in a chat transcript has been
lost.

**The format.** Every entry has four parts, and an entry missing any of them is incomplete:

| part | what it must contain |
|---|---|
| **The scenario** | the problem, optimisation, or trap, stated concretely |
| **How we got to the answer** | the reasoning — including what was rejected, and why |
| **Defensive argument** | the answer when an interviewer challenges this directly |
| **Show-off argument** | how to raise it *unprompted*, and the opening that gets you there |

The last two are why this file exists rather than being folded into the handoff. The handoff
records what the state is, for someone continuing the work. This records why the state is what
it is, for someone defending it. Same events, different question.

**The payoff.** Read end to end, the journal reconstructs the entire project — every problem,
every trade-off, every thing that went wrong and what it taught — in one pass, without
re-reading the code. That is its test: if it cannot be used as a single-document recap of the
whole journey, it is not being maintained properly.

---

## Setup

Python 3.12 (3.13 not used — some ML wheels still lag).

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**The two-step torch install is gone.** `requirements.txt` now pins
`torch==2.13.0+cpu` behind `--extra-index-url`, so one file produces a CPU-only
environment. It had to: Hugging Face Spaces builds from `requirements.txt` and
nothing else, and a two-step install is not expressible there.

`--extra-index-url` alone would not have been enough — it is a *hint*, so pip
weighs both indexes and a newer torch on PyPI simply wins. The `+cpu`
local-version suffix is what makes it binding, because that suffix exists only on
the PyTorch index: resolution either finds the CPU wheel or fails loudly.

Verified in a clean `python:3.12-slim` container rather than asserted — it
resolves `torch-2.13.0+cpu-cp312-cp312-manylinux_2_28_x86_64.whl` with **zero
`nvidia-*` packages in a 111-package closure**. The absence of those packages is
the real acceptance test: `torch.cuda.is_available()` returns `False` on any
machine without a GPU, *including one where the 2.5 GB CUDA build installed
perfectly*, so it would have passed while the exact failure being guarded against
had occurred. Note the wheel is `manylinux_2_28`, so the host needs **glibc ≥ 2.28**
(Debian bookworm and Ubuntu 22.04 both clear it).

`requirements-lock.txt` is the full 111-package closure captured inside that
container. It is generated, never hand-edited, and never with `pip freeze` on
Windows — that emits Windows-resolved versions and platform-only packages that
break a Linux build.

### Re-indexing

**`chroma/` is committed, and hidden from git with `skip-worktree`.** Merely
*opening* the collection rewrites the sqlite file and the HNSW segment, so without
this every run of the app or the eval leaves a 15.7 MB binary looking modified —
and one absent-minded `git add -A` puts it into history permanently.

Set the flag once per clone (it is local to a working copy and not inherited by a
fresh checkout):

```powershell
git ls-files -z chroma/ | xargs -0 git update-index --skip-worktree
```

The cost of that fix is that a **genuine** re-index is hidden too, so committing
one is a deliberate act:

```powershell
git ls-files -z chroma/ | xargs -0 git update-index --no-skip-worktree
git add chroma/ ; git commit -m "re-index"
git ls-files -z chroma/ | xargs -0 git update-index --skip-worktree
```

`python -m src.index` prints those steps on completion, so the instruction appears
in the output of the command that creates the situation rather than only here.

Local LLM — install [Ollama](https://ollama.com/download), then in a **new** terminal
(the installer's PATH change is not visible to already-open shells):

```powershell
ollama pull qwen2.5:7b      # qwen2.5:3b if you have 8 GB RAM
```

## Running the pipeline

Each stage writes to disk, so stages are re-runnable independently.

```powershell
python -m src.download          # 11 PDFs -> data/raw/
python -m src.inspect_corpus    # which PDFs are scanned images?
python -m src.extract           # -> data/processed/pages.jsonl
python -m src.chunk             # -> data/processed/chunks.jsonl
python -m src.index             # -> chroma/  (persistent; skips already-indexed chunks)

streamlit run app.py
```

Command line, without the UI:

```powershell
python -m src.retrieve "hospital empanelment criteria"            # dense, the default
python -m src.retrieve --mode bm25 "PAN card"                     # keyword only
python -m src.retrieve --mode hybrid "empanelment renewal"        # RRF of both
python -m src.retrieve --mode rerank "annual cover per family"    # + cross-encoder, hybrid pool
python -m src.retrieve --mode rerank-bm25 "annual cover"          # + cross-encoder, bm25 pool
python -m src.retrieve --mode rerank-union "annual cover"         # + cross-encoder, union pool

python -m src.generate --mode rerank "What is the annual cover per family?"
python -m eval.pool_recall                                        # pool ceilings, no LLM
```

The same `--mode` flag reaches generation and the Streamlit sidebar, so the product can use
every retriever the eval can score. `DEFAULT_MODE` stays `vector` — reranking is a large
retrieval win with no measured answer-quality benefit, and the default is not the place for an
unmeasured bet.

### Choosing an LLM backend

Generation runs against a local Ollama model by default, or any OpenAI-compatible endpoint.
Copy `.env.example` to `.env` (gitignored) and fill it in.

Two variables select the backend, and they answer different questions:

| variable | question | values |
|---|---|---|
| `LLM_PROVIDER` | which **API shape** | `ollama` (local) or `openai` (any OpenAI-compatible endpoint) |
| `LLM_BACKEND` | which **endpoint** of that shape | any `<NAME>` for which `<NAME>_BASE_URL` etc. are defined |

Every hosted setting is read from a `<BACKEND>_*` prefix, so the URL, key, model
and upstream pin are selected **together** by one name:

```dotenv
LLM_PROVIDER=openai
LLM_BACKEND=google          # the only line you change to switch endpoint

GOOGLE_API_KEY=...
GOOGLE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
GOOGLE_MODEL=models/gemini-3.1-flash-lite

OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=google/gemini-3.1-flash-lite-20260507
OPENROUTER_PROVIDER=Google AI Studio
```

Adding a vendor is three lines of `.env` and **no code change**, which is the
strongest available form of "provider is configuration, not a branch".

**Two failure modes this exists to make unrepresentable**, both of which earlier
designs allowed. A single `OPENAI_API_KEY` resolved without reference to the
endpoint means that with two vendors configured and one slot to hold them,
switching backends is an edit — and forgetting once sends a live credential for
one vendor to another vendor as a bearer token. Matching the key to the endpoint
by hostname fixes that but leaves the URL and the **model** as separate settings
that must move together: Google wants `models/gemini-…` where OpenRouter wants
`google/gemini-…-20260507`, so a half-finished switch produces a puzzling 404.
Selecting everything by one prefix removes both, rather than detecting them.

A typo in `LLM_BACKEND` fails immediately, naming the missing variables and
listing the backends actually configured — discovered by scanning the environment
for `*_BASE_URL`, so the error message cannot itself go stale.

**A hosted model is a different model** — never compare a hosted number against a
local one and attribute the difference to retrieval. Every results file records
`llm_provider`, `llm_backend` and `llm_model`, so no run is ambiguous about what
produced it. `llm_backend` was added because the endpoint was previously
*unrecoverable*: `llm_model` names the model and `served_by` names the upstream
deployment, but nothing recorded which endpoint was called. Google-direct and
OpenRouter runs were distinguishable only because their model ids happen to differ
in shape, which is luck rather than provenance.

## Evaluation

```powershell
python -m eval.run_eval --retrieval-only     # no Ollama needed; this is the CI path
python -m eval.run_eval                      # adds generation metrics
python -m eval.run_eval --retriever rerank   # vector | bm25 | hybrid | rerank
python -m eval.run_eval --min-hit-rate 0.7   # exit 1 below threshold
python -m eval.run_eval --only-rows 5,12,40-42          # re-run specific rows
python -m eval.run_eval --golden eval/paraphrase_set.csv  # the lay-phrasing set
python -m eval.diff_editions                 # regenerate Docs/empanelment-diff.md
python -m eval.pool_recall                   # candidate-pool ceilings
python -m eval.vocab_overlap                 # question/target-page word overlap
python -m eval.citation_companions           # head-to-head citation metrics
python -m eval.backfill_provenance --dry-run # add run provenance to older results files
```

### The two evaluation sets

| set | rows | role |
|---|---|---|
| `eval/golden_set.csv` | 69 (60 answerable, 9 abstain) | **the baseline.** Every published number is measured on it. |
| `eval/paraphrase_set.csv` | 17 | **a robustness check.** The highest-overlap golden questions rewritten in lay language, same facts and same target pages. |

The paraphrase set is deliberately *not* a second baseline: 17 questions is too few for a
headline figure, and its rows were chosen as the least representative ones in the corpus. Its
purpose is to answer one question — how much of a retrieval score survives a user who does not
phrase things the way the documents do. See
[Does BM25 actually win?](#does-bm25-actually-win-or-did-the-question-author-write-like-the-documents)

### Golden set schema

`eval/golden_set.csv` — one question per row:

| Column | Meaning |
|---|---|
| `question` | Asked verbatim. This text gets embedded, so typos cost retrieval quality. |
| `expected_answer` | Human reference for manual review, **not** auto-compared. Literal `ABSTAIN` marks an unanswerable question. |
| `source_file` | Filename(s). `,` or `;` separated. |
| `page` | Page number(s), same separators. |
| `must_contain` | The bare value the answer must state — see below. **`;` separated only**, since values like `5,00,000` contain commas. Often blank. |
| `notes` | What this row tests. |

Pages are **physical position in the file**, matching your PDF viewer's page counter — not
the number printed on the page. Government PDFs have roman-numeral front matter, so the two
routinely differ.

One filename broadcasts across several pages (`empanelment_v2_0.pdf` + `5;6`). Equal-length
lists pair positionally, which is what version-conflict rows need, since the answer sits on
a different page in each edition.

### What `must_contain` is for

A case-insensitive substring test against **the model's answer**, with whitespace collapsed.
It catches exactly one failure: *the right page was retrieved and the model stated the wrong
figure.* It is deliberately not a test of phrasing, completeness or style.

So it holds **the smallest string that carries the fact — normally the bare number, with
units stripped**:

| Not this | This | Why |
|---|---|---|
| `48 hrs` | `48` | passes on "48 hrs", "48 hours", "forty-eight hours" |
| `136 percent` | `136` | passes on both "136 percent" and "136%" |
| `15 working days` | `15` | passes however the model phrases the period |
| `5,00,000` | `5,00,000` | unchanged — the commas are formatting, not units |

The source document's wording is not the only correct wording. A user-facing answer that says
"within 48 hours" when the manual says "48 hrs" is a *better* answer, not a wrong one, and a
metric that fails it is measuring the wrong thing.

A phrase is right only when the phrase **is** the fact — acronym expansions like
`Deputy District Officer`, or proper nouns like `Aadhaar`. Leave the field blank for yes/no,
definitional and descriptive questions; there is no load-bearing value to check, and
citation correctness and the abstention metrics still cover those rows.

Two failure modes to avoid at the edges. Short common words pass unconditionally — `No`
matches inside "notice", "cannot" and "known". And a bare single digit can match a citation
marker, so `5` passes on an answer that cites `[5]` without ever stating the figure; stripping
citations before the comparison is a pending fix.

**`must_contain_pass` is a floor, never a target.** Optimising the prompt to raise it would
push the model toward reciting source text verbatim — worse product behaviour, not better.

### Finding page numbers

```powershell
python -m eval.find "inpatient beds"
python -m eval.find "show-cause notice" --file empanelment_v2_0.pdf
python -m eval.find "\d+ working days" --regex
```

Plain keyword search over `pages.jsonl`, deliberately **not** vector search — using the
system's own retrieval to decide which page an answer is on is circular, and would score
itself perfectly by construction.

### Why these metrics

Every run writes a self-describing JSON file to `eval/results/`, recording k, the embedding
model and the chunk parameters alongside the metrics — a metrics table is meaningless
without knowing what produced it.

**Every run records which eval scored it, and what actually served it.** `question_set_sha` is
a content hash of the question file — line endings normalised, so a Windows checkout and a git
blob agree — and `served_by` lists the deployments that answered, where a list longer than one
entry *is* a blended run. `descriptor` is composed from those fields rather than typed beside
them. This exists because the alternative was tried: run identity lived in a hand-typed `label`,
and two runs labelled `openrouter-…` turned out to be the unpinned ones (gotcha 20). Backfill
historical files with `python -m eval.backfill_provenance`.

**MRR, not just hit rate.** Hit rate is binary: rank 1 and rank 5 both score 1.0. MRR scores
them 1.0 and 0.2. Since the known weakness is answer-bearing chunks ranking below topical
ones, MRR is the number the Phase 2 reranker has to move; hit rate could stay flat while the
reranker does real work.

**Retrieval metrics need no LLM**, which is what makes CI viable: GitHub Actions cannot run
Ollama, but `--retrieval-only` still measures hit rate and MRR — the half of the system most
likely to regress. Faithfulness is deliberately not scored: it needs a judge, and an LLM
judge grading an LLM's answers largely measures the model agreeing with itself.

Latency is measured after a warmup call to both stages. Unwarmed, the embedding model load
(~5s) and Ollama's model load land entirely on question 1 and distort p50/p95.

### Known gaps — answers the pipeline cannot reach

`eval/known_gaps.csv` holds questions that were written, verified against the PDFs, and then
**excluded from scoring** because their answer is not in the extracted text at all. In each
case the value is rendered as part of an image — a chart, or a table saved as a graphic —
so PyMuPDF never sees it.

The evidence is specific rather than assumed: for the helpline number, the word "helpline"
*is* extracted from p.30 of `operation_manual.pdf` while `14255` appears nowhere in the file.
Same shape for the HBP 2.1 procedure count on p.18.

This is a real limitation and worth stating plainly: `src/inspect_corpus.py` cleared all 11
PDFs as text-native, but it measures **average characters per page**, which cannot detect an
image-embedded table sitting on an otherwise text-heavy page. Document-level triage is not
the same as content-level coverage.

They are excluded rather than deleted for two reasons. Scored, they would be permanent
retrieval failures — capping hit rate for a reason unrelated to retrieval quality, and
immune to anything Phase 2 reranking does. Deleted, the finding would be lost. Kept aside,
they are the concrete case for adding OCR in a later phase.

**The golden set is 69 questions** (60 answerable, 9 expected to abstain). Per the brief's
anti-goals it is hand-written and hand-verified, never generated.

**Its biggest known limitation is who wrote it.** The questions were written by someone
reading the documents, so they reuse the documents' vocabulary — "cover amount on family
floater basis" rather than "how much money do I get for an operation". Lexical overlap
between question and document is exactly what BM25 scores, so **BM25's win below may be
partly an artefact of authorship rather than a property of the corpus.** Every retrieval
figure in this README inherits that bias. The test is to re-run with questions phrased by
someone who has not read the corpus; it is not yet done, and it is the single largest open
threat to these numbers.

**It was known to be incomplete, and a full review on 2026-08-28 found how incomplete.**
Eighteen of the 60 answerable rows gained target pages; two of them (35, 66) had listed a page
that does not contain the answer at all, and had been scoring a guaranteed citation failure in
every run since the set was written. One row — 41 — listed a single page for a sentence that
appears **verbatim on six pages across two documents**.

Every published figure moved as a result. **This is a measurement change, not an improvement.**
The review is written up under
[the completeness review](#the-golden-set-was-incomplete-and-correcting-it-moved-every-number),
including a prediction made before the re-scoring that turned out to be wrong. Both the old and
new figures are kept visible throughout. `citation_correctness` should still be read as a
**floor** — the review was thorough, not exhaustive.

## Retrieval results — what each Phase 2 change bought

69 hand-written questions (60 answerable, 9 expected to abstain), k=5, one change at a
time, each measured on its own. Retrieval metrics need no LLM, so every row here is
reproducible in minutes with `--retrieval-only`.

> **These are retrieval numbers only** — they say nothing about answer quality, which is
> measured separately in [Generation results](#generation-results--did-better-retrieval-produce-better-answers)
> and does **not** follow the same direction. Retrieval metrics need no LLM, so every row
> here reproduces in minutes with `--retrieval-only`.

| Retriever | hit@1 | hit@3 | hit@5 | **MRR** | retrieve p50 |
|---|---|---|---|---|---|
| `vector` — dense only (Phase 1 baseline) | 56.7% | 78.3% | 91.7% | **0.699** | 36 ms |
| `bm25` — keyword only | 70.0% | 83.3% | 86.7% | **0.766** | 5 ms |
| `hybrid` — RRF of the two | 61.7% | 88.3% | 91.7% | **0.753** | 41 ms |
| `rerank` — hybrid top-30, cross-encoder | **81.7%** | **95.0%** | **96.7%** | **0.879** | 3,486 ms |
| **change vs baseline** | **+25.0 pts** | **+16.7 pts** | **+5.0 pts** | **+0.180** | ×97 slower |

> **These figures are goldenv3, 2026-08-28.** Eighteen rows gained target pages after a
> completeness review found the golden set was missing pages that genuinely answer the
> question. **Every number here rose because the scorer was corrected, not because retrieval
> improved** — the retriever is byte-identical and re-scoring the 24 August runs against the
> corrected set reproduces these figures exactly. The superseded goldenv1 figures were
> `vector` 48.3/71.7/90.0/0.624 and `rerank` 71.7/85.0/95.0/0.795, a headline of **+0.171**.
> Correcting the eval made the reranking gain slightly *larger*, not smaller — see
> [the completeness review](#the-golden-set-was-incomplete-and-correcting-it-moved-every-number).

> **Read the BM25 row with the caveat below.** Its lead over the embeddings holds only for
> questions written by someone who had read the documents. On lay phrasing it collapses and
> the ranking inverts — see [Does BM25 actually win, or did the question author write like the
> documents?](#does-bm25-actually-win-or-did-the-question-author-write-like-the-documents)

Three of those rows are more interesting than the summary line.

### Does BM25 actually win, or did the question author write like the documents?

The golden set was written by someone reading the corpus, so the questions reuse the corpus's
own vocabulary — *"cover amount on family floater basis"* rather than *"how much money do I get
for an operation"*. **BM25 scores exactly that lexical overlap.** So its measured lead may be a
property of the author rather than of the corpus.

Measured, not assumed. `eval/vocab_overlap.py` scores each question's content words against its
target page, using the *same tokenizer BM25 uses*:

| | |
|---|---|
| mean overlap | **81.1%** |
| median | 83.3% |
| questions reusing **every** content word from their target page | **19 of 60** |

Measured against goldenv3. The completeness review raised these — overlap is scored against the
union of a question's target pages, so adding a target can only raise it. The set-wide mean moved
78.1% → 81.1% and the questions reusing *every* content word moved 15 → 19 of 60. **The bias this
quantifies is therefore slightly worse than first reported, not better.**

Then the paired test: the 17 highest-overlap questions rewritten in lay language, keeping the
same facts and the **same target pages**, so retrieval is the only thing that can move. Rewrites
were drafted from the question and the human-written expected answer — never from page text —
and hand-reviewed (`eval/make_paraphrases.py`). Mean overlap fell **98.2% → 36.1%**.

Those 17 rows were chosen by the goldenv1 overlap ranking, and that selection is deliberately
*not* re-derived against goldenv3 — 19 rows now tie at 100% where 15 did, so a fresh top-17 would
be a different set, and swapping the rows would silently change what the paired experiment
measures rather than update it.

| retriever | MRR original | MRR lay phrasing | change | hit@1 |
|---|---|---|---|---|
| `vector` | 0.799 | 0.453 | −43% | 64.7% → 29.4% |
| `bm25` | **0.971** | **0.159** | **−84%** | 94.1% → **5.9%** |
| `hybrid` | 0.941 | 0.461 | −51% | 88.2% → 35.3% |
| `rerank` | 0.971 | **0.600** | **−38%** | 94.1% → 52.9% |

Both arms re-scored against goldenv3 on 2026-08-29, after the paraphrase set's targets were
brought back into line with the golden rows they pair with — three of its 17 rows had been left
behind by the completeness review, which would have scored the two sets against different
answers and called the difference phrasing.

**The ranking inverts.**

```
original wording:   rerank 0.971  =  bm25 0.971  >  hybrid 0.941  >  vector 0.799
lay wording:        rerank 0.600  >  hybrid 0.461  ~  vector 0.453  >  bm25 0.159
```

BM25 goes from **tied first to last**, finding the right page first in **1 of 17 questions**. Vector
goes from last to second. Both outcomes were **pre-registered before the run**: that BM25's lead
would shrink if the bias was real, and that reranking would degrade least because a
cross-encoder reads question and passage together. The first held far more strongly than
"shrink" anticipated.

Three consequences:

- **The +0.180 MRR headline above is measured on favourable phrasing.** Treat it as an upper
  bound. The four-retriever table is not wrong, but it answers "which retriever wins on
  questions phrased like the documents", which is not the question a deployed system faces.
- **Hybrid inherits the weakness, though not as badly as first measured.** On the corrected
  scoring hybrid (0.461) and plain vector (0.453) are indistinguishable — a 0.008 gap on 17
  questions is noise, not an ordering. An earlier version of this section reported hybrid at
  0.402 against vector's 0.443 and concluded that fusion drags the result *below* dense
  retrieval alone. **That no longer holds.** What survives is the weaker and still useful claim:
  fusing in a retriever that has stopped working buys nothing — hybrid's large advantage on
  document-phrased questions (0.941 vs 0.799) evaporates entirely on lay phrasing.
- **Everything degrades sharply.** Even the best retriever loses 38%. That is a product finding
  independent of BM25: this system is brittle to phrasing, and the eval set as originally
  written could not have shown it.

**Two caveats, both meaning this is an upper bound on the effect.** The 17 rows were selected as
the *highest-overlap* in the set (98.2% mean against 81.1% set-wide), so they are where the bias
bites hardest by construction. And the rewrites are LLM-drafted — a proxy for user language that
strips almost all domain vocabulary, where a real user would likely keep some ("Ayushman card",
"claim"). Neither rescues a hit@1 of 5.9%: a 15-questions-to-1 collapse is not a small-sample
artifact.

`eval/paraphrase_set.csv` is kept as a **permanent second evaluation set**. Run any retriever
against it with `--golden eval/paraphrase_set.csv`. It is a robustness check, not a replacement
baseline — 17 questions is too few to be a headline number, and its rows are deliberately the
least representative ones.

### Which candidate pool should the reranker get?

A reranker can only reorder what it is handed, so the candidate pool sets its ceiling. Three
pools measured at depth 30, everything else identical:

| pool fed to the cross-encoder | hit@1 | hit@3 | hit@5 | MRR | p50 | pool recall@30 |
|---|---|---|---|---|---|---|
| `hybrid` — RRF of both, cut to 30 | 81.7% | 95.0% | 96.7% | 0.879 | 2.0 s | 96.7% |
| `bm25` — BM25 top 30 | **83.3%** | **96.7%** | 98.3% | **0.896** | 3.7 s | **100%** |
| `union` — both lists, deduped (~50) | 81.7% | **96.7%** | **100%** | 0.891 | 6.7 s | **100%** |

Re-scored to goldenv3 from the saved candidate lists; the arms themselves were not re-run,
because retrieval is deterministic (design decision 17) and re-scoring the hybrid arm
reproduces the fresh run above to three decimal places.

**`hybrid` was kept, on latency, not on quality.** It loses the coverage comparison — 96.7%
against the union's 100% hit@5 — and the target is a public demo on free hosting where the
cross-encoder is projected to run ~4× slower than locally. Anyone reversing this should
reverse it on latency evidence, not because they believe hybrid retrieves better. It does not.

Two things that comparison taught, neither visible in the aggregate:

**Recall is a ceiling, not a score.** BM25's recall lead over hybrid is **+2 questions and −1
question**, not a strict improvement — the pools are not nested. And that net +1 became net
**zero** after reranking, because a pool *gain* is optional while a pool *loss* is mandatory:
one recovered question the cross-encoder promoted to rank 1, another it declined to promote at
all, and the lost one was simply unrecoverable.

**Fusion ranks *and truncates*, and only the truncation costs anything here.** RRF merges up
to 60 chunks and cuts back to 30; that cut is the only place a page can be lost. The reranker
then re-sorts entirely by its own score, discarding RRF's ordering. So in a reranking pipeline
fusion contributes nothing downstream while its truncation still costs pages. Row 61 (`DDO`)
is the clean case: BM25 finds the glossary page at rank 17, dense retrieval never does, and
fusion pushes it out of the pool entirely. Row 62 (`CSC`) is worse — both retrievers find a
*different* valid page, neither corroborates the other, and fusion returns neither.

**Disclosures on this comparison.** The `union` arm was **post-hoc** — suggested by the
failure analysis above, not pre-registered like the other two. A decision rule for the
hybrid-vs-bm25 comparison *was* fixed in advance. And the union's depth-25 operating point
(same 100% ceiling as depth 30, ~17% fewer candidates) was chosen by reading golden-set
recall, which is test-set contact under the project's own rule against tuning on the eval
set. `RRF_K`, fusion depth and `k` remain at inherited defaults.

**BM25 alone beat the embeddings.** Not the expected result. On MRR (0.766 vs 0.699) and
hit@1 (70.0% vs 56.7%) a bag-of-words scorer with no semantics outperformed
`bge-small-en-v1.5`, at a seventh of the latency. It loses on hit@5 (86.7% vs 91.7%):
when BM25 misses it misses completely, whereas dense retrieval degrades gracefully. The
corpus explains it — these are government manuals full of rare, exact tokens (`HWCs`,
`PAN card`, `5,00,000`, `HBP 2.2`) that a 384-dimension embedding blurs together and an IDF
term rewards precisely.

**Fusion made hit@1 worse.** RRF dropped rank-1 accuracy to 61.7%, below BM25's 70.0%, while
lifting hit@3 to 88.3%. That is the mechanism working as designed rather than a bug: RRF
rewards chunks both retrievers agree on, so a chunk one retriever ranks first and the other
never returns gets pushed down. Taken as a final ranker, fusion is a poor trade here.

It was kept because it is meant to be a **candidate generator** for the reranker, not a final
ranker — and on that job the honest current answer is that **it is losing to BM25 alone**:

| Pool for reranking | recall@5 | recall@10 | recall@20 | recall@30 |
|---|---|---|---|---|
| `vector` | 91.7% | 91.7% | 95.0% | 96.7% |
| `bm25` | 86.7% | 90.0% | 96.7% | **100.0%** |
| `hybrid` | 91.7% | 95.0% | 96.7% | 96.7% |

A reranker can only reorder what it is handed, so pool recall is its hard ceiling — and BM25
alone now reaches **every** golden page by depth 30, where the fused pool reaches 96.7%.
`hybrid` is the only pool that fails to reach 100%.

> **Read that 100% with the authorship caveat attached, always.** It is a *golden-set* number,
> measured on questions written by someone who had read the documents — which is precisely the
> lexical overlap BM25 scores. On the paraphrase set the ordering **inverts** and BM25 finds the
> right page first in 1 of 17 questions. A BM25-only pool reaching 100% here is not evidence
> that a BM25-only pool is the right design; it is the same authorship artifact showing up in a
> new column. See [Does BM25 actually win?](#does-bm25-actually-win-or-did-the-question-author-write-like-the-documents) On an earlier
56-question version of this set the two tied at 100% and fusion was kept on a margin
argument; **that argument has since reversed and the design has not yet caught up.** Testing
a BM25-only pool is the top open item.

Row 61 shows how fusion actively destroys a find:

```
question: "What do mean by DDO?"     golden page: operation_manual.pdf p.3

vector   NOT IN TOP 30
bm25     rank 17            <- the only retriever that finds it
hybrid   NOT IN TOP 30      <- RRF drops it below 30 chunks both retrievers agreed on
```

A demotion *inside* the pool is recoverable by the reranker. Being pushed *out* of the pool
is not — so fusion here discards precisely the contribution BM25 was added to make.

**Reranking is where the gain is**, and it is the gain the baseline predicted: the Phase 1
gap between hit@1 and hit@5 said the right chunk was nearly always retrieved and merely
ranked badly. Closing that was the whole thesis of Phase 2, and it closed — MRR moved
0.699 → 0.879 and hit@1 rose 25 points.

### A claim that did not survive a bigger question set

An earlier 56-question version of this set produced `hit@5 = 100%` and `recall@20 = 100%`
for the fused pool. Both figures dropped when eleven questions were added — to 95.0% and
96.7%. The perfect scores were artefacts of the smaller set, and losing them is a useful
correction rather than a regression: they were the numbers most likely to be flattering, and
they were being used to justify an architecture choice that the larger set now contradicts.

### Where retrieval fails: glossary pages, and fusion throws them away

Two questions still miss at k=5, and they are the same kind of question — an acronym answered
by an abbreviations table. But the reason changed when the golden set was corrected, and the
new reason is worse for the architecture:

```
row 61  "What do mean by DDO?"    vector MISS   bm25 rank 17   hybrid NOT IN POOL
row 62  "What do mean by CSC?"    vector rank 22  bm25 rank 26  hybrid NOT IN POOL
```

**`reached by NO pool at depth 30: 0`.** Every golden page in the set is now found by *some*
component retriever within depth 30. Neither of these is a retrieval failure any more — both
are **fusion discarding a find a component made.** RRF rewards chunks both retrievers agree
on, so a page that only one retriever reaches gets pushed below the cut, and a page pushed out
of the pool is unrecoverable by the reranker.

The underlying difficulty is still real and worth stating: **a glossary entry mentions a term
once, in a list, with no explanatory context.** `DDO` appears on exactly one page of the whole
corpus and dense retrieval does not surface it; `CSC` appears on 15 pages, where the pages that
*use* the term outrank the page that defines it. But the corpus is no longer the binding
constraint — the fusion step is.

Both retrievers systematically prefer pages that discuss a term over the page that defines
it, and no amount of reranking fixes it, because the cross-encoder never sees the page.

### Two predictions, tested

Both were registered before the code was written.

**"BM25 should fix row 39 (`PAN card`), and do nothing for row 24."** Half right. `PAN card`
occurs in 2 of 872 chunks; dense retrieval missed it entirely at k=5 and BM25 put it at
**rank 1**. But row 24 was also fixed (MISS → rank 3), because the prediction reasoned from
the wrong property. Row 24 was filed as a *layout* problem — the answer sits in the second
column of a multi-column page — but the difficulty a retriever sees is in the *query*, and
`HWCs` occurs in only 4 of 872 chunks. It is the same rare-token case as `PAN card` wearing
a different label.

**"Vector retrieval should cite worse than reranking."** *Wrong.* Registered after the
reranked generation run, from the observation that questions whose golden page lands at rank 1
cite correctly 79% of the time against ~55% deeper. Vector retrieval has hit@1 of 48% against
rerank's 72%, so it should have scored around 68%. It scored **78.3%** head-to-head — better
than reranking. The correlation between rank and citation accuracy was real *within* a run and
did not survive as a causal prediction *across* runs, because changing the retriever changes
the whole window composition, not just where the golden chunk sits in it.

**"Reranking should fix rows 26 and 35."** Both were retrieved at rank 4–5 in Phase 1 with
the model abstaining anyway. Row 26 now reaches **rank 1** and row 35 **rank 3**. But the
prediction was about *abstention*, which is a generation outcome — and no generation run has
been done on this question set, so **this one is not yet resolved**. The retrieval
precondition improved; whether the model now answers instead of declining is unmeasured.

### Where reranking still fails

The cross-encoder improved 20 questions against its own input and regressed 8, and leaves 17
of 60 short of rank 1 — three of them missing from the top 5 entirely. The failures are worth
reading, because they are not random.

**It underweights an answer phrased differently from the question.** Row 24 asks "How many
HWCs are estimated to be setup by 2022?" The golden chunk says `1,50,000 health and wellness
centers will be set up`. It scored **-7.987** — near the bottom of the pool — despite being
a 358-token chunk that plainly contains the answer, well inside the model's input window.
The sentence never uses the acronym or the date, and an MS MARCO-trained reranker keys hard
on that surface overlap. This is the exact mirror image of BM25's strength, and the reason
fusion is worth keeping upstream of it even though fusion alone ranks worse.

**It cannot tell the two empanelment editions apart.** Row 41 asks about a show-cause
penalty; the golden page is `empanelment_v2_0.pdf` p.59 and the reranker promoted
`empanelment_dec2021.pdf` p.23 above it. Both editions state the rule, in near-identical
language, with different numbers. No reranker can resolve that — it is
[open question 1](Docs/HANDOFF.md), which edition is in force, and it needs a metadata
answer rather than a retrieval one.

> **~~Adjacent pages of the same document crowd each other out.~~ Retracted 2026-08-28 — this
> was an eval failure, not a reranker failure.** The paragraph read: *"Row 30's top five are
> `grievance_redressal.pdf` pages 23, 24, 22, 25 and — fifth — the golden page 16. Appeal
> timelines recur across that whole chapter."* All four of those pages state the 30-day appeal
> rule the question asks for; the golden set listed one of them. The reranker returned five
> correct pages and was scored 1 for 5. Worse, `vector` returned **the same five pages** in a
> different order, so this was never an example of reranking making a window homogeneous — the
> two windows were identical. What it is an example of is [the metric punishing
> breadth](#the-golden-set-was-incomplete-and-correcting-it-moved-every-number). Kept visible
> rather than deleted, because a failure mode that turned out to be a measurement artifact is
> the most useful kind of correction to be able to show.

**It can demote a page the pool had ranked well.** Row 58 entered the candidate pool at
rank 3 and came out below the top 5. Reranking is not monotone — it is a different model with
different opinions, and sometimes the retriever was right.

**Caveat, stated rather than worked around:** the cross-encoder has a 512-token input window
and chunks target ~600 tokens, so **34.3% of chunks (299 of 872) are truncated** before it
scores them. A chunk whose only relevant sentence sits in its tail can be scored as
irrelevant. It is not the cause of any regression above — row 24's chunk is well inside the
window — but it is a live risk, and re-chunking to fit would change the indexing that the
Phase 1 baseline was measured against.

## Generation results — did better retrieval produce better answers?

**Partly — and not in the way the earlier version of this section claimed.** Reranking
reduced false refusals on every model tested, and improved citation *precision* on none.

Six full runs: two retrievers (`vector`, `rerank`) × three model/endpoint combinations. Within
each pair the model, the prompt and the questions are fixed, so **retrieval is the only
variable**. Every figure is restricted to the questions *both* arms of that pair answered —
the arms decline different numbers, so an unrestricted comparison would score different
subsets — and re-scored against the current golden set. Reproduce with
`python -m eval.citation_companions`.

| head-to-head, `vector` → `rerank` | n | cited a golden page | **citation precision** | citations/answer |
|---|---|---|---|---|
| local `qwen2.5:7b` | 47 | 89.4% → 83.0% (**−6.4**) | 83.3% → 72.7% (**−10.6**) | 1.52 → 1.68 |
| hosted `gemini-3.1-flash-lite`, Google endpoint | 52 | 98.1% → **100.0%** (**+1.9**) | 93.6% → 93.9% (**+0.3**) | 1.56 → 1.63 |
| hosted `gemini-3.1-flash-lite`, OpenRouter **pinned** | 52 | 98.1% → **100.0%** (**+1.9**) | 93.6% → 93.9% (**+0.3**) | 1.56 → 1.63 |
| hosted `qwen-2.5-7b-instruct`, unquantised | 48 | 85.4% → 85.4% (**0.0**) | 81.2% → 76.0% (**−5.2**) | 1.43 → 1.62 |

> **goldenv3, 2026-08-28.** Re-scored from the saved answers against the corrected golden set —
> no model was re-run and nothing was paid for. Absolute attribution rises about **17 points**
> across every arm: the models were far better at citing than the eval said. The superseded
> goldenv2 figures were 65.3% → 56.7% (local), 76.3% → 76.5% (hosted `flash-lite`), 63.3% →
> 61.2% (hosted `qwen`). **`cited a golden page` is now saturated** for `flash-lite` +
> `rerank` at 100.0% and can no longer move.

Row 2 is not a typo: pinned to Google AI Studio through OpenRouter, `flash-lite` reproduces the
direct-endpoint run **to the digit**, and a repeat of it was byte-identical across all 69
answers in both arms. An unpinned OpenRouter run of the same model gave 93.6% → 93.9% as
94.6% → 93.8%, flipping the sign of the delta, because it was blended across deployments —
that difference was routing, not measurement error (gotcha 16). Its `served_by` field reads
`{Google: 38, Google AI Studio: 31}`, which is what identifies it as unpinned (gotcha 20).

Row 3 settles a confound in the local result. The local `qwen2.5:7b` runs through Ollama, which
serves a *quantised* copy — so "the model is weak" and "the compression hurt it" predicted the
same observation. Running the **same model family unquantised** reproduces the penalty in both
metrics, so the cause is the model, not Ollama. The magnitudes are smaller, especially precision
(−2.1 against −8.6), which suggests quantisation *amplifies* the effect without causing it.

Retrieval improved identically in every row — MRR 0.699 → 0.879, hit@1 56.7% → 81.7%.

### Why the two citation columns disagree

`cited a golden page` passes if **any** cited page is a golden one. So a model that cites more
sources gets more chances to pass it, and **reranking measurably makes models cite more**
(right-hand column, every row). The metric rewards that behaviour change whether or not
attribution improved.

Citation precision — *what fraction of the pages it cited were right* — removes that tailwind.
Applied to the hosted model, the entire apparent gain goes with it, twice, on two independent
serving paths. Applied to the local model, the damage is **larger** than the headline number
said, because it degraded *despite* the same tailwind.

### The golden set was incomplete, and correcting it moved every number

A completeness review on 2026-08-28 added target pages to **18 of the 60 answerable rows**. The
detector inverted the usual assumption: instead of asking whether the model cited the right
page, it collected every page the models cited that the golden set did *not* list, counted by
how many of the 13 committed generation runs cited it. A page cited by twelve of thirteen runs
across three model families is not one model hallucinating — it is a page the question author
forgot to list. Two rows were worse than incomplete: rows 35 and 66 listed a page that does not
contain the answer at all, and scored a guaranteed citation failure in **every** run.

**A prediction registered before the re-scoring, and lost.** The expectation was that the
correction would *compress* the precision gap, because reranking pulls more of these pages into
the window and so had more opportunity to be marked wrong. The opposite happened. Both arms
gained ~17 points, but `vector` gained more, so the penalty **widened**: −8.6 → −10.6 locally
and −2.1 → −5.2 on the unquantised hosted copy.

The mechanism, measured rather than assumed — *of the citations scored wrong under the old set,
what fraction turn out to be right under the corrected one?*

| | citations | scored wrong before | now correct | **recovery rate** |
|---|---|---|---|---|
| local `qwen` — `vector` | 70 | 31 | 18 | **58.1%** |
| local `qwen` — `rerank` | 77 | 39 | 15 | **38.5%** |
| `flash-lite` — `vector` | 81 | 29 | 21 | **72.4%** |
| `flash-lite` — `rerank` | 85 | 30 | 21 | **70.0%** |

When the dense-retrieval arm cited a page the eval called wrong, the eval was wrong 58% of the
time. When the reranked arm did, only 38%. **Reranking's mistakes were more often real
mistakes**, and the incomplete eval had been *flattering* reranking rather than penalising it.
On `flash-lite` both arms recover at the same rate, which is exactly why its delta did not move.

**A second, separable defect the review exposed: the old metric punished breadth.** Row 30's
`vector` answer cited five pages, every one of which states the rule asked for, and scored
**0.20** because four were unlisted. An answer citing one of those same pages scored **1.00**.
That is the precise inverse of the `citation_correctness` bias in gotcha 18 — one metric rewards
citing broadly, the other punished it — and the eval's incompleteness is what drove the second.
Treat both columns as having been unreliable in *opposite* directions before this correction.

> **A confound that was checked and turned out small.** Reranking also changes how many golden
> pages are in the window, not just where they rank — row 25 below goes from 1-of-5 golden to
> 4-of-5, and a model citing blindly from a 4-of-5 window scores ~80% precision on chance
> alone. Measured across all questions rather than that one, the window holds **1.10 → 1.19
> golden pages** on average, moving the chance baseline by **~1.7 points**. Real, and not
> material to the deltas above.
>
> Recorded because the check was worth running, and because an earlier version of this section
> reported it as a serious open defect on the strength of row 25 alone — which was generalising
> from one vivid example. Note also that this base rate is a property of the **retriever**, not
> the model: every model sees identical windows, so it cancels entirely from the multi-model
> comparison below and applies only to `vector`-vs-`rerank`.

> **Correction, 2026-08-27.** This section previously read *"It depends on the model, and that
> is the finding"*, reporting **−6.5 pts** for the local model and **+3.8 pts** for the hosted
> one, and concluded that a model which already attributes well converts a retrieval gain into
> an answer gain. The negative half of that survives and is slightly understated. **The
> positive half does not survive**: measured by precision, reranking did not improve the
> hosted model's attribution. The superseded numbers are kept visible rather than deleted,
> because how a result was corrected is part of the result.
>
> Two further caveats on the old figures. They were reported over **46** questions; the
> intersection of the two arms is verifiably **47**, and the 46 could not be reproduced from
> the repo — which is why the recomputation now lives in a script. And the hosted `+3.8` was
> only ever **two questions out of 52**, which the precision column is what makes visible.

### What reranking actually bought

Not attribution — refusals. The model declines less often when the evidence is genuinely
there, and this replicates on **every** pair:

| pair | refused despite evidence | denominator |
|---|---|---|
| local `qwen2.5:7b` | 16.4% → **10.3%** | 55 → 58 |
| hosted `flash-lite`, Google endpoint | 7.3% → **5.2%** | 55 → 58 |
| hosted `flash-lite`, OpenRouter pinned | 7.3% → **5.2%** | 55 → 58 |
| hosted `qwen-2.5-7b`, unquantised | 12.7% → **10.3%** | 55 → 58 |

The denominator grows in every row because that rate is conditioned on the golden page having
been retrieved at all (design decision 18), and reranking retrieves three more of them. So the
improvement is real on both counts: more questions have their evidence present, **and** a
smaller share of those get refused anyway.

The denominators moved 54 → 55 and 57 → 58 with the goldenv3 correction, because one more
question now has its evidence counted as retrieved in each arm. The rates are essentially
unchanged and the finding is untouched — unlike the citation metrics, this one barely felt the
eval correction, because it is conditioned on retrieval rather than scored against targets.

`must_contain` moved only on the local model, and downward — 93.3% → 86.2%, against 96.8% →
96.8% on both hosted pairs. **These figures are unaffected by the goldenv3 correction**: the
check runs against the model's answer text, not against target pages. Consistent with the citation result: the local model handles the
reranked window worse, the hosted model is indifferent to it.

### The sharpest version: reranking's gain is the retriever's, not the model's

Compare each model against a baseline you could ship in ten lines — **ignore the model's
citations entirely and always cite chunk `[1]`**. Its precision is just the rate at which
rank 1 is a golden page.

| | always-cite-`[1]` | model's precision | **model's lift** |
|---|---|---|---|
| local `qwen2.5:7b` — vector | 63.0% | 83.3% | **+20.3** |
| local `qwen2.5:7b` — rerank | **87.2%** | 72.7% | **−14.5** |
| hosted `qwen-2.5-7b` — vector | 61.7% | 81.2% | **+19.5** |
| hosted `qwen-2.5-7b` — rerank | **87.5%** | 76.0% | **−11.5** |
| hosted `flash-lite` — vector | 61.5% | 93.6% | **+32.1** |
| hosted `flash-lite` — rerank | **86.5%** | 93.9% | **+7.4** |

Under dense retrieval every model beats the trivial baseline clearly. **Under reranking that
added value collapses on all three** — to +7.4 on the hosted light model, and to *negative* on
both 7B models, where you would have gotten better citations by discarding their output and
citing the first chunk.

The mechanism is in the left column: it jumps ~25 points in every pair, because reranking's
achievement is putting the right chunk first (hit@1 56.7% → 81.7%). Note what did **not**
happen on `flash-lite`: its precision barely moved between arms (93.6% → 93.9%). Its lift
collapsed because **the bar rose**, not because the model got worse — which is the second
caveat below, now the dominant effect rather than a footnote. **Reranking's benefit is
realised by the retriever; the generator adds nothing on top of it,** and the weaker generator
gives some back.

Two caveats, both load-bearing:

- **This is precision only, and precision ignores coverage.** The local rerank model cites
  1.68 pages at 56.7% precision — 0.95 golden pages per answer — against the baseline's 0.77.
  It surfaces *more* correct pages, more noisily. Whether that is worse depends on whether a
  spurious citation costs more than a missing one, which is a product question, not a metric.
- **A shrinking lift can mean the baseline got good, not that the model got worse.** If
  reranking puts the right chunk at rank 1, a model citing rank 1 is being correct rather than
  lazy. These numbers cannot separate the two readings.

Comparing against a trivial baseline is standard practice rather than anything novel here — the
lead-3 baseline in summarization and popularity baselines in recommender systems are the same
discipline, and both exposed years of apparent progress that a ten-line heuristic matched.

### So the honest summary

Reranking is a large **retrieval** win (MRR +0.180) that converts into exactly one **answer**
win — fewer false refusals — and no measurable attribution win on either model. It actively
harms attribution on a small local model. "We added reranking and the system improved" remains
unsupportable; so, now, does "better retrieval helps models that already attribute well."

Whether a genuinely frontier model behaves differently is **untested** — `flash-lite` is a
light model, and that is the next measurement.

### The mechanism: reranking makes the context window harder to attribute within

This is what happens on the local model, and it does **not** appear on the hosted one — where
the only two questions that changed were pages `vector` missed entirely and `rerank` found.

Two questions had the golden page at **rank 1 in both runs**, so retrieval position was
identical and the only difference is the other four chunks:

```
row 44   vector: p.34* p.40  p.49  p.44  p.33   -> cited [1] = p.34*   CORRECT
         rerank: p.34* p.40  p.27  p.33  p.30   -> cited [4] = p.33    WRONG

row 25   vector: 1 golden page  + 4 unrelated   -> cited the golden one
         rerank: 4 golden pages + 1 non-golden  -> cited the NON-golden one
```

**A reranker makes the window homogeneous by construction.** It returns the five most
relevant chunks, and the most relevant chunks tend to be near-duplicates of each other:
adjacent pages of one section, restating one fact. Dense retrieval returns a scattered window
in which the right chunk stands out; reranking returns a tight cluster in which five chunks
all look like plausible sources. Row 25 is the sharpest case — reranking filled four of five
slots with *correct* pages and the model cited the one that was not.

So reranking raised the probability that evidence is present, and lowered the model's ability
to say which chunk it used.

### What reranking did buy: coverage

| | `vector` | `rerank` |
|---|---|---|
| questions answered | 47 | **52** |
| false abstention rate | 16.4% | **10.3%** |
| abstention recall (out-of-corpus) | **100%** | **100%** |

More evidence in the window means the model refuses less often, while still never answering
a question the corpus cannot support. That is a real improvement — it is simply **not the one
anyone would have predicted**, and it is only visible because retrieval and generation were
measured on separate axes.

### How much to trust this

Two models, one corpus, 46 and 52 questions head-to-head. Enough to show the effect is
**model-dependent**, not enough to say which models fall on which side without testing them.

The golden set was corrected mid-way — four rows gained target pages. Both local arms were
re-scored against the corrected set before the comparison above, and the fix moved both arms
identically (one row, for both), so it is not the source of the difference. The models are.

`citation_correctness` still partly measures golden-set completeness rather than model
behaviour, so treat every figure here as a **floor**.

**This replication contradicted an earlier version of this section, which reported the local
result alone and concluded that better retrieval does not produce better answers.** That
claim was too strong, and it is corrected above rather than quietly removed.

### Cost

Reranking takes retrieval from 26 ms to 3.3 s per query, which sounds fatal and is not:
generation on this machine is ~127 s per question, so the reranker adds about **2.5% to
end-to-end latency** in exchange for +0.180 MRR. On a hosted LLM that arithmetic reverses
and 3.3 s would dominate — worth stating, since the tradeoff is a property of the deployment,
not of the reranker.

That 3.3 s is also not a constant. The cross-encoder batches its 30 candidates and pads them
to the longest sequence present, so a pool of short chunks is genuinely cheaper than one
containing a 512-token chunk. An earlier measurement of the same configuration on a busy
machine read 6.1 s.

### Where the time actually goes

Ollama reports its own breakdown, and `src/generate.py` now captures it. Two diagnostic
samples, consistent:

| | prompt eval (prefill) | generation (decode) | model load |
|---|---|---|---|
| cold | **162.9 s** · 2,456 tok · 15.1 tok/s | 7.6 s · 30 tok · 3.9 tok/s | 10.0 s |
| warm | **161.3 s** · 2,547 tok · 15.8 tok/s | 9.1 s · 36 tok · 3.9 tok/s | 0.9 s |

**~95% of generation time is spent reading the prompt, before the model writes a word.**
Prefill is the *faster* phase per token (15 vs 3.9 tok/s); it dominates because there are
~80× more prompt tokens than answer tokens — five retrieved chunks in, one short cited
answer out.

The consequence is that **`k` is the primary latency parameter**, not just a quality one.
Capping `num_predict` harder would save nothing. And reranking earns a second dividend here:
hit@3 is 78.3% under dense retrieval and 95.0% after reranking, which makes a smaller `k`
defensible for the first time.

A query therefore costs about **2¼ minutes end to end** locally, which is measured,
reproducible, and not demoable. That is a property of running a 7B model on CPU, not of the
pipeline.

**The hosted backend confirms it** — the direction, not the magnitude. Against an
OpenAI-compatible endpoint generation stops being the bottleneck entirely and the cross-encoder
becomes the slowest component, which inverts every latency argument above. Set
`LLM_PROVIDER=openai` and `LLM_BACKEND=<name>` to switch; Ollama stays the default and remains
the only source of the prefill/decode split on identical hardware.

> **~~Against an OpenAI-compatible endpoint the same call takes ~0.5 s — 0.1 s prefill plus
> 0.4 s decode, measured.~~ Corrected 2026-08-31: that figure is not supported by any results
> file in this repo.** Generation p50 across every committed hosted run:
>
> | model | upstream | gen p50 | gen p95 |
> |---|---|---|---|
> | `gemini-3.1-flash-lite` via OpenRouter | Google AI Studio | 1,112 ms | 1,465 ms |
> | `gemini-3.1-flash-lite` via OpenRouter | Google AI Studio | 1,231 ms | 1,778 ms |
> | `gemini-3.1-flash-lite` via OpenRouter | unpinned | 1,448 ms | 2,637 ms |
> | `gemini-3.1-flash-lite` **Google direct** | — | 2,185 ms | 5,048 ms |
> | `gemini-3.1-flash-lite` **Google direct** | — | 3,978 ms | 7,251 ms |
> | `qwen-2.5-7b-instruct` | Phala | 1,247 ms | 2,979 ms |
>
> **The fastest committed run is 1,112 ms and nothing is near 500 ms**, so treat hosted
> generation as **~1–2 s**, not sub-second. The error was quoting a figure without re-deriving
> it from the results files, and it survived because it pointed the right way — generation
> really did stop being the bottleneck, so nobody checked the number that said so. It was
> found only when it was used as the basis of a deployment projection and the arithmetic
> mattered.
>
> **Two further things that table shows, neither of them good news for the demo.** The Google
> *direct* endpoint — the one chosen as the deployment backend — is the slowest hosted path
> here and by far the most variable, with a p95 of 5.0 and 7.3 s against OpenRouter-pinned's
> 1.5–1.8 s, on the same underlying model. And a three-question spot check on 2026-08-31 did
> **not** reproduce that gap (Google ~2.1 s, OpenRouter ~2.0 s), so the evidence conflicts and
> three questions cannot settle a p95. Google direct was chosen because its *outputs* are
> byte-identical to the pinned OpenRouter path; that was never a claim about latency, and it
> should not have been allowed to stand in for one. **Backend choice may reopen at D-2 on
> latency grounds.**

Two things learned running it that are not in the provider documentation:

- **The daily token cap is invisible.** Per-minute limits appear in response headers; the
  200,000 tokens/day cap appears **only in a 429 body**. Pacing against the headers cannot see
  it coming.
- **Every retry is a billed request**, so retrying through a rate limit burns several times a
  run's question count and drives `retry-after` from ~15 s to *hundreds* of seconds. Pacing
  proactively against the reported budget is strictly better than retrying reactively.

## Deployment measurements — what was verified before anything was hosted

The target is **Streamlit Community Cloud**, free tier. Everything below was measured
locally in containers, *before* anything was hosted, because each answer changes what
gets built. None of it is the host's own number: these are projections with a
measurement behind them rather than projections with reasoning behind them.

### Where it is hosted, and why not the obvious place

The plan named Hugging Face Spaces on the free CPU tier. That is no longer possible:

```
create_repo(space_sdk="streamlit")  ->  Invalid option: expected one of
                                        "gradio"|"docker"|"static" at sdk
create_repo(space_sdk="docker")     ->  402 Payment Required
                                        Static Spaces are free for everyone, but hosting
                                        Gradio and Docker Spaces on free cpu-basic
                                        requires a PRO subscription.
```

**The Streamlit SDK has been removed, and the remaining runnable SDKs need a paid plan.**
The Streamlit-SDK documentation page is still live and still describes selecting it, which
is how the wrong belief survived two rounds of work — see journal entry 31, which is about
ranking evidence rather than about Hugging Face.

Streamlit Community Cloud runs the full app, free, deployed straight from the GitHub
repository — no second repo, no sync step, no Git LFS. `Dockerfile` and `deploy_space.py`
are kept as the paid Hugging Face fallback, and the Dockerfile earns its place anyway: it
is what made every measurement in this section possible.

**Worth stating plainly, because it explains a constraint most RAG demos never meet.** This
app loads PyTorch, a 133 MB embedding model and a 90 MB cross-encoder into its own process.
A demo that calls an embeddings API and a hosted vector database is a ~100 MB Python process
and fits anywhere. The memory ceiling below is the price of the brief's zero-cost,
no-vendor-lock-in stack, not an accident.

### The memory ceiling, and the one parameter that moves it

Peak RSS through a realistic sequence, 2 vCPU, swap disabled:

| stage | peak RSS |
|---|---|
| baseline (interpreter only) | 11 MB |
| after startup — Chroma plus both models | 587 MB |
| after a `vector` query | 672 MB |
| after a `bm25` query (builds the lexical index) | 696 MB |
| after a `rerank` query | **1,169 MB** |

**Reranking is the memory cost, not the models sitting in memory.** One cross-encoder pass
adds 473 MB — over four times what the entire BM25 index costs. Under hard caps the app is
OOM-killed (exit 137) at both 768 MB and 512 MB, and both die at the *same step*, the first
rerank query. Everything up to and including BM25 survives even 512 MB, because those pages
are largely file-backed and evictable; reranking allocates anonymous memory that is not.

`CrossEncoder.predict` pads every batch to the longest sequence in it — recorded in gotcha 24
as a *latency* property, and it drives peak memory the same way. So batch size is the lever:

| batch | peak RSS | rerank | scores |
|---|---|---|---|
| 32 (library default) | 1,186 MB | 4,709 ms | `+5.1277 +3.2527 +2.7193 +2.2807 +1.1764` |
| 16 | 991 MB | 5,195 ms | identical |
| **8** | **876 MB** | **5,286 ms** | identical |
| 4 | 828 MB | 6,590 ms | identical |

**The scores are bit-identical at every batch size**, returning the same five pages in the
same order. Padding changes what is held in memory, not what the model computes — which is
what makes this a pure memory/latency trade and **not** a quality parameter, so setting it is
not tuning against the golden set. At the default the app is killed under a 768 MB cap; at 8
it survives with margin. That one variable is the difference between reranking being
available on free hosting and not being available at all.

`PMJAY_RERANK_BATCH` is **unset by default**, so the eval harness runs at the library's 32 and
reproduces every committed number exactly. The 8 is applied in `app.py`, the product layer.

### The environment that will run this reproduces every retrieval figure exactly

`requirements.txt` pins 9 direct dependencies; the environment that actually runs is
**111 packages**. The other 102 are chosen by pip at install time from whatever
satisfies the declared ranges *that day* — and four of them had already moved away
from the versions every published number was measured on:

| package | measured on (Windows venv) | Linux resolves today |
|---|---|---|
| `transformers` | 5.15.0 | **5.16.1** |
| `tokenizers` | 0.22.2 | **0.23.1** |
| `huggingface-hub` | 1.27.0 | **1.29.0** |
| `onnxruntime` | 1.28.0 | **1.29.0** |

`tokenizers` turns a question into the integer ids `bge-small` embeds and the
cross-encoder scores, and `transformers` owns the loading and pooling around it. So
this is the hot path, and the failure mode is silent — the Space would serve slightly
different retrieval from what this README describes, with nothing anywhere saying so.

**Measured instead of pinned around.** All four retrievers were re-run inside the
container against the live golden set and compared to the committed baselines:

| retriever | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| `vector` | 0.5667 = | 0.7833 = | 0.9167 = | 0.6994 = |
| `bm25` | 0.7000 = | 0.8333 = | 0.8667 = | 0.7658 = |
| `hybrid` | 0.6167 = | 0.8833 = | 0.9167 = | 0.7528 = |
| `rerank` | 0.8167 = | 0.9500 = | 0.9667 = | 0.8792 = |

**16 metrics, largest absolute difference 0.000000.** The drift is immaterial to
retrieval, and the lockfile therefore records an environment that was *proven
equivalent* rather than pinned defensively against a risk never demonstrated.

This also extends [design decision 17](#design-decisions--do-not-silently-reverse-these)
further than it was written. "Retrieval is byte-reproducible" was established across
days and process restarts on one machine; it now holds across **a different OS, a
different CPU, and four different library versions in the hot path**. It says nothing
about generation, and nothing about latency.

### Thread count is a deployment parameter, worth ~48% of reranked latency

`docker run --cpus=2` throttles CPU *quota* but does not change what the library sees:
`os.cpu_count()` reads the host, so torch sized its pool from 8 cores and chose 4
threads, which then contended for 2 cores' worth of time. That is not a 2-vCPU box, it
is a **worse** one. Four arms under the same budget, 20 questions each:

| mode | threads | retrieve p50 | p95 |
|---|---|---|---|
| `rerank` | torch default (4) | 7,615 ms | 8,120 ms |
| `rerank` | **pinned to 2** | **3,974 ms** | 4,242 ms |
| `vector` | torch default (4) | 109 ms | 182 ms |
| `vector` | **pinned to 2** | **39 ms** | 54 ms |

Pinning nearly halves reranked retrieval and cuts dense retrieval to a third. Same
code, same models, same CPU budget — the only change is not asking for more
parallelism than the container is allowed to deliver.

**So the deployed app sets it, from `PMJAY_TORCH_THREADS` (default 2), in `app.py`
only** — see design decision 32. Shipping without it would have cost ~3.6 s per query
on a machine with no visible defect, and the natural suspect would have been the
cross-encoder: the component *already known* to be slow, and therefore the one that
would have absorbed the blame. A performance bug hiding behind a legitimately
expensive component is close to undiscoverable by intuition.

### The resulting projection, and what it does not settle

```
                    retrieval   generation      end to end
rerank, 2 vCPU         4.0 s     1.2-2.2 s      5.2-6.2 s     ABOVE the ~5 s threshold
vector, 2 vCPU        0.04 s     1.2-2.2 s      1.2-2.2 s
```

Generation is the measured **1.2–2.2 s** band from the committed runs, not the ~0.5 s this
section originally claimed — see the correction above. An earlier version of this projection
read `~4.5 s end to end` for `rerank`, which put it just *under* the threshold; on the
corrected generation figure it lands *above*. **That is a real change of direction, and it came
from a documentation error rather than from any new measurement of the system.**

DEPLOYMENT.md projected "~20–30 s" for the reranker on free hosting, from reasoning alone. The
measured projection is still far better than that, and **partly for a reason that is
configuration rather than hardware** — see the thread-count finding above.

**This does not settle whether the demo defaults to `rerank` — but it now leans against
it.** Two of these cores under a cgroup quota are not two of a cloud provider's shared vCPUs;
there is no cold start, no network I/O and no noisy neighbour in the container. So D-2 decides.
What the corrected arithmetic changes is the direction of the prior: `rerank` is over the
threshold rather than under it, and if Google direct's committed p95 of 5–7 s is real, a
reranked p95 could approach 11 s, which is not a demo.

int8 ONNX quantisation is therefore back on the table where it previously was not. It would
cut the 4.0 s retrieval component, at the cost of a full re-baseline of all four retrievers —
quantisation can shift scores and that must be measured rather than assumed. Do not reach for
it before D-2 produces a real number.

### Cold start is ~26 s, and the download is not the reason

From a fully warm model cache under the 2-vCPU budget:

| | |
|---|---|
| `bge-small` load | 8.7 s |
| cross-encoder load | 9.9 s |
| **both ready, including the torch/sentence-transformers imports** | **25.8 s** |

The deployment plan's concern was the cross-encoder's ~90 MB download landing on one
unlucky visitor. That is real and is now moved into startup — but the **load** costs
more than the download, and no packaging choice removes it. It also weakens the case
for switching to the Docker SDK purely to bake weights into an image: doing so saves
the download and not the 26 s.

### The Chroma index travels

`chroma/` is written on Windows and read on Linux. Opened in a `python:3.12-slim`
container: collection `pmjay`, **872 chunks**, and the HNSW segment answered a query.
So the index does not need rebuilding on the host, which is what makes committing it
worthwhile — see [Re-indexing](#re-indexing) for the `skip-worktree` consequence.

## Layout

```
data/raw/              downloaded PDFs (gitignored)
data/processed/        pages.jsonl, chunks.jsonl (gitignored)
src/download.py        corpus fetch, browser UA + %PDF validation
src/inspect_corpus.py  text-native vs scanned triage
src/extract.py         PyMuPDF, one record per page
src/chunk.py           ~600-token windows, ~100-token overlap
src/index.py           BGE embeddings -> Chroma; model + query prefix live here
src/retrieve.py        vector / bm25 / hybrid RRF / cross-encoder rerank
src/generate.py        prompt assembly + LLM call; backend selected by LLM_BACKEND
config/prompts.yaml    versioned prompts
app.py                 Streamlit UI; sets torch threads, reads baselines from results
chroma/                committed index, hidden with skip-worktree (see Re-indexing)
requirements.txt       9 direct pins, incl. torch==2.13.0+cpu
requirements-lock.txt  the full 111-package closure, generated on Linux
Dockerfile             the deployed environment, reproducible locally; HF/container fallback
.dockerignore          keeps .venv, .git and .env OUT of the build context
deploy_space.py        Hugging Face fallback only -- not the active deployment path
Docs/SPACE_README.md   the Space landing card -- becomes README.md on the Space only
eval/golden_set.csv    hand-written questions, committed
eval/known_gaps.csv    written but unscorable (answer lives in an image)
eval/run_eval.py       scoring harness; --retrieval-only needs no LLM
eval/find.py           keyword lookup, for filling in page numbers
eval/diff_editions.py  where the two empanelment editions disagree
eval/backfill_provenance.py  adds question-set hash + served_by to older results files
eval/results/          one committed JSON per run
Docs/HANDOFF.md        authoritative status: what is done, half-done, and next
Docs/DEPLOYMENT.md     the original hosting plan; steps 1-5 are done
Docs/PMJAY-RAG-PROJECT.md  the original brief
Docs/empanelment-diff.md   where the two empanelment editions disagree
```

## Corpus provenance

The `nha.gov.in/img/...` URLs in the project brief **no longer serve PDFs.** The NHA
portal was rebuilt as a single-page app (redeployed 12 Aug 2026); those paths now return
the app shell as `HTTP 200 text/html`. Search engines still index the old URLs, so they
look alive until you check the bytes. The `%PDF` magic-byte check in `src/download.py` is
what caught this — a status-code check alone would have written eleven corrupt files.

Separately, `nha.gov.in` presents a certificate chain that Windows trusts but `certifi`
does not, so `requests` fails with `CERTIFICATE_VERIFY_FAILED: self-signed certificate in
certificate chain`. Fixed with `truststore`, which routes verification through the OS
trust store — rather than `verify=False`, which disables verification and would not have
helped anyway, since the URL was dead.

| Local filename | Source now used | Pages | Note |
|---|---|---|---|
| `operation_manual.pdf` | Kerala SHA | 32 | April 2022 edition |
| `hbp_2_2_manual.pdf` | `hem.nha.gov.in` | 64 | live |
| `stg_manual.pdf` | Wayback, 2025-02-14 | 35 | no live mirror found |
| `grievance_redressal.pdf` | PM-JAY CGRMS portal | 30 | live |
| `empanelment_dec2021.pdf` | NITI for States | 46 | December 2021, no version number printed |
| `empanelment_v2_0.pdf` | Kerala SHA | 64 | cover states "Version – 2.0" |
| `antifraud_guidelines.pdf` | UP Ayushman portal | 30 | live |
| `antifraud_guidebook_2024.pdf` | S3WaaS CDN | 164 | live |
| `field_investigation_manual.pdf` | Kerala SHA | 52 | live |
| `beneficiary_identification.pdf` | UP Ayushman portal | 16 | live |
| `fraud_analytics_rfe.pdf` | Wayback, 2025-10-18 | 108 | live capture, replay is rate-limited |

### The version-conflict pair was not a pair

The brief's premise is that two conflicting editions of the empanelment guidelines exist,
and that a naive system will cite the superseded one. The two files it names are:

- `Hospital-Empanelment-Guidelines-21-12-22.pdf`
- `Revised-Empanelment-and-De-empanelment-Guideline.pdf`

Both were fetched and hashed. **They are byte-identical** — sha256 `9B61270B…`, 1,481,305
bytes each. They are one document served under two filenames on `nha.gov.in`, and both are
the 46-page December 2021 edition. Indexing both would have added ~65 duplicate chunks,
skewed retrieval, and produced version-conflict eval cases that test a document against
itself. Only one copy is downloaded; see `src/download.py` for the reasoning.

The **genuine** conflict is between two different editions:

| | `empanelment_dec2021.pdf` | `empanelment_v2_0.pdf` |
|---|---|---|
| Pages | 46 | 64 |
| Self-declared version | none printed | "Version – 2.0" |
| Date on cover | December 2021 | not printed |
| Source | NITI for States | Kerala SHA |

Version 2.0 states its own version, which is stronger evidence than a date inferred from a
filename — but **which edition is currently in force is still unconfirmed**, and the whole
point of these test cases is knowing which rule is current. Settle it against NHA's own
circulars before writing the version-conflict questions; do not infer it from filenames,
which is precisely the mistake that produced the false pair above.

Retrieval does surface both editions: "minimum bed requirements for empanelment" returns
`empanelment_v2_0.pdf` p.40 and `empanelment_dec2021.pdf` p.30 at ranks 1 and 2.

### Corpus triage

All 11 PDFs are text-native — 1,184 to 2,627 characters per page. **No OCR is needed**,
which closes open question #1 in the brief. Verify with `python -m src.inspect_corpus`.

## Design decisions — do not silently reverse these

The permanent record of choices where a reasonable engineer could have gone the other way.
Each states what was chosen *over* what, because a decision without its alternative is an
assertion.

**Phase 1**

1. **Page numbers are captured at extraction and carried by every stage.** Citations are the
   point of the project and retrofitting page tracking is painful.
2. **Chunks never span a page boundary.** Every chunk carries exactly one page number, so a
   citation always points at a page that genuinely contains the text. Costs cross-page
   context — a paragraph running across a break is split in the index too — and buys
   guaranteed citation accuracy. Revisit only with evidence from the eval.
3. **The BGE query prefix is applied query-side only**, in `src/index.py:embed_query`.
   Applying it to documents too, or omitting it from queries, degrades retrieval *silently*.
   `retrieve.py` imports from `index.py` so the two sides cannot drift.
4. **Embeddings are L2-normalised and the Chroma space is cosine.** Chroma defaults to `l2`;
   mismatching them changes ranking with no error.
5. **Page numbers are physical position in the file** (`i + 1`), matching a PDF viewer's page
   counter — not the number printed on the page.
6. **No orchestration framework.** The retrieval loop is plain Python on purpose.
7. **`num_ctx` is 8192 on the Ollama call.** Five chunks of ~600 tokens overruns the 4096
   default, which truncates from the *front* and silently drops the sources.
8. **The golden set is anchored to `(source_file, page)`, never chunk IDs.** This is what lets
   the eval survive re-chunking, re-embedding and model swaps — without it, no Phase 2 number
   could be compared to the Phase 1 baseline.
9. **`must_contain` holds the smallest string that carries the fact** and is matched against
   the model's answer, not the page. See [What `must_contain` is for](#what-must_contain-is-for).
   **It is a floor, never a target** — optimising the prompt to raise it would push the model
   toward reciting source text verbatim, which is worse product behaviour.
10. **Retrieval metrics need no LLM** (`--retrieval-only`). Deliberate, and what makes CI
    possible later.
11. **Errored questions are excluded from generation metrics**, not counted as wrong. A network
    blip must never look like a quality regression.

**Phase 2**

12. **Fusion merges ranks, never scores.** A cosine similarity of 0.69 and a BM25 score of
    12.55 are on different scales; combining them numerically needs a normalisation step that
    is itself a tuned parameter. Positions are comparable without one.
13. **`RRF_K = 60` and `FUSION_DEPTH = 30` are left at published defaults, not tuned.** Tuning
    either against the 69 evaluation questions would be fitting a constant to the test set and
    reporting the fit as a measurement. If you ever tune them, say so here.
14. **The BM25 index is built from the Chroma collection, not from `chunks.jsonl`.** Makes it
    structurally impossible for the lexical and dense sides to search different corpora.
15. **The BM25 tokenizer keeps Indian-format numbers whole.** `\d[\d.,]*\d` before `[a-z0-9]+`,
    so `5,00,000` survives as one high-IDF token. Hyphens deliberately split, so "PM JAY"
    matches "PM-JAY".
16. **Tokenisation symmetry is per-retriever and opposite.** BM25 applies `tokenize()` to both
    query and corpus; BGE applies its prefix to the query only. Each is enforced inside one
    function so they cannot drift.
17. **Every ranking breaks ties on `chunk_id`.** BM25, RRF and reranking all sort by
    `(-score, chunk_id)`. Without it, two runs of identical code can report different numbers.
18. **Prompts live in `config/prompts.yaml` with a `version` field**, recorded in every
    generation results file. v1 is byte-identical to the `phase-1` tag, which is what keeps
    Phase 2 comparable to the baseline. The decline string is defined once and substituted into
    rule 3 via `{abstain}`, so the instruction and the string the eval matches cannot diverge.
    **Bump `version` on every edit.**
19. **`false_abstention_rate` is conditioned on the golden page having been retrieved.** Do not
    revert to the unconditioned form as the headline number.
20. **One build reaches every phase, by flag — no per-phase branches.** `--retriever vector`
    reproduces Phase 1 exactly, so today's code scores both phases with the *same harness*.
    This has to be actively preserved: it does not extend to prompts v2 (use `PMJAY_PROMPTS`),
    and cannot extend to re-chunking or an embedding swap, which force a full re-baseline.
21. **Results from a superseded golden set move to `eval/results/archive-<n>q/`, never
    deleted.** The JSON `label` does not record question count, so the folder does it, with a
    README naming what changed.
22. **`DEFAULT_MODE` stays `vector`** until generation evidence justifies changing it.
    Switching the product's default for unmeasured reasons is what this rules out.
23. **The rerank candidate pool is a parameter, and `hybrid` was chosen on LATENCY, not
    quality.** The union pool measures strictly better on coverage (98.3% vs 95.0% hit@5).
    Anyone reversing this should reverse it on latency evidence, not because they think hybrid
    retrieves better — it does not. **The quality case for hybrid got weaker again in
    2026-08-27:** on lay phrasing its large advantage over plain vector disappears entirely
    (0.941 → 0.461 against vector's 0.799 → 0.453), because RRF fuses in a BM25 arm that has
    effectively stopped working. ~~It scores *below* plain vector, 0.402 vs 0.443~~ — that
    stronger form was an artifact of scoring the two sets against different targets and did not
    survive re-scoring on 2026-08-29; the two are tied. **And again in 2026-08-28:** on
    the corrected golden set a BM25-only pool reaches **100%** recall at depth 30 while hybrid
    reaches 96.7%, and hybrid is now the only pool that fails to reach every golden page.
    Hybrid's remaining justification is entirely latency. Two counterweights before acting on
    this: the BM25 evidence is golden-set evidence and the paraphrase set inverts it; and the
    lay-phrasing claim above was itself *overstated* before re-scoring — hybrid does not fall
    below plain vector, it ties it.
24. **Losing arms stay reachable by flag, never deleted.** `rerank-bm25` and `rerank-union` both
    lost and both remain modes. A results file naming a mode that no longer exists is
    unreproducible archaeology.
25. **`hit["score"]` is labelled with what it actually is, from one definition.** `SCORE_LABELS`
    in `src/retrieve.py` maps mode to `cosine` / `bm25` / `rrf` / `ce logit`. A bare "score" of
    0.86, 7.73 and 0.032 invites a comparison that means nothing.
26. **Citation markers are stripped before the `must_contain` comparison, and only there** —
    after `parse_citations`, substituting a SPACE so "the fee [3] is 48" cannot fuse. The raw
    answer is still what gets saved.
27. **The results `config` block records the LLM, and `null` on retrieval-only runs.** Naming a
    model that had no influence would be worse than naming none.
28. **The serving provider is recorded on every hosted run (`served_by`), and pinning is
    optional.** An aggregator resolves one model id to several deployments and picks per
    request. Recording is unconditional; pinning is opt-in, because a pinned provider going
    down should fail the run loudly rather than swap deployments mid-benchmark.
29. **Results are saved BEFORE the report is printed.** A formatting bug in the report once
    destroyed two completed, paid-for 69-question runs. Answers are expensive and
    unrecoverable; a printed table can be regenerated from the file at any time.
30. **The cross-encoder has a 512-token window and chunks target ~600 tokens**, so the tail of
    a long chunk is invisible to the reranker. Stated rather than worked around: re-chunking to
    fit would change the indexing the Phase 1 baseline was measured against.


**Deployment**

31. **`chroma/` is committed, and hidden from git with `skip-worktree`.** Chosen over
    committing `chunks.jsonl` and rebuilding at startup, which would cost 30–60 s on
    every wake of a sleeping Space. The cost is that *opening* the collection rewrites
    the sqlite file and the HNSW segment, so without the flag every run leaves a
    15.7 MB binary looking modified and one `git add -A` bloats history permanently.
    The flag hides a genuine re-index too, which is why `src/index.py` prints the
    un-hide steps on completion — the instruction lives in the output of the command
    that creates the situation, not only in a document. See [Re-indexing](#re-indexing).
32. **`torch.set_num_threads` is set in `app.py`, from an env var, and NOT in
    `src/retrieve.py`.** Every committed evaluation number was measured under torch's
    default threading; setting it inside the pipeline would silently re-baseline the
    whole project. It is a property of the deployed product, not of the retriever.
    An env var (`PMJAY_TORCH_THREADS`, default 2) rather than a hardcoded 2, because
    the value that is right for a 2-vCPU host is wrong for an 8-core development
    machine and hardcoding would quietly tax local use. `0` leaves torch alone.
33. **The hosted backend is selected by one name, `LLM_BACKEND`, with every setting
    read from a `<BACKEND>_*` prefix.** Chosen over a single `OPENAI_*` group with the
    key resolved by hostname. Both alternatives were built and discarded: a
    non-endpoint-aware key can be sent to the wrong vendor, and endpoint-matched keys
    still leave the URL and model as separate settings that must move together. One
    prefix makes both mismatches unrepresentable, and keeps the vendor list in `.env`
    rather than in code — adding a provider is configuration with no code change.

34. **`PMJAY_RERANK_BATCH` defaults to UNSET, and the deployment sets 8.** The library
    default of 32 is what every committed evaluation number was measured under, and leaving
    it untouched in the pipeline is what keeps those numbers reproducible. The product needs
    8 to survive a 1 GB host. Adopting it required first proving it is not a quality
    parameter: scores are bit-identical at 32, 16, 8 and 4. **If a future model makes scores
    move with batch size, this stops being free and must be re-measured and disclosed.**
35. **Hosting is Streamlit Community Cloud, chosen after Hugging Face Spaces became
    unavailable on a free tier**, not on preference. Kept over the alternatives (paying for
    HF PRO, Google Cloud Run, a static precomputed page) because it runs the *same* stack
    from the same `requirements.txt`, so every published number still describes what is
    deployed — the same reason the anti-goals rule out AnythingLLM and Open WebUI.
36. **`app.py`'s boot order is load-bearing and documented as such.** Secrets are bridged from
    `st.secrets` into `os.environ`, then thread and batch defaults are set, and only then are
    `src` modules imported — because they read their settings at import time and one of them
    pulls torch. Moving an import above that block disables the settings silently, with no
    error and no signal beyond the app being slower or dying under memory pressure.

## Gotchas — each of these cost hours

**Corpus and environment**

1. **The brief's `nha.gov.in` URLs are dead.** The portal became a single-page app; those paths
   return the app shell as `HTTP 200 text/html`. The `%PDF` magic-byte check in
   `src/download.py` is what caught it.
2. **TLS:** `nha.gov.in` presents a chain Windows trusts but `certifi` does not. Fixed with
   `truststore`, which uses the OS trust store — **not** `verify=False`.
3. **The brief's "two conflicting empanelment editions" are byte-identical** — one document
   under two filenames, same sha256. See [the version-conflict pair](#the-version-conflict-pair-was-not-a-pair).
4. **`empanelment_v2_0.pdf` contradicts itself** — show-cause response is 5 working days on
   p.29 and 3 on p.34. Genuine test material.
5. **`field_investigation_manual.pdf` also contradicts itself** — the mortality report is
   "within 48 hrs" on p.35 and "within 7 days" on p.17. Found because two stronger models
   flagged it unprompted while a lighter one did not.
6. **Some values live inside images.** Four questions moved to `eval/known_gaps.csv` because the
   answer is not in the extracted text at all. `src/inspect_corpus.py` cleared all 11 PDFs as
   text-native because it measures *average characters per page*, which cannot see an image
   table on a text-heavy page. **Document-level triage is not content-level coverage.**
7. **Use `.venv\Scripts\python.exe` explicitly.** System `python` is 3.13 and has none of the
   dependencies. `ModuleNotFoundError: chromadb` almost always means the wrong interpreter.
   **The exception, which cost time twice in one session:** a script run from *outside* the
   project tree fails identically for a different reason — Python seeds `sys.path` from the
   script's directory, not the working directory, so `import src...` fails even under the
   right interpreter. Fix with `sys.path.insert(0, os.getcwd())`. A heuristic that is usually
   right is most dangerous on the occasion it is not, because it gets trusted without
   re-deriving it.
8. **Windows console is cp1252** and crashes on non-encodable characters; entry points
   reconfigure stdout with `errors="replace"`.
9. **CSV values containing commas must be quoted** (`"4,500"`). One unquoted value shifted a
   whole row and put the filename in the `page` column.
10. **`grep` buffers when piping to a file**, so a backgrounded run appears to produce no output.
    Use `python -u`. Piping also **replaces the exit code with grep's**, which once masked a
    hard crash as `exit 0`.

**Measurement**

11. **Latency must be measured after a warmup call to both stages**, or the embedding load (~5s)
    and the model load land entirely on question 1.
12. **Ollama evicts an idle model after 5 minutes.** Mid-eval that meant a ~2.5 min cold reload
    that blew a 300s timeout. Fixed with `keep_alive: "30m"`; `gen_stats["load_ms"]` exposes it.
13. **A machine that sleeps mid-run silently corrupts latency numbers.** One question logged
    3,051 s of prompt eval at 0.76 tok/s against the usual ~15, purely from a suspend. Locally
    the tell is that only *one* phase inflates. **Hosted endpoints report no phase split, so a
    suspend leaves no signature at all** — prevention, not detection: `powercfg /change
    standby-timeout-ac 0`.
14. **Re-running the same questions gives fake prefill numbers — Ollama caches prompts.** A
    repeat run reported 10,392 tok/s against the true ~15. **Prefill numbers from any repeat run
    are worthless.**
15. **Local generation IS reproducible — but only from a cold model.** Unload before any run you
    will compare; three fixed questions produced byte-identical answers across two cold passes.
16. **Hosted reproducibility is PROVIDER-DEPENDENT — measure it, do not assume it either way.**
    Measured 2026-08-27 by running the same configuration twice:

    | setup | result |
    |---|---|
    | `gemini-3.1-flash-lite` pinned to Google AI Studio | **0 of 69 answers differ** — byte-identical, both arms |
    | `qwen-2.5-7b-instruct` pinned to Phala | ~2 pts drift on citation metrics, 6.7 on `must_contain` |
    | `gemini-3.1-flash-lite` **unpinned** | **19 of 69 answers differ** from the pinned run |

    So `temperature: 0` *can* give byte-identical hosted output — but only on a provider whose
    serving stack is deterministic, and only when pinned. **The dominant source of variance is
    provider blending, not floating-point nondeterminism**: unpinned, one model id is served by
    several deployments picked per request (decision 28).

    An earlier version of this entry claimed hosted runs are never reproducible and quoted a
    ~2-point noise floor. That generalised one provider's behaviour to all of them. The right
    procedure is to **pin, then run the same configuration twice and diff the answers** before
    trusting any small delta.
17. **A single-digit `must_contain` can pass on a citation marker.** `must_contain: 5` matched an
    answer citing `[5]` that never stated the figure. Fixed by design decision 26.
18. **`citation_correctness` is an ANY-match and rewards citing broadly.** It cancels when
    comparing one model against itself and does *not* cancel across models. Read
    `citations_per_answer` and `citation_precision` beside it — see
    [Why the two citation columns disagree](#why-the-two-citation-columns-disagree).
19. **A golden-set edit propagates to some results and not others — asymmetrically.** When the
    set gained four rows on 2026-08-25, the *generation* numbers followed automatically, because
    `eval/citation_companions.py` re-scores from saved answers against the current set. The
    *retrieval* table did not, because no equivalent re-scorer existed, and it stayed goldenv1
    for three days without anything warning about it. It cost nothing that time — re-scoring
    later showed v1 → v2 moved retrieval by **exactly zero** on all four retrievers — but the
    asymmetry is the trap: half your numbers silently track the eval and half silently don't.
    Retrieval results files save their candidate lists, so any past run can be re-scored against
    any golden version without re-running it.
20. **A results file's `label` is a human-typed claim; `served_by` is data.** Two runs labelled
    `openrouter-…` were assumed pinned on the strength of the label. They were not: `served_by`
    across their 69 cases reads `{Google: 38, Google AI Studio: 31}` — **blended mid-run**,
    while the genuinely pinned runs read `{Google AI Studio: 69}`. A provider set of size > 1
    *is* the definition of an unpinned run and needs no answer-diffing to establish. Design
    decision 28 recorded exactly the right field; the mistake was reading the label instead of
    it. The golden-set version has no such field yet, and with three versions live it is the
    next thing to make self-describing.
21. **Errors shrink the sample silently.** Excluded questions (decision 11) mean a run over 61
    questions looks like a run over 69. One archived file has metrics computed over 17 of 69 and
    looked entirely normal. Always report the denominator.

**Retrieval**

22. **In `hybrid` and `rerank` modes, `hit["score"]` is no longer a similarity.** It is an RRF
    score (~0.03) or a cross-encoder logit (unbounded, often negative). Anything thresholding or
    comparing `score` across modes breaks silently.
23. **`CrossEncoder.predict` defaults to `batch_size=32`.** Depth ≤32 is one batch; 33–63 costs
    two, the second mostly padding. If you raise `FUSION_DEPTH`, go to 64, not 40.
24. **Reranking latency varies with chunk length, not just candidate count** — batches pad to the
    longest sequence present, so one 512-token chunk makes every chunk in that batch cost 512.
25. **`src.retrieve`'s CLI shows only the first 400 characters of a ~2,400-character chunk**,
    which makes correct retrieval look wrong. Not yet fixed.

## Anti-goals — from the brief

- **Do not generate eval questions with an LLM.** The golden set is hand-written and
  hand-verified. Scoring LLM-written questions with an LLM judge measures the model agreeing
  with itself.
- Do not add hybrid retrieval or reranking without recording the baseline first (done).
- Do not adopt a heavy orchestration framework.
- Do not drop page-number tracking anywhere in the pipeline.
- Do not start multilingual work until English is measured and working.
- **Do not tune hyperparameters against the golden set** without saying so. `RRF_K`, fusion
  depth and `k` are all currently untuned, which is a claim worth being able to make.

## Early observation to test in the eval

For "What is the annual health cover per family under PM-JAY?", the chunk that actually
states `Rs. 5,00,000` came back at **rank 5**; ranks 1–4 were topical scheme introductions
that never state the figure. The answer was still correct and both its citations checked
out, but dense retrieval clearly ranked *aboutness* above *answerhood* here.

That is a concrete, falsifiable prediction for what the Phase 2 reranker should fix — worth
writing eval questions that target it, and worth recording the baseline number before
touching retrieval.

**Resolved.** That question is golden row 25. Dense retrieval alone never surfaced the page
stating `5,00,000` within the top 5; BM25 put it at rank 1, and after reranking it sits at
rank 1. The prediction held: the failure was ranking *aboutness* above *answerhood*, and a
cross-encoder — the only component that reads the question and the passage together — is
what fixed it.

## Status

Phase 1 complete. Phase 2 retrieval complete and measured. Phase 2 generation measured on
**three models** — local `qwen2.5:7b`, hosted `gemini-3.1-flash-lite`, and hosted
`qwen-2.5-7b-instruct` — across both retrieval arms.

**Done**

- Hybrid BM25 + vector retrieval with reciprocal rank fusion
- Cross-encoder reranking, measured one change at a time against a recorded baseline
- Candidate-pool comparison — three pools measured, choice made on latency and disclosed
- `eval/pool_recall.py`, so the pool-recall claims are reproducible rather than ad hoc
- Prompts in a versioned `config/prompts.yaml`
- All six retrieval modes reachable from `app.py` and `python -m src.generate`, not just the
  eval harness
- Generation runs on the 69-question set for both `vector` and `rerank`, local model
- Generation latency broken down into prefill and decode
- Provider abstraction: local Ollama or any OpenAI-compatible endpoint, by env var
- **Paraphrase set re-scored against goldenv3 (2026-08-29)**, after syncing the three of its 17
  rows whose targets the completeness review had left behind
- **Run provenance is recorded rather than asserted** — every results file now carries a content
  hash of the question set that scored it, the deployments that actually served it, and a
  `descriptor` composed from those fields. All 39 historical files backfilled from data already
  on disk (`eval/backfill_provenance.py`)
- **Golden-set target completeness review (2026-08-28)** — 18 of 60 answerable rows gained
  target pages, two of which had listed a page not containing the answer. Every published
  retrieval and citation figure re-measured against the corrected set, from saved data, at no
  cost. See [the completeness review](#the-golden-set-was-incomplete-and-correcting-it-moved-every-number).

**Deployment: D-1 (pre-flight) complete, nothing hosted yet.** Verified in a clean
Linux container rather than asserted — CPU-only torch resolvable from
`requirements.txt` alone, the Chroma index travelling Windows to Linux intact, and
the dependency drift measured immaterial to all four retrievers. Two findings the
plan did not anticipate: thread count is worth ~48% of reranked latency on a 2-vCPU
budget, and cold start is ~26 s of model loading regardless of packaging. See
[Deployment measurements](#deployment-measurements--what-was-verified-before-anything-was-hosted).

**Not yet built**
- The public deployment itself, on Streamlit Community Cloud. One decision stays open
  until it is measured on the real host: whether the demo defaults to `vector` or
  `rerank`. Three independent lines of evidence currently favour `vector` — reranking
  costs ~6.3–7.8 s end to end against a ~5 s threshold, needs ~470 MB more memory, and
  showed no citation-precision gain on any model tested. `rerank` stays selectable.
- int8 ONNX quantisation, which would cut the retrieval half of that latency at the cost
  of re-baselining all four retrievers. Not needed unless the deployed number is worse
  than the projection.
- Prompt v2, targeting the false-abstention weakness, A/B'd against v1 with nothing else changed
- Handling of the empanelment version conflict, which reranking makes worse rather than better
- Faithfulness measurement — see the note under [Why these metrics](#why-these-metrics);
  it is deliberately unscored, which leaves a brief deliverable consciously open
- Public deployment — planned in [Docs/DEPLOYMENT.md](Docs/DEPLOYMENT.md)
- CI running the eval per PR

**Four times the measurement was the bug, not the system**

Each would have produced a confident, plausible, wrong number:

- A `must_contain` check for the figure `5` **passed** on an answer that only cited `[5]` and
  never stated the value. Citation markers are now stripped before the comparison.
- A hosted model cited with the CJK brackets `【1】` and later with `【1†L1-L3】`; the citation
  regex matched neither, so **every answer parsed as uncited and citation correctness would
  have read 0%**. The same model used ASCII brackets on some prompts, so sampling a few calls
  would not have caught it.
- "13 of 14 citation failures had the evidence retrieved" was reported as a finding. It is the
  base rate — 51 of 52 answered questions had the evidence retrieved. Always compare a rate
  against its base rate before calling it a result.
- A documented **reranker failure mode** — "adjacent pages crowd each other out", with a worked
  example naming four page numbers — was an eval failure. All four pages answered the question;
  the golden set listed one. The retracted paragraph is kept in place above.

**Honest position on the headline number.** The +0.180 MRR is measured in-sample: 69
hand-written questions serving as both development and test set, with no held-out split,
where a single question moves the hit rate by two points. It is also measured against a golden
set that was **corrected by its own author after seeing which pages the models cited** — a
defensible correction, verified page by page against the source text, but not an independent
one. No hyperparameter was tuned
against it — `RRF_K`, fusion depth and `k` are all at inherited defaults — but one
architecture choice (feeding the reranker the fused pool) was made by reading test-set
recall. Treat **+0.180** as an upper bound rather than an expected production figure.

And note what the generation runs did to that number's significance: **the +0.180 did not
translate into better answers at all.** A retrieval gain is not a system gain, and this README
would have claimed one if the generation runs had never been done.

## Acknowledgment

Source documents are Government of India publications from the National Health Authority
and state health agencies, used here for a non-commercial portfolio project.
