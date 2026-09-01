"""Embed chunks and store them in a persistent Chroma collection.

Also the single source of truth for the embedding model and its query prefix --
retrieve.py imports both from here so the two sides can never drift apart.

Output: chroma/ (persistent, so re-runs do not re-embed)
"""

import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

CHUNKS = Path("data/processed/chunks.jsonl")
CHROMA_DIR = "chroma"
COLLECTION = "pmjay"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# BGE expects this prefix on the QUERY side only, never on documents. Getting it
# backwards -- or applying it to both -- quietly degrades retrieval without
# raising anything.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

EMBED_BATCH = 64
ADD_BATCH = 500

_embedder = None


def load_embedder():
    """Load the embedding model once per process (first call downloads ~133 MB)."""
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


def embed_documents(texts):
    """Embed passages for indexing -- no query prefix."""
    model = load_embedder()
    return model.encode(
        texts,
        batch_size=EMBED_BATCH,
        normalize_embeddings=True,
        show_progress_bar=True,
    ).tolist()


def embed_query(query):
    """Embed a search query -- prefix applied here and nowhere else."""
    model = load_embedder()
    return model.encode(
        QUERY_PREFIX + query,
        normalize_embeddings=True,
    ).tolist()


def get_collection():
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    # Embeddings are L2-normalised above, so cosine is the matching space.
    # Chroma defaults to l2, which would rank differently.
    return client.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def load_chunks():
    if not CHUNKS.exists():
        raise SystemExit(f"{CHUNKS} not found -- run `python -m src.chunk` first")
    with CHUNKS.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


# Printed after every successful re-index. The committed index is hidden from git
# with skip-worktree, because merely OPENING the collection rewrites the sqlite
# file and the HNSW segment -- so without it, every run of the app or the eval
# leaves a 16 MB binary looking modified, and one absent-minded `git add -A` puts
# it into history permanently.
#
# The cost of that fix is exactly this: a REAL re-index is hidden too. So the
# instruction lives here, printed by the tool that creates the situation, rather
# than only in a document someone has to remember to consult. The same steps are
# in the README under "Re-indexing".
REINDEX_REMINDER = """
NOTE: the index is hidden from git (skip-worktree), so this re-index is INVISIBLE
to `git status`. To commit it:

    git ls-files -z chroma/ | xargs -0 git update-index --no-skip-worktree
    git add chroma/ && git commit -m "re-index"
    git ls-files -z chroma/ | xargs -0 git update-index --skip-worktree

Re-hide it afterwards, or every later run will show the index as modified again.
"""


def main():
    chunks = load_chunks()
    collection = get_collection()

    existing = set(collection.get(include=[])["ids"])
    pending = [c for c in chunks if c["chunk_id"] not in existing]

    print(f"{len(chunks)} chunks, {len(existing)} already indexed, {len(pending)} to embed")
    if not pending:
        print("nothing to do")
        return

    embeddings = embed_documents([c["text"] for c in pending])

    for i in range(0, len(pending), ADD_BATCH):
        batch = pending[i : i + ADD_BATCH]
        collection.add(
            ids=[c["chunk_id"] for c in batch],
            documents=[c["text"] for c in batch],
            embeddings=embeddings[i : i + ADD_BATCH],
            metadatas=[
                {
                    "source_file": c["source_file"],
                    "page": c["page"],
                    "char_start": c["char_start"],
                }
                for c in batch
            ],
        )
        print(f"added {min(i + ADD_BATCH, len(pending))}/{len(pending)}")

    print(f"\ncollection '{COLLECTION}' now holds {collection.count()} chunks in {CHROMA_DIR}/")
    print(REINDEX_REMINDER)


if __name__ == "__main__":
    main()
