# Kev-4B through llama.cpp: quantisation, CPU and AMD GPU (2026-11-26)

These experiments asked whether a quantised Kev-4B could do two things:

- run faster than the home server's CPU worker. It reads about 10 tokens/s (94 s for a
  968-token request) and scored 112 requests (56 jobs) on the night of 2026-11-25, against a
  backlog of 2,583 jobs: about 46 nights at that rate;
- fit the home server's 4 GB AMD card.

**Summary.** llama.cpp reproduces Kev faithfully.

- Q8_0 passes D20. Q4_K_M fails it, but under the production rule it makes no wrong merges and
  loses a net 3 of 209 correct ones.
- On the home server's CPU, llama.cpp gains little: Q8_0 is 1.08× the PyTorch worker's speed
  per token, and F16 about 1.5× (from 2 requests only).
- On the AMD card, Q4 is about 14–19× faster per token, but the card needs better cooling first. It reset
  the server once at stock fan settings.
- **Nothing here is in production.** A worker backend for a llama.cpp sidecar is built and
  parity-checked but not in use (`docs/ai/worker.md`, "Kev on a llama.cpp sidecar"; see "Not
  done").

## What changed from earlier notes

- **Kev does have a llama.cpp path.** llama.cpp added `POST /v1/systemone` for decision models
  (Kev, Laya, julia-1, lev, openjev) in PR #29818, merged 2026-10-02. ggml-org publishes
  `ggml-org/Kev-4B-GGUF` as Q4_K_M (3.03 GB), Q8_0 (4.48 GB) and BF16 (8.43 GB), and
  `ggml-org/Kev-0.8B-GGUF`. Earlier notes said there was no GGUF and no llama.cpp path, which
  was out of date (`ml/README.md`, `model-shortlist.md`).
- **The GGUF builds Kev's temperature in.** Its metadata has
  `qwen35.decision.temperature.noul = 2.406`, and the server always applies it. No request
  parameter turns it off. Every validated Kev score is raw (`KEV_TEMPERATURE=1.0`), so llama.cpp
  scores are uncalibrated before comparing: `p_raw = sigmoid(2.406 · logit(p))`. A production
  backend must do the same, or patch the metadata to 1.0.
- **Batch size changes speed, not scores.** In embedding mode the server sets
  `n_batch = n_ubatch = 512` unless told otherwise, so a request of 1,625 tokens runs in 4
  chunks.
  - Q4 at `-ub 2048` against `-ub 512`, 200 requests: max |Δp| 0.030 on the raw scale used in
    the tables below (0.014 on llama.cpp's calibrated scale). No decision moves except pairs
    within about 0.01 of a threshold.
  - Speed: 2.7× faster at 2,048.
  - Memory: 5.3 GB against 3.6 GB.

## Method

- **Data:** the 1,800 Phase E requests of the chosen setup (900 pairs, both orders, K2 layout,
  description capped at 150 words). Payloads came from `ml/models/prompt_grid.py`'s `payload()`,
  the approved renderer.
- **Reference:** the bf16 GPU scores in `ml/out/prompt-grid/raw/kev-K2-150.jsonl`, from Kev's
  own server on the RTX 3060.
- **Scorer:** `ml/models/kev_gguf.py` (`score` / `compare`), sending one request at a time.
- **Pair score:** the minimum of the two orders, as in production. Decisions use the
  production rule, policy `p1`: Kev ≥ 0.8 **and** pplx ≥ 0.95, on pairs that pass today's
  vetoes.
- **Labels:** `makhzan-config/labels/answer-key-v2.jsonl`.
- **llama.cpp:** build 12767, the official `server-vulkan` and `server-cuda` images, one slot
  (`-np 1`), `-c 4096`.

## Accuracy

Against the bf16 reference, on all 1,800 requests unless noted.

| Variant | Spearman | max \|Δp\| | Pair agreement at 0.5 / 0.8 / 0.9 | D20 |
|---|---|---|---|---|
| BF16 GGUF (100 pairs) | 0.9991 | 0.033 | 100 / 100 / 100% | (control) |
| **Q8_0** | 0.9993 | 0.196 | 99.4 / 99.6 / 99.3% | **passes** |
| Q8_0 on CUDA (100 pairs) | 0.9988 | 0.090 | 99 / 100 / 100% | |
| **Q4_K_M** | 0.9955 | 0.481 | 97.6 / 97.3 / 97.6% | **fails** |

D20 (`ml/quant.py`) requires Spearman ≥ 0.99 and agreement ≥ 99% at both 0.5 and 0.9.

**Under the production rule**, on pairs that pass the vetoes, against the labels:

| Kev variant | Merges | Wrong merges | Changed vs bf16 | Kev ≥ 0.8 alone: precision / recall |
|---|---|---|---|---|
| bf16 | 209 | 0 | — | 0.962 / 0.717 |
| Q8_0 | 209 | 0 | 2 (both "same", within 0.025 of the line) | 0.958 / 0.714 |
| Q4_K_M | 206 | 0 | 9 (all "same": 3 gained, 6 lost) | 0.965 / 0.725 |

- **Q4's flips are noise around 0.8, not a bias.** Of the 24 Kev-only flips at 0.8, Q4 agreed
  with the label on 14 and bf16 on 10. Most were clear twins that Kev under-scores at either
  precision, e.g. "Electrolytic Capacitor 10uF 400v" vs "10uF – 400v".
- **The only harmful Q4 flip is stopped by pplx.** "900M-T-I" vs "900M-T-IS" soldering tips,
  labelled not, scored 0.92 under Q4.
- **Expected magnitude.** llama.cpp's perplexity README puts Q4_K_M's mean KL divergence at
  about 23× Q8_0's on an 8B model. Small models usually lose more.
- **The BF16 control** separates llama.cpp's port from quantisation. All of Q4's loss is
  quantisation.

## Speed

The same requests, one at a time (mean about 860 tokens).

| Machine | Runtime | Precision | Seconds a request | Requests/s | Memory |
|---|---|---|---|---|---|
| RTX 3060 | Kev's own server (reference) | bf16 | 0.34 | 2.96 | ~11 GB |
| RTX 3060 | llama.cpp CUDA | Q8_0 | 0.44 | 2.28 | — |
| RTX 3060 | llama.cpp Vulkan | Q8_0 | 0.49 | 2.06 | 6.7 GB |
| RTX 3060 | llama.cpp Vulkan | Q4_K_M, `-ub 2048` | 0.53 | 1.88 | 5.3 GB |
| RTX 3060 | llama.cpp Vulkan | BF16 | 0.77 | 1.30 | 10.5 GB |
| RTX 3060 | llama.cpp Vulkan | Q4_K_M, `-ub 512` | 1.23 | 0.81 | 3.6 GB |
| i7-3770 (home server) | **PyTorch fp32, the current worker** | fp32 | **94** for 968 tokens (2 requests, E0006), ~2 min in production | 10.3 tokens/s | 17 GB |
| i7-3770 | llama.cpp CPU, 4 threads | Q8_0 | 87 for the same 968-token pair; 20 requests | 11.1 tokens/s | — |
| i7-3770 | llama.cpp CPU, 8 threads | F16 | 50 for 776 tokens (2 requests, E0001; ~62 s scaled to 968) | 15.4–15.7 tokens/s | — |
| RX 470/570 4 GB (home server) | llama.cpp Vulkan | Q4_K_M, `-ub 512`, 85 W, fan auto | 4.4 (8 requests before the reset, 20 on the rerun) | ~195 tokens/s | 3.6 GB |
| RX 470/570 4 GB | llama.cpp Vulkan | Q4_K_M, `-ub 512`, 65 W cap, fan 100% | 6.1 (100 requests) | ~145 tokens/s | 3.6 GB |

The CPU rows are per-token rates, because the requests differ in length; the 3060 rows are
requests/s over the same 1,800 (or 200) requests.

Notes:

- **Where the 3060's llama.cpp numbers come from.** llama-bench pp512/pp1024 for Q8_0 gives
  3,500–3,635 tokens/s on CUDA and 2,875–3,019 on Vulkan, so Vulkan costs 10–20%. The rest of
  the gap to Kev's own server is llama.cpp's fixed cost per request. On this card,
  llama.cpp gives memory, not speed.
- **The CPU numbers are what this CPU can do.**
  - llama.cpp loaded `libggml-cpu-ivybridge.so`, the right build for the i7-3770 (AVX and F16C,
    no AVX2, no FMA). Q4_K_M pp512 was 17 tokens/s.
  - Without AVX2 there are no 256-bit integer instructions. Quantised dot products run at
    128-bit width, while F16 goes through F16C into 256-bit float maths. That is why F16 beats
    Q8_0 here.
  - Q4_0/IQ4_NL repacking needs AVX2, so it does nothing on this CPU.
  - The CPU's ceiling is about 220 GFLOPS, roughly 28 tokens/s for a 4B model. F16 reaches
    about half of that; Q8_0 and PyTorch fp32 about 40%.
  - F16 at 4 threads: one request at 10.3 tokens/s (the first after loading) and one at 15.0;
    8 threads gave 15.4–15.7. Two requests are thin evidence; a longer F16 run (and an F16
    D20 check) is needed before relying on the 1.5×.
  - A published Ivy Bridge result (i5-3470T, llama 7B Q4_0, pp512 2.3 tokens/s on 2 cores)
    scales to about 10 tokens/s here.
- **Why the PyTorch worker is slow.** It runs transformers' reference Qwen3.5 layers.
  `chunk_gated_delta_rule` and `causal_conv1d` fall back to pure PyTorch on CPU, and its log
  says so.
- **Correction.** "17–20 s a request" in `docs/ai/worker.md` was measured on the desktop's CPU
  (Zen 4) capped to 6 cores, not on the home server. The home server's figure is
  `ml/out/bench-cpu/server/kev-K2-150.json`: 94 s for 968 tokens. This session first compared
  llama.cpp against the 17–20 s figure and wrongly concluded that llama.cpp was slower on the
  CPU.
- **AMD card speed.** A Polaris card's published Vulkan pp512 is about 207–258 tokens/s for
  llama 7B Q4_0. A 4B model at full clock should do about 300–350, and the throttled card did
  about 195.
- **AMD accuracy.** The AMD card's Q4 scores match the 3060 running the same Q4 file within
  0.021 on the raw scale (0.0105 calibrated), over 100 requests, so the card computes correctly.

## The AMD card (PowerColor RX 470/570 4 GB, Polaris)

- **Reset.** On the first run the home server hard-reset about 30–40 s into GPU load. The last
  journal line was at 11:02:43 UTC, the next boot at 11:03:51, with no kernel message between
  them.
  - `kernel.panic` was 0 and there is no watchdog. A kernel panic or GPU hang would therefore
    have left the machine frozen, not rebooted.
  - So this was a hardware-level reset. Heat or a power transient is the likely cause; it is not
    proven which.
  - All 38 containers came back. The reset also booted the already-installed kernel
    6.8.0-151.
- **Monitored rerun at stock settings** (fan auto, 85 W): no reset, but the card went from
  53 °C to 86 °C within 5 s of load and held 87–89 °C, against a critical limit of 94 °C.
  - The fan read 3,570 RPM idle, then dropped to 562 RPM as load began and climbed slowly to
    about 2,000.
  - The clock throttled to about 700 MHz (of 1,210), and power peaked at 97 W.
- **Fan at 100% and a 65 W cap** (sysfs, root, not persistent): 100 requests over 11 minutes,
  75 °C (peak 79 °C), no errors.
  - The clock was about 500 MHz, limited by power this time.
  - The owner has since removed both settings.
- **Conclusion:** the card works. Its cooling, and possibly its power delivery, need attention
  before sustained use: clean it, re-paste it, check the fan and its power cable. Traces are in
  `ml/out/gguf-kev/amd-monitor*.log`.

## Not done

- **D20 (decided 2026-11-26):** the owner accepted Q4_K_M on the label test
  (`decision-review.md`, "Kev quantisation"). Any other variant still needs the agreement rule,
  or the same label test plus sign-off.
- **The worker backend is built, not in use** (`docs/ai/worker.md`, "Kev on a llama.cpp
  sidecar").
  - What it does: it calls `/v1/systemone`, undoes the GGUF's temperature, and pins the GGUF by
    hash and the image by digest.
  - Its parity: against a live sidecar on the 3060, 40 requests through the whole protocol came
    within 0.016 of the stored Q4 scores.
  - Not done: the production switch (owner-gated), and a run on the AMD card under compose.
- **No soak test.** The AMD card has done at most 11 minutes of sustained load. Before a
  4-hour window it needs a full monitored 1,800-request run, after the cooling work and with the
  fan and power settings made persistent (e.g. a systemd unit).
- **No crash logging on the home server.** No `kernel.panic` timeout, kdump or pstore. These
  would not catch a power-level reset, but they would turn a freeze into a reboot with a dump.
- **CPU options not tried:** F32 (about 17 GB; likely close to F16), and Q4_0 (128-bit integer
  maths, not measured). Neither is likely to beat F16 by much (see the ceiling above).
- **Kev-0.8B was skipped.** Its own card reports a large accuracy drop: 0.697 against 0.838 on
  transfer-v4.

## Files

- `ml/models/kev_gguf.py`: the scorer and comparison.
- `ml/out/gguf-kev/` (git-ignored): every run's raw scores (`q4km-vulkan-3060.jsonl`,
  `q8-ub2048.jsonl`, `bf16-ub2048.jsonl`, `q4km-ub2048.jsonl`, `q8-cuda-ub2048.jsonl`,
  `home-cpu-*.jsonl`, `home-amd-*.jsonl`) and the AMD sensor traces.
- `ml/out/gguf/` (git-ignored): the Q4_K_M and Q8_0 GGUF files.

Sources: [llama.cpp PR #29818](https://github.com/ggml-org/llama.cpp/pull/29818),
[ggml-org/Kev-4B-GGUF](https://huggingface.co/ggml-org/Kev-4B-GGUF),
[llama.cpp perplexity README (KLD table)](https://github.com/ggml-org/llama.cpp/blob/master/tools/perplexity/README.md),
[Vulkan scoreboard](https://github.com/ggml-org/llama.cpp/discussions/10879),
[legacy-hardware llama-bench](https://www.mgroeber.de/benchmarking-llamacpp-on-legacy-hardware-2.html),
[Vulkan GDN shader, PR #20334](https://github.com/ggml-org/llama.cpp/pull/20334).
