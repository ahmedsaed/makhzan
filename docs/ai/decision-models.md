# Other decision models against Kev and pplx (2026-11-26 – 2026-11-27)

These experiments asked whether another decision model could replace or complement the two
judges then in production, Kev-4B and pplx-decider-flash v1.3, both served by llama.cpp
(`kev-llamacpp.md`, `pplx-llamacpp.md`).

**Summary.**

- **H2O-Lightning-4B** was the only candidate as good as or better than the incumbents on our
  labels. At Q4_K_M it replaced Kev as the first judge on 2026-11-27 (**D25**, policy p2 =
  {h2o: 0.578, pplx: 0.95}). With pplx Q4 second it makes 229 merges on the labelled set,
  227 correct, and the 2 wrong ones are grey-area pairs.
- **Intern-Decision-4B** and **Liquid d1-2B** were measured and are not used as judges. Intern
  trails on recall at production precision, even once its input was given in the shape it
  expects (section 8). d1 is fast and ranks reasonably but is too weak at high precision.
- **One judge is not enough**, measured by cross-validation (section 6): two judges keep the
  worst case at 2 wrong merges per half-sample, against up to 11–12 for either judge alone.
- **A d1 pre-filter** (skip a pair d1 scores very low) would cut a quarter to a third of the
  backlog with no merge lost on a real sample. Deferred by the owner (section 7).

Every number below comes from our labelled Phase E pairs. Nothing published tests pairwise
product matching, so the published benchmarks only chose what to try.

## 1. Why

Kev was the slower and weaker of the two judges: lowest recall at production precision of the
pair, most sensitive to the order the two listings are shown in, and a 4-billion-parameter model
needing about 4.1 GB on the home server's 4 GB card. The owner asked whether llama.cpp's other
decision models could do better, in either seat.

The owner's rules applied throughout:

- **Local models only** (`plan.md`): nothing leaves our machines. The model must run in
  llama.cpp, or, for a one-off measurement, in its publisher's own reference code.
- **The label test.** A candidate is judged on the labelled Phase E pairs with the approved K2
  prompt, unchanged, and under the production rule (first judge above its threshold *and* pplx
  ≥ 0.95), not only on ranking metrics.
- **D20** (`decision-review.md`): a changed model or quantisation passes on the agreement rule
  with the version it replaces, or on the label test plus the owner's sign-off.
- **AI design decisions are the owner's.** Every prompt change (K2c, the Intern structured state)
  was shown with real snippets before it ran; thresholds were proposed, then confirmed.

## 2. Research

Web research on 2026-11-26, nothing run (the private notes are in git-ignored
`ml/out/research/decision-models-2026-11-26.md`).

**llama.cpp decision types** (`common/common.h`, b12767): openjev, lev, kev, nimble, laya, clef,
pplx-decider, vllm-decision2, vllm-d3, lfm2-d1, lfm2-d1-omni, granite-switch, h2o-lightning,
openbmb-minicpm-ocr-jev, lfm3-d1, lfm3-d1-omni. Julia-1 has no type of its own, and
Intern-Decision has none and no pull request.

**Shortlist, tested:**

| Model | Size | Licence | Published claims (self-reported unless marked) | Why tested |
|---|---|---|---|---|
| H2O-Lightning-4B | 4B (Qwen3.5-4B + merged LoRA); Q4_K_M 2.71 GB, Q8_0 4.48 GB | Apache-2.0 | 202–206/231 on public JevBench (vendor); 75 on JevBench 1.8.10 (independent); Arabic Belebele 92.5% | Native `/v1/systemone`, official GGUF with per-quant agreement (Q4_K_M 98.5%), fits 4 GB |
| Intern-Decision-4B | 4B | Apache-2.0 | Average 90.02 against Kev's 79.56 in its own paper's table | The best published comparison that includes Kev |
| Liquid d1-2B | 2B (LFM3-VL-2B); Q8_0 1.85 GB | LFM Open License v1.0 | JevBench v1.4.1 77.9; independent calibration error 0.012, the lowest on that board | Small, fast, Arabic among its 16 languages |

**Dropped:**

- **openjev:** 27B, CC BY-NC 4.0. The project is free, open source and non-commercial, so the
  licence would have been acceptable, but at Q4_K_M it is 19.4 GB, too big for any of our cards.
- **lev:** weakest on minimal-edit pairs (vitaminc, paws), which is our hard case. Skipped by
  the owner.
- **julia-1:** 144M parameters, a baseline or pre-filter rather than a judge. Skipped by the owner.
- **Others:** granite-switch-4.1-8b (no licence stated, too big), vllm-d3 (8B/26B, no GGUF),
  nimble (9B), clef (27B), MiniCPM-OCR-Jev (two options only).

**Licences.** `model-shortlist.md` required commercial self-hosting. The owner clarified on
2026-11-26 that makhzan is non-commercial, so a revenue cap such as d1's (free below US$10M
annual revenue) is no obstacle. Size, not licence, excluded openjev.

**Best practices per model** were researched before each run so that a poor score could not be
our configuration:

- **H2O:** the prompt template is in the GGUF; inputs NFC-normalised (its shim does, llama.cpp
  does not); `-np 1 --no-kv-unified --no-mmproj`. llama.cpp is causal only; the publisher's
  recommended bidirectional mode needs its vLLM fork (vendor: 202 against 206/231).
- **d1:** non-causal, so `-b`/`-ub` must cover the whole prompt.
- **Intern:** no llama.cpp type; scored with its publisher's `inference.py` (HF transformers,
  BF16), raw P(yes) at temperature 1 (its calibration temperature is 1.99).

## 3. Method

- **Pairs:** the Phase E answer key (`makhzan-config/labels/answer-key-v2.jsonl`), the pairs that
  pass the vetoes, "unsure" left out: **626 pairs, 385 "same"**.
- **Prompts:** K2, Kev's approved payload (description capped at 150 words), and K2c, the same
  with the approved criteria added to the question. No new wording.
- **Both orders:** each pair is scored as A,B and B,A, and the pair's score is the lower of the
  two, as in production.
- **Raw scale:** llama.cpp returns calibrated probabilities where a GGUF bakes in a temperature
  T (H2O 0.8, d1 1.3374, Kev 2.406). The analysis converts back with raw = sigmoid(T · logit p),
  as the worker does.
- **Metrics:** AUC, average precision (AP), and recall at the precision each incumbent achieves
  at its production threshold: 0.962 (Kev ≥ 0.8) and 0.991 (pplx ≥ 0.95). Each model's matched
  threshold is reported beside it.
- **Production rule:** merges, correct and wrong when the candidate takes one judge's seat at
  its matched threshold and the other judge stays.
- **Hardware:** the desktop's RTX 3060 12 GB for accuracy, and the home server's RX 470/570 4 GB
  (Vulkan, held to clock states 0–2 at about 85 W, `kev-llamacpp.md`) for the deployed one.

## 4. Results

**Ranking and recall** (raw scale; matched threshold in brackets):

| Model | AUC | AP | Recall @ 0.962 | Recall @ 0.991 |
|---|---|---|---|---|
| Kev BF16 | 0.942 | 0.962 | 0.722 (0.796) | 0.397 (0.974) |
| pplx BF16 | 0.956 | 0.973 | 0.743 (0.905) | 0.587 (0.949) |
| H2O Q8 K2 | 0.950 | 0.970 | **0.769** (0.578) | 0.569 (0.742) |
| H2O Q8 K2c | 0.951 | 0.970 | 0.764 (0.659) | 0.582 (0.764) |
| H2O Q4 K2 | 0.951 | 0.971 | 0.761 (0.597) | **0.621** |
| Intern K2, string state | 0.932 | 0.952 | 0.610 (0.852) | 0.369 (0.958) |
| Intern K2c, string state | 0.933 | 0.951 | 0.582 (0.953) | 0.091 (0.991) |
| Intern K2, structured state | 0.939 | 0.958 | 0.720 | 0.291 |
| Intern K2c, structured state | 0.943 | 0.960 | 0.756 | 0.218 |
| d1 Q8 K2 | 0.921 | 0.947 | 0.655 (0.981) | 0.288 (0.996) |
| d1 Q8 K2c | 0.923 | 0.950 | 0.670 (0.995) | 0.312 (0.999) |

The criteria (K2c) helped no model consistently (and cost Intern most of its recall at 0.991);
K2 stays.

**Production rule, merges / correct / wrong.** Baseline, BF16 Kev ≥ 0.8 and BF16 pplx ≥ 0.95:
209 / 209 / 0.

| Candidate | Replacing Kev | Replacing pplx |
|---|---|---|
| H2O K2 | 217 / 216 / 1 | 211 / 210 / 1 |
| H2O K2c | 215 / 214 / 1 | 213 / 211 / 2 |
| Intern K2, string | 184 / 183 / 1 | 143 / 142 / 1 |
| Intern K2c, string | 178 / 178 / 0 | 35 / 35 / 0 |
| Intern K2, structured | 213 / 212 / 1 | — |
| Intern K2c, structured | 220 / 218 / 2 | — |
| d1 K2 | 196 / 196 / 0 | 102 / 102 / 0 |
| d1 K2c | 196 / 195 / 1 | 113 / 113 / 0 |

With pplx at Q4_K_S, the production quantisation:

| First judge | Merges / correct / wrong | Wrong pairs |
|---|---|---|
| Kev Q4 ≥ 0.8 (p1) | 217 / 216 / 1 | E0098 |
| H2O Q4 or Q8 ≥ 0.578 (**p2**) | 229 / 227 / 2 | E0098, E0639 |
| H2O Q4 ≥ 0.597 (its own matched threshold) | 228 / 226 / 2 | E0098, E0639 |
| Kev OR H2O | 236 / 234 / 2 | |
| Kev AND H2O | 211 / 210 / 1 | |

Every wrong merge in these tables is a grey-area pair (E0098, E0639, E0535, E0138), the kind the
owner ruled acceptable for pplx Q4.

**Speed and memory.**

| Model | Hardware | Batch (`-ub`) | Requests/s | Tokens/s | Memory |
|---|---|---|---|---|---|
| H2O Q8 | 3060 | 512 | 1.01 | 941 | |
| H2O Q8 | 3060 | 2048 | 2.76 | | |
| H2O Q4 | 3060 | 512 | 0.87 | 811 | 3,908 MiB peak |
| H2O Q4 | 3060 | 2048 | 2.72 | 2,529 | 3,823 MiB peak (about 624 MiB of it other processes) |
| Kev Q4 | 3060 | 512 | 0.81 | | |
| Kev Q4 | 3060 | 2048 | 1.88 | | 5.3 GB |
| d1 Q8 | 3060 | | ~8.3 | | 2.7 GB |
| Intern BF16 (HF transformers) | 3060 | | ~2.3 | | 9.1 GB |
| H2O Q4 | RX 470/570, state 2, 85 W | 512 | 0.24 (4.20 s each) | 231 | fits 4 GB |
| H2O Q4 | RX 470/570, state 2, 85 W | 2048 | 0.25 (3.97 s each) | 244 | fits 4 GB |

The first comparison made H2O look slow: it set H2O Q8 at batch 512 against Kev Q4 at batch
2048. **That was a configuration artefact.** At the same batch H2O is as fast as Kev or faster.
On the AMD card a bigger batch gains about 5%, because the card is power-bound, so the deployed
setup keeps 512. The card's scores were within 0.016 of the 3060's on every request.

**Order sensitivity** (mean |score(A,B) − score(B,A)|, lower is better): pplx 0.047; d1
0.054–0.066; H2O 0.074–0.075; Kev 0.106; Intern 0.105–0.119 (structured 0.108–0.123).

## 5. H2O in depth

**Q4 against Q8 (D20).** Spearman 0.9962; |Δp| at most 0.198, mean 0.017. Pair agreement is
98.56% at 0.5 and 98.33% at 0.578. Q4 therefore **fails the agreement rule**. The owner accepted
it on the label test: at 0.578 it makes the same merges as Q8 (229 / 227 / 2), with higher AP
and recall at 0.991.

**Error analysis: H2O at 0.578 against Kev at 0.8,** each alone, at the same precision:

- Both make **11 false merges**. H2O misses 89 true pairs and Kev 109; H2O alone finds 39 that
  Kev misses, and Kev alone 19.
- **H2O's false merges that Kev avoids:** E0639, E0037 and E0739 are grey-area. E0570 (UT201+
  against UT201) and E0361 (an LM2596 pair) are real mistakes.
- **Kev's false merges that H2O avoids:** E0076, E0307 and E0683 are real mistakes; E0016 and
  E0376 are grey-area.

H2O's errors are fewer and milder, and under the two-judge rule pplx removes E0570 and E0361.

**Its scale.** H2O's raw scores sit between about 0.09 and 0.90, so its thresholds are lower
than Kev's (0.578 here, against Kev's 0.8). A threshold carried over from Kev would be wrong.

## 6. One judge or two

The owner asked whether any model could do the job alone.

**In sample**, each judge alone can reach precision ≥ 0.99:

- H2O Q4 ≥ 0.7299: 239 merges, 2 wrong (E0098, E0778);
- pplx Q4 ≥ 0.948: 241 merges, 2 wrong (E0098, E0639);
- the two-judge rule (p2): 227 merges, 2 wrong.

That costs only a few merges, but a threshold chosen on the same pairs it is scored on flatters
the single judge. So: **cross-validation**, 500 random 50/50 splits. Each split picks the
threshold on one half (the lowest reaching precision ≥ 0.99) and scores the other half.

| Setup | Mean precision | Worst 5% | Recall | Wrong merges per half |
|---|---|---|---|---|
| H2O alone | 0.9856 | 0.9627 | 0.624 | up to 11; ≥ 3 in 31% of splits |
| pplx alone | 0.9851 | 0.9590 | | up to 12 |
| Rule, H2O threshold tuned per split | 0.9914 | 0.9825 | 0.591 | at most 2 |
| Rule, fixed (0.578, 0.95) | 0.9911 | 0.9818 | | |

A single judge's threshold sits on a steep part of its curve and moves with the sample; the
second judge removes that variance. **Decision: keep two judges.** The cost is about 3 points of
recall.

## 7. The d1 pre-filter (deferred)

d1 is about 3 times faster than H2O at batch 2048 on the 3060 (8.3 against 2.7 requests/s). As a gate it would skip pairs it scores very low, so
the judges never see them.

**On Phase E** (pair score below the cut):

| Cut | Pairs dropped | "Same" pairs lost |
|---|---|---|
| < 0.05 | 7% | 0 |
| < 0.10 | 11% | 1 |
| < 0.20 | 15% | 4 |

**On the real backlog**: 1,000 uniformly drawn backlog pairs (seed 20261127) and 500 pairs the
production judges had merged (seed 7), at 7.7–8.6 requests/s. Merges were judged by the old BF16
Kev and pplx decisions.

| Cut | Backlog dropped | Merges lost |
|---|---|---|
| < 0.05 | 25.4% | 0 |
| < 0.10 | 34.7% | 0 |
| < 0.20 | 45.1% | 0 |
| < 0.30 | 50.1% | 0 |
| < 0.50 | 59.3% | 1 (of 500) |

The labelled set loses "same" pairs where the backlog sample loses no merge. The backlog
sample is measured against production decisions, not labels, so a pair both judges missed
cannot show up as lost. **Deferred by the owner** (2026-11-27): the backlog clears without it. Revisit
for a big backlog or when a new shop is onboarded. Using it would need at least a third model in the
router, a broker stage, and the owner's choice of cut.

## 8. Intern: a string is not a structure

Intern-Decision's template takes the state as JSON (`## State\n{json.dumps(state)}`). The first
run passed it Kev's K2 text block, one string, which `json.dumps` turned into a single quoted
line full of `\n` escapes. That is not the input it was trained on.

The **structured state** keeps the same fields, labels, order and values, as an object:
`"Listing A"` and `"Listing B"`, one key per field, specifications as an object. The
instructions are unchanged. It costs about 7–9% more tokens. The owner approved a two-pair draft
(`intern_struct_draft.py`) before it ran.

Structure helped: recall at 0.962 rose from 0.61 to 0.72 (K2) and 0.76 (K2c), and the rule
with Intern replacing Kev went from 184 to 213–220 merges. It still trails H2O, most at
precision 0.991 (0.22–0.29 against 0.57–0.62), and its order sensitivity did not improve. **The
Intern weights were deleted on 2026-11-27.**

**Open idea, the owner's call:** H2O and pplx also receive the state as text. H2O's template
(`record: {state}`) and pplx's might read a structured state better too. It is a prompt change,
so it would need the owner's approval, the label test and, since it changes the prompt version,
a re-score of standing decisions.

## 9. D25

**Decided 2026-11-27** (`decision-review.md`, "H2O first"; PR #97). The first judge is
H2O-Lightning-4B Q4_K_M at 0.578 on the raw scale; pplx Q4_K_S ≥ 0.95 stays second; policy
p2 = {h2o: 0.578, pplx: 0.95}. p1 stays as history and the rollback. The GGUF is pinned by
revision `61f8d8b7…` and sha256
`5ec969c6edbad5f1750141742f635cc7f01576bf9432151f730f0a6c30042768` (2.71 GB).

**Its floor, 0.19.** The group check blocks an AI join when any two members score below a
floor (Kev's was 0.05). H2O's floor was chosen to block what Kev's did, on the labelled set
(463 "not same" pairs):

| Floor | "Not same" blocked | "Same" blocked |
|---|---|---|
| Kev < 0.05 | 358 | 16 |
| H2O < 0.185 | 351 | 11 |
| **H2O < 0.19** | **358** | **12** |
| H2O < 0.195 | 365 | 16 |

At 0.19 H2O blocks exactly as many wrong pairs as Kev did and fewer right ones. Proposed by the
session, confirmed by the owner.

## 10. Files and how to reproduce

Scripts (in this repository):

- `ml/models/compare_models.py`: `render` writes the K2/K2c requests; `score` sends them to a
  llama.cpp `/v1/systemone` server; `analyse` produces section 4's tables (`analysis.json`).
- `ml/models/intern_runner.py`: scores the requests with Intern's own reference code, inside
  its container.
- `ml/models/intern_struct_requests.py`, `intern_struct_draft.py`, `intern_struct_analyse.py`:
  section 8's structured state: the requests, the two-pair draft, and the comparison
  (`intern-struct-analysis.json`, which also covers H2O Q4 and the 0.578 rule).
- `ml/models/d1_prefilter_score.py`, `d1_prefilter_analyse.py`: section 7.

Each script's docstring gives its command. They read the answer key from the private
configuration beside this repository and write to git-ignored `ml/out/models-compare/`, which
holds every raw score (`h2o-K2.jsonl`, `h2o-K2c.jsonl`, `h2o-q4-K2.jsonl`, `d1-K2*.jsonl`,
`intern-K2*.jsonl`, `intern-struct-K2*.jsonl`, `h2o-card-ub*.jsonl`, `speed-*.jsonl`),
`parity-h2o-llamacpp-3060.json`, `intern-structured-draft.md` and `d1-prefilter/`.

**Not kept as scripts** (one-off analyses run inline; their method is described above and their
inputs are in `ml/out/`):

- the cross-validation (section 6);
- the H2O / Kev error analysis (section 5);
- the floor table (section 9);
- drawing the d1 pre-filter's backlog samples (section 7).

Re-running them means rewriting them from these descriptions; the exact random splits of section
6 would differ.

Sources: [llama.cpp h2o-lightning, PR #30361](https://github.com/ggml-org/llama.cpp/pull/30361),
[h2oai/h2o-lightning-4b](https://huggingface.co/h2oai/h2o-lightning-4b),
[h2oai/h2o-lightning-4b-gguf](https://huggingface.co/h2oai/h2o-lightning-4b-gguf),
[LiquidAI/d1-2B](https://huggingface.co/LiquidAI/d1-2B),
[LFM licence](https://docs.liquid.ai/lfm/help/model-license),
Intern-Decision (arXiv 2610.22131).
