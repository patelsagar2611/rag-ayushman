# Hugging Face Space, Docker SDK.
#
# WHY DOCKER AND NOT THE STREAMLIT SDK. There is no Streamlit SDK any more --
# the Hub API accepts only "gradio", "docker" and "static", and rejects
# "streamlit" outright, even though the Streamlit SDK documentation page is
# still live and still describes it. The API is the ground truth. Gradio was
# not considered: it would mean rewriting the interface, and app.py is the
# artifact every measurement in the README describes.
#
# The base image is python:3.12-slim, which is what the D-1 acceptance test ran
# on -- same interpreter, same glibc floor (the torch wheel is manylinux_2_28),
# same resolver behaviour that produced requirements-lock.txt.

FROM python:3.12-slim

# Spaces run containers as a non-root user with uid 1000. Creating it ourselves
# means the HF cache, the app directory and Chroma's sqlite store are all owned
# by the user that will actually run them -- Chroma opens its store READ-WRITE
# even for a pure read, so a root-owned index would fail at startup rather than
# on first query.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

# Dependencies first, so the ~200 MB torch layer is cached across code changes.
# requirements.txt here is the generated lockfile: the full 111-package closure
# captured inside this same base image. See requirements-lock.txt in the source
# repo for why, and deploy_space.py for the rename.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# BAKE THE MODELS INTO THE IMAGE. This is the thing the old Streamlit SDK could
# not do: it had only requirements.txt (pip) and packages.txt (apt), neither of
# which executes code, so a model download could not happen before startup.
#
# src/ is copied first so the model names come from their single source of truth
# (src/index.EMBED_MODEL and src/retrieve.RERANK_MODEL) rather than being
# repeated here, where they could drift. The cost is that editing src/ rebuilds
# this layer; the alternative was duplicating two model ids into a Dockerfile,
# which is exactly the kind of copy this project keeps getting bitten by.
COPY --chown=user src/ src/
RUN python -c "\
from src.index import EMBED_MODEL; \
from src.retrieve import RERANK_MODEL; \
from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer(EMBED_MODEL); \
CrossEncoder(RERANK_MODEL); \
print('baked:', EMBED_MODEL, RERANK_MODEL)"

COPY --chown=user . .

# Measured: 4 threads contending for a 2-core quota costs ~48% of reranked
# retrieval latency (7,615 ms -> 3,974 ms p50). torch sizes its pool from the
# HOST's core count, which is not what the cgroup grants. Set here rather than
# as a Space Variable so it cannot be lost by editing settings.
ENV PMJAY_TORCH_THREADS=2

# Cross-encoder batch size. At the library default of 32 the app is OOM-killed
# under a 768 MB cap (peak 1,186 MB); at 8 it peaks at ~868 MB and survives, for
# ~12% more latency. Scores are bit-identical at every batch size, so this costs
# nothing in ranking quality -- see the measurement table in src/retrieve.py.
ENV PMJAY_RERANK_BATCH=8

# The deployment's backend, baked in rather than set as Space Variables. These are
# configuration, not secrets, and putting them here means the image DESCRIBES what
# it runs -- a pulled image answers "which endpoint, which model" without anyone
# reading a settings page that may since have been edited. It also reduces the
# manual setup on the Space to exactly one item, the API key, which is the step
# most likely to be missed.
#
# The trade is that changing the model means a rebuild rather than editing a
# Variable. Accepted: the model is part of what every published number describes,
# so changing it SHOULD be a deliberate, versioned act.
#
# These mirror the google block in .env.example, which is the local source of
# truth. GOOGLE_API_KEY is deliberately absent -- it is a Space Secret.
ENV LLM_PROVIDER=openai \
    LLM_BACKEND=google \
    GOOGLE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/ \
    GOOGLE_MODEL=models/gemini-3.1-flash-lite

# Streamlit's default port. Declared as app_port in the Space's README front
# matter; the two must agree or the Space serves nothing.
EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
