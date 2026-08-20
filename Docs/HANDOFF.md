# Handoff — PM-JAY RAG

Context for a fresh session picking this project up. Read this before touching code.
The project brief is [PMJAY-RAG-PROJECT.md](PMJAY-RAG-PROJECT.md); this file records what
was actually built, what was discovered along the way, and what is next.

**Where things stand:** Phase 1 is complete and measured. Phase 2 (hybrid retrieval +
reranking) is next. CI/CD is deliberately deferred until after Phase 2.

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

## 3. Baseline — Phase 1, recorded 2026-08-19

`eval/results/20260819T102845Z.json`, 56 questions (49 answerable, 7 abstain):

| Metric | Value |
|---|---|
| `hit_rate@1` | 51.0% |
| `hit_rate@3` | 73.5% |
| `hit_rate@5` | 89.8% |
| `mrr` | 0.641 |
| retrieve p50 / p95 | 127 ms / 260 ms |

Full run (`20260819T163840Z.json`, same 56 questions, k=5):

| Metric | Value |
|---|---|
| `abstention_recall` | 100% (7/7) |
| `false_abstention_rate` | 18.4% (9/49) — but see section 3a |
| `citation_correctness` | 72.5% |
| `must_contain_pass` | 74.1% (of 27 checked) |
| `uncited_answers` | 1 |
| generate p50 / p95 | 126.9 s / 169.5 s |

**The number that matters for Phase 2 is the gap between `hit_rate@1` (51%) and
`hit_rate@5` (90%).** The right chunk is nearly always retrieved but ranked first only half
the time. That is exactly what a cross-encoder reranker is supposed to fix, and **MRR 0.641
is the headline number to move.** `hit_rate@5` can barely improve; MRR can.

## 3a. Do these BEFORE Phase 2 — they protect attribution

1. **Condition `false_abstention_rate` on the target having been retrieved.** As written it
   counts abstentions where retrieval failed and declining was *correct*. Of the 9 false
   abstentions, **7 had the golden page retrieved** and 2 did not, so the honest figure is
   7/44 = **15.9%**, not 18.4%.
   This matters less for the absolute number than for attribution: when Phase 2 fixes some of
   the 5 retrieval misses, questions leave the "correctly abstained" bucket and the metric
   moves for reasons unrelated to abstention behaviour — crediting the reranker with a prompt
   improvement it never made. Small change to `summarise()` in `eval/run_eval.py`.

2. **Capture Ollama's latency breakdown.** The response JSON carries `prompt_eval_duration`,
   `prompt_eval_count`, `eval_duration` and `eval_count`; `src/generate.py` currently discards
   them. Without the split there is no way to know whether p50 of 127 s is prompt processing
   or token generation — and the fix differs completely. If prompt eval dominates, use fewer
   or smaller chunks; if generation dominates, cap `num_predict` harder or use a smaller model.
   Do not tune latency before measuring which half it is.

3. **Finalise the golden set first.** Metrics over 56 questions cannot be compared with
   metrics over 60. If questions are added, re-record the baseline before starting Phase 2 —
   `--retrieval-only` costs seconds, the full run about two hours.

4. **Optional: a fast iteration subset.** ~15 questions covering the known failure modes, for
   rapid iteration. **Strictly an iteration tool** — a subset chosen to cover known failures is
   deliberately biased, so subset numbers must never appear in the metrics table or README.
   Only full-set runs get reported.

## 3b. Known behaviour worth reviewing by hand

- **7 of 9 false abstentions had the evidence retrieved**, 4 of them at rank 1. The pattern is
  yes/no and read-the-table questions (rows 33, 35, 40) plus negation (row 53) — the model
  declines when the answer must be *inferred* rather than copied. This is prompt strictness,
  not retrieval, and Phase 2's move of prompts into `config/prompts.yaml` is what makes it
  A/B-testable.
- **5 questions failed retrieval but only 2 abstained.** The other 3 answered with no golden
  chunk retrieved — hallucination candidates, worth reading manually.
- **Use `--no-save` for exploratory runs** rather than saving unlabelled results. Always pass
  `--label` on runs worth keeping; unlabelled files become archaeology.

## 4. Design decisions — do not silently reverse these

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
6. **Prompts are inline in `src/generate.py`.** Moving them to a versioned
   `config/prompts.yaml` is Phase 2 work.
7. **The golden set is anchored to `(source_file, page)`, never chunk IDs.** This is what lets
   the eval survive re-chunking, re-embedding and model swaps — without it, no Phase 2 number
   could be compared to the Phase 1 baseline.
8. **`must_contain` is matched against the model's answer, not against the page.**
9. **Retrieval metrics need no LLM** (`--retrieval-only`). Deliberate, and what makes CI
   possible later.
10. **Errored questions are excluded from generation metrics**, not counted as wrong. A
    network blip must never look like a quality regression.

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
7. **Ollama's default `num_ctx` is 4096** — too small for 5 chunks, and it truncates from the
   front, silently dropping the sources. Set to 8192.
8. **`num_predict: 512`** caps answer length. Uncapped, one enumerating answer can run for
   minutes on CPU and dominate a whole eval run.
9. **Latency must be measured after a warmup call to both stages**, or the embedding-model
   load (~5s) and Ollama's model load land entirely on question 1 and distort p50/p95.
10. **CSV values containing commas must be quoted** (`"4,500"`). One unquoted value shifted a
    whole row and put the filename in the `page` column. `must_contain` therefore splits on
    `;` only.
11. **Windows console is cp1252** and crashes on non-encodable characters; `eval/find.py`
    reconfigures stdout with `errors="replace"`.
12. **`grep` buffers when piping to a file**, so a backgrounded run appears to produce no
    output. Use `--line-buffered`, or run it in a terminal and watch the progress marks
    (`.` hit, `x` miss, `E` generation error).

## 6. Open questions

1. **Which empanelment edition is currently in force?** Unresolved. Version 2.0 declares its
   version; the other is dated December 2021. Settle against NHA circulars, not filenames —
   inferring from filenames is what produced the false pair in gotcha 3.
   `Docs/empanelment-diff.md` lists 13 same-clause-different-number pairs.
2. **Golden set row 25 is incomplete.** "5,00,000" appears in **7** documents; only 4 are
   listed as targets, so a correct retrieval scored as a miss. Add the missing pages
   (`operation_manual.pdf` p.17, `antifraud_guidebook_2024.pdf` p.13,
   `empanelment_dec2021.pdf` p.7) or drop the row. As written it understates hit rate.
3. **Abstention is the model's judgement, with no similarity threshold.** Observed top scores:
   ~0.79 in-corpus vs ~0.53 out-of-corpus. A threshold looks learnable, but must be set from
   the eval set with its false-abstention cost measured — not guessed from two examples.
4. **`k = 5` is untuned**, and the right value may change once reranking exists.
5. **56 questions, slightly under the brief's 60-80.** Four more would put it on spec.

## 7. Next: Phase 2

Per the brief, and **re-running the eval after each individual change, recording the number
every time** — the point is knowing what each change bought, not the final total.

1. **BM25** keyword search via `rank-bm25`, alongside the existing vector search. Expected to
   help where embeddings are weak: exact package codes, specific figures.
2. **Reciprocal rank fusion** to merge the BM25 and vector result lists.
3. **Cross-encoder reranking** of the top ~30 with `cross-encoder/ms-marco-MiniLM-L-6-v2`.
   The change most likely to move MRR.
4. **Move prompts to `config/prompts.yaml`** with a version field.
5. **Handle the empanelment version conflict** — metadata field vs separate collections.
   Open question 1 gates the expected answers, not the retrieval work.

Then CI/CD: `--retrieval-only --min-hit-rate` runs on the runner (no Ollama available);
generation metrics run locally and are committed as a results file CI verifies. Retrieval
enforced by execution, generation by attestation, tradeoff stated honestly in the README.

**A real possibility to plan for:** hybrid retrieval and reranking may show little or no gain.
The brief is explicit that reporting that honestly is more credible than assuming it helped.
Do not tune until the numbers look good.

## 8. Anti-goals — from the brief

- **Do not generate eval questions with an LLM.** The 56 in `eval/golden_set.csv` are
  hand-written and hand-verified. Scoring LLM-written questions with an LLM judge measures
  the model agreeing with itself.
- Do not add hybrid retrieval or reranking without recording the baseline first (done).
- Do not adopt a heavy orchestration framework.
- Do not drop page-number tracking anywhere in the pipeline.
- Do not start the multilingual work until English is measured and working.
