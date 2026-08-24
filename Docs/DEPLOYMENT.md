# Deployment plan — hosted LLM and public demo

Status: **planned, not built.** Nothing in this document has been implemented.

Companion to [HANDOFF.md](HANDOFF.md). Read §3a.2 there first — the latency measurement is
what this whole document exists to answer.

---

## 1. The problem

A single question currently takes about **2¼ minutes**:

```
retrieval    ~6 s     (vector + BM25 + RRF + cross-encoder)
generation  ~127 s    (qwen2.5:7b on CPU)   ← 96% of the wall clock
```

That is not a demo. It is also not a bug — it is the expected consequence of two deliberate
Phase 1 choices: a 7B model, and a local zero-cost stack with no GPU. The number was recorded
in the Phase 1 baseline (`generate p50 = 126.9 s`); what was missing was the connection to
"can this be shown to anyone."

**96% of the problem is one component.** The retrieval pipeline is light and does not need
changing.

## 2. Two tracks, and they are independent

The most useful thing to understand before planning any of this:

| | What it needs | What it unblocks |
|---|---|---|
| **Track A — hosted LLM** | An API adapter and an env var. **No deployment.** | Fast benchmarks. A 2.5 h eval becomes ~10 min. |
| **Track B — public demo** | Hosting, committed index, secrets, a fast-enough reranker. | A link someone else can open. |

**Track A does not require Track B.** The eval is a local CLI script — retrieval runs on the
laptop (~6 s/question) and only the LLM call goes over the network (~2 s). Fifty-six questions
finish in roughly eight minutes, from the laptop, with nothing deployed.

Do Track A first. It is small, it unblocks every remaining Phase 2 measurement, and it is
independent of every hosting decision below.

---

## 3. Track A — hosted LLM backend

### What changes in the code

The endpoint is already an env var, which is most of the battle:

```python
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
```

What is Ollama-specific is the request and response *shape* — `prompt`, `options.num_ctx`,
`options.num_predict`, and the `prompt_eval_duration` / `eval_duration` fields that
`parse_stats` reads. Most hosted providers speak the OpenAI chat format (`messages`, `usage`).

Realistically **30–50 lines**: a provider abstraction selected by env var
(`LLM_PROVIDER=ollama|openai`), with `call_ollama` and a new `call_openai_compatible` behind
one interface, plus `parse_stats` tolerating a provider that reports token counts but no
prefill/decode split.

Keep Ollama working. It is the local baseline and the only source of the prefill/decode split.

### Provider choice

| Provider | Why | Watch out for |
|---|---|---|
| **Groq** (suggested) | Very fast inference, OpenAI-compatible, free tier | Model catalogue changes; no `qwen2.5:7b` |
| Google Gemini | Generous free tier | Different API unless using the OpenAI-compat endpoint |
| OpenRouter | Aggregates many models, some free | Variable latency, model availability shifts |
| Together AI | Free starting credits | Credits expire |

Check current free-tier limits at the source — they change often.

### Two things to get right before the first hosted run

1. **The hosted model is a different model.** You will not find `qwen2.5:7b` at the same
   quantisation. So citation correctness, abstention behaviour and `must_contain` will all
   move — for model reasons, not retrieval reasons. **Never compare a local number against a
   hosted number and attribute the difference to retrieval.**
2. **Record the model in the results file.** The `config` block records `embed_model` but not
   the LLM. With two models in play every results file becomes ambiguous. This is item 3 in
   HANDOFF §7 and it must land *before* the first hosted run, not after.

Pick one hosted model and lock it for every hosted benchmark.

### The benchmark grid

Retrieval metrics are unaffected by where the LLM runs — they never touch it. Only generation
metrics change. So the grid is smaller than it looks:

| | Phase 1 | Phase 2 | Note |
|---|---|---|---|
| Retrieval metrics | have it | have it | environment-independent — already done |
| Generation, local | have it (2026-08-19) | ~2.5 h | slow; optional |
| Generation, hosted | ~10 min | ~10 min | **the pair that matters** |

Both hosted cells come from **one build**, by flag — see HANDOFF design decision 19:

```powershell
$env:LLM_PROVIDER="groq"
python -m eval.run_eval --retriever vector --label "hosted-phase1-baseline"
python -m eval.run_eval --retriever rerank --label "hosted-phase2-rerank"
```

**That pair is the answer to "what did Phase 2 buy?"** — same model, same harness, same
golden set, retrieval the only variable. Twenty minutes of runtime.

The local Phase 2 run becomes optional. It is worth doing overnight once, to complete the
local grid and keep the prefill/decode story, but it is no longer on the critical path.

---

## 4. Track B — public demo

### Where to host

| Option | Free tier | Verdict |
|---|---|---|
| **Hugging Face Spaces** | 2 vCPU, 16 GB RAM, Streamlit SDK | **Suggested.** RAM headroom for torch. |
| Streamlit Community Cloud | ~1 GB RAM | Risky — torch + two models will likely OOM. |
| Render / Railway / Fly.io | Varies, shrinking | Needs Docker; more moving parts. |

**Hugging Face Spaces is the better fit**, and the reason is concrete: this app loads torch,
`bge-small` (133 MB) and a cross-encoder (90 MB). That is comfortable in 16 GB and marginal in
1 GB. Spaces is also ML-native, so model caching between restarts works without extra effort.

Both free tiers sleep when idle — expect a ~30 s cold start on the first visit.

### The trap: your reranker becomes the bottleneck

Free hosting gives you 1–2 weak vCPUs against your laptop's 8–16 cores. **The cross-encoder
gets slower, not faster** — expect ~20–30 s instead of 6 s. Combined with a ~2 s hosted LLM,
the latency profile inverts completely:

| Setup | Retrieval | Generation | Total |
|---|---|---|---|
| Today (local CPU + local 7B) | 6 s | ~127 s | **~2¼ min** |
| Free host + hosted LLM, unchanged reranker | **~25 s** | ~2 s | **~27 s** |
| Free host + hosted LLM + **int8 ONNX reranker** | ~6 s | ~2 s | **~8 s** |
| Free host + hosted LLM + **reranker API** | ~1 s | ~2 s | **~3 s** |
| Free host + hosted LLM + **no reranker** | ~1 s | ~2 s | ~3 s (throws away Phase 2) |

Three ways to fix it, in order of preference:

1. **Quantise the cross-encoder to int8 ONNX** (`optimum` + ONNX Runtime). Typically 3–4×
   faster on CPU, stays free, keeps the model you measured. Re-run the retrieval eval after —
   quantisation can shift scores slightly, and that must be measured, not assumed.
2. **Use a reranker API** (Cohere Rerank, Jina). Fastest, but adds a dependency, a second key,
   and a different model than the one benchmarked.
3. **Reduce `FUSION_DEPTH` to 10.** Recall@10 was 98%, so it costs ~1 question in 49. Least
   effort, smallest gain — and note this is exactly the test-set tuning that HANDOFF design
   decision 12 warns about, so it must be disclosed if done.

Note the reversal: HANDOFF open question 7 says depth tuning is not worth 2 s out of 133 s.
**On a hosted LLM that reasoning flips** — reranking becomes ~75% of query time and depth
suddenly matters. Same code, opposite conclusion, because the deployment changed.

### The index has to get onto the host

`chroma/` is **gitignored and 16 MB**; `data/processed/` is gitignored too. Nothing deployable
exists in the repo today.

| Option | Trade |
|---|---|
| **Commit `chroma/`** (suggested) | 16 MB, works immediately, no cold-start cost. But it is a binary blob that rewrites wholesale on every re-index — history will bloat if re-indexed often. |
| Commit `chunks.jsonl` (1.5 MB), build index at startup | Clean, diffable, text. Costs ~30–60 s embedding 872 chunks on every cold start — bad for a sleeping app. |
| Host the index in a HF Dataset repo | Cleanest separation, most moving parts. |

Committing `chroma/` is the pragmatic choice at this size. It needs a deliberate `.gitignore`
change, and the comment there (`# rebuildable via src/index.py`) should be updated to say why
it is now committed.

`data/processed/pages.jsonl` is only used by the eval's `validate()`, which degrades
gracefully when missing — not needed for the app. `chunks.jsonl` is not needed at runtime
either, because BM25 builds from Chroma (HANDOFF design decision 13, paying off).

### Secrets

API keys go in the Space's secrets manager and are read with `os.getenv`. Never committed,
never in `app.py`, never in a results file. Add a `.env.example` documenting the variable
names so the setup is reproducible without leaking anything.

### Protecting the quota

A public demo on a free API tier can be drained by one enthusiastic visitor. Before sharing
the link:

- A dropdown of ~8 suggested questions alongside the free-text box, so most visits cost one
  cached-ish call rather than an arbitrary one
- A simple per-session rate limit in `st.session_state`
- A visible note that it is a portfolio demo on a free tier

---

## 5. Suggested order

Steps 1–3 are from HANDOFF §7 and are prerequisites — benchmarks are not trustworthy without
them.

| # | Step | Effort |
|---|---|---|
| 1 | Finish the golden set, re-run all four retrieval modes | ~10 min run |
| 2 | Thread `mode` through `answer()`, expose in `app.py` | small |
| 3 | Record the LLM model in the results `config` | trivial |
| 4 | **Provider abstraction + Groq backend** | 30–50 lines |
| 5 | Hosted Phase 1 and Phase 2 generation runs | ~20 min |
| 6 | int8 ONNX reranker, re-run retrieval eval to confirm no drift | medium |
| 7 | Commit `chroma/`, un-ignore it, note why | trivial |
| 8 | Create the Space, add secrets, push, verify cold start | small |
| 9 | Question dropdown + rate limit, then share | small |
| 10 | *Optional:* local Phase 2 generation run overnight | 2.5 h unattended |

Steps 4 and 5 are the high-value ones. They unblock every remaining Phase 2 number and need
no hosting at all.

## 6. Cost

**₹0 / month** for a portfolio demo at low traffic: free app hosting, free LLM tier, Chroma
and BM25 running in-process, embeddings and reranking on CPU. The real limits are rate caps
and cold starts, not money.

## 7. What to put in the README afterwards

Keep both numbers. **"127 s on local CPU, ~8 s deployed, and here is the breakdown of why"**
is a stronger portfolio story than only ever having had the fast one — it demonstrates the
measurement, and the measurement is the part most projects skip.

State plainly which model produced which number.
