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
# Build from the ml/ directory (docs/ai/worker.md, "Images"):
#   docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/kev-cpu-lean:1.0 \
#     -t makhzan-ml/kev-worker-cpu:1.0 ml
#
# Nothing here changes how the model scores: the worker sets the same environment the compose
# services and the CPU benchmark used (makhzan_ml/worker/judges.py) and adds only the worker's
# own standard-library code. The base images are local builds, referenced by tag; they are not
# in a registry, so FROM cannot pin them by digest. Report the built image's id at hello with
# -e MAKHZAN_IMAGE=... (the run commands in docs/ai/worker.md do).
ARG BASE=makhzan-ml/kev-cpu-lean:1.0
FROM ${BASE}

# The Kev serving code the base image was built from (kev/Dockerfile*: KEV_COMMIT); the worker
# refuses to score if this disagrees with its pin. Not read by the pplx images.
ARG KEV_COMMIT=6b719c3c3f367295f6ef336f4f751cf5ff970abc
ENV MAKHZAN_KEV_COMMIT=${KEV_COMMIT} \
    PYTHONPATH=/opt/makhzan${PYTHONPATH:+:${PYTHONPATH}} \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1

COPY makhzan_ml/__init__.py /opt/makhzan/makhzan_ml/__init__.py
COPY makhzan_ml/worker /opt/makhzan/makhzan_ml/worker
RUN python -c "import makhzan_ml.worker.run, makhzan_ml.worker.judges; print('makhzan_ml.worker ok')"

ENTRYPOINT ["python", "-m", "makhzan_ml.worker"]
CMD ["--config", "/etc/makhzan-ai/worker.toml"]
