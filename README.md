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
improved retrieval by 24% in MRR. It reduced false refusals on every model tested — and
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

# CPU-only torch FIRST, or pip pulls the ~2.5 GB CUDA build as a
# sentence-transformers dependency
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

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
Copy `.env.example` to `.env` (gitignored) and fill it in:

```powershell
# local, the default and the baseline
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b

# or any OpenAI-compatible endpoint
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=openai/gpt-oss-120b
GROQ_API_KEY=...
```

Only the base URL and model name change between providers, so switching is configuration
rather than code. **A hosted model is a different model** — never compare a hosted number
against a local one and attribute the difference to retrieval. Every results file records
`llm_provider` and `llm_model` so no run is ambiguous about what produced it.

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

**It is also known to be incomplete in places.** One row listed a single page for a fact
stated on two; the model answered from the unlisted page, cited it, and scored as a citation
failure — the model was right and the golden set was wrong. Four rows have since gained
targets. `citation_correctness` below should therefore be read as a **floor**.

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
| `vector` — dense only (Phase 1 baseline) | 48.3% | 71.7% | 90.0% | **0.624** | 26 ms |
| `bm25` — keyword only | 58.3% | 78.3% | 81.7% | **0.677** | 2 ms |
| `hybrid` — RRF of the two | 51.7% | 81.7% | 86.7% | **0.671** | 29 ms |
| `rerank` — hybrid top-30, cross-encoder | **71.7%** | **85.0%** | **95.0%** | **0.795** | 3,269 ms |
| **change vs baseline** | **+23.4 pts** | **+13.3 pts** | **+5.0 pts** | **+0.171** | ×126 slower |

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
| mean overlap | **78.1%** |
| median | 83.3% |
| questions reusing **every** content word from their target page | **15 of 60** |

Then the paired test: the 17 highest-overlap questions rewritten in lay language, keeping the
same facts and the **same target pages**, so retrieval is the only thing that can move. Rewrites
were drafted from the question and the human-written expected answer — never from page text —
and hand-reviewed (`eval/make_paraphrases.py`). Mean overlap fell 97.9% → 34.6%.

| retriever | MRR original | MRR lay phrasing | change | hit@1 |
|---|---|---|---|---|
| `vector` | 0.789 | 0.443 | −44% | 64.7% → 29.4% |
| `bm25` | **0.941** | **0.144** | **−85%** | 88.2% → **5.9%** |
| `hybrid` | 0.912 | 0.402 | −56% | 82.4% → 29.4% |
| `rerank` | 0.971 | **0.590** | **−39%** | 94.1% → 52.9% |

**The ranking inverts.**

```
original wording:   rerank 0.971  >  bm25 0.941  >  hybrid 0.912  >  vector 0.789
lay wording:        rerank 0.590  >  vector 0.443  >  hybrid 0.402  >  bm25 0.144
```

BM25 goes from second to last, finding the right page first in **1 of 17 questions**. Vector
goes from last to second. Both outcomes were **pre-registered before the run**: that BM25's lead
would shrink if the bias was real, and that reranking would degrade least because a
cross-encoder reads question and passage together. The first held far more strongly than
"shrink" anticipated.

Three consequences:

- **The +0.171 MRR headline above is measured on favourable phrasing.** Treat it as an upper
  bound. The four-retriever table is not wrong, but it answers "which retriever wins on
  questions phrased like the documents", which is not the question a deployed system faces.
- **Hybrid inherits the weakness.** At 0.402 it falls *below* plain vector, because RRF is
  fusing in a retriever that has stopped working.
- **Everything degrades sharply.** Even the best retriever loses 39%. That is a product finding
  independent of BM25: this system is brittle to phrasing, and the eval set as originally
  written could not have shown it.

**Two caveats, both meaning this is an upper bound on the effect.** The 17 rows were selected as
the *highest-overlap* in the set (97.9% mean against 78.1% set-wide), so they are where the bias
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
| `hybrid` — RRF of both, cut to 30 | 71.7% | 85.0% | 95.0% | 0.795 | 2.0 s | 96.7% |
| `bm25` — BM25 top 30 | **73.3%** | 86.7% | 95.0% | **0.808** | 3.7 s | 98.3% |
| `union` — both lists, deduped (~50) | 71.7% | 86.7% | **98.3%** | 0.806 | 6.7 s | **100%** |

**`hybrid` was kept, on latency, not on quality.** It loses the coverage comparison — 95.0%
against the union's 98.3% hit@5 — and the target is a public demo on free hosting where the
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

**BM25 alone beat the embeddings.** Not the expected result. On MRR (0.677 vs 0.624) and
hit@1 (58.3% vs 48.3%) a bag-of-words scorer with no semantics outperformed
`bge-small-en-v1.5`, at a thirteenth of the latency. It loses on hit@5 (81.7% vs 90.0%):
when BM25 misses it misses completely, whereas dense retrieval degrades gracefully. The
corpus explains it — these are government manuals full of rare, exact tokens (`HWCs`,
`PAN card`, `5,00,000`, `HBP 2.2`) that a 384-dimension embedding blurs together and an IDF
term rewards precisely.

**Fusion made hit@1 worse.** RRF dropped rank-1 accuracy to 51.7%, below BM25's 58.3%, while
lifting hit@3 to 81.7%. That is the mechanism working as designed rather than a bug: RRF
rewards chunks both retrievers agree on, so a chunk one retriever ranks first and the other
never returns gets pushed down. Taken as a final ranker, fusion is a poor trade here.

It was kept because it is meant to be a **candidate generator** for the reranker, not a final
ranker — and on that job the honest current answer is that **it is losing to BM25 alone**:

| Pool for reranking | recall@5 | recall@10 | recall@20 | recall@30 |
|---|---|---|---|---|
| `vector` | 90.0% | 90.0% | 95.0% | 96.7% |
| `bm25` | 81.7% | 86.7% | 95.0% | **98.3%** |
| `hybrid` | 86.7% | 95.0% | 96.7% | 96.7% |

A reranker can only reorder what it is handed, so pool recall is its hard ceiling — and BM25
alone reaches more golden pages by depth 30 than the fused pool does. On an earlier
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
0.624 → 0.795 and hit@1 rose 23 points.

### A claim that did not survive a bigger question set

An earlier 56-question version of this set produced `hit@5 = 100%` and `recall@20 = 100%`
for the fused pool. Both figures dropped when eleven questions were added — to 95.0% and
96.7%. The perfect scores were artefacts of the smaller set, and losing them is a useful
correction rather than a regression: they were the numbers most likely to be flattering, and
they were being used to justify an architecture choice that the larger set now contradicts.

### Where retrieval fails completely: glossary pages

Two questions have their golden page absent from the candidate pool entirely, and they are
the same kind of question — an acronym answered by an abbreviations table.

- `DDO` appears on **exactly one page of the whole corpus** — the glossary — and dense
  retrieval still does not surface it at all.
- `CSC` appears on 15 pages. All five golden targets are glossary pages; the fifteen
  competitors are pages that *use* the term, and they win.

**A glossary entry mentions a term once, in a list, with no explanatory context.** Both
retrievers systematically prefer pages that discuss a term over the page that defines it, and
no amount of reranking fixes it, because the cross-encoder never sees the page.

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

**Adjacent pages of the same document crowd each other out.** Row 30's top five are
`grievance_redressal.pdf` pages 23, 24, 22, 25 and — fifth — the golden page 16. Appeal
timelines recur across that whole chapter.

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
| local `qwen2.5:7b` | 47 | 78.7% → 72.3% (**−6.4**) | 65.3% → 56.7% (**−8.6**) | 1.52 → 1.68 |
| hosted `gemini-3.1-flash-lite`, Google endpoint | 52 | 90.4% → 94.2% (**+3.8**) | 76.3% → 76.5% (**+0.2**) | 1.56 → 1.63 |
| hosted `gemini-3.1-flash-lite`, OpenRouter **pinned** | 52 | 90.4% → 94.2% (**+3.8**) | 76.3% → 76.5% (**+0.2**) | 1.56 → 1.63 |
| hosted `qwen-2.5-7b-instruct`, unquantised | 48 | 77.1% → 72.9% (**−4.2**) | 63.3% → 61.2% (**−2.1**) | 1.43 → 1.62 |

Row 2 is not a typo: pinned to Google AI Studio through OpenRouter, `flash-lite` reproduces the
direct-endpoint run **to the digit**, and a repeat of it was byte-identical across all 69
answers in both arms. An unpinned OpenRouter run of the same model gave 76.3% → 76.5% as
77.3% → 76.5%, because it was blended across deployments — that difference was routing, not
measurement error (gotcha 16).

Row 3 settles a confound in the local result. The local `qwen2.5:7b` runs through Ollama, which
serves a *quantised* copy — so "the model is weak" and "the compression hurt it" predicted the
same observation. Running the **same model family unquantised** reproduces the penalty in both
metrics, so the cause is the model, not Ollama. The magnitudes are smaller, especially precision
(−2.1 against −8.6), which suggests quantisation *amplifies* the effect without causing it.

Retrieval improved identically in every row — MRR 0.624 → 0.795, hit@1 48.3% → 71.7%.

### Why the two citation columns disagree

`cited a golden page` passes if **any** cited page is a golden one. So a model that cites more
sources gets more chances to pass it, and **reranking measurably makes models cite more**
(right-hand column, every row). The metric rewards that behaviour change whether or not
attribution improved.

Citation precision — *what fraction of the pages it cited were right* — removes that tailwind.
Applied to the hosted model, the entire +3.8 point gain goes with it, twice, on two independent
serving paths. Applied to the local model, the damage is **larger** than the headline number
said, because it degraded *despite* the same tailwind.

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
| local `qwen2.5:7b` | 14.8% → **10.5%** | 54 → 57 |
| hosted, Google endpoint | 7.4% → **5.3%** | 54 → 57 |
| hosted, via OpenRouter | 7.4% → **5.3%** | 54 → 57 |

The denominator grows in every row because that rate is conditioned on the golden page having
been retrieved at all (design decision 18), and reranking retrieves three more of them. So the
improvement is real on both counts: more questions have their evidence present, **and** a
smaller share of those get refused anyway.

`must_contain` moved only on the local model, and downward — 93.3% → 86.2%, against 96.8% →
96.8% on both hosted pairs. Consistent with the citation result: the local model handles the
reranked window worse, the hosted model is indifferent to it.

### The sharpest version: reranking's gain is the retriever's, not the model's

Compare each model against a baseline you could ship in ten lines — **ignore the model's
citations entirely and always cite chunk `[1]`**. Its precision is just the rate at which
rank 1 is a golden page.

| | always-cite-`[1]` | model's precision | **model's lift** |
|---|---|---|---|
| local `qwen2.5:7b` — vector | 54.3% | 65.3% | **+10.9** |
| local `qwen2.5:7b` — rerank | 76.6% | 56.7% | **−19.9** |
| hosted `flash-lite` — vector | 51.9% | 76.3% | **+24.4** |
| hosted `flash-lite` — rerank | 75.0% | 76.5% | **+1.5** |

Under dense retrieval both models beat the trivial baseline clearly. **Under reranking that
added value collapses on both** — to +1.5 on the hosted model, and to *negative* on the local
one, where you would have gotten better citations by discarding its output and citing the first
chunk.

The mechanism is in the left column: it jumps ~23 points in both pairs, because reranking's
achievement is putting the right chunk first (hit@1 48.3% → 71.7%). **Reranking's benefit is
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

Reranking is a large **retrieval** win (MRR +0.171) that converts into exactly one **answer**
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
| false abstention rate | 14.8% | **10.5%** |
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
end-to-end latency** in exchange for +0.171 MRR. On a hosted LLM that arithmetic reverses
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
hit@3 was 73.5% in Phase 1 and is 89.8% now, which makes a smaller `k` defensible for the
first time.

A query therefore costs about **2¼ minutes end to end** locally, which is measured,
reproducible, and not demoable. That is a property of running a 7B model on CPU, not of the
pipeline.

**The hosted backend confirms it.** Against an OpenAI-compatible endpoint the same call takes
**~0.5 s** — 0.1 s prefill plus 0.4 s decode, measured. Generation stops being the bottleneck
entirely and the cross-encoder becomes the slowest component, which inverts every latency
argument above. Set `LLM_PROVIDER=openai` to switch; Ollama stays the default and remains the
only source of the prefill/decode split on identical hardware.

Two things learned running it that are not in the provider documentation:

- **The daily token cap is invisible.** Per-minute limits appear in response headers; the
  200,000 tokens/day cap appears **only in a 429 body**. Pacing against the headers cannot see
  it coming.
- **Every retry is a billed request**, so retrying through a rate limit burns several times a
  run's question count and drives `retry-after` from ~15 s to *hundreds* of seconds. Pacing
  proactively against the reported budget is strictly better than retrying reactively.

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
src/generate.py        prompt assembly + Ollama call, with latency breakdown
config/prompts.yaml    versioned prompts
app.py                 Streamlit UI
eval/golden_set.csv    hand-written questions, committed
eval/known_gaps.csv    written but unscorable (answer lives in an image)
eval/run_eval.py       scoring harness; --retrieval-only needs no LLM
eval/find.py           keyword lookup, for filling in page numbers
eval/diff_editions.py  where the two empanelment editions disagree
eval/results/          one committed JSON per run
Docs/HANDOFF.md        authoritative status: what is done, half-done, and next
Docs/DEPLOYMENT.md     hosted-LLM and public-demo plan (not built yet)
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
    2026-08-27:** on lay phrasing it scores *below plain vector* (0.402 vs 0.443), because RRF
    fuses in a BM25 arm that has effectively stopped working. Hybrid's remaining justification
    is entirely latency.
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
   dependencies. `ModuleNotFoundError: chromadb` always means the wrong interpreter.
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
19. **Errors shrink the sample silently.** Excluded questions (decision 11) mean a run over 61
    questions looks like a run over 69. One archived file has metrics computed over 17 of 69 and
    looked entirely normal. Always report the denominator.

**Retrieval**

20. **In `hybrid` and `rerank` modes, `hit["score"]` is no longer a similarity.** It is an RRF
    score (~0.03) or a cross-encoder logit (unbounded, often negative). Anything thresholding or
    comparing `score` across modes breaks silently.
21. **`CrossEncoder.predict` defaults to `batch_size=32`.** Depth ≤32 is one batch; 33–63 costs
    two, the second mostly padding. If you raise `FUSION_DEPTH`, go to 64, not 40.
22. **Reranking latency varies with chunk length, not just candidate count** — batches pad to the
    longest sequence present, so one 512-token chunk makes every chunk in that batch cost 512.
23. **`src.retrieve`'s CLI shows only the first 400 characters of a ~2,400-character chunk**,
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

**Not yet built**

- **The paraphrase experiment** — the largest open threat to every retrieval number here. The
  golden set was written by someone reading the documents, so questions reuse document
  vocabulary, and lexical overlap is exactly what BM25 scores. **BM25's lead may be an
  authorship artifact.** Cheap to test and not yet done.
- **Golden-set target completeness** — confirmed incomplete in at least one row. Row 9 lists
  only p.41 while p.39 states the same threshold; the model answered from p.39, cited it, and
  scored as a *citation failure*. The model was right and the golden set was wrong. 14 citation
  failures remain unreviewed.
- Prompt v2, targeting the false-abstention weakness, A/B'd against v1 with nothing else changed
- Handling of the empanelment version conflict, which reranking makes worse rather than better
- Faithfulness measurement — see the note under [Why these metrics](#why-these-metrics);
  it is deliberately unscored, which leaves a brief deliverable consciously open
- The paraphrase experiment on golden-set vocabulary bias
- Public deployment — planned in [Docs/DEPLOYMENT.md](Docs/DEPLOYMENT.md)
- CI running the eval per PR

**Three times the measurement was the bug, not the system**

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

**Honest position on the headline number.** The +0.171 MRR is measured in-sample: 69
hand-written questions serving as both development and test set, with no held-out split,
where a single question moves the hit rate by two points. No hyperparameter was tuned
against it — `RRF_K`, fusion depth and `k` are all at inherited defaults — but one
architecture choice (feeding the reranker the fused pool) was made by reading test-set
recall. Treat **+0.171** as an upper bound rather than an expected production figure.

And note what the generation runs did to that number's significance: **the +0.171 did not
translate into better answers at all.** A retrieval gain is not a system gain, and this README
would have claimed one if the generation runs had never been done.

## Acknowledgment

Source documents are Government of India publications from the National Health Authority
and state health agencies, used here for a non-commercial portfolio project.
