"""Answer a question from retrieved chunks, with citations, via a local or hosted LLM.

The prompt text lives in config/prompts.yaml, not here. Prompt edits and retrieval
changes move the same generation metrics, so the prompt carries a version number
that every results file records -- otherwise a reranking gain and a prompt tweak
made the same afternoon are indistinguishable after the fact.
"""

import os
import re
import sys
import time
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

# Reads .env if present. The API key lives there and .env is gitignored; nothing
# in this module ever holds a key as a literal.
load_dotenv()

from src.retrieve import DEFAULT_K, DEFAULT_MODE, MODES, SCORE_LABELS, search

PROMPTS_PATH = Path(os.getenv("PMJAY_PROMPTS", "config/prompts.yaml"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

# Which backend answers. "ollama" is the local baseline and the only source of a
# true prefill/decode split; "openai" is any OpenAI-compatible chat endpoint,
# defaulting to Groq. Recorded in every generation results file (decision 26).
#
# Ollama stays the default deliberately. A hosted model is a DIFFERENT model, so
# switching the default would silently change what every unqualified `run_eval`
# measures.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
PROVIDERS = ("ollama", "openai")

# OpenAI-compatible settings. Base URL is a variable so the same adapter reaches
# Groq, OpenRouter, Together or a local vLLM without a code change.
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "openai/gpt-oss-120b")
OPENAI_API_KEY = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")

# The model actually in play, for the results `config` block. Reading OLLAMA_MODEL
# there would mislabel every hosted run.
LLM_MODEL = OLLAMA_MODEL if LLM_PROVIDER == "ollama" else OPENAI_MODEL

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


def parse_openai_stats(payload, elapsed_ms):
    """Map an OpenAI-compatible `usage` block onto the same stats shape as Ollama.

    Same keys as parse_stats so the eval, the CLI and the app read one shape
    regardless of who generated. Providers vary in what they report:

      Groq returns prompt_time / completion_time / queue_time, so the
      prefill-vs-decode split survives.
      Others return token COUNTS only. Those come back as 0.0 ms with real token
      counts rather than as an invented split -- a fabricated prefill number
      would quietly corrupt the one measurement (section 3a.2) this project has
      actually built an argument on.

    queue_ms has no local equivalent. It is time spent waiting for a slot on a
    shared endpoint, so it belongs to the provider's load rather than to this
    system, and it is kept separate rather than folded into either half.
    """
    usage = payload.get("usage") or {}

    def ms(key):
        value = usage.get(key)
        return float(value) * 1000 if value else 0.0

    stats = {
        # Wall clock measured here, because a provider that reports no timing at
        # all would otherwise report a total of zero for a call that took a second.
        "total_ms": ms("total_time") or elapsed_ms,
        # No model to load: a hosted endpoint keeps it resident. Zero is the honest
        # value, not a missing one.
        "load_ms": 0.0,
        "queue_ms": ms("queue_time"),
        "prompt_eval_ms": ms("prompt_time"),
        "prompt_eval_tokens": usage.get("prompt_tokens", 0),
        "eval_ms": ms("completion_time"),
        "eval_tokens": usage.get("completion_tokens", 0),
    }
    for half in ("prompt_eval", "eval"):
        duration, tokens = stats[half + "_ms"], stats[half + "_tokens"]
        stats[half + "_tps"] = tokens / (duration / 1000) if duration else 0.0
    return stats


# Retried on: 429 (free tiers rate-limit, and 69 sequential questions will hit it)
# and 5xx. A dropped question is not merely a lost data point -- design decision 10
# excludes errored questions from generation metrics, so an un-retried 429 silently
# shrinks the denominator instead of showing up as a failure.
RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 5

# --- Proactive pacing -------------------------------------------------------
#
# Retrying after a 429 is the obvious strategy and the wrong one, because on this
# provider EVERY REQUEST COUNTS -- including the ones that come back 429. A run
# that retries its way through a rate limit burns three to five times its question
# count against the daily request budget. Drain that budget and retry-after jumps
# from ~15 seconds to several hundred, so the failure compounds: retries cause
# exhaustion, exhaustion causes longer retries.
#
# So we pace instead. The provider reports what is left and when it resets on every
# response; read that and wait BEFORE sending a request that would be refused. Same
# wall-clock time as retrying, but no wasted requests and no cascade.
#
# Reactive retry is kept below as a backstop for the cases pacing cannot predict --
# a burst from another process sharing the key, or a 5xx.
_rate = {"tokens_left": None, "tokens_reset_s": 0.0,
         "requests_left": None, "requests_reset_s": 0.0}

# Groq reports durations as "622ms", "1m26.4s", "1h49m26.4s".
_DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?$")


def parse_reset(value):
    """Seconds until a rate-limit window resets, from the provider's own format."""
    if not value:
        return 0.0
    m = _DURATION_RE.match(value.strip())
    if not m:
        return 0.0
    h, mins, secs, ms = m.groups()
    return (int(h or 0) * 3600 + int(mins or 0) * 60
            + float(secs or 0) + float(ms or 0) / 1000)


def note_limits(headers):
    """Record what the provider just told us about remaining budget."""
    def num(key):
        try:
            return int(headers.get(key))
        except (TypeError, ValueError):
            return None
    _rate["tokens_left"] = num("x-ratelimit-remaining-tokens")
    _rate["requests_left"] = num("x-ratelimit-remaining-requests")
    _rate["tokens_reset_s"] = parse_reset(headers.get("x-ratelimit-reset-tokens"))
    _rate["requests_reset_s"] = parse_reset(headers.get("x-ratelimit-reset-requests"))


# Roughly what one question costs: ~2.4k prompt tokens plus the answer. Used only
# to decide whether the next call fits in the remaining budget, so an overestimate
# is the safe direction -- it waits slightly too often rather than too rarely.
TOKENS_PER_CALL = 3200


def pace():
    """Wait until the next request will not be refused."""
    left, reset = _rate["tokens_left"], _rate["tokens_reset_s"]
    if left is not None and left < TOKENS_PER_CALL and reset > 0:
        time.sleep(reset + 0.5)
        # The window has rolled over; the next response will refresh this.
        _rate["tokens_left"] = None


def call_openai_compatible(prompt):
    """Return (answer_text, stats) from an OpenAI-compatible chat endpoint.

    The prompt is sent as ONE user message rather than split into system + user
    turns. That is deliberate: prompts v1 is byte-identical to the phase-1 tag
    (decision 17), and re-cutting it into roles would change the text the model
    sees, so a hosted-vs-local difference could no longer be attributed to the
    model. One message keeps the bytes identical to what Ollama receives.

    No num_ctx equivalent is needed -- the hosted context windows here are ~131k
    against the ~2.4k these prompts actually use, so gotcha 7's silent front-
    truncation cannot happen.
    """
    if not OPENAI_API_KEY:
        raise SystemExit(
            "No API key. Put GROQ_API_KEY=... in .env (gitignored) or set it in "
            "the environment. See .env.example."
        )

    delay = 2.0
    for attempt in range(MAX_RETRIES):
        pace()
        started = time.perf_counter()
        response = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                # Matches the Ollama call so the two differ only by model.
                "temperature": 0,
                # NOT 512, unlike Ollama's num_predict, and the difference is
                # deliberate. Reasoning models bill their chain of thought against
                # this same budget, so an equal NUMBER is not an equal answer
                # budget. At 512, openai/gpt-oss-120b spent the whole allowance
                # reasoning on one question and returned empty content -- an answer
                # that silently scored as a wrong answer rather than as an error.
                # Matching the local number would be matching the label, not the
                # thing the label refers to.
                "max_tokens": 1536,
            },
            timeout=180,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        note_limits(response.headers)

        # A DAILY quota is not a transient condition and retrying it is pure waste --
        # every retry is itself a billed request, and the wait is measured in hours.
        # This limit appears in NO response header; the 429 body is the only place it
        # is ever stated, which is why pacing against the per-minute headers cannot
        # see it coming. Fail immediately and say what to do.
        if response.status_code == 429 and "per day" in response.text:
            raise SystemExit(
                f"Daily quota exhausted on {OPENAI_MODEL}. Retrying will not help: "
                "every retry is itself a billed request and the reset is hours away. "
                "Wait for the reset, point OPENAI_BASE_URL and OPENAI_MODEL at another "
                f"provider, or upgrade the tier. Provider said: {response.text[:240]}"
            )

        if response.status_code in RETRY_STATUSES and attempt < MAX_RETRIES - 1:
            # Honour the provider's own backoff when it sends one.
            wait = float(response.headers.get("retry-after", delay))
            print(f"[{response.status_code}; retry in {wait:.0f}s]", end="", flush=True)
            time.sleep(wait)
            delay *= 2
            continue

        # A Cloudflare bot-block returns 403 with a text/plain "error code: 1010"
        # body and looks exactly like an auth failure. Say so, because the wrong
        # theory here costs an hour (gotcha 23).
        if response.status_code == 403 and "1010" in response.text:
            raise SystemExit(
                "Cloudflare blocked this client (error 1010) -- this is NOT an "
                "invalid key. Something about the HTTP client was fingerprinted; "
                "requests works where urllib does not."
            )
        response.raise_for_status()
        break

    payload = response.json()
    message = payload["choices"][0]["message"]
    text = (message.get("content") or "").strip()

    # Empty content means the model produced no answer at all -- typically the
    # whole token budget went to reasoning. Scored naively this looks like a wrong
    # answer, which is worse than an error: design decision 10 excludes errors from
    # the metrics precisely so infrastructure problems cannot masquerade as quality
    # regressions. Raise, so the eval records it as an error instead.
    if not text:
        raise RuntimeError(
            f"{OPENAI_MODEL} returned empty content "
            f"({payload.get('usage', {}).get('completion_tokens', 0)} completion tokens, "
            f"max_tokens={1536}) -- the token budget was consumed before any answer."
        )

    # Some reasoning models emit chain-of-thought INLINE in content instead of in a
    # separate field. That would flow straight into outcome.answer and corrupt
    # citation parsing, must_contain and abstention detection at once. Fail loudly
    # rather than silently scoring the model's thinking. qwen/qwen3.6-27b on Groq
    # does exactly this, which is why it is not the default despite being the
    # closest relative of the local qwen2.5:7b baseline.
    if "<think>" in text:
        raise SystemExit(
            f"{OPENAI_MODEL} emitted an inline <think> block. This model is not "
            "usable with this harness unmodified -- its reasoning would be scored "
            "as the answer. Pick a model that keeps content clean."
        )

    return text, parse_openai_stats(payload, elapsed_ms)


def call_llm(prompt):
    """Dispatch to the configured backend."""
    if LLM_PROVIDER == "ollama":
        return call_ollama(prompt)
    if LLM_PROVIDER == "openai":
        return call_openai_compatible(prompt)
    raise SystemExit(f"unknown LLM_PROVIDER {LLM_PROVIDER!r} -- expected one of {PROVIDERS}")


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
    return call_llm(build_prompt(question, hits))


def answer(question, k=DEFAULT_K, mode=DEFAULT_MODE):
    """Return (answer_text, hits, stats). hits let the UI show the evidence.

    `mode` is a parameter rather than a constant so the product can reach every
    retrieval mode the eval can. Without it the four Phase 2 retrievers were
    measurable but not usable: the eval calls search() directly, while this
    function -- and therefore the CLI and the Streamlit app -- stayed on Phase 1
    dense retrieval regardless. A harness that scores a path the app never takes
    is measuring a different build than the one being shipped.

    The default stays DEFAULT_MODE (vector) deliberately. Reranking is a large
    RETRIEVAL win, but nothing yet shows it produces better ANSWERS, and changing
    what the product does by default for an unmeasured reason is what design
    decision 21 rules out. Revisit once the generation runs exist.
    """
    hits = search(question, k=k, mode=mode)
    text, stats = answer_from_hits(question, hits)
    return text, hits, stats


USAGE = 'usage: python -m src.generate [--mode MODE] "your question"'


def main():
    # The Windows console is cp1252 and cannot encode the private-use glyphs PDF
    # extraction leaves behind -- printing one killed this command mid-output. Same
    # remedy as eval/find.py, but applied inside main() rather than at import: this
    # module is imported by app.py and the eval, and reconfiguring their stdout as a
    # side effect of an import is not this function's business.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) < 2:
        raise SystemExit(USAGE)

    # Parsed exactly as src.retrieve's CLI parses it, so both entry points take the
    # same flag in the same position.
    args = sys.argv[1:]
    mode = DEFAULT_MODE
    if args[0] == "--mode":
        mode = args[1] if len(args) > 1 else ""
        args = args[2:]
    if mode not in MODES:
        raise SystemExit(f"unknown retrieval mode {mode!r} -- expected one of {MODES}")
    if not args:
        raise SystemExit(USAGE)

    question = " ".join(args)
    text, hits, stats = answer(question, mode=mode)

    # Both variables that decide what comes back, printed where the answer is read.
    print(f"mode: {mode}   llm: {LLM_PROVIDER}/{LLM_MODEL}")

    print(f"\n{text}\n")
    print("-" * 70)
    # Labelled with what the number actually is -- a cosine similarity in vector
    # mode, an RRF score in hybrid, a cross-encoder logit in rerank. A bare "score"
    # invites comparing values across modes, which is meaningless (gotcha 15).
    label = SCORE_LABELS[mode]
    for hit in hits:
        print(f"[{hit['rank']}] {hit['source_file']} p.{hit['page']}  "
              f"({label} {hit['score']:.3f})")

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
