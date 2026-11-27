# The AI-matching worker for the llama.cpp backend (production since 2026-11-27): the worker alone,
# on python-slim, with no torch and no model code. The model runs in a llama.cpp sidecar beside it
# (ml/deploy/home-server/compose.yml, kev-llamacpp / pplx-llamacpp); the worker hashes the GGUF it
# is pinned to, talks to the sidecar over HTTP and scores with the standard library only
# (makhzan_ml/worker/judges.py, _load_llamacpp). It also runs the broker proxy.
#
# Built by CI and published to GHCR as worker-llamacpp (ml/docker-bake.hcl,
# .github/workflows/ai-worker-image-build.yml), smoke-tested first with
# `python -m makhzan_ml.worker.smoke --backend llamacpp --model kev|pplx`; locally:
#   docker buildx bake -f ml/docker-bake.hcl worker-llamacpp --load
#
# The image names itself at hello as <repo>:sha-<commit> (run.image_reference), the tag CI puts on
# exactly that tested build. No weights: the GGUFs are mounted from the host at run time.

# The same pinned base as the lean model images (ml/kev/Dockerfile.cpu-lean); its tzdata gives the
# worker's windows their time zone.
FROM python:3.13.9-slim-bookworm@sha256:b685a4fa58bb19d1814d78a1ec0f0208f351452724f78b20212c984d6e124a34

ENV PYTHONPATH=/opt/makhzan \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY makhzan_ml/__init__.py /opt/makhzan/makhzan_ml/__init__.py
COPY makhzan_ml/worker /opt/makhzan/makhzan_ml/worker
RUN python -c "import makhzan_ml.worker.run, makhzan_ml.worker.judges, makhzan_ml.worker.supervisor, makhzan_ml.worker.proxy, zoneinfo; zoneinfo.ZoneInfo('Africa/Cairo'); print('makhzan_ml.worker ok')"

# Not root, as the lean torch images (uid 1000); compose runs it as the host's UID:GID anyway.
RUN useradd --uid 1000 --create-home worker
USER worker

# Last, so a new commit rebuilds only this layer. CI passes the commit it builds and the GHCR
# repository; a local build says "local" unless given --build-arg REVISION=$(git rev-parse HEAD).
ARG IMAGE_REPO=makhzan-ml/worker-llamacpp
ARG REVISION=local
ENV MAKHZAN_IMAGE_REPO=${IMAGE_REPO} MAKHZAN_IMAGE_REVISION=${REVISION}

ENTRYPOINT ["python", "-m", "makhzan_ml.worker"]
CMD ["--config", "/etc/makhzan-ai/worker.toml"]
