"""Streamlit UI: ask a question, get a cited answer, inspect the evidence.

Run with:  streamlit run app.py
"""

import requests
import streamlit as st

from src.generate import OLLAMA_MODEL, answer
from src.index import COLLECTION, get_collection
from src.retrieve import DEFAULT_K

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

with st.sidebar:
    st.metric("Indexed chunks", f"{count:,}")
    st.caption(f"Model: `{OLLAMA_MODEL}`")
    k = st.slider("Chunks retrieved (k)", 1, 15, DEFAULT_K)

question = st.text_input(
    "Question",
    placeholder="What is the maximum annual cover per family under PM-JAY?",
)

if question:
    try:
        with st.spinner("Retrieving and generating…"):
            text, hits, stats = answer(question, k=k)
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

    st.markdown(f"### Sources ({len(hits)})")
    for hit in hits:
        with st.expander(
            f"[{hit['rank']}] {hit['source_file']} — page {hit['page']}  "
            f"(score {hit['score']:.3f})"
        ):
            st.text(hit["text"])
            st.caption(f"chunk_id: `{hit['chunk_id']}`")
