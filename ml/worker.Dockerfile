# The AI-matching worker (makhzan_ml.worker) on top of a model image: one Dockerfile, four images.
#
# The worker runs the model in-process, on the scoring path every validated score went through,
# so it is a thin layer over the image that already holds the model's code and pinned packages:
#
#   BASE                              image                          worker
#   makhzan-ml/kev-cpu-lean:1.0       ml/kev/Dockerfile.cpu-lean      home-kev   (CPU, fp32)
#   makhzan-ml/pplx-decider-cpu-lean:1.3  ml/pplx/Dockerfile.cpu-lean desk/home-pplx on CPU
#   makhzan-ml/kev:1.0                ml/kev/Dockerfile               desk-kev   (GPU, bf16)
#   makhzan-ml/pplx-decider:1.3       ml/pplx/Dockerfile              desk-pplx  (GPU, bf16)
#
# The two CPU workers are built by CI and published to GHCR, each chained onto the lean base
# built in the same run (ml/docker-bake.hcl, .github/workflows/ai-worker-images.yml); the same
# chain builds locally with `docker buildx bake -f ml/docker-bake.hcl kev-worker-cpu`. The GPU
# workers are local builds from the ml/ directory (docs/ai/worker.md, "Images"):
#   docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/kev:1.0 \
#     -t makhzan-ml/kev-worker-gpu:1.0 ml
#
# Nothing here changes how the model scores: the worker sets the same environment the compose
# services and the CPU benchmark used (makhzan_ml/worker/judges.py) and adds only the worker's
# own standard-library code. Report the image at hello with -e MAKHZAN_IMAGE=... (its registry
# digest, or a local build's id; the run commands in docs/ai/worker.md do).
ARG BASE=makhzan-ml/kev-cpu-lean:1.0
FROM ${BASE}

# MAKHZAN_KEV_COMMIT, the Kev serving code the worker checks against its pin, comes from the
# Kev base images (ml/kev/Dockerfile*, an ENV beside the source it was built from); it is not
# set here, so a worker layer cannot claim a commit its base does not hold. Unset in the pplx
# images, which do not read it.
ENV PYTHONPATH=/opt/makhzan${PYTHONPATH:+:${PYTHONPATH}} \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1

COPY makhzan_ml/__init__.py /opt/makhzan/makhzan_ml/__init__.py
COPY makhzan_ml/worker /opt/makhzan/makhzan_ml/worker
RUN python -c "import makhzan_ml.worker.run, makhzan_ml.worker.judges; print('makhzan_ml.worker ok')"

ENTRYPOINT ["python", "-m", "makhzan_ml.worker"]
CMD ["--config", "/etc/makhzan-ai/worker.toml"]
