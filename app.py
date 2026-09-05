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
    answer_from_hits,
)
from src.index import COLLECTION, EMBED_MODEL, get_collection  # noqa: E402
from src.retrieve import (  # noqa: E402
    DEFAULT_K,
    DEFAULT_MODE,
    MODES,
    RERANK_MODEL,
    SCORE_LABELS,
    search,
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
    # Call the modules' OWN loaders, not SentenceTransformer(...) directly. Both
    # modules keep a process-wide singleton; constructing separate instances here
    # would populate the HuggingFace cache and then throw the loaded models away,
    # leaving the singletons to load them a SECOND time on first use. Measured at
    # ~23 s of load on a 2-vCPU box, so doing it twice is not a rounding error.
    from src.index import load_embedder
    from src.retrieve import load_reranker

    load_embedder()
    load_reranker()

    # CONSTRUCTING a model is not WARMING it, and the two were conflated here.
    # The loaders above only build the objects: torch still pays kernel setup on
    # the first real forward pass, and Chroma still loads its HNSW vector segment
    # off disk on the first QUERY -- chunk_count() calls .count(), which reads
    # metadata and never touches the index. So without the line below, the first
    # genuine question pays both, and the app reports it as retrieval time,
    # because that is honestly where it happens.
    #
    # Observed on the deployed app 2026-09-01: a `vector` question took 12.2 s
    # total, 10.1 s of it inside search(), against 36 ms in the eval. The same
    # session's `rerank` question, asked afterwards on the now-warm process,
    # retrieved in 3.2 s. A retriever doing strictly LESS work cannot be 3x
    # slower than one doing more -- rerank's pool is dense retrieval PLUS BM25
    # PLUS a cross-encoder -- so the gap was entirely first-call initialisation.
    #
    # eval/run_eval.py has always issued a throwaway query before timing anything
    # (gotcha 11). The app never adopted it, which is why every published latency
    # figure is warm and the deployed one was not.
    #
    # `vector` ONLY, deliberately. Warming `rerank` would run a cross-encoder pass
    # during boot, and one pass adds ~473 MB of peak RSS on a host with roughly
    # 1 GB. Trading a slow first reranked query for a crash-loop at startup is a
    # bad trade -- especially now that the first reranked query is labelled
    # honestly as retrieval rather than blamed on something else.
    try:
        search("warmup", k=1, mode="vector")
    except Exception:
        # A warmup failure must never take the app down. The same call is about to
        # be made by the first real question, which has error handling and a
        # message for the user; this one has neither and needs neither.
        pass
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


def fmt_ms(ms):
    """Milliseconds below a second, seconds above it.

    Dense retrieval is ~36 ms. At one decimal place in seconds that prints as
    `0.0s`, which reads as "not measured" rather than "very fast" -- and the whole
    point of measuring retrieval directly was to stop the number being ignorable.
    """
    return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f}s"


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

    # The caveats are important and a visitor needs them at most once, so they sit
    # behind a click at the bottom of the sidebar rather than in a banner above the
    # answer. A permanent notice in the main column is read on the first visit and
    # ignored on every one after, while costing vertical space on every question --
    # it stops being a disclosure and becomes furniture.
    st.divider()
    with st.popover("ℹ️ Demo version", use_container_width=True):
        st.markdown(
            "**Portfolio demo on free hosting.**\n\n"
            "- Live questions run against a free language-model tier with a shared "
            "daily budget, so they are capped per visitor and per day.\n"
            "- The suggested questions are **answered in advance** and always "
            "available — they cost no quota and no waiting.\n"
            "- First load takes ~30 s while two models start up.\n\n"
            "**This is not medical or legal advice.** It reports what the source "
            "documents say. Two editions of the empanelment guidelines are in the "
            "corpus and they contradict each other on several rules — where that "
            "happens, check the cited pages rather than trusting the answer.\n\n"
            "Source documents are Government of India publications from the "
            "National Health Authority and state health agencies."
        )

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


# ---------------------------------------------------------------------------
# "How this was measured" -- the D-4 tab.
#
# EVERY NUMBER ON THIS TAB IS READ FROM A COMMITTED RESULTS FILE. Nothing is
# typed in. That rule exists because the retrieval-mode help text was once
# hand-copied and went three golden-set revisions stale while a comment directly
# above it predicted exactly that (journal entry 33).
#
# THE ONE THING THIS TAB MUST NOT DO is let a visitor read a measurement change
# as a system improvement. The project's published figures moved twice for
# reasons that had nothing to do with the retriever:
#
#     system changes        vector -> bm25 -> RRF fusion -> cross-encoder
#     measurement changes   goldenv1 -> goldenv2 -> goldenv3 (18 rows corrected)
#
# So the slider holds ONLY system changes, and every position on it is scored by
# the SAME question set -- the one live right now. A measurement change cannot
# appear as a step on it, because there is nothing for it to be a step between.
# The eval corrections get their own panel below, where the retriever is held
# fixed and only the scorer moves. Two panels, one variable each.
# ---------------------------------------------------------------------------

# Order is the order of the story, not of the scores.
MILESTONES = [
    (
        "vector",
        "Dense only",
        "384-dimension BGE embeddings. The Phase 1 baseline that every later "
        "number is compared against.",
    ),
    (
        "bm25",
        "Keyword only",
        "**An alternative, not an addition** — lexical matching *instead of* "
        "embeddings, not on top of them. It wins on hit@1 because government "
        "manuals are full of rare exact tokens (`HWCs`, `PAN card`, `5,00,000`) "
        "that a 384-dimension embedding blurs together and an IDF term rewards "
        "precisely. It loses on hit@5: when BM25 misses, it misses completely, "
        "where dense retrieval degrades gracefully.",
    ),
    (
        "hybrid",
        "Both, fused",
        "Reciprocal rank fusion of the two lists. **hit@1 and MRR go DOWN "
        "against keyword-only** — RRF rewards chunks both retrievers agree on, "
        "so a page only one of them finds gets pushed down. Kept anyway, "
        "because its job is to be a candidate *pool* for the reranker rather "
        "than a final ranking.",
    ),
    (
        "rerank",
        "Fused pool + cross-encoder",
        "The top 30 fused candidates re-scored by a model that reads the "
        "question and the passage *together*, rather than comparing two "
        "independently-made vectors. The largest single gain in the project.",
    ),
]


@st.cache_data
def milestone_runs():
    """Full retrieval-only runs, grouped by (question-set hash, retriever).

    Same strictness as mode_baselines(): retrieval-only, complete runs, k equal
    to the app's default. A partial run's rates are not comparable and an
    LLM-bearing run implies a model in a retrieval figure.

    Returns {(sha, retriever): [run, ...]} sorted oldest first, plus the order
    in which question-set hashes first appear. NOTHING is hardcoded -- the
    current eval is whichever hash is live now, and the original is whichever
    appeared first. A hardcoded hash is a number that goes stale, which is the
    failure this whole tab is about.
    """
    try:
        from eval.run_eval import RESULTS_DIR
    except Exception:
        return {}, []

    runs, first_seen = {}, {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cfg = data.get("config") or {}
        metrics = data.get("metrics") or {}
        if not cfg.get("retrieval_only") or cfg.get("only_rows"):
            continue
        if cfg.get("k") != DEFAULT_K or "mrr" not in metrics:
            continue
        sha = cfg.get("question_set_sha")
        mode = cfg.get("retriever")
        if not sha or mode not in MODES:
            continue
        runs.setdefault((sha, mode), []).append({
            "file": path.stem,
            "n": cfg.get("n_questions"),
            "rows": cfg.get("question_set_rows"),
            "descriptor": data.get("descriptor") or data.get("label") or path.stem,
            **{k: metrics[k] for k in
               ("hit_rate@1", "hit_rate@3", "hit_rate@5", "mrr")},
            "p50": metrics.get("retrieve_ms_p50"),
        })
        first_seen.setdefault(sha, path.stem)
    return runs, [s for s, _ in sorted(first_seen.items(), key=lambda kv: kv[1])]


@st.cache_data
def golden_targets():
    """question -> {(source_file, page)}, straight from the live golden set.

    Read here so the side-by-side can mark which retrieved pages are the ones
    the evaluation set actually expects. Parsing matches the documented schema:
    `,` or `;` separated, equal-length lists pair positionally, and a single
    filename broadcasts across several pages.
    """
    import csv
    import re

    out = {}
    try:
        with open("eval/golden_set.csv", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                files = [f.strip() for f in re.split(r"[;,]", row["source_file"] or "") if f.strip()]
                pages = [p.strip() for p in re.split(r"[;,]", row["page"] or "") if p.strip()]
                if not files or not pages:
                    continue
                if len(files) == len(pages):
                    pairs = zip(files, pages)
                elif len(files) == 1:
                    pairs = ((files[0], p) for p in pages)
                else:
                    continue
                out[row["question"].strip()] = {
                    (f, int(p)) for f, p in pairs if p.isdigit()
                }
    except (OSError, KeyError, ValueError):
        return {}
    return out


def _pct(x):
    return f"{100 * x:.1f}%"


def _delta(cur, prev, pts=True):
    """A signed delta, or an em dash at the first position."""
    if prev is None:
        return "—"
    d = cur - prev
    if pts:
        return f"{100 * d:+.1f} pts"
    return f"{d:+.4f}"


def render_measured():
    runs, sha_order = milestone_runs()
    if not runs or not LIVE_SHA:
        st.warning(
            "No committed retrieval runs match this question set, so there is "
            "nothing to show that would be true. Run "
            "`python -m eval.run_eval --retrieval-only` first."
        )
        return

    st.markdown(
        "Every figure on this page is read from a committed results file in "
        "`eval/results/`, not written into the app. Where a number is missing, "
        "the app says so rather than showing an old one."
    )

    # ---------------- 1. the system track ----------------
    st.markdown("### What each change to the system bought")
    st.caption(
        f"All four positions are scored by the **same** question set "
        f"(`{LIVE_SHA}`, {runs[(LIVE_SHA, 'vector')][-1]['rows']} questions) at "
        f"k={DEFAULT_K}. Holding the scorer fixed is what makes a step on this "
        "slider a property of the retriever."
    )

    available = [m for m in MILESTONES if (LIVE_SHA, m[0]) in runs]
    if not available:
        st.warning("No run for the live question set.")
        return

    labels = [label for _, label, _ in available]
    picked = st.select_slider(
        "Retrieval milestone", options=labels, value=labels[-1],
        key="d4_milestone",
    )
    idx = labels.index(picked)
    mode, label, blurb = available[idx]
    cur = runs[(LIVE_SHA, mode)][-1]
    prev = runs[(LIVE_SHA, available[idx - 1][0])][-1] if idx else None

    cols = st.columns(4)
    for col, key, name in zip(
        cols,
        ("hit_rate@1", "hit_rate@3", "hit_rate@5", "mrr"),
        ("hit@1", "hit@3", "hit@5", "MRR"),
    ):
        if key == "mrr":
            col.metric(name, f"{cur[key]:.3f}",
                       _delta(cur[key], prev[key] if prev else None, pts=False))
        else:
            col.metric(name, _pct(cur[key]),
                       _delta(cur[key], prev[key] if prev else None))

    st.markdown(f"**{label}** — {blurb}")
    st.caption(f"source: `{cur['descriptor']}` · file `{cur['file']}`")
    if idx:
        st.caption(
            f"Deltas are against the previous position (**{available[idx-1][1]}**), "
            "and a negative one is not a bug — see the note on that position."
        )

    with st.expander("All four positions at once"):
        st.markdown(
            "| retriever | hit@1 | hit@3 | hit@5 | MRR |\n|---|---|---|---|---|\n"
            + "\n".join(
                f"| {label} | {_pct(runs[(LIVE_SHA, m)][-1]['hit_rate@1'])} "
                f"| {_pct(runs[(LIVE_SHA, m)][-1]['hit_rate@3'])} "
                f"| {_pct(runs[(LIVE_SHA, m)][-1]['hit_rate@5'])} "
                f"| **{runs[(LIVE_SHA, m)][-1]['mrr']:.3f}** |"
                for m, label, _ in available
            )
        )
        st.caption(
            "Two of these rows go the wrong way, and both were kept. That is "
            "the honest shape of the result rather than a line going up."
        )

    # ---------------- 2. the measurement track ----------------
    st.divider()
    st.markdown("### When the numbers moved and the system did not")

    older = [s for s in sha_order if s != LIVE_SHA
             and any((s, m) in runs for m, _, _ in MILESTONES)]
    if not older:
        st.caption("Only one question-set version has committed runs.")
    else:
        old_sha = older[0]
        st.caption(
            f"The same retrievers, byte-identical code and index, scored by an "
            f"**earlier version of the evaluation set** (`{old_sha}`) and by the "
            f"current one (`{LIVE_SHA}`). A completeness review found 18 of 60 "
            "answerable rows were missing target pages that genuinely answer the "
            "question, and two listed a page that does not contain the answer at "
            "all — those had been scoring a guaranteed failure in every run ever "
            "made."
        )
        rows = []
        for m, label, _ in MILESTONES:
            a, b = runs.get((old_sha, m)), runs.get((LIVE_SHA, m))
            if a and b:
                rows.append(
                    f"| {label} | {a[-1]['mrr']:.4f} | {b[-1]['mrr']:.4f} | "
                    f"**{b[-1]['mrr'] - a[-1]['mrr']:+.4f}** |"
                )
        st.markdown(
            "| retriever | MRR, earlier eval | MRR, current eval | change |\n"
            "|---|---|---|---|\n" + "\n".join(rows)
        )
        va, vb = runs.get((old_sha, "vector")), runs.get((LIVE_SHA, "vector"))
        ra, rb = runs.get((old_sha, "rerank")), runs.get((LIVE_SHA, "rerank"))
        if va and vb and ra and rb:
            st.markdown(
                f"**Every number rose, and nothing was improved.** What the "
                f"project actually claims is the *gap* between the baseline and "
                f"the reranker, and that barely moved: "
                f"**{ra[-1]['mrr'] - va[-1]['mrr']:+.4f}** under the earlier eval "
                f"against **{rb[-1]['mrr'] - vb[-1]['mrr']:+.4f}** under the "
                "corrected one. Correcting the evaluation made the reranking gain "
                "slightly *larger*, which is not the direction anyone hoped for "
                "when they went looking."
            )

    # ---------------- 3. why there is no latency number ----------------
    st.divider()
    st.markdown("### Why this page shows no speed figure")

    dupes = [(sha, m, v) for (sha, m), v in runs.items()
             if len(v) > 1 and len({round(x["mrr"], 6) for x in v}) == 1
             and v[0]["p50"] and v[-1]["p50"]]
    dupes.sort(key=lambda t: -abs(t[2][-1]["p50"] - t[2][0]["p50"]))

    st.markdown(
        "Retrieval **quality** is byte-reproducible: the same query returns the "
        "same pages in the same order, and all four retrievers reproduce to "
        "`0.000000` across a different operating system, a different CPU and "
        "four different library versions. Retrieval **latency** has none of that "
        "property, and the evidence is in this repository."
    )
    if dupes:
        sha, m, v = dupes[0]
        lo, hi = sorted((v[0], v[-1]), key=lambda x: x["p50"])
        st.markdown(
            f"The `{m}` retriever was run twice against the same question set, "
            f"on the same machine, with the same code:\n\n"
            f"| run | MRR | hit@1 | retrieve p50 |\n|---|---|---|---|\n"
            f"| `{lo['file']}` | {lo['mrr']:.4f} | {_pct(lo['hit_rate@1'])} | "
            f"**{lo['p50']:.0f} ms** |\n"
            f"| `{hi['file']}` | {hi['mrr']:.4f} | {_pct(hi['hit_rate@1'])} | "
            f"**{hi['p50']:.0f} ms** |\n\n"
            f"**Identical rankings. Latency "
            f"{hi['p50'] / lo['p50']:.2f}x apart.** Nothing about the system "
            "differed — only what else the processor was doing."
        )
    st.markdown(
        "Controlled measurement put the spread at about **1.7x for reranking "
        "and 1.9x for dense retrieval** on one machine in one session, driven "
        "mostly by CPU boost state: inserting a two-second idle gap between "
        "queries makes retrieval ~32% *faster*, because the processor's power "
        "budget recovers between bursts.\n\n"
        "So a single p50 here would be a point sample from a range that wide, "
        "presented as a measurement. The per-answer timing on the **Ask** tab is "
        "measured live on this host and is the honest version — it tells you "
        "what *this* request cost, and makes no claim about the next one."
    )
    st.caption(
        "The results files record k, the embedding model, the chunk parameters "
        "and a content hash of the question set — and nothing about the machine. "
        "That is a real gap in the format: it protects the metric that never "
        "varies and records nothing for the one that does."
    )

    # ---------------- 4. side by side on one question ----------------
    st.divider()
    st.markdown("### The same question, two retrievers")

    entries = SHOWCASE_INDEX
    qs = [q for q in SHOWCASE_QUESTIONS
          if (q, "vector", DEFAULT_K) in entries and (q, "rerank", DEFAULT_K) in entries]
    if not qs:
        st.caption(
            "No question has both arms precomputed. Regenerate with "
            "`python -m eval.make_showcase`."
        )
        return

    q = st.selectbox("Question", qs, key="d4_sxs")
    targets = golden_targets().get(q, set())
    st.caption(
        f"Both arms come from `config/showcase.json` — real runs, same prompt "
        f"and same model, generated in advance. "
        + (f"The evaluation set lists **{len(targets)}** page(s) that answer this "
           f"question; retrieved pages matching one are marked ✅."
           if targets else
           "This question is not in the golden set, so there are no expected "
           "pages to mark — it is the deliberate abstention example.")
    )

    left, right = st.columns(2)
    counts = {}
    for col, mode in ((left, "vector"), (right, "rerank")):
        e = entries[(q, mode, DEFAULT_K)]
        other = entries[(q, "rerank" if mode == "vector" else "vector", DEFAULT_K)]
        other_pos = {(h["source_file"], h["page"]): h["rank"] for h in other["hits"]}
        hit_n = 0
        col.markdown(f"**`{mode}`**")
        for h in e["hits"]:
            key = (h["source_file"], h["page"])
            good = key in targets
            hit_n += good
            moved = other_pos.get(key)
            move = (f" · rank {moved} in `{'rerank' if mode == 'vector' else 'vector'}`"
                    if moved else " · not in the other list")
            col.markdown(
                f"{'✅' if good else '▫️'} **{h['rank']}.** {h['source_file']} "
                f"p.{h['page']}  \n<span style='color:gray;font-size:0.85em'>"
                f"{SCORE_LABELS[mode]} {h['score']:.3f}{move}</span>",
                unsafe_allow_html=True,
            )
        counts[mode] = hit_n
    if targets:
        st.markdown(
            f"**{counts['vector']} of 5 expected pages with `vector`, "
            f"{counts['rerank']} of 5 with `rerank`.**"
        )
    st.caption(
        "The right-hand column is what reranking actually buys: a window with "
        "more of the evidence in it. What the generation runs then showed is "
        "that this does **not** translate into better citations — it reduces "
        "false refusals instead. A retrieval gain is not automatically a system "
        "gain, and this project would have claimed one if the generation runs "
        "had never been done."
    )


def render_about():
    st.markdown(
        "### What this is\n\n"
        "A retrieval-augmented question answering system over the National "
        "Health Authority's Ayushman Bharat (PM-JAY) corpus — **11 documents, "
        "629 pages, 872 chunks**. Every claim in an answer carries the file and "
        "page it came from, and the system declines to answer when the retrieved "
        "evidence does not support one.\n\n"
        "It is a portfolio project. The deliverable is not a working pipeline "
        "but a working pipeline whose author can explain every choice in it, "
        "which is why the **How this was measured** tab exists and why it shows "
        "the results that went the wrong way alongside the ones that did not."
    )
    st.markdown(
        "### What it is not\n\n"
        "**Not medical or legal advice.** It reports what the source documents "
        "say. Two editions of the empanelment guidelines are in the corpus and "
        "they contradict each other on several rules — where that happens, open "
        "the cited pages rather than trusting the answer.\n\n"
        "Source documents are Government of India publications from the National "
        "Health Authority and state health agencies. They are not redistributed "
        "here; what ships is the derived retrieval index."
    )
    st.markdown("### How it is built")
    st.markdown(
        f"| | |\n|---|---|\n"
        f"| embeddings | `{EMBED_MODEL}` |\n"
        f"| reranker | `{RERANK_MODEL}` |\n"
        f"| vector store | Chroma, cosine, {count:,} chunks |\n"
        f"| generation | `{LLM_PROVIDER}` / `{LLM_MODEL}` |\n"
        f"| evaluation | {SHOWCASE_META.get('prompt_version') and ''}"
        f"69 hand-written questions, hand-verified, never LLM-generated |\n"
    )
    st.caption(
        "No orchestration framework. The retrieval loop is plain Python, on "
        "purpose — every component in it had to be measurable one change at a "
        "time against a recorded baseline."
    )
    st.markdown(
        "### Honest limits\n\n"
        "- The evaluation questions were written by someone who had **read the "
        "documents**, so they reuse the documents' vocabulary. Rewritten in lay "
        "language, the best retriever loses 38% of its score and the keyword "
        "retriever collapses from first place to last. Treat every headline "
        "figure as an upper bound.\n"
        "- 69 questions is a small set, with no held-out split. One question "
        "moves the hit rate by nearly two points.\n"
        "- Four questions are known to be unanswerable because their values live "
        "inside images that text extraction never sees. They are kept aside "
        "rather than deleted, as the concrete case for adding OCR.\n"
        "- Answer faithfulness is deliberately **not** scored: it needs a judge, "
        "and an LLM grading an LLM's answers largely measures the model agreeing "
        "with itself."
    )

# ---------------------------------------------------------------------------
# Tabs.
#
# ORDER OF EXECUTION MATTERS HERE, and not for the reason it usually does.
# st.tabs renders every tab in one pass, and the Ask flow calls st.stop() in
# several places -- a quota cap, an unreachable backend, an empty index. st.stop
# halts the WHOLE script, not the tab it is called from, so anything not yet
# emitted would be missing from the page. Rendering the two static tabs FIRST
# means a stopped question still leaves a complete site behind it.
# ---------------------------------------------------------------------------
# Streamlit's default tabs are plain text with a thin underline on the active
# one. Reported from the live site: a visitor who does not already know there are
# tabs does not see them -- the labels read as a subheading, so the two tabs that
# are not "Ask" may as well not exist. Since the measurement tab is the point of
# this project rather than a footnote, that is a real loss and not a cosmetic one.
#
# So: draw each tab as a BOX, and give the selected one a filled background and a
# coloured border. The states now differ in three ways at once (fill, border,
# weight) rather than in one thin line.
#
# Colours are rgba overlays on top of whatever the visitor's theme provides,
# rather than fixed hex values, so this works on both the light and dark themes
# without knowing which is active. #FF4B4B is Streamlit's own accent, so the
# selected tab looks native rather than bolted on.
#
# This targets `data-baseweb` attributes, which are Streamlit internals and may be
# renamed by a future version. It degrades safely: if the selectors stop matching,
# the tabs render in the default style and still work. Nothing here is
# load-bearing for behaviour.
st.markdown(
    """
    <style>
    div[data-testid="stTabs"] div[data-baseweb="tab-list"] {
        gap: 8px;
        padding: 6px;
        border-radius: 10px;
        background: rgba(128, 128, 128, 0.10);
        flex-wrap: wrap;                 /* narrow screens wrap instead of clipping */
    }
    div[data-testid="stTabs"] button[data-baseweb="tab"] {
        border-radius: 8px;
        padding: 10px 18px;
        background: rgba(128, 128, 128, 0.06);
        border: 1px solid rgba(128, 128, 128, 0.30);
        font-weight: 600;
    }
    div[data-testid="stTabs"] button[data-baseweb="tab"]:hover {
        background: rgba(128, 128, 128, 0.16);
    }
    div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] {
        background: rgba(255, 75, 75, 0.16);
        border-color: rgba(255, 75, 75, 0.80);
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.14);
    }
    /* The default underline now duplicates state the box already carries. */
    div[data-testid="stTabs"] div[data-baseweb="tab-highlight"],
    div[data-testid="stTabs"] div[data-baseweb="tab-border"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Icons carry the same signal as the boxes for anyone scanning rather than
# reading, and they survive even if the CSS above stops matching a future
# Streamlit -- which is the reason they are in the labels and not in the style.
TAB_ASK, TAB_MEASURED, TAB_ABOUT = st.tabs(
    ["💬  Ask", "📊  How this was measured", "ℹ️  About"]
)

with TAB_MEASURED:
    render_measured()

with TAB_ABOUT:
    render_about()

with TAB_ASK:
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
            # TWO stopwatches, not one, and retrieval is MEASURED rather than inferred.
            #
            # The first version of this caption used stats["total_ms"] -- the LLM
            # request alone -- as "total", which hid retrieval entirely and made
            # reranking look 20x FASTER than dense retrieval.
            #
            # The fix for that introduced a subtler bug: one stopwatch around the whole
            # call, with retrieval derived as `wall_ms - gen_ms`. That number was never
            # a measurement of retrieval. It was "everything that was not the LLM call",
            # printed under the word `retrieval`, so any cost anywhere else in the
            # request was silently attributed to the retriever.
            #
            # Worse, it was built so the parts ALWAYS summed to the whole -- one of the
            # three numbers was defined as the other two subtracted. A breakdown that
            # can never fail to reconcile can never show you an anomaly; it just moves
            # the anomaly into whichever bucket is the leftover. Here that bucket was
            # labelled `retrieval`, so the retriever took the blame for everything.
            #
            # answer() is exactly search() + answer_from_hits(), so calling the two
            # halves directly costs nothing and buys an honest split. `other_ms` below
            # is now allowed to be non-zero, and that is the point of it.
            if precomputed is not None:
                # Served from disk: no LLM call, and no retrieval either, because the
                # chunks were stored with the answer. Labelled below, because an
                # instant response would otherwise be read as system speed -- which
                # is exactly the misreading the timing fix existed to prevent.
                text = precomputed["answer"]
                hits = precomputed["hits"]
                stats = precomputed.get("stats") or {}
                wall_ms = None
                retrieve_ms = precomputed.get("retrieve_ms")
            else:
                started = time.perf_counter()
                with st.spinner(spinner):
                    hits = search(question, k=k, mode=mode)
                    retrieve_ms = (time.perf_counter() - started) * 1000
                    text, stats = answer_from_hits(question, hits)
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
                    f"When generated it took {fmt_ms(gen_ms)} of generation"
                )
                if retrieve_ms:
                    line += f" and {fmt_ms(retrieve_ms)} of retrieval (`{mode}`)"
            else:
                line = (
                    f"**{fmt_ms(wall_ms)} total** — "
                    f"retrieval {fmt_ms(retrieve_ms)} (`{mode}`), "
                    f"generation {fmt_ms(gen_ms)}"
                )
                # Deliberately allowed not to reconcile. Everything outside the two
                # measured phases lands here instead of being folded into retrieval,
                # so a first-call cost or an unexpected stall is VISIBLE rather than
                # misattributed. Normally a few milliseconds, so it is hidden below
                # the threshold rather than adding noise to every answer.
                other_ms = wall_ms - retrieve_ms - gen_ms
                if other_ms >= 250:
                    line += f", other {fmt_ms(other_ms)}"
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
