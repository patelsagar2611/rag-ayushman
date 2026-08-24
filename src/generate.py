"""Answer a question from retrieved chunks, with citations, via a local Ollama model.

The prompt text lives in config/prompts.yaml, not here. Prompt edits and retrieval
changes move the same generation metrics, so the prompt carries a version number
that every results file records -- otherwise a reranking gain and a prompt tweak
made the same afternoon are indistinguishable after the fact.
"""

import os
import sys
from pathlib import Path

import requests
import yaml

from src.retrieve import DEFAULT_K, search

PROMPTS_PATH = Path(os.getenv("PMJAY_PROMPTS", "config/prompts.yaml"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

def load_prompts(path=PROMPTS_PATH):
    """Read the prompt config, failing loudly if it is missing or unversioned.

    An unversioned prompt is worse than a hardcoded one: it looks configurable
    while making the results files that reference it untraceable.
    """
    if not path.exists():
        raise SystemExit(f"{path} not found -- the prompt config is not optional")

    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = {"version", "abstain", "system", "source_block", "template"} - set(config)
    if missing:
        raise SystemExit(f"{path} is missing required key(s): {sorted(missing)}")
    return config


PROMPTS = load_prompts()
PROMPT_VERSION = PROMPTS["version"]

# The decline string, defined once in the config. src/generate emits it and
# eval/run_eval compares against it; if the two ever drifted, every correct
# abstention would score as a wrong answer.
ABSTAIN = PROMPTS["abstain"]

# Substituted into rule 3 so the instruction and the string the eval matches
# cannot diverge.
SYSTEM_PROMPT = PROMPTS["system"].format(abstain=ABSTAIN)


def build_prompt(question, hits):
    """Number each chunk with its file and page so the model can cite them."""
    blocks = [
        PROMPTS["source_block"].format(
            rank=hit["rank"],
            source_file=hit["source_file"],
            page=hit["page"],
            text=hit["text"],
        )
        for hit in hits
    ]
    return PROMPTS["template"].format(
        system=SYSTEM_PROMPT,
        sources="\n\n".join(blocks),
        question=question,
    )


# Ollama reports every duration in NANOSECONDS.
NS_PER_MS = 1_000_000


def parse_stats(payload):
    """Pull Ollama's latency breakdown out of a /api/generate response.

    The two halves of generation time have opposite fixes, and a single total
    cannot tell them apart:

      prompt_eval_duration  ingesting the prompt, i.e. the retrieved chunks. If
                            this dominates, send fewer or smaller chunks.
      eval_duration         producing the answer tokens. If this dominates, cap
                            num_predict harder, or move to a smaller model.

    load_duration is model load. The eval's warmup call exists to keep it out of
    the per-question numbers; capturing it is how we confirm that held, and how a
    mid-run eviction (gotcha 6) shows up as itself rather than as slow generation.

    Read defensively -- a fully cached prompt can come back with the prompt_eval
    keys absent rather than zeroed.
    """
    def ms(key):
        return payload.get(key, 0) / NS_PER_MS

    stats = {
        "total_ms": ms("total_duration"),
        "load_ms": ms("load_duration"),
        "prompt_eval_ms": ms("prompt_eval_duration"),
        "prompt_eval_tokens": payload.get("prompt_eval_count", 0),
        "eval_ms": ms("eval_duration"),
        "eval_tokens": payload.get("eval_count", 0),
    }
    # Throughput is the actionable form: "3 tok/s generating" says more about
    # where a 127 s question went than the raw duration does.
    for half in ("prompt_eval", "eval"):
        duration, tokens = stats[half + "_ms"], stats[half + "_tokens"]
        stats[half + "_tps"] = tokens / (duration / 1000) if duration else 0.0
    return stats


def call_ollama(prompt):
    """Return (answer_text, stats); see parse_stats for what stats carries."""
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            # Ollama unloads an idle model after 5 minutes by default. Mid-eval
            # that means a cold reload -- ~2.5 minutes for a 7B model on CPU --
            # which blew past the old 300s timeout and killed a whole run.
            "keep_alive": "30m",
            "options": {
                # Deterministic, so eval runs are comparable across changes.
                "temperature": 0,
                # Five chunks of ~600 tokens overruns Ollama's 4096 default, which
                # would silently drop the sources at the front of the prompt.
                "num_ctx": 8192,
                # Cap the answer. Uncapped, the model can enumerate for 1000+
                # tokens -- minutes at CPU speed -- and one verbose answer then
                # dominates the runtime of a whole eval. A cited answer needs
                # nothing like this much room.
                "num_predict": 512,
            },
        },
        # Generous enough to survive one cold reload on top of generation.
        timeout=900,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["response"].strip(), parse_stats(payload)


def answer_from_hits(question, hits):
    """Generate from chunks that have already been retrieved.

    Split out so the eval harness can score retrieval and generation against the
    same single retrieval, rather than searching twice and risking the chunks it
    scored citations against not being the chunks the model actually saw.

    Returns (answer_text, stats) -- callers that do not want the timings discard
    them explicitly, which is better than the module hiding them in global state.
    """
    if not hits:
        return ABSTAIN, {}
    return call_ollama(build_prompt(question, hits))


def answer(question, k=DEFAULT_K):
    """Return (answer_text, hits, stats). hits let the UI show the evidence."""
    hits = search(question, k=k)
    text, stats = answer_from_hits(question, hits)
    return text, hits, stats


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: python -m src.generate "your question"')

    question = " ".join(sys.argv[1:])
    text, hits, stats = answer(question)

    print(f"\n{text}\n")
    print("-" * 70)
    for hit in hits:
        print(f"[{hit['rank']}] {hit['source_file']} p.{hit['page']}  (score {hit['score']:.3f})")

    if stats:
        print("-" * 70)
        print(f"prompt eval {stats['prompt_eval_ms'] / 1000:8.1f}s  "
              f"{stats['prompt_eval_tokens']:5d} tok  {stats['prompt_eval_tps']:6.1f} tok/s")
        print(f"generation  {stats['eval_ms'] / 1000:8.1f}s  "
              f"{stats['eval_tokens']:5d} tok  {stats['eval_tps']:6.1f} tok/s")
        print(f"model load  {stats['load_ms'] / 1000:8.1f}s")
        print(f"total       {stats['total_ms'] / 1000:8.1f}s")


if __name__ == "__main__":
    main()
