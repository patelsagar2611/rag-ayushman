"""Streamlit UI: ask a question, get a cited answer, inspect the evidence.

Run with:  streamlit run app.py
"""

import requests
import streamlit as st

from src.generate import LLM_MODEL, LLM_PROVIDER, OLLAMA_MODEL, answer
from src.index import COLLECTION, get_collection
from src.retrieve import DEFAULT_K, DEFAULT_MODE, MODES, SCORE_LABELS

st.set_page_config(page_title="PM-JAY RAG", page_icon="📄", layout="centered")

st.title("PM-JAY document assistant")
st.caption(
    "Answers come only from the National Health Authority PM-JAY corpus, "
    "with the file and page behind every claim."
)


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

# One line per mode, shown under the selector. The cost half matters as much as
# the quality half: rerank is a ~3 s cross-encoder pass and the first use of it in
# a session also downloads ~90 MB, so a user who picks it should know why the
# answer got slower.
#
# The figures are the 69-question retrieval baselines (HANDOFF section 3d), copied
# here rather than computed. That makes them a thing that can go stale: re-run the
# baselines, or change the rerank candidate pool, and these need updating with them.
MODE_HELP = {
    "vector": "Dense embeddings (Phase 1 baseline). MRR 0.624, ~26 ms.",
    "bm25": "Lexical keyword match. MRR 0.677, ~2 ms. Strong on rare terms.",
    "hybrid": "Vector + BM25 merged by rank fusion. MRR 0.671, ~29 ms.",
    "rerank": "Hybrid pool re-scored by a cross-encoder. MRR 0.795, ~3.3 s.",
    "rerank-bm25": "BM25 pool re-scored by a cross-encoder. MRR 0.808, ~3.3 s.",
    "rerank-union": "Vector+BM25 union re-scored. Best coverage (hit@5 98.3%), ~6.7 s.",
}

with st.sidebar:
    st.metric("Indexed chunks", f"{count:,}")
    st.caption(f"LLM: `{LLM_PROVIDER}` / `{LLM_MODEL}`")
    k = st.slider("Chunks retrieved (k)", 1, 15, DEFAULT_K)
    # Default is DEFAULT_MODE, not the best-scoring mode. Reranking wins clearly on
    # RETRIEVAL, but no generation run has yet shown it produces better answers, and
    # the default is not the place to make an unmeasured bet (design decision 21).
    mode = st.selectbox(
        "Retrieval mode",
        MODES,
        index=MODES.index(DEFAULT_MODE),
        help="How candidate chunks are found before the model reads them.",
    )
    st.caption(MODE_HELP[mode])

question = st.text_input(
    "Question",
    placeholder="What is the maximum annual cover per family under PM-JAY?",
)

if question:
    try:
        spinner = (
            "Reranking (first run downloads the cross-encoder), then generating…"
            if mode == "rerank"
            else "Retrieving and generating…"
        )
        with st.spinner(spinner):
            text, hits, stats = answer(question, k=k, mode=mode)
    except requests.exceptions.ConnectionError:
        st.error(
            "Could not reach Ollama. Check the tray icon is running, then confirm "
            f"`ollama run {OLLAMA_MODEL}` works in a terminal."
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
    # across modes that share no scale (gotcha 15).
    label = SCORE_LABELS[mode]
    st.markdown(f"### Sources ({len(hits)})")
    for hit in hits:
        with st.expander(
            f"[{hit['rank']}] {hit['source_file']} — page {hit['page']}  "
            f"({label} {hit['score']:.3f})"
        ):
            st.text(hit["text"])
            st.caption(f"chunk_id: `{hit['chunk_id']}`")
