# PM-JAY RAG

Retrieval Augmented Generation over the National Health Authority's Ayushman Bharat
(PM-JAY) corpus. Answers carry a filename and page number for every claim, and the
system declines to answer when the retrieved evidence does not support one.

Fully local, zero-cost stack: PyMuPDF, BGE embeddings, Chroma, Ollama, Streamlit.

**Status:** Phase 1 complete and running end to end — 11 documents, 629 pages, 872 chunks
indexed. Cited answers, citation correctness and abstention all verified by hand. See
[Docs/PMJAY-RAG-PROJECT.md](Docs/PMJAY-RAG-PROJECT.md) for the full project brief and
phase plan.

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
python -m src.retrieve "hospital empanelment criteria"   # retrieval only
python -m src.generate "What is the annual cover per family?"
```

## Evaluation

```powershell
python -m eval.run_eval --retrieval-only     # no Ollama needed; this is the CI path
python -m eval.run_eval                      # adds generation metrics
python -m eval.run_eval --min-hit-rate 0.7   # exit 1 below threshold
python -m eval.diff_editions                 # regenerate Docs/empanelment-diff.md
```

Questions live in `eval/golden_set.csv` (`question, expected_answer, source_file, page,
notes`). `source_file` and `page` may each be a comma-separated list paired by position, so
one question can point at several pages — which the version-conflict questions need, since
the answer lives in two documents. `expected_answer` of literally `ABSTAIN`, with empty
`source_file`/`page`, marks a question the corpus should not be able to answer.

Every run writes a self-describing JSON file to `eval/results/`, recording k, the embedding
model and the chunk parameters alongside the metrics — a metrics table is meaningless
without knowing what produced it.

**Retrieval metrics need no LLM**, which is what makes CI viable: GitHub Actions cannot run
Ollama, but `--retrieval-only` still measures hit rate and MRR — the half of the system most
likely to regress. Faithfulness is deliberately not scored: it needs a judge, and an LLM
judge grading an LLM's answers largely measures the model agreeing with itself.

The golden set currently holds **2 example rows, not a real eval set.** They exist to show
the two row shapes and must be verified or deleted. Writing the remaining 60–80 by hand is
the next task, and per the brief's anti-goals it must not be generated.

## Layout

```
data/raw/              downloaded PDFs (gitignored)
data/processed/        pages.jsonl, chunks.jsonl (gitignored)
src/download.py        corpus fetch, browser UA + %PDF validation
src/inspect_corpus.py  text-native vs scanned triage
src/extract.py         PyMuPDF, one record per page
src/chunk.py           ~600-token windows, ~100-token overlap
src/index.py           BGE embeddings -> Chroma; model + query prefix live here
src/retrieve.py        dense vector search
src/generate.py        prompt construction + Ollama call
app.py                 Streamlit UI
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

**Prompts are inline in `src/generate.py` for now.** Moving them to a versioned
`config/prompts.yaml` is Phase 2 work.

## Early observation to test in the eval

For "What is the annual health cover per family under PM-JAY?", the chunk that actually
states `Rs. 5,00,000` came back at **rank 5**; ranks 1–4 were topical scheme introductions
that never state the figure. The answer was still correct and both its citations checked
out, but dense retrieval clearly ranked *aboutness* above *answerhood* here.

That is a concrete, falsifiable prediction for what the Phase 2 reranker should fix — worth
writing eval questions that target it, and worth recording the baseline number before
touching retrieval.

## Not yet built

- Golden eval set (60–80 hand-written QA pairs) — Phase 3, and written by hand, not generated
- Hybrid BM25 + vector retrieval with reciprocal rank fusion — Phase 2
- Cross-encoder reranking — Phase 2
- Metrics table, failure analysis, CI — Phase 3

Baseline metrics must be recorded before any of the Phase 2 retrieval work, or there is
no way to say what it bought.

## Acknowledgment

Source documents are Government of India publications from the National Health Authority
and state health agencies, used here for a non-commercial portfolio project.
