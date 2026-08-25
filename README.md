# PM-JAY RAG

Retrieval Augmented Generation over the National Health Authority's Ayushman Bharat
(PM-JAY) corpus. Answers carry a filename and page number for every claim, and the
system declines to answer when the retrieved evidence does not support one.

Zero-cost stack: PyMuPDF, BGE embeddings, Chroma, Streamlit, and either a local Ollama model
or any OpenAI-compatible hosted endpoint.

**Status:** Phase 1 complete. Phase 2 retrieval complete and measured; Phase 2 generation
measured on a local model. 11 documents, 629 pages, 872 chunks, 69 hand-written evaluation
questions.

**The headline result: whether better retrieval produces better answers depends on the
model.** Reranking improved retrieval by 24% in MRR. On a local 7B model that made attribution
slightly *worse*; on a hosted model it made it better. Same retrieval, same prompt, same
questions — opposite conclusions. See
[Generation results](#generation-results--did-better-retrieval-produce-better-answers).

[Docs/PMJAY-RAG-PROJECT.md](Docs/PMJAY-RAG-PROJECT.md) is the project brief;
[Docs/HANDOFF.md](Docs/HANDOFF.md) is the authoritative status document.

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
python -m eval.diff_editions                 # regenerate Docs/empanelment-diff.md
```

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

Three of those rows are more interesting than the summary line.

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

**It depends on the model, and that is the finding.**

Four full runs: two retrievers (`vector`, `rerank`) × two models. Within each pair the model,
the prompt and the questions are fixed, so **retrieval is the only variable**. Both pairs are
scored against the same golden set. The arms decline different numbers of questions, so every
figure below is restricted to the questions *both* arms of that pair answered — otherwise the
metrics score different subsets.

| head-to-head | `vector` | `rerank` | Δ |
|---|---|---|---|
| **local `qwen2.5:7b`** — 46 questions | **80.4%** | 73.9% | **−6.5 pts** |
| **hosted `gemini-3.1-flash-lite`** — 52 questions | 90.4% | **94.2%** | **+3.8 pts** |

Retrieval improved identically in both rows — MRR 0.624 → 0.795, hit@1 48.3% → 71.7%. The
answers moved in **opposite directions**.

The local pair took ~3 hours per arm on CPU; the hosted pair ~10 minutes each.

### Reading it

The local model attributes worse in absolute terms — 80.4% against the hosted model's 90.4%
under identical retrieval. **The model that already attributes well converts a retrieval gain
into an answer gain. The model that struggles with attribution is made worse by the same
change**, because of the mechanism below.

So "we added reranking and the system improved" is not a claim retrieval metrics can support.
It has to be measured per model, and a result measured on one model does not transfer.

A caution on the local pair: it also showed **4 wrong figures against `vector`'s 1** on
`must_contain`. On the hosted pair that difference vanished — one failure each, the same
question. Small numbers, and the honest reading is that the `must_contain` gap was noise while
the citation gap was not.

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

## Design notes

**Page numbers are captured at extraction and carried by every stage.** Citations are
the point of the project and retrofitting page tracking is painful.

**Chunks never span a page boundary.** Every chunk carries exactly one page number, so
a citation always points at a page that genuinely contains the text. The cost: a short
page yields a short chunk, and a paragraph running across a page break is split in the
index too. Worth revisiting if the eval shows answers cut in half at page boundaries.

**The BGE query prefix is applied query-side only**, in `src/index.py:embed_query`.
Applying it to documents too — or omitting it from queries — degrades retrieval silently.
Both sides import from one module so they cannot drift.

**`num_ctx` is set to 8192 on the Ollama call.** Five chunks of ~600 tokens overruns the
4096 default, which would silently drop the sources at the front of the prompt.

**Prompts live in `config/prompts.yaml` with a `version` field**, which every results
file records. Prompt edits and retrieval changes move the same generation metrics, so
without the version there is no way to tell a reranking gain from a prompt tweak made the
same afternoon. Version 1 is the Phase 1 prompt moved across verbatim — verified
byte-identical to the `phase-1` tag, so the Phase 2 generation run stays comparable.

**Fusion merges ranks, never scores.** A cosine similarity of 0.69 and a BM25 score of
12.55 are numbers on different scales, and combining them directly needs a normalisation
step that is itself a tuned parameter. Reciprocal rank fusion needs no such step. `RRF_K`
is left at the published default of 60 rather than tuned against these 69 questions —
fitting a constant to the test set and reporting the result as a measurement is exactly
the failure mode this eval exists to avoid.

**The cross-encoder has a 512-token window and chunks target ~600 tokens**, so the tail of
a long chunk is truncated and invisible to the reranker. Stated rather than worked around:
re-chunking to fit would change the indexing the Phase 1 baseline was measured against.

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

Phase 1 complete. Phase 2 retrieval complete and measured; Phase 2 generation measured on a
local model, with a hosted replication outstanding. [Docs/HANDOFF.md](Docs/HANDOFF.md) is the
authoritative status document.

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

- **Hosted generation replication** — the free tier caps at 200,000 tokens/day and one
  69-question arm consumes essentially all of it
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
