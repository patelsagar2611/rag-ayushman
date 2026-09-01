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

# 17. The pre-registered experiment that inverted a headline result

**The scenario.** The project's retrieval results showed keyword search (BM25) beating dense
embeddings — MRR 0.677 against 0.624, and a wider gap on hit@1. That was a genuine surprise
worth reporting, and it was reported.

But the evaluation questions were hand-written by someone reading the source documents, so they
reuse the documents' own vocabulary: *"cover amount on family floater basis"* rather than *"how
much money do I get for an operation"*. **BM25 scores exactly that lexical overlap.** So the
result might be measuring the question author, not the corpus.

**How we got to the answer.** Measured the bias first rather than assuming it, using the same
tokenizer BM25 itself uses: mean overlap between question and target page **78.1%**, and **15 of
60 questions reused every content word** from their target page.

Then a **paired** test — the same facts and the *same target pages*, only the wording changed,
so retrieval is the only thing that can move. This design choice mattered: the intuitive
alternative, collecting real user questions from public FAQs, would have produced genuine user
language but different answers and different target pages, so any drop couldn't be attributed
to vocabulary.

The rewrites were drafted by a model given the question and the human-written expected answer,
**never any page text**, then hand-reviewed. Two were rejected for expanding a domain acronym
into the wrong domain — *EHCP* (Empanelled Health Care Provider) became a UK education plan,
*NHA* (National Health Authority) became a housing authority — and one for drifting to a
different information need. Dropping them was the *conservative* choice: they were the most
jargon-dense rows, so excluding them makes the effect harder to detect, not easier.

**Two outcomes were pre-registered before running**: that BM25's lead would shrink if the bias
was real, and that reranking would degrade least, because a cross-encoder reads question and
passage together rather than matching tokens.

| retriever | MRR original | MRR lay phrasing | change |
|---|---|---|---|
| `vector` | 0.789 | 0.443 | −44% |
| `bm25` | **0.941** | **0.144** | **−85%** |
| `hybrid` | 0.912 | 0.402 | −56% |
| `rerank` | 0.971 | 0.590 | −39% |

**The ranking inverted.** BM25 went from second-best to last, finding the right page first in
1 of 17 questions. Vector went from last to second. Reranking degraded least, as predicted.

**Defensive argument.** "My headline retrieval result was that keyword search beat embeddings. I
didn't trust it, because I'd written the evaluation questions myself while reading the source
documents — and lexical overlap is precisely what BM25 scores. So I measured the overlap: 78%
on average, with a quarter of the questions reusing every content word from their target page.
Then I ran a paired test with the same facts and the same target pages, rewritten in lay
language. BM25 dropped 85% and went from second place to last. My reported advantage was
substantially an artifact of my own authorship. I pre-registered the predictions before running
so I couldn't reinterpret the outcome, and I deliberately excluded the rows most favourable to
the finding, which makes the effect harder to detect rather than easier."

**Show-off argument.** Openings: *"how do you know your evaluation is valid?"*, *"tell me about
a surprising result"*, *"what's the hardest part of building a RAG system?"*
> "The most useful experiment I ran was one designed to attack my own headline result. I'd found
> that keyword search beat embeddings on my eval — genuinely surprising, and the kind of thing
> you'd want to write up. But I'd written the eval questions myself with the documents open, and
> lexical overlap is exactly what BM25 rewards. So I measured it: 78% average overlap between
> question and answer page. Then I rewrote the worst offenders in plain language, keeping the
> same facts and the same target pages, and BM25 collapsed by 85% — from second-best retriever
> to last. The reranker degraded least, which I'd predicted, because it actually reads the
> question against the passage instead of matching words. The real lesson isn't about BM25 —
> it's that if you write your own eval set from the source documents, you've encoded your
> reading of them into the benchmark, and you will not see it unless you go looking."

**Cross-reference:** this is the retrieval-side counterpart to entry 16. Both are the same move
— compare against something that isolates what you're actually measuring — and both found the
headline number was measuring the setup rather than the system.

---

# 18. Chunks never span a page boundary

**The scenario.** Standard RAG chunking slides a window over the whole document, letting chunks
straddle page breaks. That maximises context per chunk. It also means a chunk can contain text
from pages 12 and 13, so a citation pointing at "page 12" may be quoting page 13.

**How we got to the answer.** Citations are the entire point of this project — the promise is
that every claim carries a filename and page you can check. A citation that is *usually* right
is a worse product than one that is *always* right, because a user who finds one wrong page
stops trusting all of them. So chunking is constrained to page boundaries and every chunk
carries exactly one page number.

The cost is real and was accepted knowingly: a paragraph running across a page break is split in
the index, and a short page yields a short chunk. Recorded as revisitable *if the eval shows
answers cut in half at page boundaries* — it hasn't.

**Defensive argument.** "I gave up cross-page context deliberately. My chunks never span a page
boundary, so every chunk carries exactly one page number and a citation always points at a page
that genuinely contains the text. The alternative gets you slightly better context and citations
that are approximately right — and approximately-right citations are worse than none, because
the user can't tell which ones to trust. I wrote down the condition that would make me reverse
it: eval evidence of answers being truncated at page breaks. That hasn't appeared."

**Show-off argument.** Openings: *"how did you approach chunking?"*, *"what's a constraint you
imposed on yourself?"*
> "My chunking rule is one most RAG tutorials would call a mistake — chunks never cross a page
> boundary, so I lose context at every page break. I did it because citation accuracy was the
> product, not a feature of it. If a citation can point at the wrong page even occasionally, a
> user who catches one stops trusting all of them. Constraining chunks to pages makes wrong page
> numbers structurally impossible rather than merely unlikely."

---

# 19. Fusion merges ranks, never scores

**The scenario.** Combining a dense retriever with BM25 means reconciling their outputs. The
obvious approach is a weighted sum of scores.

**How we got to the answer.** The numbers aren't on the same scale — a cosine similarity around
0.69 against a BM25 score around 12.55. Combining them needs a normalisation step, and **that
normalisation is itself a tuned parameter**. Tuning it means fitting a constant to the 69
evaluation questions and then reporting the fit as a measurement, which is the exact failure the
eval exists to prevent.

Reciprocal rank fusion needs no normalisation: it combines *positions*, which are already
comparable. `RRF_K` was left at the published default of 60 rather than tuned, and that
restraint is a claim the project can make.

**Defensive argument.** "I fused ranks rather than scores because the scores are on
incomparable scales — cosine similarity around 0.7 against BM25 around 12. Any weighted
combination needs a normalisation constant, and I'd have had to tune that against my own
evaluation set, which turns a measurement into a fit. Rank positions are comparable without one.
I also left the RRF constant at its published default rather than tuning it, so I can honestly
say no hyperparameter in this system was fitted to the test set."

**Show-off argument.** Openings: *"how do you combine retrievers?"*, *"how do you avoid
overfitting an eval set?"*
> "The thing I'd flag about hybrid retrieval is that the obvious implementation quietly costs you
> your evaluation. Weighted score fusion needs a normalisation constant because the two scores
> are on different scales — and the only place to tune that constant is your eval set, which
> means your headline number is partly a fit to the thing you're measuring against. Reciprocal
> rank fusion sidesteps it entirely by combining positions. It's the boring choice that keeps
> your numbers honest."

---

# 20. Two metrics that were measuring the wrong denominator

**The scenario.** Two related mistakes, both of which produced confident, plausible, wrong
numbers.

**False abstention, unconditioned.** The rate of "the model refused to answer" counted every
refusal against the model — including refusals where retrieval never surfaced the evidence.
Declining to answer with no evidence in front of you is *correct behaviour*, not a failure. The
metric was conditioned on the golden page having actually been retrieved, and the unconditioned
version demoted to a secondary figure explicitly labelled "do not quote this".

**A finding that was just the base rate.** "13 of 14 citation failures had the evidence
retrieved" was written down as a result — it sounds like retrieval is fine and the model is at
fault. But **51 of 52 answered questions had the evidence retrieved**. The failures matched the
population almost exactly. There was no signal at all.

**How we got to the answer.** Both are the same error: a rate is meaningless until compared
against the rate you'd expect anyway. The second one is why the project later added explicit
base-rate baselines to its citation metrics (entry 16) — the discipline generalised.

**Defensive argument.** "I reported that 13 of 14 citation failures had the evidence retrieved,
which reads as 'retrieval is fine, the model is the problem'. Then I checked the base rate: 51
of 52 answered questions had the evidence retrieved. My failures matched the overall population
— there was no finding. It's the same error as my unconditioned false-abstention rate, which
counted refusals against the model even when retrieval had given it nothing to work with. Both
taught me the same thing: always state what the number would be if nothing interesting were
happening."

**Show-off argument.** Openings: *"tell me about a wrong conclusion you caught"*, *"how do you
know a metric is telling you something?"*
> "I once wrote down that 13 of 14 of my failures had the evidence retrieved — which sounds like
> a clean diagnosis pointing at the model. Then I checked the base rate: 51 of 52 of *all*
> answered questions had the evidence retrieved. My failure population was identical to the
> general population. I'd found nothing and nearly reported it as something. Now every rate in
> the project is published next to what it would be by chance."

---

# 21. One build reaches every phase, by flag

**The scenario.** The project has two measured phases. The natural way to preserve a baseline is
to tag or branch the Phase 1 code and keep it around to re-run.

**How we got to the answer.** That would mean Phase 1 numbers are produced by *one harness* and
Phase 2 numbers by *another* — so any difference between them could be the retrieval change or
could be a harness change, and there'd be no way to tell. The same trap as the unconditioned
false-abstention rate: a definition quietly changing underneath a comparison.

Instead, retrieval mode and `k` are runtime parameters, so `--retriever vector` reproduces Phase
1 exactly with *today's* code. Prompt v1 was verified byte-identical to the `phase-1` git tag,
so generation stays comparable too.

**This property has to be actively defended**, and its limits are written down: it does not
extend to a new prompt file (use the `PMJAY_PROMPTS` env var) and it *cannot* extend to
re-chunking or an embedding-model swap, which change the index and force a full re-baseline.

**Defensive argument.** "I never branched per phase. Retrieval mode is a flag, so today's code
reproduces the Phase 1 baseline exactly — which means when I compare phases, the harness is
held constant and the only variable is the thing I changed. Separate builds would have meant
comparing numbers produced by two different scoring implementations. I also wrote down where the
property breaks: anything that changes the index forces a full re-baseline, and no flag can
paper over that."

**Show-off argument.** Openings: *"how do you keep benchmarks comparable over time?"*, *"how do
you manage experiment versions?"*
> "I made a rule that one build has to reach every phase by flag — no per-phase branches. It
> sounds like a code-hygiene preference; it's actually about measurement validity. If your Phase
> 1 numbers came out of a tagged old build and your Phase 2 numbers out of the current one, a
> difference between them might be your improvement or might be a scoring change you made in
> between, and you can't separate them. I verified the prompt was byte-identical to the old tag
> for the same reason."

---

# 22. A fact-check that passed on a citation marker

**The scenario.** The eval verifies a model stated the right figure with a substring check —
`must_contain: 5` should confirm the answer contains "5". It runs against the raw answer, which
also contains citation markers `[1]`–`[5]`.

So an answer reading *"…as set out in the guidelines [5]"* **passed** a check for the figure `5`
while never stating the value. A silent false pass, and seven golden rows carried a bare digit —
five of them values ≤ 5, and therefore reachable as citation markers.

**How we got to the answer.** Citation markers are metadata, not content, so stripping them
before the comparison is unambiguously correct and reintroduces no sensitivity to phrasing. Two
details are load-bearing: the strip runs *after* citation parsing, which needs the markers; and
it substitutes a **space** rather than nothing, so "the fee [3] is 48" cannot fuse into one
token.

**The fix can only lower the score, never raise it** — and since that metric is explicitly a
floor rather than a target, a lower honest number is the correct outcome. It landed *before* the
first full generation run, which is the point: fixing it afterwards would have meant discarding
that baseline or carrying a known-inflated number forever.

**Defensive argument.** "My fact-check ran against the raw answer, which contains citation
markers — so a check for the figure 5 passed on an answer that cited source [5] and never stated
the value. Seven of my rows had bare digits and five were small enough to be reachable that way.
I strip citations before the comparison now, after parsing them and substituting a space so
adjacent tokens can't fuse. The fix could only lower my scores, which is the right direction for
a metric that's a floor rather than a target — and I fixed it before the run it would have
contaminated, not after."

**Show-off argument.** Openings: *"how do you validate an evaluation harness?"*, *"tell me about
a bug in your own tooling"*
> "My favourite bug in this project was in the eval, not the system. I check that answers state
> the right number with a substring match — and the answers contain citation markers like [5].
> So a check for the figure 5 passed on an answer that cited source 5 and never mentioned the
> value at all. Silently, and in the flattering direction. Roughly a third of my checked rows
> were vulnerable. The lesson I took is that evaluation code deserves the same scrutiny as
> product code, and errors in it are worse because they're self-congratulatory."

---

# 23. The two conflicting documents were the same document

**The scenario.** The project brief's premise was that two conflicting editions of the hospital
empanelment guidelines exist, and a naive system would cite the superseded one. It named both
files. Building version-conflict test cases was a headline deliverable.

**How we got to the answer.** Both files were fetched and hashed. **They are byte-identical** —
same sha256, same 1,481,305 bytes. One document served under two filenames, both the same 46-page
December 2021 edition.

Indexing both would have added ~65 duplicate chunks, skewed retrieval toward whatever they
covered, and produced version-conflict eval cases that test a document against itself — which
would have *passed*, convincingly, while measuring nothing.

A genuine conflicting pair was then found: a 46-page December 2021 edition and a 64-page one
whose cover states "Version – 2.0", sourced from a state health agency mirror. **Which is
currently in force is still unconfirmed**, and is deliberately left open rather than inferred
from filenames — inferring from filenames is exactly what produced the false pair.

**Defensive argument.** "The brief told me two conflicting documents existed and named them. I
hashed them: identical, one file under two names. If I'd trusted the premise I'd have indexed
duplicates and built test cases comparing a document against itself — and they'd have passed. I
found a genuinely conflicting pair afterwards, but I've left 'which edition is in force'
explicitly unresolved rather than guessing from the filename dates, because guessing from
filenames is what created the fake pair in the first place."

**Show-off argument.** Openings: *"tell me about assumptions you checked"*, *"what surprised you
about working with real-world documents?"*
> "The first thing I did on the corpus was hash every file — and two documents the project spec
> described as conflicting editions turned out to be byte-identical. Same file, two filenames on
> the government portal. Had I taken the spec at face value, I'd have indexed duplicate content
> and written test cases that compared a document to itself, which would have passed and told me
> nothing. Requirements describing real-world data are a hypothesis, and hashing is a cheap way
> to test one."

---

# 24. Document-level triage is not content-level coverage

**The scenario.** Before building, a script checked whether the PDFs were text-native or scanned
images needing OCR. It measured **average characters per page** and cleared all 11 as text-native.
No OCR needed.

**How we got to the answer.** Four evaluation questions were later written, verified against the
PDFs by eye, and then found unanswerable — the values are rendered *inside images*: a chart, or a
table saved as a graphic, on pages that are otherwise full of text.

The evidence is specific rather than assumed. For the helpline number, the word "helpline" *is*
extracted from page 30 while the number `14255` appears nowhere in the file.

The triage script wasn't wrong; it answered a different question than the one that mattered.
**An average over a page cannot see an image-embedded table sitting on a text-heavy page.**

Those questions moved to a separate file rather than being deleted or scored. Scored, they'd be
permanent retrieval failures capping the hit rate for reasons unrelated to retrieval quality, and
immune to any Phase 2 improvement. Deleted, the finding would be lost. Kept aside, they are the
concrete case for adding OCR later.

**Defensive argument.** "I checked up front whether the corpus needed OCR, using average
characters per page, and cleared all 11 documents. That check was measuring the wrong thing — an
average over a page can't detect a table rendered as an image on a page that's otherwise text.
I found out when questions I'd verified by eye turned out unanswerable: the word 'helpline'
extracts from the page, the number doesn't exist in the file. I moved those to a known-gaps file
rather than scoring them, because scored they'd cap my hit rate for a reason unrelated to
retrieval — and rather than deleting them, because they're the evidence for adding OCR."

**Show-off argument.** Openings: *"what went wrong with your data pipeline?"*, *"how do you
validate document ingestion?"*
> "I learned that document-level triage isn't content-level coverage. I checked whether my PDFs
> needed OCR by measuring characters per page, and everything passed. Then questions I'd verified
> by reading the PDF came back unanswerable — because the numbers were inside images sitting on
> otherwise text-heavy pages. The average can't see that. What made it diagnosable is that I could
> show the surrounding word extracts fine while the number appears nowhere in the file, so it
> wasn't a retrieval problem at all."

---

# 25. The option we chose lost the quality comparison

**The scenario.** A reranker can only reorder what it's given, so the candidate pool sets its
ceiling. Three pools were measured with everything else identical:

| pool | hit@5 | MRR | latency | pool recall |
|---|---|---|---|---|
| `hybrid` (kept) | 95.0% | 0.795 | **2.0 s** | 96.7% |
| `bm25` | 95.0% | **0.808** | 3.7 s | 98.3% |
| `union` | **98.3%** | 0.806 | 6.7 s | **100%** |

**How we got to the answer.** Hybrid was kept — and it **lost**. The union reduces retrieval to a
single failing question and hybrid does not. The reason for keeping it is entirely latency: the
target is a public demo on free hosting where the cross-encoder is projected to run ~4× slower
than locally, and 6.7 s of retrieval before generation even starts is not a usable product.

That reasoning is recorded in the design decisions in a deliberately blunt form: *anyone
reversing this should reverse it on latency evidence, not because they think hybrid retrieves
better — it does not.* Both losing arms remain reachable by flag rather than deleted, because a
results file naming a mode that no longer exists is unreproducible archaeology.

Two things that comparison taught, neither visible in the aggregate:

- **Recall is a ceiling, not a score.** BM25's recall lead was +2 questions and −1, not a strict
  improvement — the pools aren't nested. And the net +1 became net *zero* after reranking,
  because a pool gain is optional while a pool loss is mandatory.
- **Fusion ranks *and truncates*, and in a reranking pipeline only the truncation matters.** RRF
  merges up to 60 chunks, cuts to 30, and then the reranker re-sorts by its own score — discarding
  RRF's ordering entirely. So fusion contributes nothing downstream while its truncation still
  loses pages.

**Defensive argument.** "I kept the hybrid pool and it lost the quality comparison — the union
pool has better coverage and reduces retrieval to one failing question. I kept hybrid because
it's three times faster and the deployment target is free hosting where the cross-encoder runs
about four times slower again. I wrote that down bluntly, that anyone reversing the decision
should do it on latency evidence rather than believing hybrid retrieves better, because it
doesn't. The most useful thing I learned from that comparison is that recall is a ceiling rather
than a score — the pool with higher recall didn't produce better results, because a recall gain
is optional for the reranker to exploit while a recall loss is unrecoverable."

**Show-off argument.** Openings: *"tell me about a trade-off"*, *"a time you chose the worse
option"*, *"how do you weigh quality against performance?"*
> "I shipped the component that lost my own benchmark. Three candidate pools for my reranker: the
> one I kept has the worst coverage and is three times faster than the best one. The deciding
> factor was that my deployment target is free hosting where that stage runs four times slower
> again, and seven seconds before the model even starts generating isn't a product. What I made
> sure to do was write it down as 'chosen on latency, not quality' — because in six months
> someone reads 'we kept hybrid' and assumes it won. It didn't."

---

# 26. The reranker failure that turned out to be an eval failure

**The scenario.** The README's *"Where reranking still fails"* section listed four named failure
modes, each with a worked example. One of them read:

> **Adjacent pages of the same document crowd each other out.** Row 30's top five are
> `grievance_redressal.pdf` pages 23, 24, 22, 25 and — fifth — the golden page 16.

The picture is vivid: the cross-encoder pulls in a cluster of near-duplicate pages from one
chapter and buries the answer at rank 5. It was written up as evidence that reranking makes the
context window homogeneous, and it sat in the permanent record as a known weakness of the system.

Reviewing the golden set for target completeness, I pulled the text of those four pages. All four
state the rule the question asks for — *"if either party is not satisfied with DGNO's decision,
then they can appeal to DGRC within 30 days of the DGNO order"* — in the grievance-handling matrix
that runs across that whole chapter.

**The reranker had returned five correct pages and been scored 1 for 5.**

**How we got to the answer.** The detector that found it was not aimed at this. I was looking for
golden-set incompleteness by a different route: for every row, collect every page the models
*cited* that the golden set does not list, counted by how many independent runs cited it. A page
cited by twelve of thirteen runs across three model families is not one model hallucinating — it
is the models reading a page the question author forgot to list. Row 30 surfaced with four such
pages, each cited by nine or ten runs.

What makes the case airtight is that this row was never a citation failure. Row 30 scored a
golden hit in **13 of 13** runs, because the models cited page 16 *as well*. So the row looked
healthy on the headline metric and was quietly wrong on two others — `citation_precision`, which
counts the four correct-but-unlisted pages as wrong citations, and the retrieval metrics, where
four of the five retrieved pages were being scored as misses.

Two things were rejected on the way. The first was to trust the README: the entry was specific,
had a worked example, and named real page numbers, which is exactly the shape of a finding that
does not get re-checked. The second was to treat the four pages as duplicates that should be
excluded on principle. They are not duplicates in the way that matters: they are different rows
of a matrix covering different grievance types, each independently stating the 30-day appeal
window. A user given any one of them has been correctly answered.

**Then the example got worse for me, not better.** Checking the *other* arm, dense retrieval
returned **the same five pages** in a different order:

```
row 30   vector  window: p.23  p.16  p.22  p.25  p.24   -> cited all five  -> scored 0.20
         rerank  window: p.23  p.24  p.22  p.25  p.16   -> cited only p.16 -> scored 1.00
```

The windows are identical. So this was never an example of reranking making a window
homogeneous — there was no difference in homogeneity to observe. The only difference is what
the *model* did with the same five chunks, and the metric gave **0.20 to the answer that cited
five correct pages and 1.00 to the answer that cited one of them.**

So the correction cuts deeper than "one example was wrong". The *mechanism* the README describes
is real and confirmed elsewhere — row 25 remains a clean case of reranking filling four of five
slots with correct pages and the model citing the fifth. But row 30 was never evidence for it,
and the thing it is actually evidence for is a different defect entirely: **the old metric
punished breadth.** That is the exact inverse of the known `citation_correctness` bias, which
*rewards* citing broadly. Both citation columns were unreliable, in opposite directions, at the
same time.

**The generalisation, which is the actual finding.** Eighteen of sixty answerable rows turned out
to have a defensible missing target, and `citation_precision` — the metric that had just replaced
`citation_correctness` as the headline attribution number after entry 9 — is the metric most
exposed to it, because every correct-but-unlisted page counts against it.

**A prediction I registered here, and got wrong.** I wrote that the bias would not be uniform
across arms — that reranking pulls more of these pages into the window, so it had more opportunity
to be penalised, and that correcting the set would therefore *compress* the precision gap. The
re-scoring says the opposite. Correcting the targets raised precision for both arms by about
seventeen points, but it raised the **`vector`** arm more, so the gap **widened** on both 7B
models: −8.6 → −10.6 locally and −2.1 → −5.2 on the unquantised hosted copy. On `flash-lite` it
moved 0.1 of a point.

The mechanism, measured rather than reasoned about the second time. For each arm: of the
citations my eval scored *wrong*, what fraction turn out to be right once the targets are fixed?

| | citations | scored wrong before | now correct | **recovery rate** |
|---|---|---|---|---|
| local `qwen` — `vector` | 70 | 31 | 18 | **58.1%** |
| local `qwen` — `rerank` | 77 | 39 | 15 | **38.5%** |
| `flash-lite` — `vector` | 81 | 29 | 21 | **72.4%** |
| `flash-lite` — `rerank` | 85 | 30 | 21 | **70.0%** |

When the dense arm cited a page my eval called wrong, **my eval was the thing that was wrong 58%
of the time**. When the reranked arm did, only 38%. Reranking's mistakes were more often real
mistakes. And on `flash-lite` both arms recover identically, which is precisely why its delta did
not move — the effect is specific to the small models, matching the model-dependence this project
had already measured from a different direction.

The incomplete golden set had been **flattering** reranking, not penalising it. I had the sign
backwards because I reasoned from a plausible story about window composition instead of computing
a recovery rate, which took one query over data already on disk.

That is the third consecutive experiment in this project where the evaluation, not the system,
turned out to be the weak link — after the citation base-rate error and the golden-set vocabulary
bias.

**Defensive argument.** "My README documented a reranker failure mode with a worked example, and
the example was wrong. The question asks how many days you have to appeal a grievance decision;
the reranker returned four pages I had scored as misses and all four state the 30-day rule. My
eval listed one target page for a fact the document states five times. I found it with a detector
that inverts the usual assumption — instead of asking whether the model cited the right page, I
collected every page the models cited that my golden set did *not* list, and counted how many
independent runs cited each one. Twelve of thirteen runs agreeing on an unlisted page is not
hallucination, it's my eval being incomplete. Nineteen of sixty rows had that problem. The
important part isn't the fix, it's what it did to the headline. I predicted the correction would
shrink my reported precision penalty for reranking, because reranking puts more of these pages in
the window and so had more chances to be marked wrong. I was wrong — correcting it made the
penalty *larger* on both 7B models, because the dense-retrieval arm gained more. Its scattered
window meant the pages it cited off-target were more often genuinely correct pages I hadn't
listed. So the incomplete eval had been flattering reranking the whole time. I kept both the wrong
version and the failed prediction visible rather than quietly fixing the numbers, because how a
result was corrected is part of the result."

**Show-off argument.** Openings: *"tell me about a time you were wrong"*, *"how do you know your
evaluation is any good?"*, *"what would you do differently?"*
> "I had a section in my README titled 'where reranking still fails', with four named failure
> modes and worked examples. One of them was wrong — and not wrong in a subtle way. I'd written
> that the reranker crowds the answer out with near-duplicate pages from the same chapter, and
> shown the top five for one question with the correct page sitting at rank 5. When I actually
> read the other four pages, all four answered the question. The reranker had gone five for five
> and my eval had scored it one for five. What worries me more than the mistake is how I found
> it: not by re-reading my own documentation, which I'd have believed, but by building a detector
> that assumed the *models* might be right — collecting every page they cited that my golden set
> didn't list. Nineteen of my sixty questions had a missing target. That's the third time on this
> project that the measurement was the bug rather than the system, and I've stopped treating my
> eval set as ground truth. It's a hypothesis with a version number."

---

# 27. The label said pinned; the data said blended

**The scenario.** Four hosted evaluation runs of the same model sit in `eval/results/`, and the
README reports two of them as a pinned-provider replication — the claim being that routing the
same model through an aggregator, pinned to one deployment, reproduces the direct-endpoint run
exactly. Re-scoring everything against a corrected golden set, I picked the pair whose `label`
field read `openrouter-phase1-vector-69q-goldenv2-gemini-3.1-flash-lite` and computed the numbers.

They did not match the direct-endpoint run. The vector arm came out 94.6% against 93.6%, and
citations-per-answer differed in the third digit. Either the README's replication claim was wrong,
or I had the wrong files.

**How we got to the answer.** The slow way first, and I did take it: diff all 69 answers between
the two files. **19 of 69 differ** — which is the exact figure the README already attributes to an
*unpinned* run in its reproducibility gotcha. So these were the unpinned runs, mislabelled by
omission: the label names the aggregator but never says whether the pin took.

The fast way was sitting in the file the whole time. Every hosted run records `served_by` per
question, from design decision 28. Counted across the 69 cases:

```
20260826T182707Z   served_by = {Google: 38, Google AI Studio: 31}   <- blended mid-run
20260827T045345Z   served_by = {Google AI Studio: 69}               <- pinned
20260826T210353Z   served_by = {Phala: 69}                          <- pinned
20260825T193407Z   served_by = {None: 69}, model id "models/gemini" <- native endpoint
```

**A provider set of size greater than one *is* the definition of an unpinned run.** No diffing, no
inference, one aggregation over data already on disk. Re-run with the genuinely pinned pair, the
README's claim held exactly: 93.6% → 93.9%, identical to the direct endpoint on the corrected
golden set as it had been on the old one.

The rejected option was to rename the files, which is what "mislabelled" suggests. That treats the
symptom. The real defect is that a results file's identity is split between fields the code writes
and a `label` string a human types, and I read the human's. Renaming produces a *better* typed
label, which is still a typed label.

What the failure exposed as genuinely missing is one field further along the same axis. With three
versions of the golden set now live, **which eval scored a run is recorded nowhere except that same
hand-typed label** — the files literally say `goldenv2` in a string. The fix that generalises is to
record a content hash of the golden set in `config`, promote `served_by` to a config-level set so
pinning is visible without scanning cases, and derive the label from those fields rather than
accepting one by hand.

**Defensive argument.** "I once spent an hour diffing 69 model outputs to work out whether a
benchmark run had been pinned to a single serving deployment. The answer was already in the file:
I record the serving provider on every request, and that run showed 38 responses from one
deployment and 31 from another — blended mid-run, which is what unpinned means. I'd read the
filename label, which a human had typed and which named the aggregator without saying whether the
pin held. The lesson wasn't 'rename the files'. It was that run identity was split between fields
the code writes and a string a person types, and I'd trusted the string. The generalisation is the
part I care about: the same file records which *eval set* scored it the same untrustworthy way,
and I now have three versions of that eval set. So the fix is a content hash of the golden set in
every results file, and a label derived from the recorded fields instead of typed alongside them."

**Show-off argument.** Openings: *"how do you keep experiments reproducible?"*, *"tell me about
debugging something that turned out to be your own bookkeeping"*, *"what does good ML infra look
like to you?"*
> "The most useful field in my results files is one I almost didn't add — I record which serving
> deployment answered every single request, not just which model I asked for. A model id on a
> hosted aggregator isn't one thing; it can be nine deployments at two price points, picked per
> request. That field is what let me prove a benchmark run had been blended across two deployments
> mid-run: 38 responses from one, 31 from the other. What's slightly embarrassing is that I
> established the same fact first by diffing 69 model outputs, because I'd trusted a filename label
> a human typed over the data the code recorded. That's the actual lesson — anything about a run
> that a person types is a claim, and anything the code writes is evidence. I'm now applying it to
> the one piece of run identity still stored as a typed claim, which is which version of my
> evaluation set produced the number."

---

# 28. Fixing one eval set silently broke its paired control

**The scenario.** This project has two question sets. `golden_set.csv` is the baseline;
`paraphrase_set.csv` is a **paired control** — the same 17 facts, rewritten in lay language,
deliberately pointing at the *same target pages*, so that phrasing is the only variable and any
difference in score is attributable to it.

A completeness review then corrected the golden set, adding target pages to 18 rows. Three of
those rows are among the 17 the paraphrase set pairs with. Nothing warned about it, nothing
failed, and both files still validated cleanly on their own.

**The pairing was broken.** The original arm was being scored against a page list that included
`empanelment_dec2021.pdf` p.15; the lay arm, asking the same question, was scored against a list
that did not. The experiment's one guarantee — that only the wording differs — had quietly
stopped holding, and the resulting gap would have been reported as a phrasing effect.

**How we got to the answer.** Not by noticing it directly. The review's write-up needed a line
saying whether the paraphrase figures were current, and checking that meant comparing each
paraphrase row's targets against the golden row it derives from. Four rows disagreed; three
substantively.

The instinct was to re-run and report. Rejected — re-running would have produced *numbers*, and
numbers computed on a broken pairing look exactly like numbers computed on a sound one. The
targets had to be synced first, which meant the fix belonged in the CSV before the run, not in a
caveat after it.

The re-scored experiment then contradicted a claim the README had been making, and had made
*more* strongly earlier the same day:

```
published (mismatched targets)   hybrid 0.402  <  vector 0.443   "fusion drags it BELOW vector"
re-scored (paired targets)       hybrid 0.461  ~  vector 0.453   tied, inside noise
```

The headline finding was untouched — BM25 still collapses from 0.971 to 0.159 and finds the right
page first in 1 of 17 lay-phrased questions. But the *secondary* claim, that fusing in a dead
retriever drags the result below plain dense retrieval, was an artifact of the mismatch. What
survives is weaker and still worth saying: hybrid's large advantage on document-phrased questions
evaporates on lay phrasing, so fusion buys nothing there. It does not go negative.

**The general lesson, which is the reason this is an entry.** A derived evaluation artifact has a
dependency on its parent, and CSV files do not declare dependencies. Every consumer of the golden
set had to be updated when it changed, and the ones that were code — `citation_companions.py`
re-scores from the current set on every invocation — updated themselves. The one that was *data*
did not, and there was no mechanism by which it could. That is the same asymmetry as gotcha 19,
where a golden-set edit propagated automatically to the generation numbers and silently failed to
reach the retrieval table, arriving here in a second form.

**Defensive argument.** "I have a paired control set — the same evaluation questions rewritten in
everyday language, pointing at the same answer pages, so phrasing is the only variable. Then I
corrected the main set, and three of the paired rows were in that correction. Nothing broke;
both files still validated. But the control was no longer controlling, because the two arms were
being scored against different answers, and the gap between them would have been reported as a
phrasing effect. I caught it while checking whether a published table was still current. Syncing
the targets and re-running changed one of my own conclusions: I'd written that fusion drags
retrieval below plain dense search on lay phrasing, and properly paired they're tied — the real
finding is just that fusion's advantage disappears. The lesson I took is that a derived eval
artifact has a dependency its file format can't express. My scoring *code* re-reads the golden set
every run so it can't go stale; my derived *data* had no such mechanism, and that asymmetry has
now bitten me twice."

**Show-off argument.** Openings: *"how do you design an experiment?"*, *"tell me about a control
you had to fix"*, *"what breaks when your evaluation data changes?"*
> "The subtlest bug I've hit on this project wasn't in code — it was two CSV files drifting apart.
> I run a paired experiment: 17 questions in the documents' own vocabulary, the same 17 rewritten
> the way a real user would ask, same target pages, so the only variable is phrasing. Then I
> corrected the main question set and three of those 17 rows were in the correction. Both files
> still passed validation independently; the pairing between them is a relationship neither file
> can express. So my control arm was being scored against a stricter answer key than my treatment
> arm, and the difference would have been published as a phrasing effect. Fixing it actually cost
> me a conclusion — one of my secondary claims turned out to be an artifact of the mismatch. What
> I'd build differently is to stop storing the derived set as an independent file and derive it at
> load time from the parent, so it cannot drift."

---

# 29. `--platform` is an exact tag match, not a compatibility range

**The scenario.** Hugging Face Spaces installs from `requirements.txt` and nothing else, so the
project's two-step local install — CPU-only torch from the PyTorch index first, then everything
else — is unavailable there. Left alone, pip resolves torch from PyPI as a `sentence-transformers`
dependency and pulls the ~2.5 GB CUDA build. This was identified as the single biggest build risk
and resolved in isolation before anything else was touched.

**How we got to the answer.** Two separate problems, and the second was nearly invisible.

The first is that `--extra-index-url` is a *hint*, not a constraint: pip considers both indexes and
picks by version precedence, so a newer torch on PyPI simply wins and the flag does nothing. The
fix is the `+cpu` local-version suffix, which exists only on the PyTorch index — so resolution
either finds the CPU wheel or fails loudly. That much was reasoned out in advance.

The second was not. Rather than pay for a Space build to test it, the graph was resolved for the
target platform from the development machine with `pip install --dry-run --report`, which computes
the full plan and downloads nothing. But `--platform` on pip is an **exact wheel-tag match**, not a
compatibility range. Pip does not reason that a `manylinux_2_28` wheel runs happily on a glibc 2.36
host — it installs a wheel only if its tag is literally in the list you supplied. So supplying one
guessed tag returns *"no matching distribution"*, which is indistinguishable from *"this wheel does
not exist"* — and the obvious next move from there is to loosen the pin, landing straight back on
the CUDA wheel.

Four plausible tags were supplied instead of one, on the prior that a 2026 torch build would have
moved off `manylinux2014` (a glibc 2.17 floor from 2012). The `--report` JSON records the exact URL
pip chose, and the filename was the answer: `manylinux_2_28_x86_64`. A single-tag attempt with the
obvious guess would have failed.

That produced a *new* deployment constraint that had not been written down anywhere: the host image
needs **glibc >= 2.28**. Confirmed afterwards in a container at glibc 2.41, with the caveat recorded
that this is a newer base than Spaces is likely to run — which is still a valid pass, because the
requirement is a floor and glibc is backward-compatible.

**The sharpest part is which test actually proves anything.** The intuitive check,
`torch.cuda.is_available()`, returns `False` on any machine without a GPU — *including one where the
2.5 GB CUDA build installed perfectly*. It would have passed while the exact failure being guarded
against had occurred. The real signal is the **absence of `nvidia-*` packages** in the resolved
closure: those are dependencies of the CUDA build and appear whether or not a GPU exists. Zero of
them, in a closure of 111 packages, is what closes the question.

**Defensive argument.** "Spaces builds from `requirements.txt` alone, so the CPU-only torch install
had to be expressible in one file. `--extra-index-url` is a hint rather than a constraint, so I
pinned `torch==2.13.0+cpu` — that local-version suffix only exists on the PyTorch index, which makes
resolution either find the right wheel or fail loudly instead of silently substituting. I verified it
with a dry-run resolve against the target platform before spending a build, and I passed several
manylinux tags rather than one, because pip's `--platform` is an exact tag match and a wrong guess
returns 'no distribution found' — which looks exactly like 'the wheel doesn't exist'. The report told
me it was `manylinux_2_28`, which turned into a documented glibc floor for the host. And the check I
trust isn't `cuda.is_available()` — that returns False on any CPU box, including one where the CUDA
build installed fine. It's that zero `nvidia-*` packages appear in the closure."

**Show-off argument.** Openings: *"tell me about a deployment problem"*, *"how do you de-risk
something before you ship it"*, or anything about dependency management.
> "The one I'd pick is small and cost nothing, which is the point. My app needs PyTorch but only on
> CPU, and the default resolution pulls a 2.5 GB CUDA build that would blow the image budget. The
> usual advice is `--extra-index-url`, and that advice is wrong — it's a hint, so pip weighs both
> indexes and a newer PyPI version just wins. What actually binds it is pinning the `+cpu` local
> version, because that suffix only exists on one index. Then rather than testing it by pushing and
> waiting on a build, I resolved the target platform's graph locally with `--dry-run --report`, which
> plans the install without downloading it. That surfaced something I'd have got wrong: pip's
> platform flag is an exact tag match, not a compatibility range, so guessing one tag gives you a
> false negative that reads as 'this wheel doesn't exist'. And the acceptance test people reach for —
> `torch.cuda.is_available()` — proves nothing, because it's False on any machine without a GPU even
> if you installed the CUDA build. The real check is that no `nvidia-*` packages appear at all."

---

# 30. The sanitiser corrupted the thing it was protecting, and the run exited 0

**The scenario.** A bash acceptance script authored on Windows was to be executed inside a Linux
container. A stray CRLF would make bash fail on line 1, so the invocation was defensively piped
through a carriage-return strip first. The run completed, reported **exit code 0**, and every
meaningful section had failed.

**How we got to the answer.** The output was full of words like `impot`, `toch`, `gep` and
`equiements`. The guard had deleted every literal letter **`r`**, not carriage returns.

The cause is a quoting boundary: PowerShell 5.1 re-quotes arguments when handing them to a native
executable, and the escaped quote inside the command string was consumed. `tr` received the argument
`r`. The command crossed three parsers — PowerShell, then Docker, then bash — and each one is
entitled to reinterpret backslashes. Nothing warned.

Two compounding failures made it worse than a typo.

**The exit code was inherited, not constructed.** `set -u` does not catch command failures, so with
six of seven sections broken the script still exited 0, because its last statement was an `echo`.
This project already carries a gotcha in exactly this shape — piping to `grep` replaces the exit
code and once masked a hard crash as `exit 0`. Same lesson, new costume: **a script's exit status is
a claim it has to earn.** The rewrite gives every check an explicit PASS/FAIL, tallies them, and
exits non-zero if any failed.

**The first verification attempt reproduced the bug.** Checking whether the file really had CRLFs,
a `grep -c` for a carriage return reported 74 — every line. That was itself wrong, matching the
letter `r` for the same reason. Only a byte-level count settled it: **0 CR bytes, 74 LF**. The file
had been clean Unix all along, so the guard was not merely harmful, it was never needed. A
pattern-based check was unreliable for diagnosing a problem *about* pattern mangling; the
authoritative check had to operate on bytes.

**Defensive argument.** "I added a defensive CRLF strip to a script before running it in a container,
and it silently deleted every letter 'r' in the file, because the argument crossed PowerShell, Docker
and bash and one of them ate the backslash. The run still exited 0, because the exit code came from
the last echo rather than from anything the script had verified. Two things came out of it. I don't
add a guard against a condition I haven't confirmed exists — I checked afterwards and the file had
zero CR bytes, so the guard was pure risk. And an acceptance script has to construct its own exit
status: mine now tallies explicit passes and failures and exits non-zero on any. The related trap is
that my first check was a grep for a carriage return, which returned a confidently wrong answer by
matching the letter — you can't diagnose a mangling problem with a tool subject to the same
mangling. A byte count is what settled it."

**Show-off argument.** Openings: *"tell me about a bug that wasted your time"*, *"a time your own
tooling misled you"*, or anything about defensive programming.
> "My favourite recent one is a defensive measure that caused the exact outage it was preventing. I
> was running a Windows-authored shell script inside a Linux container and added a CRLF strip, just
> in case. It deleted every letter 'r' in the script — `import` became `impot`, `grep` became `gep` —
> because the argument crossed three parsers and one of them consumed the backslash. What actually
> worries me isn't the quoting; it's that the run reported success. Six of seven checks had failed
> and the exit code was 0, because it came from the last echo. So the fix wasn't better escaping, it
> was making the script earn its exit status — every check reports pass or fail, and the script exits
> non-zero if any failed. And there's a coda: my first attempt to verify the file had CRLFs used a
> grep for a carriage return, which told me all 74 lines had them. That was the same bug again — it
> matched the letter. The file had zero CR bytes. You can't diagnose a mangling problem with a tool
> that's subject to the mangling."

---

# 31. The plan assumed a build step the platform does not have

**The scenario.** The deployment plan, written a day earlier, contained a task: *fetch both models at
build time and warm them at startup, so no visitor ever pays for a download* — and argued that doing
so made an open question moot, namely whether a Space wake is a restart (model cache survives) or a
rebuild (it does not). The app loads two models, `bge-small` at 133 MB and a cross-encoder at 90 MB,
and today the cross-encoder downloads lazily on the first reranked query.

**How we got to the answer.** Reading the platform's actual extension points before designing around
them. A Streamlit-SDK Space has exactly two hooks: `requirements.txt`, which pip consumes, and
`packages.txt`, which apt consumes. **Neither can execute project code**, and downloading a model
means running `SentenceTransformer(...)`. Only the Docker SDK provides a `Dockerfile` with a `RUN`
line that can bake weights into an image layer.

So on the chosen SDK, "build time" and "startup" are the same moment, and the plan's claim that
baking it in made the restart-vs-rebuild question moot **does not hold** — the question stays open
and has to be measured.

The choice was put to the owner rather than taken, because it is a real trade:

- **Streamlit SDK, warm at import** — load both models inside a `@st.cache_resource` at module scope,
  so the download happens during container start rather than lazily mid-session. Keeps the SDK the
  plan assumed. The cost is that whether a cold-start visitor still watches the download depends on
  whether Spaces marks the app ready before or after the first script run — unverified, and a
  measurement rather than something to reason out.
- **Docker SDK, prefetch in a RUN layer** — weights genuinely baked into the image, and explicit
  control of the base image's Python version. Costs a Dockerfile as a new artifact to maintain.

Streamlit SDK was chosen, on the grounds that it reaches the deployment's *measurement* phase sooner,
and that measurement is what settles two other open decisions. Switching to Docker stays available if
the startup number shows visitors actually paying the download.

**The transferable finding is not about Spaces.** A task list written in prose can encode a platform
capability that nobody checked, and it reads as authoritative afterwards precisely because it is
written down. This one would have been discovered while implementing it, at the point where it is
most expensive to change course.

**Defensive argument.** "My deployment plan said to fetch the models at build time so no visitor pays
for the download. When I went to implement it I checked what the platform actually offers, and a
Streamlit-SDK Space has two hooks — a pip file and an apt file. Neither runs code, and downloading a
model means running code. Only the Docker SDK has a build step that can. So on my SDK, build time and
startup are the same moment, and the plan's claim that this made the restart-versus-rebuild question
moot was wrong — that question is still open. I chose to warm both models at import so the download
lands in container start rather than mid-session, and I kept the Docker route available, but I wrote
down that whether a cold-start visitor still waits is unverified rather than pretending it's solved."

**Show-off argument.** Openings: *"tell me about a plan that didn't survive contact"*, *"how do you
handle a spec that turns out to be wrong"*, or anything on deployment platforms.
> "I'd written a deployment plan with a step that said 'bake the models into the image at build time
> so no user pays for the download', and it read as settled because it was written down. When I got
> to it, I checked what the platform actually exposes rather than assuming, and the SDK I'd chosen has
> exactly two extension points — a requirements file and an apt file. Neither executes code. Fetching
> a model is executing code. So the step was impossible as written; only the Docker SDK has a real
> build stage. What I find interesting is the failure mode of my own plan — I'd also written that
> baking the models in made a separate open question moot, and that conclusion silently depended on
> the impossible step. One wrong assumption had closed a question that was still open. I picked the
> lighter option, warming at import so the download moves into container start, and I explicitly
> re-opened the question I'd prematurely closed rather than carrying the plan's conclusion forward."

---

# 32. The container throttled the CPU but never told the library

**The scenario.** The deployment target is a 2-vCPU Hugging Face Space, and the whole of
deployment phase D-2 hangs on one number: what a reranked query costs there. The existing figure
was a projection written from reasoning — *"expect ~20–30 s instead of 6 s"* — with no measurement
behind it, and two open decisions depended on it: whether the demo defaults to reranking, and
whether the cross-encoder needs int8 quantisation. Rather than wait for the Space to exist, the
pipeline was run in a container capped with `--cpus=2`.

**How we got to the answer.** The first version of that measurement would have been wrong, and the
tell was a debug line printed almost by accident: `host cpus visible to python: 8`.

`--cpus=2` is a **cgroup CPU quota** — the container gets two cores' worth of *time*. It does not
change what the kernel reports, so `os.cpu_count()` still returns the host's 8, and torch sizes its
intra-op thread pool from that. It chose 4 threads (torch uses physical cores, not logical), and
those 4 threads then contended for a quota of 2. That is not a simulation of a 2-vCPU box; it is a
simulation of something *worse* — a real 2-vCPU machine would run 2 threads with no oversubscription.

So the measurement was run as four arms under the same `--cpus=2` budget, varying only the thread
count, over 20 questions each:

```
mode     threads      p50        p95
rerank   default    7,615 ms   8,120 ms
rerank   pinned 2   3,974 ms   4,242 ms      -47.8%
vector   default      109 ms     182 ms
vector   pinned 2       39 ms      54 ms     -64%
```

**Pinning the thread count nearly halves reranked retrieval, and cuts dense retrieval to a third.**
Same code, same models, same CPU budget. The only change is not asking for more parallelism than
the container is allowed to deliver — the surplus threads spend their time being descheduled.

Two consequences, and the second matters more than the first.

**The projection changed.** The faithful figure is ~4.0 s of retrieval plus the measured ~0.5 s of
hosted generation — about **4.5 s end to end**, against a pre-registered threshold of ~5 s for
switching the demo's default retrieval mode. The pessimistic arm would have read 8.1 s and closed
that question in the wrong direction. It is still a projection and is recorded as one: two cores
under a cgroup quota are not two of a cloud provider's shared vCPUs, and there is no cold start,
network I/O or noisy neighbour in it. What changed is that the decision became live instead of
looking hopeless, and that int8 quantisation — which would have forced a full re-baseline of all
four retrievers — is not needed yet.

**Thread count became a deployment parameter.** `torch.set_num_threads()` now belongs in the
deployed app, set from an environment variable. Shipping without it would have cost ~3.6 s per
query on a machine that had no obvious defect, and the natural suspect would have been the
cross-encoder itself — the component that was *already* known to be slow, and therefore the one
that would have absorbed the blame. A performance bug hiding behind a legitimately expensive
component is close to undiscoverable by intuition.

The setting is deliberately an **env var defaulting to 2, not a hardcoded 2**, because the value
that is right for a 2-vCPU host is wrong for an 8-core development machine. And it is set in
`app.py` and **not** in the retrieval module: every committed evaluation number was measured under
torch's default threading, and changing that inside the pipeline would silently re-baseline the
entire project. It is a property of the deployed product, not of the retriever.

**Defensive argument.** "I needed to know what a query would cost on a 2-vCPU host before the host
existed, so I ran the pipeline in a container capped at 2 CPUs. That measurement was nearly wrong.
`--cpus` is a cgroup quota, not a visible core count, so the library still saw the host's 8 cores
and sized its thread pool from them — 4 threads sharing 2 cores' worth of time. I caught it because
I'd printed the visible CPU count, and I ran the measurement as four arms varying only thread count.
Pinning to 2 cut reranked retrieval by 48%, from 7.6 s to 4.0 s. So the honest projection is ~4.5 s
end to end rather than ~8, and the thread count became something I set explicitly in the deployed
app — from an env var, because the right value differs between the server and my laptop, and in the
UI layer rather than the retrieval layer, because changing it in the pipeline would have
re-baselined every number I've published."

**Show-off argument.** Openings: *"tell me about performance work"*, *"how do you test something
before the infrastructure exists"*, or anything about containers and resource limits.
> "There's a trap in benchmarking inside a container that I nearly walked into. I wanted to know how
> my reranker would behave on a 2-vCPU host before I had one, so I ran it with `--cpus=2`. But that
> flag is a CPU-time quota, not a core count — the kernel still reports every host core, so PyTorch
> sized its thread pool from 8 cores and spawned 4 threads to share 2 cores' worth of time. That's
> not a 2-vCPU box, it's worse than one, because you've added contention on top of the throttle. I
> only noticed because I'd printed the visible CPU count in the setup line. When I pinned threads to
> 2, latency dropped 48% — 7.6 s to 4.0 s — which moved my end-to-end projection from about 8
> seconds to 4.5, and 5 was my threshold for a product decision. What I take from it isn't really
> about containers: it's that the slow component was already the prime suspect, so a genuine
> configuration bug would have hidden behind it indefinitely. Nobody investigates the thing they've
> already explained."

---

# 33. Two UI surfaces that were correct when written and wrong by the time anyone looked

**The scenario.** Preparing the Streamlit app for deployment turned up two defects in it. Neither
is a coding error; both would pass any test that was written for them; and both had been sitting
in the app for weeks looking perfectly reasonable.

1. **The retrieval-mode help text quoted MRRs of 0.624, 0.677 and 0.795.** The live figures are
   0.699, 0.766 and 0.879. The numbers had been copied into the source by hand, and the golden set
   was revised three times afterwards.
2. **The latency caption rendered `prompt 0.0s, generation 0.0s` under a query that took 1.8 s.**

**How we got to the answer.** The two look unrelated and share a root: *a surface that was accurate
when it was written, on a path nobody re-checked when the deployment target changed.*

The first is the ordinary version. The stale numbers were not a slip — the comment sitting directly
above them **predicted the failure**: *"these are copied here rather than computed. That makes them
a thing that can go stale."* The prediction was correct and the warning changed nothing, which is
the useful part. A comment saying "remember to update this" is not a mitigation; it is a record of
knowing better. So the fix was not to correct the numbers but to remove the possibility: the help
text is now prose written in the source and figures read from the committed results files at
startup, under a deliberately strict rule — retrieval-only runs, scored by the question set that is
live *right now* (matched on content hash, not filename), full runs only, and `k` equal to the
app's default.

The strictness immediately earned itself. Two of the six retrieval modes have no results file
matching the live question set, because their current figures were re-scored from saved candidate
lists rather than re-run. The UI now says *"no current measurement"* for those two instead of
displaying the superseded numbers it used to display. **The rule did not just refresh the numbers,
it discovered that two of them should never have been shown at all.**

The second defect is subtler and was found by accident, in the output of a one-question smoke test
against the hosted endpoint. The timing fields really were zero: only the local backend reports a
prefill/decode split, and an OpenAI-compatible endpoint returns token counts with no phase timings.
The generation module is documented as tolerating exactly that. The UI then rendered those fields
unconditionally — **correct data, displayed without asking whether the data existed.**

What makes it worth an entry is *when* it would have surfaced. Every local test used Ollama, the one
backend that does report the split, so the bug was invisible for the entire project. The deployed
app is hosted. So the first person ever to see it would have been a visitor to the public demo, and
they would have seen it on **100% of queries** — a stat line reading 0.0 s for both phases of a
query that visibly took two seconds, on a project whose entire pitch is that its numbers are
trustworthy. The fix shows the split only when the provider reports one, and otherwise says so.

**The shared lesson.** Both surfaces were validated against the environment they were written in and
never re-validated when the target moved. Tests would not have caught either: the numbers were
"correct" as literals, and the timing fields were correctly read from a real response. What catches
this class is asking, of every surface that displays something, *under which backend and which data
version is this still true?*

**Defensive argument.** "Two display bugs came out of getting the app ready to deploy, and neither
was a coding error. The mode help text quoted retrieval scores that were three golden-set revisions
stale — and the comment above them had explicitly warned they would go stale, which tells you a
comment is not a mitigation. So I made them derived instead: read from the committed results files
at startup, filtered to runs scored by the question set that's live right now, matched on a content
hash. That immediately showed two of my six modes have no current measurement at all, so the UI now
says so rather than showing an old number. The second was a latency caption printing 0.0 s for
prefill and decode. The data was right — only the local backend reports that split, hosted endpoints
don't — but I rendered it without checking it existed. Since the deployment is hosted, every visitor
would have seen it and I never would have, because I only ever tested locally. Both are the same
mistake: a surface that was true in the environment it was written in and never re-checked when the
target changed."

**Show-off argument.** Openings: *"what do you do before shipping something"*, *"tell me about a bug
tests wouldn't catch"*, or anything about documentation and code drifting apart.
> "The bug I think about most from this project is one that would only ever have been visible to
> other people. My app showed a latency breakdown — prefill time, decode time — and against my local
> model it was accurate. The deployed version calls a hosted API, which returns token counts but no
> phase timings, so those fields come back zero. The UI printed them anyway: '0.0 seconds prompt,
> 0.0 seconds generation' under a query that took nearly two seconds. Correct data, rendered without
> asking whether the data existed. And the asymmetry is what makes it interesting — it was invisible
> to me for the whole project because I only tested against the one backend that reports the split,
> and it would have been visible to every single visitor on every single query, on a project whose
> whole claim is that its measurements are careful. I found it in a one-question smoke test I almost
> didn't bother running. It pairs with a second one I found the same day — help text quoting scores
> that were three revisions out of date, under a comment that had predicted they'd go stale. Same
> root: things that were true when written, on paths nobody re-checked after the target moved."

---

*Every entry from the project's earlier phases has now been backfilled. New findings get an entry
in the session that produces them — see the process rule in the
[README](../README.md#important--the-engineering-journal-is-a-required-deliverable).*
