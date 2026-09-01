---
title: PM-JAY Document Assistant
emoji: 📄
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 8501
pinned: false
license: mit
short_description: Cited answers over India's PM-JAY health scheme documents, with the retrieval measured rather than asserted.
---

<!-- The Hugging Face Space landing card. NOT the active deployment: the app runs
     on Streamlit Community Cloud, deployed straight from the GitHub repo. Kept
     because a Docker Space needs a PRO subscription, so this is the paid
     fallback rather than the current path. -->

# PM-JAY document assistant

Ask a question about India's Ayushman Bharat (PM-JAY) health scheme and get an answer
built **only** from the National Health Authority's own published documents — with the
filename and page number behind every claim, and a refusal when the retrieved evidence
does not support one.

11 documents · 629 pages · 872 indexed chunks · 69 hand-written evaluation questions.

## What is actually interesting here

Most RAG demos show you an answer. This one shows you **what the answer cost and how
well it works**, because the retrieval was measured one change at a time against a
hand-written, hand-verified question set.

**Reranking improved retrieval by 26% and bought almost no answer quality.** MRR went
0.699 → 0.879 and rank-1 accuracy rose 25 points. The only measurable benefit in the
generated answers was fewer false refusals; citation *precision* improved on no model
tested and got *worse* on a small local one. "We added reranking and the system
improved" is a claim this project can't support, and it went looking.

**A keyword scorer beat the embeddings.** Plain BM25 outscored `bge-small-en-v1.5` on
this corpus — government manuals are full of rare exact tokens (`HWCs`, `PAN card`,
`5,00,000`) that a 384-dimension embedding blurs and an IDF term rewards. Then a
robustness check inverted the result: on the same questions rephrased in everyday
language, BM25 finds the right page first in **1 of 17** questions.

**The evaluation set turned out to be wrong, and correcting it moved every published
number.** A review found 18 of 60 answerable questions were missing pages that genuinely
answer them — two listed a page that does not contain the answer at all. A documented
"reranker failure" turned out to be a measurement failure.

## Try the retrieval modes

The sidebar switches retriever: dense embeddings, BM25, rank fusion, or a cross-encoder
reranker — each showing its measured MRR and latency, read from the committed evaluation
results rather than typed in. Expand any source to see the exact chunk and page the
answer came from.

## Honest limitations

- **This is a portfolio demo on free hosting.** First load takes ~30 seconds while two
  models load, and there is a daily quota shared by everyone.
- **Not medical or legal advice.** It reports what the source documents say. Two
  editions of the empanelment guidelines are in the corpus and they contradict each
  other on several rules; which one is currently in force is an open question.
- **English only**, and the evaluation questions were written by someone who had read
  the documents — which measurably flatters the retrieval scores.

## The full engineering record

Source, the 69-question evaluation set, every results file, 33 design decisions, 25
gotchas and a 33-entry engineering journal:
**[github.com/patelsagar2611/rag-ayushman](https://github.com/patelsagar2611/rag-ayushman)**

Source documents are Government of India publications from the National Health Authority
and state health agencies, used here for a non-commercial portfolio project.
