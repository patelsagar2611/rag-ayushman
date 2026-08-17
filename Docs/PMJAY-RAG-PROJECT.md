# PM-JAY RAG — Project Brief

A production-grade Retrieval Augmented Generation system over Ayushman Bharat (PM-JAY)
scheme documents. Built as a portfolio project to demonstrate understanding of the full
lifecycle of a production AI system.

**Environment:** Windows, Python 3.12, fully local / zero-cost stack.
**Status:** Not started.

---

## 1. Project target

An "ask my docs" system over the National Health Authority's PM-JAY corpus that answers
questions **with verifiable citations** — filename and page number — and **declines to
answer** when the retrieved evidence does not support a response.

The demo test: ask a question, get an answer, and be able to open the cited PDF at the
cited page and read the sentence the answer came from.

### Why this corpus

- Government of India publications — freely downloadable, reproducible with acknowledgment.
- **Two versions of the empanelment guidelines exist.** A naive system will happily cite the
  superseded one. Handling "which rule is current" correctly is a real retrieval problem.
- **Three overlapping anti-fraud documents.** Good stress test for retrieval precision —
  similar content across different sources.
- Dense with specific numbers (package rates, percentages, day limits) that are easy to
  verify and hard for a sloppy pipeline to get right.

### What "done" looks like

A public GitHub repo containing:

- Working Streamlit app with cited answers
- A hand-verified evaluation set of 60–80 QA pairs
- A before/after metrics table showing what hybrid retrieval and reranking actually bought
- CI that runs the eval on every PR and fails below a quality threshold
- A README with a failure analysis section — where it breaks and why

---

## 2. Goals by phase

### Phase 1 — Fundamentals (target: one weekend)

**Goal:** end-to-end working pipeline, however ugly.

- Ingest PDFs, extract text with page numbers preserved
- Chunk at ~600 tokens with ~100 token overlap
- Embed and store in Chroma
- Retrieve top-k, generate an answer with source + page citations
- Minimal Streamlit UI

**Do not optimize anything in this phase.**

### Phase 2 — Production quality

**Goal:** measurable retrieval improvements, defensible with numbers.

- Hybrid retrieval — BM25 keyword search merged with vector search via reciprocal rank fusion
- Cross-encoder reranking of the top ~30 candidates
- Citation enforcement — abstain when retrieved chunks do not support an answer
- Prompts stored in a versioned config file, not hardcoded strings
- Handle the empanelment version-conflict case correctly

### Phase 3 — Shippable

**Goal:** demonstrate lifecycle discipline.

- Golden eval set: 60–80 hand-verified QA pairs with source doc + page
- Offline eval script measuring faithfulness (are the answer's claims supported by the
  retrieved chunks?) and retrieval hit rate
- Wire into GitHub Actions — eval runs per PR, build fails below threshold
- README with metrics table and honest failure analysis

### Phase 4 — Multilingual (later, after English works)

The differentiator. Not part of the initial build.

- Swap to a multilingual embedding model (BGE-M3 or multilingual-e5)
- Script normalization for Devanagari / romanized / English query variants
- Re-measure everything and publish the delta

---

## 3. Corpus

Download into `data/raw/`. All confirmed live as of August 2026.

### Core scheme documents

| Document | URL |
|---|---|
| Operation Manual | `https://nha.gov.in/img/resources/Operation%20Manual%20for%20AB%20PM-JAY.pdf` |
| Health Benefit Package 2.2 manual (64pp, text-native — verified) | `https://nha.gov.in/img/resources/HBP-2.2-manual.pdf` |
| Standard Treatment Guidelines booklet | `https://nha.gov.in/img/pmjay-files/STG-Manual-Booklet-final.pdf` |
| Grievance Redressal Guidelines (Dec 2021) | `https://nha.gov.in/img/resources/OM-Grievance-Redressal-Guideline-Dec-2021.pdf` |

### Version-conflict pair — download BOTH

| Document | URL |
|---|---|
| Hospital Empanelment Guidelines (21-12-22) | `https://nha.gov.in/img/resources/Hospital-Empanelment-Guidelines-21-12-22.pdf` |
| Revised Empanelment and De-empanelment Guideline | `https://nha.gov.in/img/resources/Revised-Empanelment-and-De-empanelment-Guideline.pdf` |

### Anti-fraud cluster

| Document | URL |
|---|---|
| Anti-Fraud Guidelines | `https://ayushmanup.in/admin/Clients/Doc/79_Guidelines-Anti-Fraud-Guidelines.pdf` |
| Anti-Fraud Practitioners' Guidebook (2024) | `https://cdnbbsr.s3waas.gov.in/s3169779d3852b32ce8b1a1724dbf5217d/uploads/2024/09/20240924831436164.pdf` |
| Field Investigation and Medical Audit Manual | `https://sha.kerala.gov.in/wp-content/uploads/2026/03/NHA_Field-Investigation-and-Medical-Audit-Manual_April-2020.pdf` |

### Process documents

| Document | URL |
|---|---|
| Beneficiary Identification Guidelines | `https://ayushmanup.in/admin/Clients/Doc/85_Guidelines-on-Process-of-Beneficiary-Identification.pdf` |
| Fraud Analytics RFE | `https://nha.gov.in/img/pmjay-files/RFE_fraud_Analytics_Services.pdf` |

**Hub page for more:** `https://pmjay.gov.in/resources/documents`

---

## 4. Download troubleshooting

The links are valid — `HBP-2.2-manual.pdf` was fetched and verified. If downloads fail,
it is a transport problem, not a dead link. Work through these in order.

### Fix 1 — Use a browser User-Agent (most likely cause)

Many Indian government servers reject requests with default `curl`, `wget`, or
`python-requests` user-agent strings. Browsers work, scripts don't.

Save as `download_corpus.py` and run it:

```python
import time
from pathlib import Path
import requests

OUT = Path("data/raw")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}

URLS = {
    "operation_manual.pdf": "https://nha.gov.in/img/resources/Operation%20Manual%20for%20AB%20PM-JAY.pdf",
    "hbp_2_2_manual.pdf": "https://nha.gov.in/img/resources/HBP-2.2-manual.pdf",
    "stg_manual.pdf": "https://nha.gov.in/img/pmjay-files/STG-Manual-Booklet-final.pdf",
    "grievance_redressal.pdf": "https://nha.gov.in/img/resources/OM-Grievance-Redressal-Guideline-Dec-2021.pdf",
    "empanelment_2022_12_21.pdf": "https://nha.gov.in/img/resources/Hospital-Empanelment-Guidelines-21-12-22.pdf",
    "empanelment_revised.pdf": "https://nha.gov.in/img/resources/Revised-Empanelment-and-De-empanelment-Guideline.pdf",
    "antifraud_guidelines.pdf": "https://ayushmanup.in/admin/Clients/Doc/79_Guidelines-Anti-Fraud-Guidelines.pdf",
    "antifraud_guidebook_2024.pdf": "https://cdnbbsr.s3waas.gov.in/s3169779d3852b32ce8b1a1724dbf5217d/uploads/2024/09/20240924831436164.pdf",
    "field_investigation_manual.pdf": "https://sha.kerala.gov.in/wp-content/uploads/2026/03/NHA_Field-Investigation-and-Medical-Audit-Manual_April-2020.pdf",
    "beneficiary_identification.pdf": "https://ayushmanup.in/admin/Clients/Doc/85_Guidelines-on-Process-of-Beneficiary-Identification.pdf",
    "fraud_analytics_rfe.pdf": "https://nha.gov.in/img/pmjay-files/RFE_fraud_Analytics_Services.pdf",
}

for name, url in URLS.items():
    dest = OUT / name
    if dest.exists() and dest.stat().st_size > 10_000:
        print(f"skip   {name}")
        continue
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=120, verify=True)
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                print(f"WARN   {name}: not a PDF (got HTML? login page?)")
                break
            dest.write_bytes(r.content)
            print(f"ok     {name}  ({len(r.content)//1024} KB)")
            break
        except Exception as e:
            print(f"retry  {name} [{attempt+1}/3]: {type(e).__name__}")
            time.sleep(3)
    else:
        print(f"FAILED {name}")
```

The `startswith(b"%PDF")` check matters — some servers return an HTML error page with a
200 status, which silently saves as a corrupt "PDF".

### Fix 2 — TLS / certificate errors

Some `.gov.in` hosts have incomplete certificate chains. If you see `SSLError` or
`CERTIFICATE_VERIFY_FAILED`:

```powershell
pip install --upgrade certifi
```

If that doesn't fix it, set `verify=False` in the script **for these government sources
only** and add `import urllib3; urllib3.disable_warnings()`. Acceptable here because these
are public documents whose content you can eyeball — never do this in production code.

### Fix 3 — Manual browser download

Open the URL in Chrome or Edge, then `Ctrl+S`, or right-click the page → Save as.
If Chrome opens the PDF in its viewer instead, use the download icon in the top-right of
the viewer. Slow but reliable for eleven files.

### Fix 4 — ISP or DNS blocking

Some Indian ISPs intermittently fail on government domains. Test:

```powershell
Test-NetConnection nha.gov.in -Port 443
```

If that fails but browsing works, try switching DNS to 1.1.1.1 or 8.8.8.8, or use mobile
hotspot for the download step only.

### Fix 5 — State mirrors

Many state health agencies host copies of the same NHA documents. If `nha.gov.in` is
unreachable, search for the document title plus `site:*.gov.in filetype:pdf`. The Kerala
SHA and UP Ayushman portals (already used above) are reliable mirrors.

### Fix 6 — Wayback Machine

Prefix any URL with `https://web.archive.org/web/2024/` as a last resort. Content may be
an older revision — note this in your README if you use it, since document version matters
for this project.

### After downloading — sanity check

```powershell
python -c "import fitz; d=fitz.open('data/raw/hbp_2_2_manual.pdf'); print(d.page_count, len(d[5].get_text()))"
```

If character count is near zero, that PDF is a scanned image and needs OCR. Set those
aside rather than blocking on them — most NHA manuals are text-native.

---

## 5. Environment setup (Windows)

```powershell
# Python 3.12 from python.org — tick "Add Python to PATH"
# Avoid 3.13; some ML wheels still lag

mkdir C:\dev\pmjay-rag        # keep path short: Windows 260-char limit
cd C:\dev\pmjay-rag
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

If activation fails with an execution policy error (the single most common blocker):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Install CPU-only PyTorch **first**, explicitly — otherwise pip may pull a ~2.5 GB CUDA build:

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install chromadb sentence-transformers pymupdf rank-bm25 streamlit requests python-dotenv
```

Local LLM — install Ollama for Windows from `https://ollama.com/download`, then:

```powershell
ollama pull qwen2.5:7b      # use qwen2.5:3b if you have 8 GB RAM
```

### Windows gotchas

- Hugging Face symlink warnings are cosmetic. Silence with `HF_HUB_DISABLE_SYMLINKS_WARNING=1`.
- Avoid `unstructured` and `layoutparser` — heavy native deps, awkward on Windows.
  PyMuPDF (`fitz`) covers PDF parsing without them.
- Models cache to `C:\Users\<you>\.cache\huggingface` — first run downloads ~500 MB.

---

## 6. Build steps

### Step 1 — Extract

Use PyMuPDF, not pypdf — better with multi-column government layouts and much faster.
Extract page by page. **Store the page number in metadata from the very start.** Citations
are the point of this project and retrofitting page tracking later is painful.

Output per page: `{text, source_file, page_number}`

### Step 2 — Chunk

~600 tokens with ~100 overlap. For English, approximate: split on paragraph breaks,
accumulate to roughly 2,400 characters, carry the last ~400 characters forward.

Output per chunk: `{chunk_id, text, source_file, page, char_start}`

Overlap matters because a chunk boundary landing mid-sentence destroys context on both sides.

### Step 3 — Embed and index

Model: `BAAI/bge-small-en-v1.5` — 133 MB, fast on CPU, clearly better than MiniLM.
Store in a **persistent** Chroma collection so re-runs don't re-embed.

Note: BGE models expect a query prefix (`"Represent this sentence for searching relevant
passages: "`) on the query side only, not on documents. Getting this wrong quietly degrades
retrieval.

### Step 4 — Retrieve and generate

- Embed query with the same model
- Pull top-5
- Build a prompt numbering each chunk with its source file and page
- Instruct the model to cite by number and to say it cannot answer if the chunks don't cover it
- Call Ollama at `http://localhost:11434/api/generate`

### Step 5 — Streamlit UI

`streamlit run app.py`. Question box, answer, and an expander showing retrieved chunks with
filenames and page numbers. This is your README screenshot.

**Phase 1 ends here. Get this working before touching anything below.**

### Step 6 — Golden eval set (BEFORE any optimization)

60–80 questions written by hand. CSV: `question, expected_answer, source_file, page, notes`.

Skew toward genuinely hard cases:
- Specific numbers (package rates, incentive percentages, day limits)
- The two empanelment versions — questions where the answer differs between them
- Content appearing in all three anti-fraud documents
- Questions the corpus does **not** answer — the system should abstain (~10% of the set)

**Write these manually.** If you generate QA pairs with an LLM and then score them with an
LLM judge, you are measuring the model's agreement with itself, and the number means nothing.

### Step 7 — Phase 2 retrieval

- Add `rank-bm25` alongside vector search
- Merge with reciprocal rank fusion
- Rerank top 30 with `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Move prompts into `config/prompts.yaml` with a version field
- **Re-run eval after each individual change and record the number**

### Step 8 — CI

GitHub Actions, free for public repos. Ollama won't run in Actions — either use a free-tier
API for the judge model, or run eval locally and have CI verify the committed results file.
State the tradeoff honestly in the README.

---

## 7. Metrics to track

| Metric | What it measures |
|---|---|
| Retrieval hit rate @k | Is the correct chunk in the top-k at all? |
| Faithfulness | Are the answer's claims supported by the retrieved chunks? |
| Abstention accuracy | Does it decline when it should, and only then? |
| Citation correctness | Does the cited page actually contain the claim? |
| Latency p50 / p95 | Per query, broken down by stage |

Record all of these before Phase 2, after hybrid retrieval, and after reranking. The
resulting table is the single most interview-valuable artifact in the project.

**Expect surprises.** On a clean corpus, hybrid retrieval and reranking sometimes show no
measurable gain because retrieval was never the bottleneck. If that happens, report it
honestly — a candidate who measured and found no improvement is more credible than one
who assumed it helped.

---

## 8. Suggested repo layout

```
pmjay-rag/
├── data/
│   ├── raw/                 # downloaded PDFs (gitignored)
│   └── processed/           # extracted text + chunks
├── config/
│   └── prompts.yaml         # versioned prompts
├── src/
│   ├── download.py
│   ├── extract.py
│   ├── chunk.py
│   ├── index.py
│   ├── retrieve.py          # vector / bm25 / hybrid / rerank
│   └── generate.py
├── eval/
│   ├── golden_set.csv       # hand-written, committed
│   ├── run_eval.py
│   └── results/             # committed, one file per run
├── .github/workflows/eval.yml
├── app.py                   # Streamlit
├── requirements.txt
└── README.md
```

---

## 9. Open questions to resolve while building

- Which of the eleven PDFs are scanned images needing OCR? Check before committing to them.
- How to represent the empanelment version conflict — metadata field, or separate collections?
- Where to set the abstention threshold, and how to measure the false-abstention rate?
- What k value for retrieval, and does the answer change after reranking is added?

---

## 10. Anti-goals

Things to deliberately *not* do:

- Do not generate the eval set with an LLM
- Do not add hybrid retrieval or reranking before the baseline is measured
- Do not use a heavy orchestration framework — the retrieval loop is ~80 lines of plain
  Python, and writing it yourself is a stronger signal than importing it
- Do not skip page-number tracking "for now"
- Do not build the multilingual version until the English version is measured and working
