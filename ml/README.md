# ml/: local model serving for the product-matching bake-off

This directory holds Docker services that serve the Phase D candidate models on the owner's
machine (RTX 3060 12 GB, Ryzen 5 8500G with 6 cores and 12 threads, 30 GB RAM). It also holds
a thin client that hides which engine runs a model, and the scripts that produced the numbers
below.

**Catalogue text never leaves the machine.** Every model runs locally and every port binds to
127.0.0.1. No catalogue data is kept in this directory or in git. The bench reads pairs from a
path you give it and writes results to `ml/out/`, which git ignores.

This directory covers serving and measurement only. Which model is best at matching is the
bake-off's question, and nothing here measures matching accuracy.

## Quick start

Services run offline by default, so on a fresh clone download the weights first
(["Downloading weights, then offline"](#downloading-weights-then-offline)). Then:

```bash
cd ml
# Small GPU services fit together (~9.5 GB). Start vLLM services ONE AT A TIME (--wait): vLLM
# profiles free GPU memory at start-up, so two starting at once break each other's profiling
# ("Error in memory profiling" / "No available memory for the cache blocks").
for s in rr-bge rr-qwen3-0.6b emb-qwen3 emb-harrier; do docker compose up -d --wait $s; done
docker compose --profile gpu-small down
docker compose up -d --wait rr-qwen3-4b      # OR kev-4b: one 4B model at a time, nothing else
```

```python
import sys; sys.path.insert(0, "ml")
from makhzan_ml.client import connect, SAME_PRODUCT
vecs = connect("emb-qwen3").embed(["ESP32 dev board 30 pin"], instruction=SAME_PRODUCT)
p = connect("rr-qwen3-4b").score([("SG90 servo", "Tower Pro SG90 micro servo 9g")])
```

`score(pairs, instruction)` returns P(yes) per pair for every judge (bge, the Qwen3 rerankers
and Kev). It is not symmetric, so score both orders if you need that. `embed(texts,
instruction)` returns unit vectors. The client uses the standard library only.

Every service sits behind a profile, so a bare `docker compose up` starts nothing. Each service
has its own profile. There are also four group profiles:

- `gpu-small`: all the small GPU services.
- `big`: the two 4B models. Do not start both.
- `cpu`: the CPU services.
- `compare`: the engines that lost the comparison, kept so it can be re-run.

| Service | Model | Engine (image), precision | Port |
|---|---|---|---|
| `emb-qwen3` | Qwen/Qwen3-Embedding-0.6B | vLLM `v0.32.0`, bf16 | 8101 |
| `emb-harrier` | microsoft/harrier-oss-v1-270m | vLLM `v0.32.0`, bf16 | 8102 |
| `rr-bge` | BAAI/bge-reranker-v2-m3 | TEI `86-1.9.4`, fp16 | 8103 |
| `rr-qwen3-0.6b` | Qwen/Qwen3-Reranker-0.6B | vLLM `v0.32.0`, bf16 | 8104 |
| `rr-qwen3-4b` | Qwen/Qwen3-Reranker-4B | vLLM `v0.32.0`, bf16 | 8105 |
| `kev-4b` | jaredpalmer/kev-4b | `kev.serve`, built here (`kev/Dockerfile`), bf16 | 8106 |
| `*-cpu` | the four small models | vLLM CPU `vllm-openai-cpu:v0.32.0-x86_64`, bf16 | 8111–8114 |
| `compare` | the engine that lost for each model | TEI or vLLM | 8121–8133 |

The licences are all permissive: Apache-2.0 (Qwen3 ×3, bge, Kev, and Qwen3.5-4B-Base under
Kev) and MIT (Harrier). No model needs a Hugging Face token.

### Files

Everything stays inside the workspace, and all of it is git-ignored:

- **Weights** go to `ml/.cache/huggingface`, bind-mounted into each container. The mount source
  is `${ML_CACHE_DIR:-./.cache}`, relative to this directory. When you run from another checkout,
  such as an agent worktree, set `ML_CACHE_DIR=<main checkout>/ml/.cache`
  so the weights are not downloaded twice. The weights take about 29 GB.
- **Compile caches** go to `ml/.cache/vllm` (vLLM's torch.compile cache) and `ml/.cache/triton`
  (Kev's Triton kernels). Without the Triton cache, the first Kev request after a cold start
  takes about 60 s.
- **Bench output** goes to `ml/out/` (`bench.py --out`, which defaults there).
- **SELinux:** the `:z` mount suffix relabels only the directories that are mounted.

The vLLM and TEI containers run as root, so files they create under `ml/.cache` are owned by
root. `kev-4b` runs as `${UID:-1000}:${GID:-1000}`; export `UID` and `GID` if yours is not 1000.
To take root-owned files back:

```bash
docker run --rm -v "$(realpath "${ML_CACHE_DIR:-ml/.cache}"):/c:z" python:3.13.9-bookworm chown -R "$(id -u):$(id -g)" /c
```

### Downloading weights, then offline

The services run with `HF_HUB_OFFLINE=1` by default, so no server contacts the Hub and the
weights must already be in `ml/.cache`. To download them, start each service once with the
Hub allowed. It downloads, turns healthy, and can then be stopped:

```bash
cd ml
# kev-4b runs as your uid; the vLLM and TEI images run as root. So: create the cache
# directories yourself (a directory Docker creates is root-owned), let kev-4b download FIRST
# (it then owns hub/, .locks/ and xet/, which root can still write into), and give anything
# root left behind back to you at the end.
C="${ML_CACHE_DIR:-.cache}"
mkdir -p "$C/huggingface" "$C/vllm" "$C/triton"
export UID GID="$(id -g)"   # kev-4b runs as ${UID}:${GID} (compose default 1000:1000)
for s in kev-4b emb-qwen3 emb-harrier rr-bge rr-qwen3-0.6b rr-qwen3-4b; do
  HF_HUB_OFFLINE=0 docker compose up -d --wait $s && docker compose stop $s
done
docker run --rm -v "$(realpath "$C"):/c:z" python:3.13.9-bookworm chown -R "$(id -u):$(id -g)" /c
```

Hub requests only ever carry model names, never catalogue text. Telemetry is off in every
service: `VLLM_NO_USAGE_STATS=1` (vLLM otherwise reports usage stats), `DO_NOT_TRACK=1` and
`HF_HUB_DISABLE_TELEMETRY=1`.

### Images

Every image is pinned by tag and digest (`tag@sha256:...`). Kev's image is built here from a
base pinned the same way, with the Kev source pinned by commit and tarball checksum and every
added package pinned by version. vLLM gets `shm_size: 2gb` rather than `ipc: host`.

## GPU in Docker

This works on this machine without changing any configuration. `docker info` lists only the
runc runtime, but Docker 29 resolves `--gpus all` and the compose `deploy.resources...devices`
reservation through CDI. `nvidia-ctk` 1.20 has generated `/run/cdi/nvidia.yaml`.
`docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi -L` and
`--device nvidia.com/gpu=all` both list the RTX 3060.

If this stops working, for example after a driver update, regenerate the CDI spec. Both
commands need sudo:

```bash
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
# or, the runtime route:
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
```

## Engines, and why

Each candidate engine was taken from the engines' own documentation (read 2026-11-13). The
final choice was then **measured**: where two engines could serve a model, both were run on
the same pairs. The faster one was kept only if it gave the same answers (see the
"Engine comparison" rows below).

- **Qwen3-Reranker 0.6B / 4B → vLLM 0.32.0.** These are causal LMs scored on the "yes"/"no"
  logits, not sequence classifiers, so TEI cannot serve them. TEI's supported rerankers are
  "CamemBERT, and XLM-RoBERTa Sequence Classification models". vLLM's scoring documentation
  lists `Qwen/Qwen3-Reranker-0.6B` and gives the conversion for the official checkpoints
  (`--hf-overrides` with `Qwen3ForSequenceClassification`, `classifier_from_token: ["no",
  "yes"]`, `is_original_qwen3_reranker: true`, plus the `qwen3_reranker.jinja` template).
  0.32.0 is the newest vLLM with a final GitHub release (0.33.0 is still `rc3` there). Its
  images use CUDA 13.0, which driver 615 supports.
- **Qwen3-Embedding-0.6B and Harrier-270m → vLLM.** Both model cards list TEI, and TEI 1.9.4
  added Harrier (PR #854). vLLM measured faster with the same answers:
  - Qwen3-Embedding-0.6B: vLLM is only 1.13× faster (137 vs 121 pairs/s at best). That is
    close enough that either engine is a reasonable choice.
  - Harrier: vLLM is about 6.5× faster (477 vs 74 pairs/s at best). TEI serves Gemma3 only in fp32 and
    without flash attention.
- **bge-reranker-v2-m3 → TEI 1.9.4 on the GPU.** It is an XLM-RoBERTa classifier, which TEI
  supports natively. TEI measured ahead of vLLM at larger batches (390 vs 343 pairs/s at best).
- **Everything on CPU → vLLM's CPU backend.** It runs bf16 on this Zen 4's AVX-512 and was 5.1–7.8×
  faster than TEI's CPU build (candle) on all three models both engines can serve:
  - Qwen3-Embedding: 7.3 vs 1.2 pairs/s.
  - Harrier: 29.1 vs 3.8 pairs/s.
  - bge: 17.4 vs 3.4 pairs/s.

  The answers matched the GPU's.
- **Kev-4B → Kev's own server (`kev.serve`), built from the pinned `kev-1.0` commit.** Kev is a
  LoRA adapter plus a pointer head on Qwen3.5-4B-Base. Kev's README documents only its own
  server (torch on CUDA/ROCm, MLX, or CPU), with no GGUF, llama.cpp, ONNX or vLLM path. vLLM
  0.32 added an endpoint with the same name, `POST /v1/systemone`, but it is not Kev. Its PR
  (#59299) prompts a generic generation model and reads label logprobs, which the PR itself
  calls "uncalibrated". The image adds flash-linear-attention 0.5.2, the version that Kev's
  fused Qwen3.5 kernels pin.
- **llama.cpp: not used.** Its niche is GGUF-quantised models, and nothing here needed
  quantisation to fit (see the verdicts below).

## Results

Setup for every run:

- **Pairs:** the 247 Phase C validation pairs (title + specs per listing) are scored for the
  checks below. Throughput is timed on 1,000 **distinct** pairs of the validation listings'
  texts, none of them a validation pair (`bench.py`, `unique_pairs`, which asserts they are
  distinct).
- **Prefix cache off for every vLLM throughput run that bench.py starts**
  (`--no-enable-prefix-caching`, set through `VLLM_EXTRA_ARGS`). With `--no-lifecycle` the
  server is yours and keeps its own setting; the result records `bench_started_server` and the
  bench warns. The ~500 listing texts necessarily recur across
  1,000 pairs. With the cache on, vLLM served the repeats from memory, and the figures measured
  the cache rather than the model. These numbers are therefore a floor. In real serving, the
  rerankers' shared template prefix would be cached legitimately and they would run somewhat
  faster.
- **Client:** 4 requests in flight. "Batch" is pairs per request. For Kev, "batch" is exactly
  the number of requests in flight, because Kev takes one state per request.
- **Load time:** measured from `up` to healthy, with weights already cached.
- **GPU memory:** for vLLM, GPU memory is its preallocated `--gpu-memory-utilization` cap, not
  what it needs. The weights alone are 7.6 GiB for the 4B reranker and about 1.2 GiB for 0.6B.
- **CPU:** CPU services ran on all 12 threads (6 cores with SMT) with 250 pairs. "Per thread"
  divides by 12; double it for a per-core figure.

**What changed from the first version of this table** (fixed after review):

1. The first version repeated texts that the cache had just seen (`unique_pairs` reused each
   A text verbatim), with the prefix cache on. That inflated every vLLM figure:
   - emb-qwen3: 223 → 137 pairs/s (best of each run).
   - emb-harrier: 1,104 → 477.
   - rr-qwen3-0.6b: 217 → 124.
   - rr-qwen3-4b: 29.4 → 18.8.
   - rr-qwen3-0.6b-cpu: 17.7 → 6.4.

   The FP8 4B "1.8× speed-up" was the same artefact: FP8 left more KV room, so more was cached.
   Measured cache-free, FP8 peaks at 18.5 pairs/s against bf16's 18.8. The TEI rows have no
   cache and barely moved.
2. Kev's "in flight 1" actually ran 4 requests. The client is fixed, and Kev re-measured gives
   10.8–10.9 pairs/s at every in-flight count.

| Service | Load s | GPU MiB loaded / peak | RAM MiB peak | pairs/s by batch | best pairs/s per thread |
|---|---|---|---|---|---|
| **`emb-qwen3`** (vLLM) | 47.1 | 2203 / 2290 | 2701 | 1: 80.6, 8: 128.3, 32: 136.8, 128: 135.1 | - |
| `emb-qwen3-tei` | 16.1 | 1379 / 2114 | 1098 | 1: 68.8, 8: 107.1, 32: 118.1, 128: 120.7 | - |
| **`emb-harrier`** (vLLM) | 47.1 | 1588 / 1651 | 3408 | 1: 160.1, 8: 398.3, 32: 476.7, 128: 463.0 | - |
| `emb-harrier-tei` | 10.7 | 1404 / 1728 | 1275 | 1: 69.6, 8: 73.5, 32: 64.9, 128: 63.8 | - |
| **`rr-bge`** (TEI) | 10.7 | 1282 / 1570 | 3449 | 1: 199.1, 8: 338.3, 32: 379.1, 128: 390.3 | - |
| `rr-bge-vllm` | 40.3 | 1528 / 1548 | 3940 | 1: 201.5, 8: 343.1, 32: 333.3, 128: 332.2 | - |
| **`rr-qwen3-0.6b`** | 47.3 | 3401 / 3488 | 2684 | 1: 93.4, 8: 124.0, 32: 123.9, 128: 123.5 | - |
| `rr-qwen3-0.6b` FP8 | 68.1 | 3405 / 3494 | 2571 | 1: 95.8, 8: 122.3, 32: 121.8, 128: 121.2 | - |
| **`rr-qwen3-4b`** | 67.5 | 9520 / 9787 | 5072 | 1: 15.4, 8: 18.8, 32: 18.7, 128: 18.8 | - |
| `rr-qwen3-4b` FP8 | 67.5 | 9522 / 9791 | 5107 | 1: 16.9, 8: 18.5, 32: 18.4, 128: 18.3 | - |
| **`kev-4b`** | 16.8¹ | 10328 / 10962 | 2905 | in flight 1: 10.8, 8: 10.8, 32: 10.9, 64: 10.9 | - |
| **`emb-qwen3-cpu`** (vLLM) | 81.9 | - | 8657 | 1: 6.7, 16: 7.3 | 0.61 |
| `emb-qwen3-cpu-tei`² | 81.2 | - | 2757 | 1: 1.2, 16: 0.9 | 0.10 |
| **`emb-harrier-cpu`** (vLLM) | 56.2 | - | 8529 | 1: 25.2, 16: 29.1 | 2.43 |
| `emb-harrier-cpu-tei`² | 31.1 | - | 2010 | 1: 3.8, 16: 3.1 | 0.31 |
| **`rr-bge-cpu`** (vLLM) | 46.0 | - | 5154 | 1: 16.2, 16: 17.4 | 1.45 |
| `rr-bge-cpu-tei`² | 151.7 | - | 5043 | 1: 3.4, 16: 2.5 | 0.28 |
| **`rr-qwen3-0.6b-cpu`** (vLLM) | 76.5 | - | 7926 | 1: 6.2, 16: 6.4 | 0.53 |

Bold rows are the served configurations. An embedder's "pair" is two texts embedded, so its
pairs/s compares directly with a judge's.

¹ Kev's load time does not include its cold first request. Without the Triton cache that
request spends about 60 s compiling kernels. Kev runs without CUDA graphs on this card (see
below), so more requests in flight do not raise its throughput. Its card expects several times
lower warm latency with graphs on.

² These rows are from the first run. TEI has no prefix cache and its other rows barely moved
on re-measurement, so they were not re-run.

### Checks: does the served number equal the model's?

Every comparison below is over the 247 validation pairs. The columns are Spearman, max |Δp|,
and agreement of yes/no decisions at 0.5 and at 0.9. A flip is a pair whose decision changed.

| Comparison | Spearman | max \|Δp\| | agree@0.5 | agree@0.9 |
|---|---|---|---|---|
| Qwen3-Reranker-0.6B: card code in transformers fp32 → vLLM **with vLLM's own template** | 0.9929 | 0.279 | 97.2% (7 flips) | 95.6% (11) |
| same → vLLM with `templates/qwen3_reranker.jinja` (explicit ending) | 0.9998 | 0.057 | 100% | 99.6% (1) |
| for scale: card code fp32 → card code bf16 (both transformers) | 0.9994 | 0.106 | 100% | 99.2% (2) |
| Qwen3-Reranker-4B: card code bf16 → vLLM (fixed template) | 0.9990 | 0.040 | 100% | 99.2% (2) |
| emb-qwen3: TEI → vLLM (cosines) | 0.9996 | 0.006 | 100% | 100% |
| emb-harrier: TEI fp32 → vLLM bf16 | 0.9999 | 0.001 | 100% | 100% |
| rr-bge: TEI → vLLM | 1.0000 | 0.013 | 99.6% (1) | 100% |
| GPU → vLLM CPU: emb-qwen3 / emb-harrier / rr-bge / rr-qwen3-0.6b | ≥ 0.9994 | ≤ 0.107 | ≥ 99.6% | ≥ 99.6% |

**The template bug.** vLLM's shipped `qwen3_reranker.jinja` ends `</think>\n\n`, but Jinja drops
a template's final newline. The prompt therefore ends `</think>\n`, which is a different token
from the model card's `</think>\n\n`. The result is scores up to 0.28 away from the card's and
7 of 247 decisions flipped at 0.5. Our copy ends on an explicit Jinja string,
`{{ "</think>\n\n" }}`, so the ending no longer depends on how the file ends. That brings vLLM
to bf16 noise: the card's own code shows the same order of flips at 0.9 between fp32 and bf16.
This is worth reporting upstream.

To re-run the check, use `parity_qwen3_reranker.py` inside the vLLM image, which already has
torch and transformers:

```bash
docker run --rm --gpus all --entrypoint python3 -w / -e HF_HUB_OFFLINE=1 \
  -v "$PWD/ml/.cache/huggingface:/root/.cache/huggingface:z" -v "$PWD/ml:/ml:ro" \
  -v <dir with validation.jsonl>:/data:ro -v "$PWD/ml/out:/out:z" vllm/vllm-openai:v0.32.0 \
  /ml/parity_qwen3_reranker.py --model Qwen/Qwen3-Reranker-0.6B --data /data/validation.jsonl \
  --served /out/scores-rr-qwen3-0.6b.json --dtype float32
```

The embedder rows compare cosines, so their 0.9 threshold is a rough check only. A couple of
pairs sitting at a cosine of about 0.9 can flip on noise.

### Quantisation verdicts

The owner's rule: adopt a quantised variant only if decision agreement is at least 99% at both
0.5 and 0.9, and Spearman is at least 0.99, measured against full precision (`quant.py`). The
variant tested was vLLM's online dynamic FP8, `--quantization fp8`. Ampere has no FP8 tensor
cores, so this runs as FP8 weights with fp16 compute (Marlin W8A16).

| Model | Why try | Speed | Spearman | max \|Δp\| | agree@0.5 | agree@0.9 | Verdict |
|---|---|---|---|---|---|---|---|
| Qwen3-Reranker-4B FP8 | speed | 18.5 vs 18.8 pairs/s (none) | 0.9959 | 0.150 | 100% | **98.4% (4 flips)** | **rejected**: full bf16 kept |
| Qwen3-Reranker-0.6B FP8 | speed | 122 vs 124 (none) | 0.9920 | 0.236 | **98.4% (4)** | **96.8% (8)** | **rejected** |

FP8 gave no speed on this card either: its apparent 1.8× on the 4B was the prefix-cache
artefact described under Results.

Verdicts for the other models:

- **Kev-4B:** quantisation is not needed. Its bf16 weights fit (10,328 MiB, about 10.1 GiB, resident) once CUDA
  graphs and the prefix cache are switched off. With graphs on, start-up runs out of memory.
  Kev documents no quantised path. bf16 is Kev's own serving default, and its card reports
  served probabilities within 0.017 of the fp32 path with no changed answers. That bf16
  comparison was not re-measured here.
- **Embedders and bge:** quantisation is not tried. They use about 2 GB each, and they are not
  the slow part. fp16 vs fp32 was checked for free, because TEI's CPU build runs fp32:
  - Qwen3-Embedding: max |Δ| 0.001 and 100% agreement.
  - bge: max |Δ| 0.002 and 100% agreement.

  fp16/bf16 is therefore the served precision.
- **Not done: int8 for the CPU path.** Examples are ONNX/OpenVINO int8, or GGUF via llama.cpp.
  This is the one place quantisation might pay, because CPU throughput is 6–29 pairs/s. It was
  not measured, so CPU serving stays bf16 until it is.

## Scripts

- `makhzan_ml/client.py`: the uniform client. `SERVICES` maps each name to its engine and port.
- `bench.py`: lifecycle, memory and throughput, and it saves validation scores. Example:
  `python3 ml/bench.py --services rr-qwen3-4b --data <validation.jsonl> --out ml/out`. Options:
  - `QUANT_ARGS="--quantization fp8"` with `--tag=-fp8` benches a variant.
  - `--n` and `--batch-sizes` set the workload.
  - `--cpu-set 0-3` pins the CPU services to fewer cores.
- `quant.py`: compares two score files with the adoption rule.
- `parity_qwen3_reranker.py`: compares the served reranker with the model card's own code.
- `bakeoff/`: the Phase D bake-off (candidate finding and pair judging, with the prompt study).
  Run in this order:
  1. `catalogue.py`: dump the local database copy.
  2. `rules.py`: today's grouping rules, via makhzan_schemas, in the ingestion venv.
  3. `contexts.py`: the context ladder.
  4. `fit.py`: per-model token budgets, inside the vLLM image.
  5. `embed.py` and `retrieval.py`: these need numpy.
  6. `judge.py`, once per running service.
  7. `evaluate.py validation`, then `evaluate.py test` once.

  Each script's docstring gives its exact command. Catalogue text goes to a private directory
  you name. `ml/out/bakeoff/` gets pair ids, scores and counts.
