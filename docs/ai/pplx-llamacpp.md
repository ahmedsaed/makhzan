# pplx-decider-flash-v1.3 through llama.cpp: conversion, quantisation, CPU (2026-11-26)

These experiments asked whether pplx, the production rule's second judge, could run through
llama.cpp as Kev now does (`docs/ai/kev-llamacpp.md`), faster on the home server and ideally
on its 4 GB card.

**Summary.**
- **The port is faithful.** BF16 matches pplx's own code.
- **Q8_0 passes D20 but needs 5.4 GB.** Every 4-bit variant fails the agreement rule.
- **The owner accepted Q4_K_S** on the label test (`decision-review.md`, "pplx quantisation").
  Together with Kev Q4 under the production rule it made 216 correct merges against bf16's 209,
  plus one grey-area pair labelled "not".
- **In production since 2026-11-27** (`decision-review.md`, "Production switch"): on the home
  server's AMD card at clock states 0–2, taking turns with Kev's sidecar, 4.6 s a request
  (`docs/ai/worker.md`, "pplx on a llama.cpp sidecar").

## How pplx differs from Kev

- **Same backbone, different attention.** pplx is Qwen3.5-4B (the same 32-layer hybrid as Kev's
  base) with a 255-row readout. Its full-attention layers are **non-causal** (bidirectional);
  the gated-delta layers stay causal. A causal run is not pplx.
- **Prompt and readout.** It reads its answer at a marker token after one question chunk
  (protocol v4, "joint-chunked-readout-v1"), not at the end of a chat reply.
- **No ready-made v1.3 GGUF from upstream.** Upstream llama.cpp knows the `pplx-decider` decision
  type (PR #30044) but converts with the older v1 prompt. The two community v1.3 GGUFs (fxoz,
  vblanco) are third-party files and were not used.
- **Temperature.** llama.cpp applies pplx's own temperature, 1.3302961587905884 from
  `decision_config.json`, which is the scale every validated pplx score and the policy's 0.95 are
  on. So, unlike Kev, nothing is undone.

## Conversion

`ml/models/convert_pplx_v13.py` wraps upstream llama.cpp's converter at a8ad690ca (build b12767,
the pinned server image's commit). It reimplements, without running, the changes in fxoz's
`convert_v13.py`:

1. a systemone template rendering pplx_decider's protocol-v4 prompt exactly;
2. `add_causal_attention(False)`;
3. nothing else: the tensor layout is the converter's own, since the runtime is the same build.

The script's docstring has the steps: BF16 conversion, `llama-imatrix`, `llama-quantize`.

- **Importance matrix (4-bit only):** 300 backlog pairs rendered as pplx sees them, with every
  Phase E listing excluded.
- **Not recorded:** the imatrix and quantize options beyond those in the docstring. The file in
  use is pinned by sha256.

## Parity

- **Tokens.** 38 of 40 requests matched pplx's own encoder token for token. E0013 differed
  because pplx's Hugging Face tokenizer normalises text to NFC and llama.cpp's does not (U+2126
  OHM SIGN). Normalising the request first makes all 40 identical.
  - 10 of the 1,800 Phase E requests contain such characters.
  - The worker now NFC-normalises what it sends, for Kev and pplx alike (`judges.nfc`).
- **BF16 GGUF, 100 pairs**, against the stored bf16 pplx scores: Spearman 0.9998, max |Δp| 0.023,
  no flips at 0.5 or 0.95.
- **Causal control** (the same GGUF forced causal): Spearman 0.967, and 11 of 100 pairs flip at
  0.95. The non-causal setting is in effect, and it matters.
- **One batch per request.** Non-causal attention needs the whole request in one batch.
  - The longest Phase E request is 3,511 tokens by the conversion run's count (3,574 as llama.cpp
    reports E0639 ba's input); the 95th percentile is 1,745.
  - So `-b`/`-ub`/`-c` must be 4096. At 2048, 6 of 200 requests failed.

## Quantisation

All 1,800 Phase E requests, on the RTX 3060 (Vulkan, one slot, `-c 4096 -ub 4096`), against the
bf16 pplx scores. The production rule uses Kev's bf16 scores.

| Variant | Size | Peak GPU memory | Requests/s | Spearman | Pair agreement 0.5 / 0.95 | D20 | Production rule (bf16: 209 merges, 0 wrong) |
|---|---|---|---|---|---|---|---|
| Q8_0 | 5.2 GB | 5,383 MiB | 2.63 | 0.9998 | 99.78 / 99.89% | passes | 208 merges, 0 "not", 1 changed (E0851, 0.951→0.949) |
| Q4_K_M | 3.1 GB | 4,014 MiB | 2.55 | 0.9975 | 98.44 / 97.89% | fails | 220 merges, 1 "not" (E0098), 13 changed |
| **Q4_K_S** | 2.9 GB | 3,849 MiB | 2.61 | 0.9971 | 98.33 / 97.78% | fails; **accepted on the label test** | 219 merges, 1 "not" (E0098), 12 changed |
| IQ4_XS | 2.9 GB | 3,360 MiB | 2.31 | 0.9962 | 96.67 / 97.33% | fails | 222 merges, 2 "not", 19 changed |

**4-bit pplx leans up; Kev's Q4 did not.**
- In the 0.85–0.99 band, about 3 in 4 scores move up (mean +0.003 to +0.006), against an even
  split for Q8. Scores just below 0.95 then cross it, so 4-bit pplx merges more.
- Kev's Q4 flips were symmetric.
- The "not" merges were all close calls that full-precision pplx had already put just under the
  line (0.92–0.95). The owner judged them grey-area:
  - E0098: ATmega328-PU vs ATmega328P;
  - E0016 (IQ4_XS): a 47 kΩ resistor with no stated wattage vs 47 kΩ 1 W;
  - E0535 (IQ4_XS): an 18650 cell, 2800 mAh vs "2800 to 3200 mAh".

**Kev and pplx together**, under the production rule on the pairs that pass the vetoes (640
pairs scored by every variant):

| Kev + pplx | Merges | Correct ("same") | Labelled "not" | vs bf16 + bf16 |
|---|---|---|---|---|
| bf16 + bf16 (today) | 209 | 209 | 0 | — |
| bf16 + Q8_0 | 208 | 208 | 0 | +0 / −1 |
| Q4 + Q8_0 | 205 | 205 | 0 | +3 / −7 |
| **Q4 + Q4_K_S** | 217 | 216 | 1 (E0098) | +15 / −7 |
| Q4 + Q4_K_M | 217 | 216 | 1 (E0098) | +15 / −7 |

pplx's upward lean mostly recovers true matches that Kev's Q4 lowers below 0.8.

To reproduce a row, combine a pplx file with a Kev file. For example, Q4 + Q4_K_S, where the
llama.cpp Kev scores are calibrated, so undo 2.406:

    python3 ml/models/pplx_gguf.py decisions ml/out/gguf-pplx/Q4_K_S.jsonl \
        --kev ml/out/gguf-kev/q4km-vulkan-3060.jsonl --kev-temperature 2.406049966812134

It prints the variant (217 merges, 216 "same", 1 "not") beside pplx bf16 with the same Kev file
(206). Without `--kev`, Kev is the stored bf16.

## Speed and placement

- **3060:** 2.3–2.6 requests/s, against 2.96 for Kev's own server.
- **The home server's card (production).** Q4_K_S at `-ub 4096 -fa on` loads in 3,273 MiB of
  the card's 4 GB. At clock states 0–2 (`kev-llamacpp.md`) it ran 1,800 requests with no
  reset: 4.6 s each (242 tokens/s), within 0.038 of the 3060's scores. Kev's model is unloaded
  first: the stack's llama.cpp router holds one at a time and loads pplx when its worker asks at
  05:05 (`docs/ai/worker.md`, "The llama.cpp router"). At stock clocks its first large job reset the server (the card's power feed), which
  is what the clock limit prevents.
- **The CPU fallback** (not set up in the home stack: it would need its own llama.cpp server without `-dev Vulkan0`, `n-gpu-layers = 0`, `device = "cpu"`), the same model version:
- **CPU, measured on the desktop** (4 threads, Q4_K_S):

  | Request | Tokens | Time | Tokens/s | Score vs the 3060's |
  |---|---|---|---|---|
  | E0193 ab (median length) | 1,052 | 13.2 s | 79.7 | 0.0099 vs 0.0089 |
  | E0639 ba (longest) | 3,574 | 48.9 s | 73.1 | 0.9909 vs 0.9915 |

- **CPU, estimated for the i7-3770, not measured.**
  - Method: Kev Q4's measured ratio, i7-3770 / desktop at pp512 (17.1 / 67.5 tokens/s).
  - Result: about 55 s for a median request and about 193 s for the longest.
  - For comparison, today's torch pplx worker takes about 2 minutes a request.
- **Timeouts.** A pplx request on the CPU therefore gets a 225 s timeout
  (`judges.LLAMACPP_REQUEST_S`). With its last posts and the join, a stop takes at most 265 s:
  under the supervisor's 270 s window-end kill, and covered by the pplx worker's compose
  `stop_grace_period` of 300 s (`docs/ai/worker.md`, "A stop sets one deadline").
- **`llama-bench` misleads for pplx on CPU.** It ran far slower than a real request: the GGUF
  carries the readout as a full-vocabulary output matrix (4.84B parameters against Kev's 4.21B),
  which the benchmark evaluates. Trimming that matrix to its 255 used rows could also save about
  0.3–0.4 GB (not tried).

## Not done

- **The CPU fallback's speed on the i7-3770 itself:** the 55 s and 193 s above are estimates.
- ~~Requests over 4,096 tokens~~ (about 1 pair in 3,000 of the real backlog): **resolved
  2026-11-27** by the owner's decision to cut their descriptions to fit, in the worker, rather
  than fail the job (`worker.md`, "Requests too long for the context"). No CPU route at 8,192.
- **Trimming the output matrix.**
- **The judge-version catch-up** (every standing decision re-scored after the switch) is the
  owner's to drain, with wider windows and the desktop.

## Files

- `ml/models/convert_pplx_v13.py`: the converter.
- `ml/models/pplx_gguf.py`: the scorer (score / compare / decisions).
- `ml/out/gguf-pplx/` (git-ignored, about 23 GB):
  - the GGUFs, BF16 and every quantisation, and the imatrix;
  - per-variant scores;
  - the rendered Phase E requests (`requests-K1-full.jsonl`), the calibration text and the run
    log.

Sources:
[llama.cpp PR #30044](https://github.com/ggml-org/llama.cpp/pull/30044),
[fxoz/pplx-decider-flash-v1.3-GGUF](https://huggingface.co/fxoz/pplx-decider-flash-v1.3-GGUF),
[perplexity-ai/pplx-decider-flash-v1.3](https://huggingface.co/perplexity-ai/pplx-decider-flash-v1.3).
