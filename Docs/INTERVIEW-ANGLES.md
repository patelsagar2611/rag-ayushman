# Interview Angles — the project's engineering journal

**Purpose.** This is the single document to re-read before an interview. Every non-obvious
problem this project hit is recorded here with the reasoning that resolved it, so the whole
journey can be recovered in one pass without re-reading the code or the handoff.

**Why this exists separately from [HANDOFF.md](HANDOFF.md).** The handoff records *what the
state is* — a reader who needs to continue the work. This file records *why the state is what
it is* — a reader who needs to defend the work. Same events, different question. The handoff
answers "what do I do next"; this answers "why did you do it that way, and what did you
consider instead."

## Format — every entry has four parts

1. **The scenario** — the problem, optimisation, or trap, stated concretely.
2. **How we got to the answer** — the reasoning, including what was rejected and why.
3. **Defensive argument** — the answer if an interviewer challenges this directly.
4. **Show-off argument** — how to *raise it unprompted* from a natural opening, plus the
   opening that gets you there.

## Two rules for using this honestly

**Claim only what was actually done.** Every entry below happened and is verifiable in the
repo. Do not upgrade "I considered" into "I built", or "measured once" into "benchmarked".
An interviewer who catches one inflated claim discounts everything else you said.

**State the limitation before you are asked.** Several entries below end in a known-open
weakness. Naming it yourself reads as rigour; being caught not knowing it reads as the
opposite. The strongest version of every answer here includes what it does *not* establish.

---

# 1. Model provider as configuration, not code

**The scenario.** The project needed to compare several LLMs on the same evaluation. The
naive structure — a branch per vendor — turns "add a model" into a code change, a review, and
a new bug surface.

**How we got to the answer.** The generation module has one adapter for *any* OpenAI-compatible
endpoint, with base URL and model name read from environment variables. Most vendors expose
an OpenAI-compatible surface, so one adapter reaches Groq, OpenRouter, Together, or a local
vLLM. Swapping models became editing a config line. The trade-off accepted: vendor-specific
features outside the common surface are unreachable — acceptable, because this project uses
only chat completion, temperature, and a token cap.

**Defensive argument.** "Provider is a variable, not a branch. The evaluation harness doesn't
know which vendor answered — it only knows it got text back. That's what made a four-model
comparison a configuration exercise instead of a refactor. The cost is that anything outside
the common API surface isn't reachable, and I checked I didn't need it before committing."

**Show-off argument.** Openings: *"tell me about a design decision you're happy with"*, or any
question about extensibility or avoiding vendor lock-in.
> "The one I'd point at is deliberately boring. Early on I made the LLM provider a config
> variable rather than a code path. It looked like over-engineering for a single-model
> project. Then the requirement became 'benchmark four models' and it cost nothing —
> whereas the branching version would have meant a refactor before I could even start
> measuring. Boring decisions compound."

---

# 2. Never trust a model name from a document — query the API

**The scenario.** Documentation, blog posts, and even the project's own handoff name specific
models and prices. All of them go stale, and a stale model id fails in ways that look like
code bugs.

**How we got to the answer.** The rule written into the handoff is blunt: *do not trust a
model name from a document, including this one.* The procedure is to query the provider's
live `/models` endpoint and decide from what comes back. This session that returned 360
models with current pricing attached — data that could be filtered and costed directly,
rather than a name someone wrote down months earlier.

**Defensive argument.** "Model availability and pricing change faster than any document I
could maintain, so I stopped maintaining one. The selection procedure queries the live API
and filters programmatically. That means the process stays correct even when every specific
name in my notes has expired."

**Show-off argument.** Openings: *"how do you keep up with how fast this field moves?"*, or
anything about documentation drift.
> "I hit this maintaining my own notes. I'd written down model names and prices, and they
> were wrong within weeks. So I inverted it — the docs record the *procedure* for choosing a
> model, and explicitly say not to trust any name in them, including their own. Documents
> should encode decision processes, not facts with short half-lives."

---

# 3. Model ids are moving pointers — the reproducibility trap

**The scenario.** An existing project rule rejected model names ending in `-latest`, because
aliases change underneath a benchmark. Checking the aggregator's metadata revealed that
*ordinary-looking* ids are aliases too:

```
anthropic/claude-opus-5       ->  anthropic/claude-opus-5-20260723
google/gemini-3.1-flash-lite  ->  google/gemini-3.1-flash-lite-20260507
openai/gpt-5-mini             ->  openai/gpt-5-mini-2025-08-07
```

**How we got to the answer.** There is no suffix to filter on — the filter written to enforce
the existing rule did **not** catch these. They were found by querying each model's
`canonical_slug`. The fix is to pin the dated form everywhere. Without it, re-running the
benchmark later measures a different model while reporting the same name — a result that
looks reproducible and is not.

**Defensive argument.** "Reproducibility isn't just pinning a version — it's verifying that
what you pinned is actually a version rather than a pointer. My rule said reject `-latest`
aliases. That rule was right in principle and incomplete in practice, because the aggregator's
plain names are aliases too. I only found it by checking the metadata rather than assuming
the id was the identity."

**Show-off argument.** Openings: *"how do you make ML experiments reproducible?"*, *"tell me
about a subtle bug"*, or anything on versioning.
> "There's one that would have silently invalidated my benchmark months later. I pinned model
> ids, thinking that was enough. It wasn't — the plain ids are aliases over dated snapshots,
> so the vendor ships a new one and your 'pinned' benchmark quietly measures something else
> while reporting the old name. Nothing errors. You just can't reproduce a number and you
> don't know why. I now pin the dated slug and verify it against the API's canonical field."

---

# 4. A cost model that broke on reasoning models

**The scenario.** Before spending money, projected cost per evaluation run was computed from
measured token usage: ~2,400 input and ~32 output tokens per question. The formula gave
cents-per-run and made the experiment look trivially affordable.

**How we got to the answer.** A single trial call against a reasoning model returned an
~80-word answer while billing **1,495 output tokens**. Reasoning models generate a private
chain of thought and bill it as output. The 32-token figure was measured on non-reasoning
models and did not transfer — the estimate was **5× low**. Rebuilt the projection from
observed per-model usage instead of one global constant.

**Defensive argument.** "My cost model was measured, but measured on the wrong population. It
assumed output tokens ≈ answer length, which stopped being true when reasoning models bill
hidden thinking as output. I caught it because I sent one real request before committing to
a full run — the estimate was five times low. The lesson isn't 'estimate better', it's that a
constant derived from one model class shouldn't be applied across classes without a check."

**Show-off argument.** Openings: *"how do you think about LLM costs?"*, *"a time your estimate
was wrong"*, or anything about reasoning models.
> "Something people miss on reasoning models: you pay for tokens you never see. I'd built a
> cost projection from measured usage — about 32 output tokens per answer. Then a reasoning
> model billed 1,495 tokens for a two-sentence answer, because the chain of thought counts as
> output. My estimate was 5× low. It's a good example of a measured number that's still
> wrong, because it was measured on a population that didn't include the case I was applying
> it to."

---

# 5. Model selection as a ladder with a control, not a leaderboard

**The scenario.** Choosing 3–4 models to benchmark. The obvious move is to pick the four
best-rated ones.

**How we got to the answer.** That would have been wrong given what the experiment asks. The
project's headline finding is that improving retrieval helped a hosted model's attribution
and *hurt* a local 7B model's, with the hypothesis that weak models get confused by
near-duplicate retrieved chunks while capable ones aren't. Testing that needs a **spread of
capability** — four top models all sit on the same side of the hypothesis and discriminate
nothing. So the slate is a ladder: a weak model, a light hosted model, a mid model, and a
frontier model, with the weak rung chosen as a *control* from the same family as the local
baseline.

**Defensive argument.** "I picked models to test a hypothesis, not to find a winner. The open
question was whether a specific failure mode is a weak-model artifact, so the selection needed
capability spread — including a deliberately weak rung. Four frontier models would have
produced a nice-looking table that answered nothing."

**Show-off argument.** Openings: *"how did you evaluate models?"*, *"how do you design an
experiment?"*
> "The part I'd defend hardest is that I deliberately included a weak model. My finding was
> that better retrieval made answers *worse* on a small local model and better on a hosted
> one — so the question was whether that's a weak-model failure mode. That only has an answer
> if the slate spans capability. Benchmarking the four best models would have been the
> intuitive move and would have told me nothing about the actual question."

---

# 6. The quantisation confound

**The scenario.** The local baseline runs through Ollama, which serves a *quantised*
(compressed) copy of the model. So when the local model attributed poorly, there were two
live explanations: the model is weak, or the compression degraded it. They were tangled, and
the project's headline claim rests on the distinction.

**How we got to the answer.** Add a control: run the *same model family, unquantised*, via
API. If the penalty reproduces, it's the model. If it disappears, it was compression. The
honest limitation — recorded rather than hidden — is that the API copy may differ in other
ways too, so this **narrows** the confound without eliminating it.

**Defensive argument.** "Running locally through Ollama means running a quantised model, so
'the model is weak' and 'the quantisation hurt it' predict the same observation. My headline
claim depends on telling them apart, so I added an unquantised control from the same family.
It narrows the confound rather than closing it — the served copy could still differ in ways I
can't see — and I state that limitation rather than claiming a clean separation."

**Show-off argument.** Openings: *"what would you do differently?"*, *"what are the limitations
of your results?"*, or any mention of local models.
> "One thing I'd flag about my own result: my local baseline runs quantised through Ollama.
> So when it underperformed, 'small model' and 'compressed model' were confounded, and my
> headline finding depends on separating them. I added an unquantised control from the same
> family. It's an improvement, not a proof — and I'd rather state that than present it as
> cleaner than it is."

---

# 7. Recording *who* served the request, not just which model

**The scenario.** Aggregators route a single model id across several upstream providers, which
can differ in quantisation and output formatting. So the model name no longer fully identifies
what produced the answer.

**How we got to the answer.** An existing project rule requires results files to record
everything that influenced the numbers. Under an aggregator, that now includes the upstream
provider. Added a `served_by` field captured from the response. The asymmetry is deliberate:
**recording is unconditional, pinning is optional** — if you pin a provider and it goes down,
the run should fail loudly rather than silently swap deployments mid-benchmark.

**Defensive argument.** "Under an aggregator the model id isn't the full identity of what
answered — the same id routes across upstreams that can differ in quantisation. My results
files record the serving provider for every run. I made recording mandatory but pinning
optional, because a pinned provider failing should stop the run, while an unrecorded provider
swap would corrupt it invisibly. Loud failure beats silent drift."

**Show-off argument.** Openings: *"what goes into your experiment logs?"*, *"how do you handle
third-party dependencies?"*
> "A subtlety with model aggregators: one model id can be served by several different
> upstreams, and they're not always identical deployments. So I log which provider actually
> answered, not just which model I asked for. Otherwise two runs that name the same model
> might be two different deployments, and you'd never see it in the results file."

---

# 8. An output-format gate before spending money

**The scenario.** The evaluation parses citations out of answers as `[1]`, `[2]`. A model that
formats citations differently scores near-zero on the headline metric — and nothing in the
output explains why.

**How we got to the answer.** This bit the project **twice**: one model emitted CJK bracket
citations `【1】`, another a dagger form `【2†L1-L3】`. So the selection procedure now requires
sending **one real corpus prompt** through each candidate before any paid run, and checking
three things: citations parse, the abstention string matches byte-for-byte, and the fact-check
substring still matches. Output shape is prompt-dependent, so sampling a few generic calls is
not enough — it has to be a real prompt from the actual pipeline.

**Defensive argument.** "My citation metric depends on a specific output format, which makes
it a silent failure: a model with different formatting scores zero and looks like a quality
problem rather than a parsing problem. It caught me twice before I made it a gate. Now every
candidate gets one real corpus prompt checked for format before it's eligible for a paid run.
It costs a fraction of a cent and it has never not been worth it."

**Show-off argument.** Openings: *"how do you validate an LLM pipeline?"*, *"tell me about a
failure that was hard to diagnose"*
> "My favourite bug class here is the metric that fails silently. My eval parses citations as
> square brackets. A model that cites with CJK brackets instead scores zero — and the failure
> looks exactly like 'this model is bad at attribution' rather than 'my regex doesn't match'.
> It happened twice before I built a format gate that runs one real prompt through any new
> model before I trust a single number from it."

---

# 9. The headline metric was biased toward verbose models

**The scenario.** Citation correctness is scored as: **any** cited page matches a golden page.
Consider a golden page of 35, with five chunks retrieved:

| behaviour | cites | scored | did it understand? |
|---|---|---|---|
| careful | `[1]` = p.35 | pass | yes |
| shotgun | `[1][2][3][4][5]` | pass | **unknown** |
| wrong | `[3]` = p.91 | fail | no |

A model that cites everything cannot fail while any correct page sits in the window.

**How we got to the answer.** This never mattered while comparing *one model against itself*
across retrieval settings — citation habits stayed constant, so the bias cancelled. A
multi-model comparison is exactly where it stops cancelling, and the difference was observed
directly: two stronger models cited two pages where a lighter one cited one.

The fix rejected: **redefining the metric.** Every archived result was computed the old way,
and silently redefining it would make old and new numbers incomparable while still looking
comparable. The fix adopted: leave the metric untouched and publish two companions beside it
— mean citations per answer, and precision (fraction of cited pages that are golden) — so the
number sits next to the thing that would inflate it.

**Defensive argument.** "My citation metric is an any-match, which means it rewards citing
everything. That was harmless while I compared one model to itself, because the bias was
constant and cancelled — but a cross-model table is precisely where it stops cancelling. I
chose not to redefine it, because that would have invalidated every archived number while
still looking comparable. Instead I publish it unchanged next to two companion statistics
that expose the bias. Disclosing a flawed metric is more useful than quietly replacing it."

**Show-off argument.** Openings: *"how do you know your evaluation is any good?"*, *"tell me
about a mistake you found in your own work"*, *"how do you handle metrics you don't trust?"*
> "I found a bias in my own headline metric. Citation correctness passed if *any* cited page
> was correct — so a model that cites all five sources every time can barely fail. It didn't
> matter while I was comparing one model against itself, because it cancelled out. It broke
> the moment I compared different models, since they cite at different rates. What I'd
> emphasise is what I *didn't* do: I didn't redefine the metric, because that would have made
> every historical number incomparable while still looking comparable. I published it
> unchanged alongside statistics that expose the bias."

---

# 10. Silent sample-size erosion

**The scenario.** When a question errors, it is *excluded* from the metrics rather than counted
as wrong — deliberately, so a network blip can't masquerade as a quality regression. But the
retry logic only retries HTTP status codes; a dropped connection is a Python exception and
skips retry entirely.

**How we got to the answer.** The failure isn't a crash — the harness catches it per question
and continues. It's quieter: a run over 61 questions **looks like** a run over 69. The project
already has an artifact of exactly this, kept deliberately: a results file where 52 of 69
questions errored and the metrics were computed over the surviving 17. The remedy is treating
connection-level exceptions as retryable, and always reporting the denominator.

**Defensive argument.** "I exclude errored questions from metrics so infrastructure problems
can't look like quality regressions. The second-order risk is that a flaky connection then
shrinks the sample silently — the run doesn't fail, it just answers fewer questions and
reports a confident-looking average. I keep a failed run in the repo as a reminder: 52 of 69
errored and the metrics were computed over 17. It looked completely normal."

**Show-off argument.** Openings: *"how do you handle flaky external APIs?"*, *"what does good
error handling look like?"*
> "There's a trap in the obvious fix. You don't want a network blip counted as a wrong answer,
> so you exclude errored rows — right call. But then failures stop being visible: your run
> quietly covers 61 of 69 questions and still reports a clean average. I keep one deliberately
> failed run in the repo where 52 of 69 errored and the metrics were computed over 17. It
> looked fine. Now I always report the denominator."

---

# 11. A sleeping machine corrupts timings — and hosted models hide it

**The scenario.** Latency is a published column. A machine that suspends mid-run inflates
whatever phase it slept through, silently.

**How we got to the answer.** Locally this is *detectable*: the local runtime reports prefill
and decode separately, so a suspend inflates one phase while the other stays normal — a
signature. One question once logged 3,051 s of prompt evaluation at 0.76 tok/s against a usual
15, purely from a suspend. **Hosted endpoints report no phase split**, so wall clock is the
only number and a suspend leaves *no signature at all*. Detection is impossible, so the
defence has to be prevention: disable sleep before any scored run, and treat any run that
overlapped a suspend as unusable.

**Defensive argument.** "Timing numbers from a laptop are only trustworthy if the laptop
stayed awake. Locally I can detect a suspend, because the runtime splits prefill from decode
and a suspend inflates only one. Hosted APIs report a single wall-clock number, so the same
corruption is undetectable after the fact. That asymmetry is why I moved from checking
afterwards to preventing beforehand — and why I discard any run that overlapped a sleep
instead of trying to repair it."

**Show-off argument.** Openings: *"how do you benchmark reliably?"*, *"what's hard about
measuring latency?"*
> "Benchmarking on a laptop taught me something about observability. When I ran models
> locally, a suspend was detectable — the runtime splits prefill and decode, and only the
> slept-through phase inflates. Once I moved to hosted APIs, that signature vanished, because
> you only get total wall clock. Same corruption, no longer detectable. I had to switch from
> validating results afterwards to controlling conditions beforehand."

---

# 12. Free tiers cost more than they save

**The scenario.** Weeks were lost to free-tier rate limits across two providers, in four
distinct failure modes — including a daily token cap stated *only* in a 429 response body and
never in a header, and a provider where every retry was itself billed against the request
budget, driving the retry-after from 15 seconds to 1,700.

**How we got to the answer.** Measured actual usage: a full 69-question run costs a few cents.
The free tiers weren't saving money in any meaningful amount — they were converting a
negligible cost into an unbounded time cost, and into engineering complexity (header-based
pacing that is blind against providers who send no headers).

**Defensive argument.** "I spent real engineering time on rate-limit handling for tiers that
were saving me pennies. The measured cost of a full evaluation run is a few cents. Once I
measured that, the decision was obvious — but the interesting part is that the free tier
wasn't just slower, it forced complexity into the code: pacing logic that reads headers is
useless against a provider that sends none, and a daily cap that only ever appears in an
error body can't be planned around at all."

**Show-off argument.** Openings: *"tell me about a trade-off you got wrong"*, *"how do you
decide when to pay for tooling?"*
> "I under-valued my own time badly. I burned days on free-tier rate limits — one provider's
> daily cap only ever appeared inside a 429 body, never a header, so you couldn't pace against
> it. Then I measured what a full eval run actually costs: a few cents. What made it worth
> writing down is that the free tier didn't just cost time, it distorted the code — I'd built
> header-based pacing that was structurally blind to a provider that sends no headers."

---

# 13. Fixing the metric immediately undermined the headline result

**The scenario.** Entry 9 identified that citation correctness is an any-match and therefore
rewards citing broadly. The fix was two companion statistics rather than a redefinition. The
companions were then backfilled onto the existing results — and the headline finding did not
survive contact with them.

The project's published claim was that better retrieval helps a hosted model's attribution
(+3.8 points) and hurts a local 7B model's (−6.5). Restricted to questions both arms answered
and re-scored against the current golden set:

| pair | any-match | precision | citations/answer |
|---|---|---|---|
| local 7B, vector → rerank (n=47) | 78.7% → 72.3% (**−6.4**) | 65.3% → 56.7% (**−8.6**) | 1.52 → 1.68 |
| hosted light, vector → rerank (n=52) | 90.4% → 94.2% (**+3.8**) | 76.3% → 76.5% (**+0.2**) | 1.56 → 1.63 |

**How we got to the answer.** Reranking makes both models cite *more* sources. Under an
any-match rule, citing more is a tailwind — more citations, more chances one lands on a golden
page. Precision removes that tailwind, and on the hosted model the entire +3.8 gain goes with
it: **+0.2 points.** The apparent improvement was mostly the metric rewarding a change in
citation behaviour, not better attribution.

The local result moves the other way and gets *worse*: −8.6 on precision against −6.4 on
any-match, a degradation that happened **despite** the same tailwind.

Two things make this defensible rather than embarrassing. The comparison was restricted to
questions both arms answered, because the arms decline different questions and a whole-file
aggregate would compare two different question sets. And the recomputation independently
rediscovered a documented fact — it flagged exactly the four golden-set rows recorded as having
changed between versions — which is evidence the re-scoring is correct rather than convenient.

**The honest revision:** reranking hurt the weak model's attribution and did essentially
nothing for the light hosted model's. The model-dependence survives; the positive half of it
largely does not. And the residual +3.8 was only ever **two questions out of 52** — thin
before this analysis, and now visibly so.

**Defensive argument.** "I found that my headline number was partly an artifact of my own
metric. Citation correctness passed if any cited page was golden, and reranking makes models
cite more — so the rerank arm got a free tailwind. Measuring precision instead, the hosted
model's +3.8 point gain becomes +0.2. I'd already established the metric was biased; what
this showed is that the bias was large enough to account for nearly all of a result I'd
published. I restricted to questions both arms answered so I wasn't comparing different
question sets, and the re-scoring independently reproduced four golden-set changes I'd
documented separately, which is how I know it's right and not just flattering in a new
direction."

**Show-off argument.** Openings: *"tell me about a result you had to walk back"*, *"how do you
know your evaluation is measuring what you think"*, *"what's the most surprising thing you
found?"*
> "The most useful thing I did on this project was disprove my own headline finding. I'd
> published that better retrieval improved attribution on one model by about four points. Then
> I fixed a known bias in the metric — it passed if *any* citation was correct, which rewards
> citing more sources — and it turned out reranking makes models cite more. Measuring
> precision instead, that four-point gain became 0.2. The improvement was mostly my metric
> rewarding a behaviour change. What I'd stress is the order of events: I identified the bias
> on principle, before I knew what it would do to my results. If I'd gone looking for it only
> after a result I disliked, I couldn't trust my own correction."

**Cross-reference:** this is the payoff of entry 9. The two are best told together — entry 9
is finding the flaw, this is paying its cost.

---

# 14. One model id, nine deployments — and the field that caught it on day one

**The scenario.** Entry 7 added a `served_by` field recording which upstream provider actually
answered, on the principle that an aggregator resolves one model id to several real
deployments. It was added on principle, before there was any evidence it mattered.

It fired on the first run that used it.

**How we got to the answer.** A single 69-question run arrived as a **blend of two different
Google endpoints, mixed question by question**: 38/31 in one arm, 33/36 in the other. Not two
runs — one run, switching mid-flight, with nothing in any response indicating a change.

Querying the endpoints API made the scale clear. A model id is a pointer to a *set*:

| model | endpoints | providers |
|---|---|---|
| `claude-opus-5` | 9 | Anthropic, AWS, Azure, Google, Bedrock — **at two different prices** |
| `gemini-3.1-flash-lite` | 7 | Google, Google AI Studio — **three price tiers** |
| `qwen-2.5-7b-instruct` | 1 | a single niche provider |

Three consequences. The arm comparison was mildly contaminated, because the *blend ratio*
differed between arms, so part of the measured difference was a mixture difference rather than
a retrieval difference. The run was **not reproducible in composition** — re-running the same
command load-balances differently. And for the frontier model, an unpinned run would blend five
providers at two price points, making even the **cost** nondeterministic.

The fix is `provider: {order: [...], allow_fallbacks: false}` — pin, and *fail* rather than
substitute. It is free to fail: the router returns 404 before any inference, so nothing is
billed.

**The honest limit:** pinning is not determinism. `temperature: 0` removes sampling randomness;
it does nothing about floating-point reduction order, GPU kernel nondeterminism, or a provider
silently changing hardware. Pinning converts an *unknown* deployment into a *known* one. The
project can claim "the serving endpoint is recorded and pinned" and cannot claim "hosted runs
are reproducible" — locally it can, and does, with byte-identical output from a cold model.

**Defensive argument.** "When you call a model through an aggregator, the model id is a pointer
to a set of deployments and the router picks per request. My first instrumented run came back
as a 55/45 blend of two endpoints inside a single evaluation — and the blend ratio differed
between the two arms I was comparing, so part of my measured difference was a mixture
difference. I pin the provider now and fail rather than fall back, which costs nothing because
a routing refusal isn't billed. What I'm careful not to claim is that this makes hosted runs
deterministic. It doesn't. It makes the deployment *known*, which is a weaker and honest
property."

**Show-off argument.** Openings: *"what's surprised you about working with LLM APIs?"*,
*"how do you validate third-party infrastructure?"*, *"what does temperature 0 actually give
you?"*
> "Something that surprised me: with an aggregator, one model id can be several different
> deployments, and the router picks per request. I added a field logging which provider
> actually answered — purely on principle, I had no evidence it mattered. First run came back
> as a 55/45 split across two endpoints *within* the same evaluation, and the ratio differed
> between my two comparison arms. So I'd been running a mixture experiment without knowing it.
> The related thing people get wrong is temperature 0 — it removes sampling randomness, but
> not floating-point nondeterminism or an infrastructure change you can't see. Pinning gets you
> a *known* deployment, not a reproducible one."

---

# 15. The metric was capped, so the expensive experiment was pointed at the wrong column

**The scenario.** The plan was a four-model comparison with citation correctness as the headline
column. The frontier model costs roughly 40× the cheap one per run. Before spending it, the
question came up: given that retrieval is identical for every model, what can a better model
actually change?

**How we got to the answer.** Two things, and the first was already visible in data on hand.

**The metric has a ceiling set by retrieval.** Citation correctness cannot exceed the rate at
which a golden page is in the context window at all — no model cites what it was never shown.
That ceiling is ~95%, and the *cheap* model already scores 94.2%. A frontier model has about
one point of headroom on the column the whole table was to be built around. Four models would
have looked identical, supporting a conclusion — "model choice doesn't matter here" — that
would have been an artifact of a saturated metric.

The real headroom is elsewhere: precision (~23 points), false abstention (~5), and a behaviour
that no metric captured at all. During screening, two stronger models **spontaneously flagged
that a source document contradicts itself** — one page saying 48 hours, another saying 7 days —
where the light model answered one figure and moved on. For a system answering from government
documents, noticing that sources disagree is close to the ideal behaviour, and nothing in the
metric set rewarded it.

**Second, a confound in the fix for the earlier confound.** Entry 13 replaced any-match with
precision to remove the "citing more sources" tailwind. But reranking also changes *how many
golden pages are in the window* — one of five under dense retrieval, four of five under
reranking, in the clearest case. A model citing blindly from a four-of-five window scores ~80%
precision by chance. **Precision is inflated by the same mechanism it was introduced to
expose** — less wrong, not right. The missing control is a base rate: golden pages per window,
per arm, with precision measured against it.

**The outcome:** run the expensive model, but re-frame what it is for. Not "does it score
higher" — it cannot, on the capped column — but "where does capability show up when the
evidence is held constant?"

**Defensive argument.** "Before spending the budget I checked what the expensive model could
possibly change, and found my headline metric was capped by retrieval — no model can cite a
page it wasn't shown. The ceiling was about 95% and the cheap model was at 94.2%. So the
expensive run would have produced four near-identical numbers and I'd have concluded model
choice didn't matter, which would have been an artifact of a saturated metric rather than a
finding. I re-pointed the comparison at precision, false abstention, and how models handle
contradictory sources. I also found my own fix from the previous round is still confounded:
reranking changes how many correct pages are in the window, and precision doesn't control for
that either. It's recorded as open rather than presented as solved."

**Show-off argument.** Openings: *"how do you decide what to measure?"*, *"tell me about a time
you changed an experiment's design"*, *"how do you avoid wasting compute?"*
> "The most valuable hour I spent was the one where I *didn't* run the expensive benchmark. I
> was about to compare four models on citation accuracy, and I stopped to ask what a better
> model could actually change — retrieval was identical for all of them by design. It turned
> out the metric was capped by retrieval: no model can cite a page it wasn't shown, that
> ceiling was ~95%, and the cheapest model was already at 94.2%. I'd have spent the budget
> producing four identical numbers and concluded model choice didn't matter. So I re-pointed
> it at the metrics that had headroom, plus a behaviour I'd noticed by accident — stronger
> models spontaneously flagged that my source documents contradict each other, where the cheap
> one just picked a number. That's the behaviour that actually matters for the product, and
> nothing in my metric set was measuring it."

**Cross-reference:** entry 13 fixed the metric; this found the fix was partial and the metric
was pointed at the wrong question. The three together — 9, 13, 15 — are one continuous story
about learning what an evaluation is really measuring.

---

# 16. The control disproved my worry — and found something bigger beside it

**The scenario.** Entry 15 flagged that reranking might inflate citation precision by putting
more *golden pages* into the window, not just ranking them higher. The evidence was one
question: `vector` returned 1 golden page of 5, `rerank` returned 4 of 5. That was written into
the README as a serious open confound.

**How we got to the answer.** Measured across all questions instead of that one: windows hold
**1.10 → 1.19 golden pages**, moving the chance baseline about **1.7 points**. The vivid
example was an outlier and I had generalised from it before checking. The README claim was
softened to match.

Then the sharper realisation, which came from being asked *"can we ignore this entirely?"*:
**base rates are a property of the retriever, not the model.** Retrieval is deterministic and
identical for every model, so this confound **cancels completely from the multi-model
comparison** and applies only to retriever-vs-retriever. The expensive experiment never needed
it.

But the second baseline, added alongside, produced the strongest result in the project.
Compare each model against *ignore the model's citations and always cite chunk `[1]`*:

| | always-cite-`[1]` | model | lift |
|---|---|---|---|
| local — vector | 54.3% | 65.3% | **+10.9** |
| local — rerank | 76.6% | 56.7% | **−19.9** |
| hosted — vector | 51.9% | 76.3% | **+24.4** |
| hosted — rerank | 75.0% | 76.5% | **+1.5** |

Both models beat the trivial baseline under dense retrieval and stop beating it under
reranking — the local one falling below it. The baseline itself jumps ~23 points, because
reranking's achievement is putting the right chunk first. **Reranking's benefit is realised by
the retriever; the generator adds nothing on top of it.**

Not a novel technique — trivial-baseline comparison is standard IR discipline. The lead-3
baseline in summarization and popularity baselines in recommender systems both exposed
stretches of apparent progress that a ten-line heuristic matched.

**Defensive argument.** "I suspected a confound and I was wrong about its size — I'd
generalised from one striking example, and measured across the set it was worth about 1.7
points. Two useful things came out of being wrong. First, base rates depend on the retriever,
not the model, so the confound cancels from my model comparison entirely — I'd been about to
control for something that couldn't affect that experiment. Second, the trivial baseline I
added alongside showed that once reranking is on, my generator adds almost nothing over
'always cite the first chunk', and on the small local model it's actively worse than that.
The caveat I keep attached is that this is precision only — the model surfaces more correct
pages than the baseline, just more noisily."

**Show-off argument.** Openings: *"how do you know a component is pulling its weight?"*,
*"tell me about a time you were wrong"*, *"what would you do differently?"*
> "I'd add trivial baselines much earlier. I built a control for a confound I'd spotted, and
> it turned out to be worth about 1.7 points — I'd generalised from one vivid example. But the
> throwaway baseline I added next to it was the most informative thing I measured: compare the
> model against 'ignore its citations, always cite chunk one.' Once reranking was on, my
> generator added essentially nothing over that, and the small local model scored *below* it.
> So the improvement I'd attributed to the whole pipeline was really the retriever's, and the
> generator was along for the ride. That's the summarization lead-3 lesson — without a trivial
> baseline you can't tell which component earned the gain."

**Cross-reference:** entries 9, 13, 15 and 16 form one continuous arc — finding a metric's
bias, fixing it, finding the fix was partial, and finally finding that the trivial baseline
mattered more than any of it.

---

# Backlog — entries still to be written

Earlier phases contain material of the same quality that predates this journal and should be
backfilled from [HANDOFF.md](HANDOFF.md) §4 and §5:

- Chunks never spanning a page boundary, so a citation always points at a page that genuinely
  contains the text (design decision 1)
- Fusion merging ranks rather than scores, avoiding a normalisation constant that would itself
  need tuning (decision 11)
- The false-abstention rate conditioned on the golden page having been retrieved (decision 18)
- One build reaching every phase by flag, so Phase 1 and Phase 2 are scored by the same
  harness (decision 19)
- A single-digit fact check passing on a citation marker — a silent false pass (gotcha 20)
- The brief's "two conflicting editions" being byte-identical, one document under two
  filenames (gotcha 3)
- Values living inside page images, invisible to text extraction and to document-level
  triage (gotcha 5)
- The candidate-pool decision, where the chosen option **lost** the quality comparison and was
  taken on latency grounds for a free-hosting target (decision 22)
