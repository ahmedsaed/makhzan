# Local AI models for makhzan's catalogue: research report

Date: 2026-11-13. Research only; no code changed. Suppliers are named by role, as in CLAUDE.md.
**[unverified]** = secondary source (blog, aggregator, or a model card's self-reported figures) that I
could not check against an independent one. **[estimate]** = my own arithmetic, not a measurement.
Benchmark on the real machines before relying on any throughput figure.

## 0. What the code does today, and where the gap is

- `grouping.py` only forms candidate groups from a **shared extracted identifier** (`base_key` →
  `mpn:<PN>`). Every other listing is `single:<source>:<id>`. `_subcluster` then splits an identifier
  group by title Jaccard, with four vetoes: same shop, value tokens, form, and price span.
- `DomainProfile.extract_identifier` defaults to `_no_identifier`, and only electronics overrides it.
  So **in 15 of 16 domains no two shops' listings can ever be grouped.** The 889 multi-shop products are
  essentially electronics.
- The largest gap is therefore **candidate generation** ("blocking"): deciding which pairs to compare at
  all. The pair *decision* comes second.
- **Safety asymmetry:** a model that adds a *veto* can only cause under-merging, which CLAUDE.md calls
  the lesser error. One that adds an *admission* route can cause over-merging, and must first pass a
  measured precision gate.
- **"Grouping by material" is a different relation from identity.** The filament maker's 53 colour
  listings come from *one shop*, so the same-shop veto correctly keeps them apart as products. A variant
  family ("PLA+ 1.75 mm 1 kg in N colours") needs its own table, one that admits same-shop members and
  shows a price per option. It must not be added to `_subcluster`.

## 1. "Decision models": what they are, the concrete models, and fit

### 1.1 The concept
"**Decision model**" (TypeSafe's term is "**System One model**") is a category that took shape in
September–October 2026.
- It is a model whose output is a *decision*, not text. You give it a **state** (any text or JSON) and
  one or more typed **questions**:
  - `choice`: pick one of N options, each with an optional description;
  - `noul`: yes/no;
  - `score`: an ordinal level.
- It returns a probability per option from **one forward pass**, with no token generation and no JSON
  to parse. Sources: [dsebastien.net, 2026-09-23, upd. 10-23](https://www.dsebastien.net/decision-models-dms/),
  [DataCamp "Top AI decision models", 2026-10-26](https://www.datacamp.com/blog/top-ai-decision-models).
- Mechanically, a model either:
  - (a) puts a scoring head on an LLM or encoder (one logit per option's closing token, then a
    softmax); or
  - (b) reads the next-token probabilities of the allowed answer tokens ("yes"/"no", "A"/"B"/"C").
- The idea is older than the name. Rerankers that score "yes" vs "no" (Qwen3-Reranker), NLI zero-shot
  classifiers, reward models and verifiers are all decision models. What is new in 2026 is general
  models trained for arbitrary typed questions, with calibration as a headline feature.
- It is **not** HRM/TRM. Those are 7–27M-parameter recursive grid-puzzle solvers, trained per task with
  no language pretraining; they cannot read a product title
  ([ARC Prize HRM analysis](https://arcprize.org/blog/hrm-analysis), [TRM arXiv 2510.04871](https://arxiv.org/html/2510.04871v1)).

### 1.2 Concrete models (only open-weight models are usable here)

| Model (date) | Size / base | Licence | Self-reported evidence | Usable? |
|---|---|---|---|---|
| TypeSafe **Jev** 1.13 (2026-09-15) | undisclosed | closed API | 0.727–0.883 on vendor sets | **No**: hosted, breaks the shop promise |
| **Microsoft-Decision-1** (2026-10) | post-trained Qwen3.5-9B | closed | — | No |
| **Kev-4B** 1.0 (2026-09-24) | frozen Qwen3.5-4B-Base + LoRA + pointer head | Apache-2.0 | 0.69 breadth vs Jev 0.757; 0.838 out-of-domain; ECE 0.03–0.10 with stored temperature; ships `kev.calibrate` | **Yes, best general candidate** (GPU, or slow CPU) |
| **Laya** (2026-09-19) | ModernBERT-large 421M (EN) / mmBERT-base 322M (multilingual) | Apache-2.0 | zero-shot 0.36, *below* the majority baseline; fine-tuned 0.766 vs Jev 0.727; 33–40 ms on a T4; per-question temperature cuts ECE 0.47→0.08 | Yes, as a **base to fine-tune** |
| **THX-01** (2026-10-10) | mmBERT-base 307M + 15M decision head | Apache-2.0 | ticket classification 98.4% vs Jev 97.4%; ECE 0.003 (internal) | Yes, to evaluate; zero-shot claims unproven |
| **SemIf** (ex-OpenJev; tool, MIT) | reads option logits of Qwen3-0.6B / MiniCPM5-2B / Qwen3.5-4B, llama.cpp CPU path | MIT (code) | balanced acc. 0.44 / 0.69 / 0.81 on its authored set; temperature fit per workload | Yes: the **logit-read pattern** on any local LLM |
| **Qwen3-Reranker** 0.6B / 4B / 8B | Qwen3; score = P("yes") vs P("no") under an *instruction* | Apache-2.0 | MTEB-R 65.8 (0.6B) vs bge-reranker-v2-m3 57.0 | **Yes**: a ready-made yes/no judge, fine-tunable |
| decider-4b, Open-Decision-Model-150M, openjev | community 4B / 150M | various | card notes sharper yes/no hurts calibration (decider-4b) | Low trust; skip |
| Granite Guardian 3.3 8B (IBM) | 8B yes/no risk judge | Apache-2.0 | safety-specific | Wrong task |

Sources: [Kev-4B card](https://huggingface.co/jaredpalmer/kev-4b);
[Laya / aiweekly](https://aiweekly.co/alerts/convai-ships-laya-a-non-autoregressive-multilingual-system-1-decision-model-at);
[THX-01 blog](https://huggingface.co/blog/doofz/thx-01-we-open-sourced-a-322m-decision-model-that);
[SemIf README](https://raw.githubusercontent.com/TheoLeeCJ/SemIf/master/README.md);
[Qwen3-Reranker-0.6B card](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B);
[Jev coverage](https://letsdatascience.com/news/typesafe-ai-launches-jev-decision-model-889a38c0).
Every accuracy figure in the table is **[unverified]**: these are the publishers' own evaluations, on
general benchmarks, not on product matching. The DataCamp list's 9B–31B "decision models" (Elephant-1,
Mammoth-1, H2O-Lightning-31B…) are too large for comfortable use and are also unverified.

### 1.3 As the pairwise "same product? yes/no" judge
- **Usage:**
  - state: "Listing A: <title> · <category> · <price> EGP · shop <role>. Listing B: …";
  - question: "Are A and B the same product, the same variant and the same pack size, so that one
    price comparison is honest?";
  - options: `yes` / `no` / `unsure`.
  - Read P(yes).
- **Zero-shot will not be good enough.** The evidence:
  - the decision models' own general numbers are 0.7–0.84;
  - Laya is below baseline zero-shot;
  - on WDC Products, even a fine-tuned Llama 3.1 8B scored 69 F1 and GPT-4o 87
    ([arXiv 2409.08185](https://arxiv.org/html/2409.08185v2)).

  Corner cases (30 vs 38 pin, 1 kg vs 250 g) are precisely where general models slip.
- **Fine-tuned, it is a good fit.** A Laya/THX-01/ModernBERT encoder, or Qwen3-Reranker-0.6B,
  fine-tuned on our pairs *is* a cross-encoder, which a July 2026 study found consistently beats
  bi-encoders ([arXiv 2607.24688](https://www.alphaxiv.org/abs/2607.24688)). The "decision model" label
  adds the typed interface and calibration discipline, not new accuracy.
- **Recommended setup:**
  - **Primary judge:** fine-tune **Qwen3-Reranker-0.6B** (instruction-following, multilingual,
    Apache) or **ModernBERT-base / mmBERT-base** (cheaper on CPU) as a binary pair classifier.
  - **Second opinion:** use **Kev-4B** zero-shot on the GPU, for review-queue triage and label
    pre-screening. Do not use it alone for decisions.
- **Getting a calibrated, high-precision threshold:**
  1. Hold out owner-labelled pairs per domain (§4.4). A model never trains on them.
  2. Fit temperature scaling, or isotonic regression once there are ≥ 500 labels, on a calibration
     split. Kev's `kev.calibrate` and SemIf's per-workload temperature do this; for our own models use
     scikit-learn.
  3. Choose a per-domain threshold *t* at which the **lower 95% bound** (Wilson interval) of precision
     on the test split is ≥ 0.98, aiming for a point estimate of ≥ 0.99. Calibration makes *t* portable
     across model versions; the precision bound is what protects the site.
  4. Symmetrise by scoring (A,B) and (B,A) and taking the minimum. Kev's card warns that option order
     can change answers, and pair order can too.
  5. Above *t*: an admission signal, still subject to every veto. From *t* down to a lower bound: the
     review queue. Below that: nothing.
  6. Recalibrate whenever the model, the prompt or the threshold changes, and log ECE with each model
     version.

### 1.4 As multiple-choice attribute pickers
- **Usage:**
  - state: the title, plus the product-page specs when the details stage has them;
  - questions: one `choice` per attribute with a **fixed per-domain vocabulary**, for example:
    - material: PLA, PLA+, PETG, ABS, TPU, nylon, *not stated*, *other*;
    - form: chip, module, board, kit, accessory, *not stated*;
    - thread standard: BSP, NPT, metric, *not stated*.
- This fits the format better than free extraction does: the answer space is closed, so there is
  nothing to normalise. Kev handles up to 255 options, and a shared state lets several questions be
  scored from one prefill.
- Always include **"not stated"** and **"other"**. Accept an answer only when its calibrated probability
  is ≥ τ (for example 0.95). Otherwise record "unknown", and treat unknown as silence: it never vetoes.
- Values that have a number (diameter, weight, voltage) stay with `values.py`. The model only says
  *which* span is the diameter.
- **Accuracy:** expect it to be good for explicit words ("Black PLA+") and poor for implied ones. A
  SetFit or encoder fine-tuned on a few hundred labels per attribute will beat zero-shot Kev
  **[estimate]**. Measure per attribute.

## 2. Other established tools

- **Embeddings for blocking.** For each listing, take the top-k nearest neighbours from *other shops*
  in the same domain. Options:
  - `bge-small-en-v1.5` / `e5-small-v2` (33M, MIT);
  - `multilingual-e5-small` (118M);
  - **EmbeddingGemma** 308M (best multilingual model under 500M on MTEB at release;
    [arXiv 2509.20354](https://arxiv.org/pdf/2509.20354); Gemma terms);
  - **Qwen3-Embedding-0.6B** (multilingual MTEB about 64.3 vs about 61.2; Apache;
    [DataLearner](https://www.datalearner.com/en/blog/embeddinggemma-on-device-multilingual-embeddings) **[unverified]**).

  It is a recall tool only: "ESP32 30 pin" and "38 pin" are close neighbours. Candidate volume
  **[estimate]**: 61k × k=10 gives at most 600k directed pairs; deduplicated, within domain and above a
  floor, perhaps 30–150k. Measure it, because it sets every later cost.
- **Ditto-style cross-encoders** (RoBERTa / ModernBERT).
  - On WDC Products with 80% corner cases, Ditto and RoBERTa are around 72–74 F1
    ([leaderboard](https://hyper.ai/en/sota/tasks/entity-resolution/benchmark/entity-resolution-on-wdc-products-80-cc-seen)
    **[unverified]**; benchmark: [arXiv 2301.09521](https://arxiv.org/abs/2301.09521)).
  - AnyMatch (GPT-2) comes within 4.4 F1 of GPT-4 at about 3,900x lower cost
    ([arXiv 2409.04073](https://arxiv.org/abs/2409.04073)).
  - Students trained on LLM-made labels run 34–459x faster than direct LLM matching
    ([Steiner & Bizer, arXiv 2606.28823](https://arxiv.org/abs/2606.28823), 2026).
  - Same thing as the fine-tuned decision model in §1.3.
- **SetFit** ([HF blog](https://huggingface.co/blog/setfit)) trains from 8–16 examples per class. Use it
  for single-listing labels (form, pack, category suggestion) in domains without rules.
- **Small generative LLMs** (Qwen3.5 0.8/2/4/9B, released 2026-03-02, Apache;
  [Artificial Analysis](https://artificialanalysis.ai/es/articles/qwen3-5-small-models)):
  - use them as **label generators** (training only, sample-checked), **review-queue explainers**
    ("differs: 1 kg vs 250 g"), and JSON-schema extractors;
  - when a decision is needed, read logits (the SemIf pattern) rather than generate text: SemIf measured
    generation 5.2x slower for the same answers.
- **GLiNER2** (Fastino, EMNLP 2025 demo; 205M base / 340M large; designed for CPU;
  [arXiv 2507.18546](https://arxiv.org/pdf/2507.18546)) does open-span extraction (brand, model, colour
  words). It is the alternative to multiple-choice pickers when the vocabulary is open.
- **Reference point:** GPT-4 reached about 91 F1 on WDC-PAVE attribute extraction
  ([arXiv 2403.02130](https://arxiv.org/abs/2403.02130v4)). No small-model numbers were found **[gap]**.

### 2.1 Labels: there is more weak supervision than it first appears
- **Same-shop pairs with near-identical titles are negatives.** CLAUDE.md: a shop's two SKUs differ.
  They are plentiful, free, *hard* negatives, and the best single source.
- Pairs that share an identifier but were split by a value or form veto are negatives too. The model
  will just relearn the rule, which is harmless.
- **The 889 multi-shop products are positives, but circular**: they are the rules' own output and
  include any current over-merges. Audit about 100 first.
- **Owner labels from the review queue** are gold, used for **evaluation and calibration only**, plus
  active-learning top-ups (pairs with P between 0.3 and 0.8, stratified by domain). Add a `ReviewReason`
  such as `possible_same_product`; `review_queue` already has `confidence`, `proposed` and `status`.
- **Kev-4B or Qwen3.5-9B pre-labels:** training only, never evaluation.

## 3. Other high-value uses

1. **Attribute pickers feeding vetoes in all 16 domains.** This is the safest win: material, thread
   standard, colour, grade and pack become vetoes. It is the prerequisite for embedding blocking to be
   safe outside electronics. Colour is a veto for identity and the *option axis* for families.
2. **Category inference.** A crosswalk is fact; authoritative sources are never inferred.
   - (a) As an offline crosswalk-authoring aid: for each unmapped name in the drift report, propose a
     `domain:slug` as a `choice` over that domain's slugs, and a human commits it to `makhzan-config`.
   - (b) For tag-cloud sources only, a classifier trained on crosswalk-mapped listings (fact labels)
     could replace keyword inference, after the measured comparison CLAUDE.md demands.
3. **Spec-key normalisation.** An LLM proposes a canonical-key table offline ("Operating Voltage" /
   "Working voltage" → `voltage`), a human reviews it, and runtime uses the table. The crosswalk pattern
   again.
4. **Title cleanup.** Defer. Shop titles are shop content, and a rewrite can misstate an offer. If it is
   ever done, apply it to the multi-shop *product* name only.
5. **Arabic (about 0.1%).** Multilingual embeddings or mmBERT-based models cover it. It needs no separate
   effort.
6. **Hybrid search.**
   - We run **Meilisearch v1.9**, where vector search is experimental. Hybrid became GA, with the
     experimental flag removed, in **v1.13**. Embedders can be HuggingFace (local, on Meilisearch's
     CPU), REST/Ollama, or user-provided vectors; composite embedders came in v1.14
     ([docs](https://www.meilisearch.com/docs/learn/advanced/vector_search),
     [v1.14](https://www.meilisearch.com/blog/meilisearch-1-14)). The latest release looks like about
     v1.56 (2026-10-26) **[unverified]**.
   - On the 5 GB server: index user-provided vectors computed offline, and embed queries with a small
     int8 model (about 35–120 MB). 61k × 384 float32 is about 94 MB raw **[estimate]**.
   - Keep `semanticRatio` low (about 0.2–0.3) so part numbers still match exactly.
7. **Parts-list import.** PRODUCT.md says parsing, not AI. The only AI role worth considering is "did you
   mean" suggestions for unmatched lines, through the search index (D9).

## 4. Runtime and operations

### 4.1 Where things run
- **Production** (4 vCPU Broadwell, AVX2, about 2 GB free): no LLMs. At most a query-time embedder if
  hybrid search ships.
- **Laptop** (RTX 3060 12 GB): training (cross-encoder, SetFit, calibration), Kev-4B or Qwen3.5-4B/9B
  label generation, and the occasional full rescoring.
- **CPU servers**: steady encoder inference: embeddings, fine-tuned 0.1–0.6B judges, attribute pickers.
  They can also run 4B logit-reads slowly on the review-queue tail.
- **Quantisation:** int8 ONNX/OpenVINO for encoders, with a 2–4.5x CPU speedup at under 0.5% accuracy
  loss ([sbert efficiency docs](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)).
  Q4_K_M–Q8_0 GGUF for LLMs in llama.cpp; avoid going below Q4 for judgements.
- **Privacy:** catalogue text may go only to the owner's own machines, over SSH/WireGuard. No rented GPUs
  and no hosted decision-model APIs (D2).

### 4.2 Throughput per CPU core [estimate]
- **Basis:** FLOP arithmetic on non-embedding parameters (2 FLOPs per parameter per token), assuming
  about 15–25 effective GFLOPS per Broadwell-class AVX2 core with int8/fp32 kernels.
- **Token counts:** pair inputs about 60 tokens; titles about 25 tokens; LLM prompts about 80 new tokens
  per pair after a cached instruction prefix.
- **Calibrate these:** published CPU numbers for these exact models were not found. Run `llama-bench -p
  512 -n 0 -t 1` and a 1,000-pair ONNX timing on each machine first.

| Task / model | Per core | 16 cores, 1 night (8 h) | Notes |
|---|---|---|---|
| Embed titles: bge-small / e5-small int8 (33M) | 40–100 titles/s | all 61k in about 1–2 min | trivial |
| Embed: Qwen3-Embedding-0.6B / EmbeddingGemma Q8 | 2–6 titles/s | 61k in 10–30 min | better recall, mostly multilingual |
| Pair judge: MiniLM-L6 cross-encoder int8 (22M) | 20–60 pairs/s | 100k pairs in 2–5 min | weakest judge |
| Pair judge: ModernBERT-base / mmBERT / Laya / THX-01 class (100–300M) | 1.5–4 pairs/s | 100k pairs in 30–70 min | **recommended CPU judge** |
| Pair judge: Qwen3-Reranker-0.6B, fine-tuned, Q8 | 0.5–1.5 pairs/s | 100k pairs in 1.2–3.5 h | multilingual, instruction-aware |
| Attribute picker: same encoder, 1 title, 3–5 questions (shared state) | 2–5 titles/s | 61k in 15–35 min | |
| GLiNER2-base | 2–6 titles/s | 61k in 10–30 min | |
| Kev-4B / Qwen3.5-4B logit read, Q4_K_M | 0.03–0.08 pairs/s | 15–35k pairs | review tail only |
| Qwen3.5-9B logit read, Q4 | 0.015–0.04 pairs/s | 8–18k pairs | label generation; prefer the GPU |

On the RTX 3060, expect roughly 20–100x those per-core figures for encoders, and about 10–30 pairs/s
for 4B prompt-only scoring **[estimate]**.

### 4.3 Distributing batch jobs across CPU-only machines
**Shape:** a pull-based work queue, idempotent work units, content-addressed results, and one import
path into production.

1. **Snapshot.** `make ai-export` on production writes `snapshot-<ts>.parquet`: the listing id, source,
   domain, category ref, title, price and an attributes subset, plus a `title_hash` per listing. It goes
   by rsync to the coordinator, and production does nothing else.
2. **Coordinator** (homelab): a small Postgres. Optionally reuse the repo's arq and Redis stack, with
   deterministic job ids for deduplication. Postgres is recommended, because `FOR UPDATE SKIP LOCKED`
   leases with an expiry handle crashed workers without extra code.
   - Table `ai_work_units(unit_id, task, model_version, shard_inputs_hash, status, leased_by,
     lease_until, attempts, result_path)`.
   - `unit_id = sha256(task, model_version, sorted input ids + their title_hashes, prompt_sha)`.
3. **Work units:** 500–2,000 items each, so a slow core finishes a unit in under an hour. Tasks:
   `embed`, `block` (one domain per unit), `judge_pairs`, `pick_attributes`, `llm_label`. Each unit
   declares its hardware: `gpu`, `cpu-avx2`, or `ram≥16G` for 9B.
   - Workers claim only units they can run; a 4B-on-CPU unit goes to a server only when the GPU queue
     is empty.
4. **Workers:** one container image per model version, with weights pinned by SHA-256. A worker:
   1. leases a unit;
   2. computes;
   3. writes `results/<unit_id>.parquet` to shared storage (NFS, MinIO or rsync);
   4. marks it done.

   **Idempotence:** rerunning a unit rewrites the same file. A unit whose id already has a result is
   skipped. A changed title changes the hash, which yields a new unit, so only the changed work is
   redone.
   - Threads: `OMP_NUM_THREADS` and llama.cpp `-t` set to the physical cores per process. Run at nice
     19 on shared boxes.
5. **Dependencies:** `embed` → `block` → `judge_pairs`. A `judge_pairs` unit for a domain becomes
   eligible only when that domain's `block` unit is done.
6. **Assemble and import.** The coordinator concatenates results for one snapshot and model version into
   an artifact containing:
   - `manifest.json`: model names, weight hashes, git SHA, thresholds, calibration parameters, ECE;
   - `pair_scores.parquet`;
   - `listing_attributes.parquet`.

   `make ai-import ARTIFACT=…` on production then does an idempotent upsert into
   `match_evidence(listing_a, listing_b, score, calibrated_p, model_version, title_hash_a, title_hash_b)`
   and `listing_ai_attributes(listing_id, key, value, p, model_version, title_hash)`. Rows whose title
   hash no longer matches are ignored as stale.
7. **Production never runs a model.** `rebuild_products` reads stored evidence, so a regroup stays a
   deterministic function of listings plus evidence, and `make regroup-dry-run` remains the deploy gate.
   Rollback means pointing at the previous `model_version`. A machine being away only delays new
   evidence.

### 4.4 Recording decisions and evaluating
- **Explainability:** add `{"admitted_by":"pair-judge","model_version":…,"p":0.993,"t":0.98,"vetoes_checked":[…]}`
  to `product_events.detail` for any merge a score helped admit. LLM explanations go into the review
  queue's `proposed` field, and are never published.
- **Gold set:**
  - about 1,500 owner-labelled cross-shop pairs, stratified by domain and similarity band (mostly the
    hard middle);
  - about 300 same-shop pairs as a sanity check;
  - split 20% calibration / 30% frozen test / 50% training top-up.
- **Metrics:**
  - per-domain precision and recall at *t*, with the Wilson lower bound;
  - ECE;
  - **cluster-level**: "products whose published range includes a false member", and the maximum price
    span;
  - the `regroup-dry-run` merge and split counts, plus a read sample.
- **Gate for auto-admission:** a precision lower bound ≥ 0.98 on the frozen test set for that domain.
  Recall only decides how much gets merged.
- **Drift:** rerun the test set on every model, prompt or threshold change. Hand-audit about 50 new
  model-admitted merges each month.

## 5. Recommended architecture, in phases (cheapest and highest-precision first)

- **Phase 0: gold set and harness.** No model. The pair-labelling review reason, the frozen split,
  metrics, and an audit of about 100 current multi-shop products. The audit gives the rules' own
  precision, the baseline every model must beat.
- **Phase 1: embedding blocking feeding the review queue, never merges.** bge-small on CPU servers
  generates cross-shop candidates per domain. Filter them through existing vetoes, then send them to
  the owner, ranked by Kev-4B P(yes) computed on the laptop. Confirmed pairs go to a `confirmed_matches`
  table that `rebuild_products` honours (vetoes still checked, conflicts logged).
  - Gain: the first cross-shop products outside electronics. **The size is unknown until measured.**
  - Side benefit: a "similar at other shops" link (not a merge, so no false range).
- **Phase 2: multiple-choice attribute pickers feeding new vetoes, in all domains.** Rules first, then
  a fine-tuned encoder picker with "not stated"/"other" and a τ ≥ 0.95 cut-off.
  - Purely restrictive, so safe. It also cuts review load and may split existing over-merges.
- **Phase 3: fine-tuned pair judge as an admission signal**, per domain, only after the phase-0 gate.
  - Model: ModernBERT-base or mmBERT on CPU, or Qwen3-Reranker-0.6B.
  - Training data: same-shop hard negatives, veto negatives, audited positives, owner labels and Kev
    pre-labels.
  - Auto-admit only when no veto fires, calibrated p ≥ *t*, and identifier/title rules (where they
    exist) don't contradict. The middle band goes to review, and its labels feed back into training.
  - Gain is uncertain: published F1 on hard product data is 72–87, so at precision ≥ 0.99 recall may be
    modest.
- **Phase 4: variant families** (grouping by material), after the options table. A new relation
  `product_families`, which admits same-shop members.
  - Family key: brand + material + defining specs from phase 2. Members differ only on the option axis.
  - Shown as one page with an options table. It never feeds identity or a single price range.
- **Phase 5 (optional): hybrid search** after upgrading Meilisearch from v1.9, behind a flag.

**Risks.**
- *Over-merging*: vetoes are hard, there is a per-domain calibrated gate, mid-confidence goes to
  review, and `regroup-dry-run` runs before deploy. Stable ids make a merge reversible, but a false
  range is public until it is split.
- *Circular labels*: audit first, and evaluate only on owner labels.
- *Drift*: title-hash invalidation, plus the monthly audit.
- *Opacity*: version and probability in `product_events`; vetoes stay the human-readable reason.
- *Hype risk*: the 2026 decision-model claims are self-reported and mostly from general benchmarks.
  Treat them as candidates to measure, not results.
- *Licences*: Qwen, Kev, Laya and THX-01 are Apache; bge and e5 are MIT. Gemma and Llama have their own
  terms.

## 6. Decisions for the owner

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Where models run | laptop + CPU servers batch / + query embedder on prod / batch on prod | Batch off-prod; prod gets only a query embedder, if hybrid search ships |
| D2 | Where catalogue text may go | own machines / + rented GPU / + hosted decision-model APIs (Jev, Microsoft-Decision-1) | Own machines only |
| D3 | Model's role in grouping | review suggestions / veto only / auto-admit | Suggestions + vetoes now; auto-admit per domain after a precision lower bound ≥ 0.98 |
| D4 | Pair judge | zero-shot Kev-4B / fine-tuned encoder (ModernBERT/mmBERT/Laya/THX-01) / fine-tuned Qwen3-Reranker-0.6B | Fine-tuned encoder on CPU; Kev-4B as triage and pre-labeller only |
| D5 | Labelling budget | ~500 / ~1,500 / ~3,000 pairs | ~1,500 in 3 sessions, stratified |
| D6 | Machine pre-labels | none / training only / training + eval | Training only, sample-checked |
| D7 | Job distribution | Postgres SKIP LOCKED queue / arq + Redis / cron + rsync per machine | Postgres queue on the homelab; content-addressed units |
| D8 | Variant families | separate same-shop-capable table / extend `_subcluster` | Separate table, after the options table |
| D9 | Parts-list AI fallback | none / "did you mean" suggestions | Decide later; suggestions only |
| D10 | Category inference | crosswalk-authoring aid / also replace keyword rules for tag-cloud shops | Aid now; replacement only after a measured comparison; never authoritative sources |
| D11 | Meilisearch upgrade from v1.9 | stay / later / now | After phase 1, as its own change |
| D12 | Publish model-derived data | internal only / show attributes or cleaned titles | Internal only (vetoes, families); display shop-stated text |
| D13 | Per-domain identifiers by rule (bearing codes such as 6204-2RS, thread specs) alongside embeddings | yes / no | Yes: rule identifiers first where a domain has them (seals-bearings), embeddings elsewhere |

## Sources (accessed 2026-11-13)
- Decision models: dsebastien.net/decision-models-dms; datacamp.com/blog/top-ai-decision-models; huggingface.co/jaredpalmer/kev-4b;
  aiweekly.co (Laya); huggingface.co/blog/doofz/thx-01-…; github.com/TheoLeeCJ/SemIf; huggingface.co/Qwen/Qwen3-Reranker-0.6B; letsdatascience.com (Jev)
- HRM/TRM: arxiv.org/abs/2510.04871; arcprize.org/blog/hrm-analysis (2025-08-15)
- Entity matching: arxiv.org/abs/2301.09521; 2409.08185; 2409.04073; 2606.28823; 2607.24688
- Embeddings / runtime: arxiv.org/abs/2509.20354; sbert.net efficiency docs
- Extraction: arxiv.org/abs/2507.18546 (GLiNER2); 2403.02130 (WDC-PAVE); huggingface.co/blog/setfit
- Small LLMs: artificialanalysis.ai (Qwen3.5 small, 2026-03)
- Search: meilisearch.com docs (hybrid GA v1.13; v1.14 composite embedders)
