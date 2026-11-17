# pplx-decider-flash-v1.3 (perplexity-ai, Apache-2.0, on Qwen3.5-4B), served by its own
# `pplx_decider` package behind a small HTTP shim (serve.py, POST /v1/decide).
#
# No general engine runs this checkpoint: its full-attention layers are noncausal and the answer
# is read by a separate 255-row readout at a marker token, not from an lm_head (model card,
# "Checkpoint format and serving"), so vLLM cannot reproduce it. The package is the model card's
# own inference code, copied from the pinned Hub revision and checked against the sha256 sums in
# that revision's release-manifest.json; its dependencies are the card's pinned
# requirements.txt plus requirements-fast.txt (flash-linear-attention, installed --no-deps so it
# cannot move torch).
FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv

FROM python:3.13.9-bookworm@sha256:4f26056fb6ace322265b99c8441e7adae065a56720432e4e722ca921217a68e3
COPY --from=uv /uv /usr/local/bin/uv

ARG REVISION=d06fb3f2d97e0a52325a0d463c450cf0338f44fe
ARG HUB=https://huggingface.co/perplexity-ai/pplx-decider-flash-v1.3/resolve/${REVISION}
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never \
    VIRTUAL_ENV=/opt/pplx/.venv PATH=/opt/pplx/.venv/bin:$PATH PYTHONPATH=/opt/pplx/src
WORKDIR /opt/pplx

RUN uv venv /opt/pplx/.venv \
 && uv pip install torch==2.14.0 torchvision==0.29.0 transformers==5.17.0 safetensors==0.8.0 \
    pillow==12.3.0 huggingface-hub==1.31.0 \
 && uv pip install --no-deps flash-linear-attention==0.5.2 fla-core==0.5.2 einops==0.8.2 \
 && python -c "import torch, transformers, fla; print(torch.__version__, transformers.__version__, fla.__version__)"

ADD --checksum=sha256:7e95504afcec8696365b936721f80a9013046a70a4d8c25802079eb04ea14d48 ${HUB}/source/src/pplx_decider/__init__.py src/pplx_decider/__init__.py
ADD --checksum=sha256:8b57c37a27365a8a12fc3b4a1853908c7c7d519bfba36871f40e092f1d77f1bf ${HUB}/source/src/pplx_decider/model.py src/pplx_decider/model.py
ADD --checksum=sha256:867392d787151402314028151ca47c8ba89cad969d5b70f2e83c9633abfad2f2 ${HUB}/source/src/pplx_decider/fast.py src/pplx_decider/fast.py
ADD --checksum=sha256:412292fba7f9e92f70f3071935f090e381910d1f6279380e728dc1c6b8380e6c ${HUB}/source/src/pplx_decider/protocol.py src/pplx_decider/protocol.py
ADD --checksum=sha256:f13de0c018e76eb37fd9d7c1fbecc2aa811bb54f650ccc69861c901b65866892 ${HUB}/source/src/pplx_decider/types.py src/pplx_decider/types.py
ADD --checksum=sha256:272a40ba42e83b437022b09fa3e5fe28bf0160b3d1905fa274589f6cfae8eeb8 ${HUB}/source/src/pplx_decider/locate.py src/pplx_decider/locate.py
COPY serve.py /opt/pplx/serve.py
RUN chmod -R a+rX /opt/pplx/src /opt/pplx/serve.py

# uid 1000, the owner's, so files written into the bind-mounted cache stay the owner's.
RUN useradd --uid 1000 --create-home pplx
USER pplx
ENV HOME=/home/pplx HF_HOME=/home/pplx/.cache/huggingface
EXPOSE 8000
ENTRYPOINT ["python", "/opt/pplx/serve.py", "--host", "0.0.0.0", "--port", "8000"]
CMD ["--model", "perplexity-ai/pplx-decider-flash-v1.3", "--revision", "d06fb3f2d97e0a52325a0d463c450cf0338f44fe"]
