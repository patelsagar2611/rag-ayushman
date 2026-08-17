"""Answer a question from retrieved chunks, with citations, via a local Ollama model.

The prompt lives inline here on purpose. Moving it to a versioned config/prompts.yaml
is Phase 2 work -- Phase 1 is meant to be end-to-end and ugly, not configurable.
"""

import os
import sys

import requests

from src.retrieve import DEFAULT_K, search

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

ABSTAIN = "I cannot answer this from the provided sources."

SYSTEM_PROMPT = f"""You answer questions about India's Ayushman Bharat PM-JAY scheme \
using ONLY the numbered sources provided below.

Rules:
1. Every factual claim must be followed by a citation in square brackets naming the \
source number, e.g. [2]. Cite more than one where more than one supports the claim.
2. Use ONLY what the sources state. Do not add background knowledge, and do not infer \
beyond what is written.
3. If the sources do not contain the answer, reply with exactly this and nothing else: \
{ABSTAIN}
4. Quote exact figures, percentages and time limits verbatim rather than paraphrasing them.
5. Where sources disagree, say so explicitly and cite each side."""


def build_prompt(question, hits):
    """Number each chunk with its file and page so the model can cite them."""
    blocks = []
    for hit in hits:
        blocks.append(
            f"[{hit['rank']}] {hit['source_file']}, page {hit['page']}\n{hit['text']}"
        )
    sources = "\n\n".join(blocks)
    return f"{SYSTEM_PROMPT}\n\nSOURCES:\n\n{sources}\n\nQUESTION: {question}\n\nANSWER:"


def call_ollama(prompt):
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                # Deterministic, so eval runs are comparable across changes.
                "temperature": 0,
                # Five chunks of ~600 tokens overruns Ollama's 4096 default, which
                # would silently drop the sources at the front of the prompt.
                "num_ctx": 8192,
            },
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["response"].strip()


def answer_from_hits(question, hits):
    """Generate from chunks that have already been retrieved.

    Split out so the eval harness can score retrieval and generation against the
    same single retrieval, rather than searching twice and risking the chunks it
    scored citations against not being the chunks the model actually saw.
    """
    if not hits:
        return ABSTAIN
    return call_ollama(build_prompt(question, hits))


def answer(question, k=DEFAULT_K):
    """Return (answer_text, hits). hits are returned so the UI can show the evidence."""
    hits = search(question, k=k)
    return answer_from_hits(question, hits), hits


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: python -m src.generate "your question"')

    question = " ".join(sys.argv[1:])
    text, hits = answer(question)

    print(f"\n{text}\n")
    print("-" * 70)
    for hit in hits:
        print(f"[{hit['rank']}] {hit['source_file']} p.{hit['page']}  (score {hit['score']:.3f})")


if __name__ == "__main__":
    main()
