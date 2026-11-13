# Kev decision model server (jaredpalmer/kev, `python -m kev.serve`, POST /v1/systemone).
#
# Kev is a LoRA adapter plus a pointer head on Qwen3.5-Base. No general engine runs that head:
# vLLM's own /v1/systemone (v0.32+) prompts a generic generation model and is not Kev, and the
# Kev repository documents no GGUF / llama.cpp / ONNX path. So this is Kev's own server, built
# from a pinned release with its own lockfile (torch 2.8.0, transformers 5.17.0), plus the
# flash-linear-attention version its fused Qwen3.5 kernels pin (kev/fused_qwen35.py FLA_VERSION).
#
# The full python image is used on purpose: Triton compiles a small C launcher at runtime and
# needs gcc and the Python headers, which the slim image lacks.
FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

FROM python:3.13.9-bookworm@sha256:4f26056fb6ace322265b99c8441e7adae065a56720432e4e722ca921217a68e3
COPY --from=uv /uv /usr/local/bin/uv

# kev-1.0 tag, pinned by commit and by the tarball's checksum, so neither a moved tag nor a
# changed archive can change the image.
ARG KEV_COMMIT=6b719c3c3f367295f6ef336f4f751cf5ff970abc
ARG FLA_VERSION=0.5.2
ARG EINOPS_VERSION=0.8.2
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/kev/.venv PATH=/opt/kev/.venv/bin:$PATH

WORKDIR /opt/kev
ADD --checksum=sha256:94176d4f2fb7942a491f8a2134bf92b93ef27632c3ba169e79704e68ae3c2934 \
    https://codeload.github.com/jaredpalmer/kev/tar.gz/${KEV_COMMIT} /tmp/kev.tar.gz
RUN tar -xzf /tmp/kev.tar.gz --strip-components=1 -C /opt/kev && rm /tmp/kev.tar.gz \
 && uv sync --frozen --no-dev --extra serve \
 # --no-deps: fla-core[cuda] would otherwise be free to move torch off the locked 2.8.0.
 && uv pip install --no-deps flash-linear-attention==${FLA_VERSION} fla-core==${FLA_VERSION} \
    einops==${EINOPS_VERSION} \
 && python -c "import torch, transformers, fla; print(torch.__version__, transformers.__version__, fla.__version__)"

# Run as uid 1000, the owner's uid, so the files it writes into the bind-mounted cache
# (ml/.cache in the workspace) are the owner's, not root's.
RUN useradd --uid 1000 --create-home kev
USER kev
ENV HOME=/home/kev HF_HOME=/home/kev/.cache/huggingface
EXPOSE 8000
ENTRYPOINT ["python", "-m", "kev.serve", "--host", "0.0.0.0", "--port", "8000"]
CMD ["--run", "jaredpalmer/kev-4b"]
