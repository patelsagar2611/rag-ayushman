"""Streamlit UI: ask a question, get a cited answer, inspect the evidence.

Run with:  streamlit run app.py
"""

import os

# ---------------------------------------------------------------------------
# Intra-op thread count. This MUST run before any import that pulls torch --
# src.index imports sentence_transformers at module scope, which imports torch,
# and torch reads these variables once at initialisation.
#
# Measured 2026-08-30 in a Linux container capped at 2 CPUs, 20 questions,
# cross-encoder reranking:
#
#     torch default (4 threads)   retrieve p50 = 7,615 ms
#     pinned to 2 threads         retrieve p50 = 3,974 ms   (-47.8%)
#
# The deployment target is a 2-vCPU Space. torch sizes its thread pool from the
# HOST's core count, which inside a container is not the number of cores the
# cgroup actually grants -- so it oversubscribes, and the threads contend for a
# quota smaller than the pool. Dense-only retrieval shows the same effect
# (109 ms -> 39 ms). Left unset, the Space would have been ~2x slower for a
# reason nothing in the app would have pointed at.
#
# Deliberately an env var rather than a hardcoded 2: this default is right for
# the deployment and wrong for an 8-core development machine, and hardcoding it
# would quietly tax local use. Set PMJAY_TORCH_THREADS=0 to leave torch alone.
#
# Deliberately set HERE and not in src/retrieve.py: every committed eval number
# was measured under torch's default threading, and changing that inside the
# pipeline would silently re-baseline the whole project. This is a property of
# the deployed product, not of the retriever.
# ---------------------------------------------------------------------------
TORCH_THREADS = os.getenv("PMJAY_TORCH_THREADS", "2")
if TORCH_THREADS != "0":
    for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(_var, TORCH_THREADS)

import json  # noqa: E402

import requests  # noqa: E402
import streamlit as st  # noqa: E402

from src.generate import (  # noqa: E402
    LLM_MODEL,
    LLM_PROVIDER,
    OLLAMA_MODEL,
    OPENAI_BASE_URL,
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
    from sentence_transformers import CrossEncoder, SentenceTransformer

    SentenceTransformer(EMBED_MODEL)
    CrossEncoder(RERANK_MODEL)
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
    if BASELINES.get(mode):
        st.caption(f"source: `{BASELINES[mode]['descriptor']}`")
    if LIVE_SHA:
        st.caption(f"question set `{LIVE_SHA}`")

question = st.text_input(
    "Question",
    placeholder="What is the maximum annual cover per family under PM-JAY?",
)

if question:
    try:
        spinner = (
            "Reranking, then generating…" if mode.startswith("rerank")
            else "Retrieving and generating…"
        )
        with st.spinner(spinner):
            text, hits, stats = answer(question, k=k, mode=mode)
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
                f"Could not reach the `{LLM_PROVIDER}` endpoint at `{OPENAI_BASE_URL}`. "
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
        st.caption(
            f"{stats['total_ms'] / 1000:.1f}s total — "
            f"prompt {stats['prompt_eval_ms'] / 1000:.1f}s "
            f"({stats['prompt_eval_tokens']} tok), "
            f"generation {stats['eval_ms'] / 1000:.1f}s "
            f"({stats['eval_tokens']} tok)"
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
