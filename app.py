"""Streamlit UI: ask a question, get a cited answer, inspect the evidence.

Run with:  streamlit run app.py
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# BOOT ORDER IS LOAD-BEARING. Everything below runs before any `src` import, and
# it has to, because src/index.py imports sentence_transformers at module scope
# (which imports torch) and src/generate.py and src/retrieve.py read their
# settings from os.environ at import time. Move an import above this block and
# the settings silently stop applying -- no error, just a slower app reading the
# wrong config.
#
# streamlit is imported first deliberately: it does NOT pull torch, so it is safe
# here, and st.secrets is needed to build the environment.
# ---------------------------------------------------------------------------

# 1. Secrets -> environment.
#
# Streamlit Community Cloud supplies configuration as st.secrets, not as
# environment variables, while every module in src/ reads os.environ. Some
# Streamlit versions also export secrets to the environment; the documentation
# does not commit to it, so this bridges explicitly rather than depending on
# behaviour that may or may not be there. setdefault, so a real environment
# variable always wins over a secret of the same name -- which is what makes the
# local .env and the Docker image's ENV keep working unchanged.
try:
    for _key, _value in dict(st.secrets).items():
        if isinstance(_value, str):
            os.environ.setdefault(_key, _value)
except Exception:
    # No secrets file at all is the normal local case, not an error.
    pass

# 2. Intra-op thread count.
#
# Measured 2026-08-30 in a Linux container capped at 2 CPUs, 20 questions,
# cross-encoder reranking:
#
#     torch default (4 threads)   retrieve p50 = 7,615 ms
#     pinned to 2 threads         retrieve p50 = 3,974 ms   (-47.8%)
#
# torch sizes its thread pool from the HOST's core count, which inside a
# container is not what the cgroup grants -- so it oversubscribes and the threads
# contend for a quota smaller than the pool. Dense-only retrieval shows the same
# effect (109 ms -> 39 ms).
#
# An env var defaulting to 2 rather than a hardcoded 2: right for the deployment,
# wrong for an 8-core development machine. PMJAY_TORCH_THREADS=0 leaves torch
# alone. Set HERE and not in src/retrieve.py, because every committed eval number
# was measured under torch's default threading and changing that inside the
# pipeline would silently re-baseline the project.
TORCH_THREADS = os.getenv("PMJAY_TORCH_THREADS", "2")
if TORCH_THREADS != "0":
    for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(_var, TORCH_THREADS)

# 3. Cross-encoder batch size.
#
# THIS ONE DECIDES WHETHER THE APP RUNS AT ALL ON FREE HOSTING. Measured peak RSS
# over 5 reranked queries in a 2-vCPU container:
#
#     batch 32 (library default)   1,186 MB   -- OOM-KILLED under a 768 MB cap
#     batch 8                        868 MB   -- survives 768 MB with margin
#
# Scores are bit-identical at every batch size, so this costs nothing in ranking
# quality (see the table in src/retrieve.py). The default is set here rather than
# in src/retrieve.py for the same reason as the thread count: the eval must keep
# reproducing its committed numbers under the untouched library default.
os.environ.setdefault("PMJAY_RERANK_BATCH", "8")

import json  # noqa: E402

import requests  # noqa: E402

from src.generate import (  # noqa: E402
    BACKEND_BASE_URL,
    LLM_BACKEND,
    LLM_MODEL,
    LLM_PROVIDER,
    OLLAMA_MODEL,
    answer,
)
from src.index import COLLECTION, EMBED_MODEL, get_collection  # noqa: E402
from src.retrieve import (  # noqa: E402
    DEFAULT_K,
    DEFAULT_MODE,
    MODES,
    RERANK_MODEL,
    SCORE_LABELS,
)

st.set_page_config(page_title="PM-JAY RAG", page_icon="📄", layout="centered")

st.title("PM-JAY document assistant")
st.caption(
    "Answers come only from the National Health Authority PM-JAY corpus, "
    "with the file and page behind every claim."
)
st.info(
    "**Portfolio demo on free hosting.** Live questions run against a free "
    "language-model tier with a shared daily budget, so they are capped. The "
    "suggested questions are answered in advance and always available. "
    "This reports what the source documents say — it is not medical or legal "
    "advice, and two editions of the empanelment guidelines in the corpus "
    "contradict each other on several rules.",
    icon="ℹ️",
)


@st.cache_resource
def warm_models():
    """Load both models once, at startup, rather than lazily mid-session.

    The embedder is pulled in by the first query either way, but the
    cross-encoder is otherwise fetched the first time someone selects a rerank
    mode -- a ~90 MB download landing on one unlucky visitor, mid-question.

    Note what this does NOT solve. The plan called for fetching both at *build*
    time, but a Streamlit-SDK Space has only two hooks -- requirements.txt (pip)
    and packages.txt (apt) -- and neither can execute code. Only the Docker SDK
    has a build stage that could. So on this SDK "build time" and "startup" are
    the same moment, and this is the earliest the download can happen.

    Measured in the 2-vCPU container from a fully warm cache: bge-small 8.7 s,
    cross-encoder 9.9 s, 25.8 s including the torch and sentence-transformers
    imports themselves. That ~26 s is the floor on a cold start even when
    nothing downloads -- larger than the download this function exists to move.
    """
    # Call the modules' OWN loaders, not SentenceTransformer(...) directly. Both
    # modules keep a process-wide singleton; constructing separate instances here
    # would populate the HuggingFace cache and then throw the loaded models away,
    # leaving the singletons to load them a SECOND time on first use. Measured at
    # ~23 s of load on a 2-vCPU box, so doing it twice is not a rounding error.
    from src.index import load_embedder
    from src.retrieve import load_reranker

    load_embedder()
    load_reranker()
    return True


@st.cache_resource
def chunk_count():
    try:
        return get_collection().count()
    except Exception:
        return None


count = chunk_count()
if not count:
    st.error(
        f"Chroma collection '{COLLECTION}' is empty or missing. Build it first:\n\n"
        "```\npython -m src.download\npython -m src.extract\n"
        "python -m src.chunk\npython -m src.index\n```"
    )
    st.stop()

with st.spinner("Loading models (first start takes ~30 s)…"):
    warm_models()


# One line per mode, shown under the selector. The cost half matters as much as
# the quality half.
#
# The PROSE is written here; the NUMBERS are read from eval/results/ at startup.
# They used to be copied into this file by hand, and by the time anyone looked
# they were three golden-set revisions stale -- quoting MRRs of 0.624 / 0.677 /
# 0.795 for retrievers that now measure 0.699 / 0.766 / 0.879. The comment above
# the old dict had predicted exactly that and it happened anyway, which is the
# argument for deriving rather than remembering: a number that has to be updated
# by hand is a number that will be wrong.
MODE_DESC = {
    "vector": "Dense embeddings (the Phase 1 baseline).",
    "bm25": "Lexical keyword match. Strong on rare exact tokens.",
    "hybrid": "Vector + BM25 merged by reciprocal rank fusion.",
    "rerank": "Hybrid pool re-scored by a cross-encoder.",
    "rerank-bm25": "BM25 pool re-scored by a cross-encoder.",
    "rerank-union": "Vector+BM25 union re-scored. Best coverage, slowest.",
}


@st.cache_data
def mode_baselines():
    """Measured figures per mode, read from committed results files.

    The selection rule is deliberately strict, because a loose one would put a
    number on screen that does not describe this system:

      * retrieval-only runs, so no LLM is implied in a retrieval figure
      * scored by the question set that is live RIGHT NOW, matched on the
        content hash rather than the filename -- `golden_set.csv` has meant
        three different things and every published figure moved when the third
        landed (gotcha 19)
      * full runs only; a --only-rows run is a partial and its rates are not
        comparable
      * k == DEFAULT_K, since hit rate is defined against k

    Newest wins, and filenames are UTC timestamps so sort order is time order.
    A mode with no matching run gets NO number rather than a stale one -- the
    whole point is that this cannot silently go out of date.
    """
    try:
        from eval.run_eval import GOLDEN, RESULTS_DIR, question_set_fingerprint

        live_sha = question_set_fingerprint(GOLDEN)
    except Exception:
        return {}, None

    found = {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cfg = data.get("config") or {}
        metrics = data.get("metrics") or {}
        if not cfg.get("retrieval_only") or cfg.get("only_rows"):
            continue
        if cfg.get("question_set_sha") != live_sha or cfg.get("k") != DEFAULT_K:
            continue
        mode = cfg.get("retriever")
        if mode not in MODES or "mrr" not in metrics:
            continue
        found[mode] = {
            "mrr": metrics["mrr"],
            "p50": metrics.get("retrieve_ms_p50"),
            "n": cfg.get("n_questions"),
            # Recorded so the caption can name the exact run behind it. The
            # descriptor is composed from the config, so it cannot disagree
            # with the file it describes.
            "descriptor": data.get("descriptor") or data.get("label") or path.stem,
        }
    return found, live_sha


BASELINES, LIVE_SHA = mode_baselines()


def mode_caption(mode, k):
    """Prose plus whatever has actually been measured for this mode."""
    text = MODE_DESC[mode]
    stats = BASELINES.get(mode)
    if not stats:
        return f"{text}  \n_No current measurement — no run in `eval/results/` matches the live question set._"
    bits = [f"MRR **{stats['mrr']:.3f}**"]
    if stats.get("p50") is not None:
        bits.append(f"retrieve p50 **{stats['p50']:.0f} ms**")
    line = f"{text}  \n{', '.join(bits)} over {stats['n']} questions at k={DEFAULT_K}."
    if k != DEFAULT_K:
        line += f" _(measured at k={DEFAULT_K}; you have k={k})_"
    return line


with st.sidebar:
    st.metric("Indexed chunks", f"{count:,}")
    st.caption(f"LLM: `{LLM_PROVIDER}` / `{LLM_MODEL}`")
    # Named rather than implied. Every retrieval figure in this UI was produced by
    # these two specific models, and a reader who cannot see which ones cannot
    # check the claim.
    st.caption(f"embeddings: `{EMBED_MODEL}`")
    k = st.slider("Chunks retrieved (k)", 1, 15, DEFAULT_K)
    # Default is DEFAULT_MODE, not the best-scoring mode. Reranking wins clearly
    # on RETRIEVAL, but the generation runs showed no citation-precision benefit
    # and a penalty on small local models, so the default is not the place to
    # make an unmeasured bet (design decision 22).
    mode = st.selectbox(
        "Retrieval mode",
        MODES,
        index=MODES.index(DEFAULT_MODE),
        help="How candidate chunks are found before the model reads them.",
    )
    st.caption(mode_caption(mode, k))
    if mode.startswith("rerank"):
        st.caption(f"reranker: `{RERANK_MODEL}`")
    if BASELINES.get(mode):
        st.caption(f"source: `{BASELINES[mode]['descriptor']}`")
    if LIVE_SHA:
        st.caption(f"question set `{LIVE_SHA}`")

# ---------------------------------------------------------------------------
# Quota protection.
#
# The deployment runs on a free tier of ~200,000 tokens/day and each live query
# costs ~2,600 prompt tokens -- about 80 questions per DAY for the whole world.
# The daily cap is invisible until it is hit: it appears only in a 429 body and
# never in a response header (gotcha 16), so it cannot be paced against.
#
# Three defences, weakest to strongest:
#   1. Precomputed showcase answers, so the common path costs nothing at all.
#   2. A per-session cap, which stops one visitor draining it by accident.
#   3. A global daily counter, which bounds the worst case.
#
# What is NOT here is IP-based limiting: unreliable behind a proxy, unpersistable
# on free hosting, and it would mean storing a visitor identifier on a health
# assistant where questions are themselves sensitive.
# ---------------------------------------------------------------------------
SESSION_LIMIT = 8
DAILY_LIMIT = 60
SHOWCASE_PATH = Path("config/showcase.json")


@st.cache_resource
def usage_counter():
    """Process-wide live-call counter, shared across sessions.

    HONEST LIMITATIONS, because a rate limit that is trusted more than it deserves
    is worse than none: this lives in memory, so it resets whenever the app
    restarts or sleeps, and it counts only what THIS process served. It bounds the
    common case; it is not a guarantee.
    """
    return {"day": None, "count": 0}


def quota_state():
    counter = usage_counter()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if counter["day"] != today:
        counter["day"], counter["count"] = today, 0
    used_session = st.session_state.get("live_calls", 0)
    return counter, used_session


@st.cache_data
def showcase():
    """Precomputed answers, keyed by (question, mode, k).

    Absent file is not an error -- it means nobody has run
    `python -m eval.make_showcase` yet, and every question falls through to a
    live call. The app must work either way.
    """
    try:
        data = json.loads(SHOWCASE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, [], {}
    index = {(e["question"], e["mode"], e["k"]): e for e in data.get("entries", [])}
    questions = list(dict.fromkeys(e["question"] for e in data.get("entries", [])))
    provenance = {k: v for k, v in data.items() if k != "entries"}
    return index, questions, provenance


SHOWCASE_INDEX, SHOWCASE_QUESTIONS, SHOWCASE_META = showcase()


PICK_YOUR_OWN = "— ask your own question below —"

if SHOWCASE_QUESTIONS:
    chosen = st.selectbox(
        "Suggested questions",
        [PICK_YOUR_OWN] + SHOWCASE_QUESTIONS,
        help="These are rows from the 69-question evaluation set, answered in "
             "advance so they cost no quota. Ask your own below for a live run.",
    )
else:
    chosen = PICK_YOUR_OWN

typed = st.text_input(
    "Ask your own",
    placeholder="What is the maximum annual cover per family under PM-JAY?",
)

# A suggested question wins only while nothing has been typed, so the text box
# is never silently ignored.
question = typed.strip() or (chosen if chosen != PICK_YOUR_OWN else "")

if question:
    precomputed = SHOWCASE_INDEX.get((question, mode, k))
    counter, used_session = quota_state()

    if precomputed is None and used_session >= SESSION_LIMIT:
        st.warning(
            f"You have asked {used_session} live questions this session, which is "
            "the per-visitor limit on this demo. The suggested questions above "
            "still work — they are answered from disk and cost nothing."
        )
        st.stop()
    if precomputed is None and counter["count"] >= DAILY_LIMIT:
        st.warning(
            "This demo has reached its daily budget for live questions. The "
            "suggested questions above still work. Live questions resume "
            "tomorrow (UTC)."
        )
        st.stop()

    try:
        spinner = (
            "Reranking, then generating…" if mode.startswith("rerank")
            else "Retrieving and generating…"
        )
        # Wall clock around the WHOLE call. stats["total_ms"] covers only the LLM
        # request, so using it as "total" hid retrieval entirely -- and retrieval
        # is where the modes actually differ. On the deployed app that made
        # reranking look 20x FASTER than dense retrieval: rerank showed 1.1 s
        # (a warm LLM call, its ~3.5 s of cross-encoder work invisible) against
        # vector's 22.2 s (a cold first LLM call, its 36 ms of retrieval
        # invisible). Both numbers were correct and the comparison they invited
        # was backwards.
        if precomputed is not None:
            # Served from disk: no LLM call, and no retrieval either, because the
            # chunks were stored with the answer. Labelled below, because an
            # instant response would otherwise be read as system speed -- which
            # is exactly the misreading the timing fix existed to prevent.
            text = precomputed["answer"]
            hits = precomputed["hits"]
            stats = precomputed.get("stats") or {}
            wall_ms = None
        else:
            started = time.perf_counter()
            with st.spinner(spinner):
                text, hits, stats = answer(question, k=k, mode=mode)
            wall_ms = (time.perf_counter() - started) * 1000
            st.session_state["live_calls"] = used_session + 1
            counter["count"] += 1
    except requests.exceptions.ConnectionError:
        # The error has to name the backend actually in use. This branch used to
        # tell every user to check their Ollama tray icon, which is nonsense on
        # a hosted deploy where Ollama was never involved.
        if LLM_PROVIDER == "ollama":
            st.error(
                "Could not reach Ollama. Check the tray icon is running, then confirm "
                f"`ollama run {OLLAMA_MODEL}` works in a terminal."
            )
        else:
            st.error(
                f"Could not reach the `{LLM_BACKEND}` endpoint at `{BACKEND_BASE_URL}`. "
                "The provider may be down, or the API key may be missing from this "
                "deployment's secrets."
            )
        st.stop()
    except SystemExit as exc:
        # src/generate.py raises SystemExit on an unrecoverable provider state --
        # most importantly the daily token cap, which appears ONLY in a 429 body
        # and never in a response header (gotcha 16), so it cannot be seen coming.
        # Exiting is right for a CLI and wrong inside Streamlit, where it renders
        # as a broken page. SystemExit derives from BaseException, so it is not
        # caught by `except Exception` and needs naming explicitly.
        st.error(
            "The language model backend is unavailable and retrying will not help.\n\n"
            f"> {exc}\n\n"
            "This is a portfolio demo running on a free tier with a daily quota. "
            "Try again tomorrow, or use one of the precomputed example questions."
        )
        st.stop()

    st.markdown("### Answer")
    st.write(text)

    if stats:
        # Only Ollama reports a prefill/decode split. An OpenAI-compatible endpoint
        # returns token counts with no phase timings, so those fields come back 0 --
        # and rendering them unconditionally printed "prompt 0.0s, generation 0.0s"
        # under a query that visibly took 1.8s. Correct data, and it reads as broken
        # instrumentation. The deployed backend is hosted, so this was the case
        # EVERY visitor would have seen; it stayed invisible locally because the
        # local backend is the one provider that does report the split.
        # Retrieval is derived rather than measured separately: the wall clock
        # covers retrieval + generation, and generation is the one the provider
        # reports. Subtracting is honest here because nothing else happens
        # between the two.
        gen_ms = stats.get("total_ms") or 0
        if wall_ms is None:
            # Precomputed. Report what the answer COST when it was generated, not
            # the zero it costs to read from disk.
            line = (
                f"**Precomputed answer** — served from disk, no model call. "
                f"When generated it took {gen_ms / 1000:.1f}s of generation"
            )
        else:
            retrieve_ms = max(wall_ms - gen_ms, 0.0)
            line = (
                f"**{wall_ms / 1000:.1f}s total** — "
                f"retrieval {retrieve_ms / 1000:.1f}s (`{mode}`), "
                f"generation {gen_ms / 1000:.1f}s"
            )
        split_reported = (stats.get("prompt_eval_ms") or 0) > 0
        if split_reported:
            line += (
                f" — prompt {stats['prompt_eval_ms'] / 1000:.1f}s "
                f"({stats['prompt_eval_tokens']} tok), "
                f"decode {stats['eval_ms'] / 1000:.1f}s "
                f"({stats['eval_tokens']} tok)"
            )
        elif stats.get("prompt_eval_tokens"):
            line += (
                f" ({stats['prompt_eval_tokens']} prompt tok, "
                f"{stats['eval_tokens']} generated; "
                "this provider reports no prefill/decode split)"
            )
        st.caption(line)
        # The first hosted call after a cold start pays DNS and a TLS handshake on
        # top of inference -- measured at 7.7 s locally and 22.2 s on the deployed
        # app, against 1.1-2.3 s warm. Saying so is better than letting a visitor
        # conclude the system is slow.
        if wall_ms is not None and gen_ms > 6000:
            st.caption(
                ":grey[The first request after the app wakes includes connection "
                "setup to the language model. Later questions are much faster.]"
            )

    # The score is labelled with what it actually is. In hybrid it is an RRF score
    # (~0.03) and in rerank a cross-encoder logit that is often negative -- neither
    # is a similarity, and an unlabelled "score" invites a reader to compare numbers
    # across modes that share no scale (gotcha 22).
    label = SCORE_LABELS[mode]
    st.markdown(f"### Sources ({len(hits)})")
    for hit in hits:
        with st.expander(
            f"[{hit['rank']}] {hit['source_file']} — page {hit['page']}  "
            f"({label} {hit['score']:.3f})"
        ):
            st.text(hit["text"])
            st.caption(f"chunk_id: `{hit['chunk_id']}`")
