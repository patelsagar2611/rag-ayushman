"""Retrieval over the PM-JAY corpus: dense vectors, BM25 keywords, or both.

Phase 1 was dense-only. Phase 2 adds the alternatives one at a time so each can be
measured on its own -- a combined "hybrid + rerank" number tells you the total but
not which half earned it.

Modes:
    vector   dense embeddings via Chroma          (the Phase 1 baseline)
    bm25     lexical keyword scoring via rank-bm25
    hybrid   the two merged by reciprocal rank fusion
    rerank   hybrid candidates re-scored by a cross-encoder
"""

import re
import sys

from src.index import embed_query, get_collection

DEFAULT_K = 5
DEFAULT_MODE = "vector"
MODES = ("vector", "bm25", "hybrid", "rerank")

# How deep to read each list before fusing. 30 is the brief's reranking depth, so
# the reranker later scores exactly the candidate set fusion produced.
FUSION_DEPTH = 30

# The damping constant from the original RRF paper (Cormack et al., 2009). Left at
# the published default deliberately: tuning it against these 56 questions would be
# fitting a constant to the test set and calling the result a measurement.
RRF_K = 60

# Cross-encoder for reranking. Unlike the bi-encoder used for indexing, this reads
# the query and the passage TOGETHER, so it can judge whether a passage actually
# answers the question rather than whether it lands nearby in vector space. That is
# also why it cannot be used for search itself: it scores one pair at a time, so
# running it over all 872 chunks per query is not affordable. It reranks a
# shortlist that cheaper retrieval has already narrowed.
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_DEPTH = FUSION_DEPTH

_reranker = None

# Tokens for BM25. Two shapes, in priority order:
#   \d[\d.,]*\d   a number, keeping its internal separators -- "5,00,000" and "2.2"
#                 must survive as single tokens, since splitting them on punctuation
#                 turns the corpus's most distinctive values into the meaningless
#                 fragments "5", "00", "000".
#   [a-z0-9]+     an ordinary alphanumeric run. Hyphenated words split here, so a
#                 query for "PM JAY" still matches a document writing "PM-JAY".
_TOKEN_RE = re.compile(r"\d[\d.,]*\d|[a-z0-9]+")

_bm25 = None


def tokenize(text):
    """Lowercase and split text the same way on both the query and the corpus side.

    Symmetry is the whole contract here. Dense retrieval has the opposite rule --
    the BGE prefix is query-side ONLY (see index.py) -- so the two are easy to
    confuse. For BM25 anything applied to one side must be applied to the other.
    """
    return _TOKEN_RE.findall(text.lower())


def load_bm25():
    """Build the BM25 index once per process, from the Chroma collection itself.

    Reading the corpus out of Chroma rather than re-reading chunks.jsonl is
    deliberate: it makes it structurally impossible for the lexical and dense
    retrievers to be searching different sets of chunks. Re-chunk without
    re-indexing and BM25 would otherwise quietly score text the vector side has
    never seen, and any hybrid comparison between them would be meaningless.

    No stopword list. BM25's IDF term already discounts words that appear
    everywhere, and a hand-written list is one more thing to get wrong.
    """
    global _bm25
    if _bm25 is None:
        from rank_bm25 import BM25Okapi

        stored = get_collection().get(include=["documents", "metadatas"])
        # Sorted so the corpus order -- and therefore tie-breaking between chunks
        # on equal scores -- is identical from run to run.
        records = sorted(
            zip(stored["ids"], stored["documents"], stored["metadatas"]),
            key=lambda r: r[0],
        )
        _bm25 = (BM25Okapi([tokenize(doc) for _, doc, _ in records]), records)
    return _bm25


def _hit(rank, chunk_id, text, meta, score):
    return {
        "rank": rank,
        "text": text,
        "source_file": meta["source_file"],
        "page": meta["page"],
        "chunk_id": chunk_id,
        "score": score,
    }


def vector_search(query, k=DEFAULT_K):
    """Top-k by embedding similarity -- the Phase 1 baseline, unchanged."""
    collection = get_collection()
    result = collection.query(
        query_embeddings=[embed_query(query)],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for rank, (chunk_id, doc, meta, dist) in enumerate(
        zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
        ),
        start=1,
    ):
        # Chroma returns cosine distance; similarity reads more naturally.
        hits.append(_hit(rank, chunk_id, doc, meta, 1 - dist))
    return hits


def bm25_search(query, k=DEFAULT_K):
    """Top-k by BM25 keyword score.

    Expected to beat embeddings exactly where embeddings are weakest: a rare term
    the dense model has no strong representation for. "PAN card" occurs in 2 of the
    872 chunks, which is nearly free for a lexical scorer to find and easy for a
    384-dimension embedding to blur into a crowd of vaguely administrative pages.

    Scores are raw BM25 -- unbounded and not comparable to the cosine similarities
    from vector_search. Nothing may compare the two numerically; that is precisely
    why the merge step uses rank fusion rather than score arithmetic.
    """
    bm25, records = load_bm25()
    scores = bm25.get_scores(tokenize(query))

    # Rank by score, breaking ties on chunk_id so the order is deterministic.
    order = sorted(range(len(records)), key=lambda i: (-scores[i], records[i][0]))

    hits = []
    for rank, i in enumerate(order[:k], start=1):
        chunk_id, doc, meta = records[i]
        hits.append(_hit(rank, chunk_id, doc, meta, float(scores[i])))
    return hits


def reciprocal_rank_fusion(ranked_lists, k=DEFAULT_K, rrf_k=RRF_K):
    """Merge several ranked lists by summing 1 / (rrf_k + rank) across them.

    Fusion happens on RANK, never on score, and that is the point. A cosine
    similarity of 0.69 and a BM25 score of 12.55 are numbers on different scales --
    one bounded, one unbounded and corpus-dependent -- so adding or weighting them
    directly requires a normalisation step that is itself a tuned parameter.
    Positions are comparable without one.

    The shape of the formula is what makes it work here: rrf_k (60) is large
    relative to the ranks in play, so the gap between rank 1 and rank 5 is small,
    and a chunk both retrievers rank moderately well beats a chunk one retriever
    loves and the other never returns. On this corpus the two disagree on 30 of 49
    answerable questions, so that agreement signal is the real content of the merge.
    """
    scores, seen, component_ranks = {}, {}, {}
    for name, hits in ranked_lists:
        for hit in hits:
            chunk_id = hit["chunk_id"]
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + hit["rank"])
            seen.setdefault(chunk_id, hit)
            component_ranks.setdefault(chunk_id, {})[name] = hit["rank"]

    # Ties broken on chunk_id so the output is deterministic run to run.
    order = sorted(scores, key=lambda cid: (-scores[cid], cid))

    fused = []
    for rank, chunk_id in enumerate(order[:k], start=1):
        hit = dict(seen[chunk_id])
        hit["rank"] = rank
        # NB: score is now an RRF score (~0.03), not a similarity. Nothing may
        # compare it numerically against a vector-mode score.
        hit["score"] = scores[chunk_id]
        # Kept for failure analysis: this shows which retriever actually found a
        # chunk, which is the difference between "fusion helped" and "fusion got
        # out of the way of the one retriever that already had it".
        hit["component_ranks"] = component_ranks[chunk_id]
        fused.append(hit)
    return fused


def hybrid_search(query, k=DEFAULT_K, depth=FUSION_DEPTH):
    """Vector and BM25 results, merged by reciprocal rank fusion."""
    return reciprocal_rank_fusion(
        [
            ("vector", vector_search(query, k=depth)),
            ("bm25", bm25_search(query, k=depth)),
        ],
        k=k,
    )


def load_reranker():
    """Load the cross-encoder once per process (first call downloads ~90 MB)."""
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(RERANK_MODEL)
    return _reranker


def rerank(query, hits, k=DEFAULT_K):
    """Re-score candidate hits with the cross-encoder and return the best k.

    Known limitation, stated rather than worked around: this model has a 512-token
    input window, and chunks here target ~600 tokens. The tail of a long chunk is
    therefore truncated and invisible to the reranker, so a chunk whose only
    relevant sentence sits at its end can be scored as though it were irrelevant.
    Splitting chunks to fit would change the indexing that the Phase 1 baseline was
    measured against, so it is left alone and recorded as a caveat instead.
    """
    if not hits:
        return []

    model = load_reranker()
    scores = model.predict([(query, hit["text"]) for hit in hits])

    # Ties broken on chunk_id so the output is deterministic run to run.
    order = sorted(range(len(hits)), key=lambda i: (-scores[i], hits[i]["chunk_id"]))

    reranked = []
    for rank, i in enumerate(order[:k], start=1):
        hit = dict(hits[i])
        # Keep the position this chunk held before reranking. Without it there is
        # no way to say whether the reranker moved anything or merely agreed with
        # the retriever it was handed.
        hit["pre_rerank_rank"] = hits[i]["rank"]
        hit["rank"] = rank
        # A cross-encoder logit, unbounded and negative for poor matches -- not a
        # similarity, and not comparable to any other mode's score.
        hit["score"] = float(scores[i])
        reranked.append(hit)
    return reranked


def rerank_search(query, k=DEFAULT_K, depth=RERANK_DEPTH):
    """Hybrid retrieval narrowed to `depth` candidates, then reranked to k.

    The candidate pool comes from fusion rather than from either retriever alone
    because fusion is what reaches every golden target: on this corpus hybrid
    recall@20 is 100%, against 98% for each component on its own. A reranker can
    only reorder what it is given, so pool recall is its hard ceiling.
    """
    return rerank(query, hybrid_search(query, k=depth), k=k)


def search(query, k=DEFAULT_K, mode=DEFAULT_MODE):
    """Return the top-k chunks for a query, best first.

    Each hit carries source_file and page so the answer can cite them.
    """
    if mode == "vector":
        return vector_search(query, k=k)
    if mode == "bm25":
        return bm25_search(query, k=k)
    if mode == "hybrid":
        return hybrid_search(query, k=k)
    if mode == "rerank":
        return rerank_search(query, k=k)
    raise ValueError(f"unknown retrieval mode {mode!r} -- expected one of {MODES}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: python -m src.retrieve [--mode MODE] "your question"')

    args = sys.argv[1:]
    mode = DEFAULT_MODE
    if args[0] == "--mode":
        mode = args[1]
        args = args[2:]

    query = " ".join(args)
    print(f"mode: {mode}")
    for hit in search(query, mode=mode):
        parts = hit.get("component_ranks")
        detail = f"  {parts}" if parts else ""
        print(f"\n[{hit['rank']}] {hit['source_file']} p.{hit['page']}  "
              f"(score {hit['score']:.4f}){detail}")
        print(hit["text"][:400].replace("\n", " "))


if __name__ == "__main__":
    main()
