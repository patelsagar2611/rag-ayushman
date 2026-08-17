"""Vector retrieval over the Chroma collection.

Phase 1 is dense retrieval only. BM25, reciprocal rank fusion and cross-encoder
reranking belong in Phase 2 -- and only after the baseline here has been measured,
or there is no way to say what they bought.
"""

import sys

from src.index import embed_query, get_collection

DEFAULT_K = 5


def search(query, k=DEFAULT_K):
    """Return the top-k chunks for a query, best first.

    Each hit carries source_file and page so the answer can cite them.
    """
    collection = get_collection()
    result = collection.query(
        query_embeddings=[embed_query(query)],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for rank, (doc, meta, dist) in enumerate(
        zip(result["documents"][0], result["metadatas"][0], result["distances"][0]), start=1
    ):
        hits.append(
            {
                "rank": rank,
                "text": doc,
                "source_file": meta["source_file"],
                "page": meta["page"],
                "chunk_id": result["ids"][0][rank - 1],
                # Chroma returns cosine distance; similarity reads more naturally.
                "score": 1 - dist,
            }
        )
    return hits


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: python -m src.retrieve "your question"')

    query = " ".join(sys.argv[1:])
    for hit in search(query):
        print(f"\n[{hit['rank']}] {hit['source_file']} p.{hit['page']}  (score {hit['score']:.3f})")
        print(hit["text"][:400].replace("\n", " "))


if __name__ == "__main__":
    main()
