# Phase D bake-off: candidate finding and pair judging

**Date:** 2026-11-13/14. **Status:** draft for `docs/ai/phase-d-bakeoff.md`. Everything ran
locally on the RTX 3060 desktop: no hosted API, no crawling, nothing on production. The data
was the Phase C labelled pairs and a local copy of the production database (the same snapshot
Phase C used: 61,134 active listings). Scripts are in `ml/bakeoff/` (branch `feat/ml-bakeoff`).
Per-pair scores, keyed by pair id only, are in `ml/out/bakeoff/` (git-ignored).

## Summary

1. **Candidate finding is not the bottleneck on this data, and it cannot separate the
   methods.** Every method puts the partner of almost every labelled `same` pair in the top 10.
   On test, within the department, pair recall@10 is 0.96 for today's title-token Jaccard and
   0.99 for Qwen3-Embedding-0.6B with structured fields. Today's identifier key, the only
   route by which today's grouping ever compares two listings, reaches 0.79. These positives
   were selected by lexical similarity or a shared code, so the number says little about the
   case embeddings exist for: the same product described in different words. **Not
   established:** recall on such pairs.
2. **Kev-4B is the best judge, by a clear margin at high precision.** On frozen test
   thresholds, at the threshold that gave precision ≥ 0.98 on validation, Kev-4B (title only)
   catches 79.8% of the same pairs with 0 false merges in 83 (Clopper-Pearson 95% lower bound
   0.957). Qwen3-Reranker-4B catches 47.1% at the equivalent point, Qwen3-Reranker-0.6B 52.9%
   and bge-reranker-v2-m3 54.8%. Today's rules score 68.3% recall at precision 0.959 (3 false
   merges), but that recall is an artefact of how the pairs were sampled, not production recall,
   so it is not a like-for-like comparison with the models (see "What today's rules means here").
3. **The plan's gate cannot be passed on this test set by any judge.** With zero errors, a
   lower bound of 0.98 needs:
   - at least 183 correct merges for a two-sided 95% Clopper-Pearson bound (the same as a
     one-sided 97.5% bound; two-sided Wilson needs 189);
   - at least 149 for a one-sided 95% bound.

   The plan's "lower 95% bound" does not say which; the owner is deciding. Either way it is
   out of reach.
   The test set has 104 same pairs in total, 90 of them in electronics. The best result, 83 of
   83, has a bound of 0.957. More labelled positives are a precondition for any automatic merge.
4. **The prompt study changed little.** Within each model, almost every instruction, context
   rung and few-shot variant is within noise of the best (paired bootstrap). One exception:
   the card's web-search default instruction is clearly worse for both Qwen3 rerankers. The
   other: full descriptions clearly hurt Qwen3-Reranker-4B. Under the rule fixed in advance
   (simplest variant within noise), every model's finalist is **title only, no examples**.
   The richer contexts cost 2–11× in throughput and bought no measurable gain.
5. **Recommendation for Phase E:** put Kev-4B (title only) behind today's vetoes as a
   **review-queue suggester**, run offline on the 3060, with candidates from Qwen3-Embedding-0.6B
   or plain title Jaccard. Do not auto-merge in any department yet. The caveats are under
   "Recommendation".

## Data and protocol

- **Labels.** Phase C: 494 pairs, 247 validation and 247 test, labelled by an agent. A 100-pair
  owner spot-check (adjudicated) overlaps both splits (60 validation, 40 test). For matching,
  `same` = 1, while `different` and `variant` = 0. `unsure` is excluded. Decided pairs:
  validation 224 (110 same), test 232 (104 same).
- **Frozen test.** Every threshold and choice was made on validation. The grid was written
  down before any judge was scored (`ml/out/bakeoff/grid.json`). Test scores were produced only
  after every choice was frozen (`frozen.json`), and evaluated once.
- **Test labels.** The primary labels are the agent labels on `test.jsonl`, as briefed. The
  Phase C README instead calls the owner-adjudicated pairs the frozen test set. Those were also
  scored, but only 38 decided pairs fall in the test split, and that sample is deliberately
  skewed to hard cases (below).
- **Departments.** Same pairs exist only in electronics (90 test / 94 validation), tools
  (8 / 10), chemicals (5 / 5), and one cross-department bearing pair per split. Every other
  department supplies only same-shop negatives (3–12 pairs each). **Per-department numbers
  outside electronics are anecdotes, not measurements**, and are reported as counts.
- **Intervals.** Precision lower bounds: Clopper-Pearson two-sided 95% (exact, the bound used
  for the gate) and Wilson 95% beside it. F1, CV-F1 and average precision (AP) use a 1,000-rep
  percentile bootstrap over pairs.

## Q1. Candidate finding

**Setup.** Each query listing ranks the whole catalogue, 61,134 active listings, excluding
itself and every listing from its own shop (same-shop listings never merge). The ranking is
either within its department or across all departments. For every labelled `same` pair, a
"pair" hit at k means either listing has the other in its top k. Ties count at their
expectation under random tie-breaking.

The methods:

- **Token Jaccard.** makhzan_schemas' title tokeniser and each department's noise list, as
  `grouping._sig_tokens`, but with the identifier and numbers kept. (Grouping strips the
  identifier only because it has already blocked on it.)
- **Character-trigram Jaccard.** The Phase C similarity.
- **Embeddings.** Harrier-270m and Qwen3-Embedding-0.6B (vLLM 0.32.0, bf16). Every text was
  embedded as a query with the instruction "Given two product listings from hardware shops,
  judge whether they are the same product: the same item, the same variant and the same pack
  size". Two texts were tried: title only (L0), and title plus structured fields (L1, below).
- **Identifier key.** Whether today's rules (`assign_identifiers`, current main) give both
  listings the same key.

**Pair recall@k on test (104 same pairs), within department / across departments.**

| method | @5 | @10 | @20 | @50 |
|---|---|---|---|---|
| identifier key (today's only route; no k) | 0.788 | | | |
| token Jaccard | 0.947 / 0.956 | 0.961 / 0.970 | 0.971 / 0.981 | 0.981 / 0.990 |
| trigram Jaccard | 0.908 / 0.917 | 0.957 / 0.967 | 0.971 / 0.981 | 0.981 / 0.990 |
| Harrier, title | 0.894 / 0.894 | 0.923 / 0.923 | 0.952 / 0.952 | 0.971 / 0.981 |
| Harrier, + fields | 0.962 / 0.962 | 0.981 / 0.971 | 0.981 / 0.990 | 0.990 / 1.000 |
| Qwen3-Emb, title | 0.971 / 0.952 | 0.981 / 0.981 | 0.990 / 1.000 | 0.990 / 1.000 |
| **Qwen3-Emb, + fields** | **0.990 / 0.990** | **0.990 / 1.000** | 0.990 / 1.000 | 0.990 / 1.000 |

How to read the table:

- Validation agrees in rank order: Qwen3-Emb + fields scored 0.982 / 0.991 at k = 5 / 10
  within department, against 0.960 / 0.968 for token Jaccard.
- The within-department ceiling is 0.990, because one test pair, a thrust bearing, is filed
  in two departments.
- The whole spread between methods is 1–5 pairs out of 104. **No method is significantly
  better than token Jaccard at k ≥ 10.**

**By department (test, within, @10).**

| department | same pairs | token Jaccard | Qwen3-Emb + fields |
|---|---|---|---|
| electronics | 90 | 0.977 | 1.000 |
| tools | 8 | 0.875 | 1.000 |
| chemicals | 5 | 1.000 | 1.000 |

The tools and chemicals rows are too few pairs to conclude anything.

**Where they differ: the rule_candidate stratum.** These are pairs that share a model code
but word their titles differently, 15 same pairs on test. Within department @10, token
Jaccard scores 0.733, trigram Jaccard 0.800, Harrier with fields 0.933 and Qwen3-Emb with
fields 0.933. That is the right direction for embeddings, but it rests on 15 pairs.

**Cost.** Each run embeds the whole catalogue (61,134 texts) on the 3060, with the other small
services resident.

| embedder | text | time | texts/s | vector | GPU (serving cap) |
|---|---|---|---|---|---|
| Harrier-270m | title | 29 s | 2,116 | 640-d | ~1.6 GB |
| Harrier-270m | + fields | 44 s | 1,378 | 640-d | ~1.6 GB |
| Qwen3-Emb-0.6B | title | 63 s | 964 | 1,024-d | ~2.2 GB |
| Qwen3-Emb-0.6B | + fields | 148 s | 414 | 1,024-d | ~2.2 GB |

- Brute-force cosine search of 220 queries against all 61k vectors takes under 0.1 s on the
  CPU (numpy).
- The catalogue's vectors take 125 MB at fp16.
- Lexical indexes build in under a second.

**Not established.** The catalogue has thousands of cross-shop twins that nobody has labelled.
The positives here were found by today's rules (today_multi), by trigram neighbours
(cross_candidate) or by a shared code (rule_candidate). Every one of those routes is lexical.
So this measures recall on pairs a lexical method already finds; the case where embeddings
should win is under-represented by construction (Phase C README).

## Q2. Pair judging

### What "today's rules" means here

- **rules_pair.** Nothing was re-implemented. Every active listing becomes a transient
  `Listing`, and `grouping.assign_identifiers` runs over all 61,134 (current identifier rules
  plus the family guard). A pair is then judged *same* only if both listings have an
  identifier, `grouping.base_key` gives them one key, and `grouping._subcluster(key, [a, b],
  domain, current={})` puts them in one cluster. That covers title agreement plus every veto:
  same shop, values, form and price span.
- **rules_full.** `grouping._group_listings(all listings, stored products)` with incumbency,
  as `rebuild_products` calls it, followed by a check whether both listings land in one group.
- **today_stored.** The snapshot's own product ids.
- **What the rules' recall means.** The rules' recall here reflects how Phase C sampled the
  pairs, not production recall. Two strata decide it:
  - The today_multi stratum was drawn from products the rules already merge. On test,
    today_stored is exactly that stratum: 66 same, 5 different.
  - The cross_candidate pairs were sampled as "not the same product today", so the rules miss
    them by construction.

  rules_full starts from the stored product ids (incumbency), and rules_pair uses the same
  identifiers and vetoes, so both inherit this. The rules' 0.683 recall (and 0.755 on
  validation) is therefore a property of the dataset, not of the rules in production. Kev's
  recall against the rules is **not a like-for-like comparison**. Only the rules' precision
  and their false merges are informative here.
- **Vetoes (for the combination).** `values.values_conflict`, `grouping._forms_conflict` (with
  the profile's strict forms), `grouping._span_ok` (with `merge_price_ratio`) and same
  supplier. Each runs on the title with its identifier taken out, as `_subcluster` builds its
  evidence.

### Judges

| service | model | engine / image | precision |
|---|---|---|---|
| rr-bge | BAAI/bge-reranker-v2-m3 | TEI `86-1.9.4` | fp16 |
| rr-qwen3-0.6b | Qwen/Qwen3-Reranker-0.6B | vLLM `v0.32.0`, the repo's fixed template | bf16 |
| rr-qwen3-4b | Qwen/Qwen3-Reranker-4B | vLLM `v0.32.0`, the repo's fixed template | bf16 |
| kev-4b | jaredpalmer/kev-4b | `kev.serve` (`makhzan-ml/kev:1.0`), `noul`, raw P(yes) (T = 1) | bf16 |

The image digests are those pinned in `ml/docker-compose.yml`. The only serving change was for
the Qwen3 rerankers: `--max-model-len 4096` instead of the stock 2,048, so that full
descriptions fit. No pair needed truncating at that length. Every pair was scored in both
orders, and the minimum was kept.

### The prompt study: grid fixed in advance

**Instructions.** Qwen3 rerankers get these verbatim as the `<Instruct>` line. Kev gets the
question form of I2–I4: Kev has no card default, and its documented usage is a yes/no question.

- **I1, the card default:** "Given a web search query, retrieve relevant passages that answer
  the query"
- **I2, the serving default:** "Given two product listings from hardware shops, judge whether
  they are the same product: the same item, the same variant and the same pack size". Kev:
  "Are listing A and listing B the same product: the same item, the same variant and the same
  pack size?"
- **I3, task-specific (the owner's wording):** "Decide whether these two shop listings sell the
  identical product: same maker, model and specification; a different value, pack size,
  variant or accessory is a different product". Kev: "Do listing A and listing B sell the
  identical product: same maker, model and specification? A different value, pack size,
  variant or accessory is a different product."
- **I4, makhzan's variant rule:** "Decide whether two shop listings are the same product, so
  that a buyer could buy either and receive the same item. Listings from the same product line
  that differ in one option (colour, size, length, capacity, rating or value) are NOT the same
  product; neither are a different model, a different package, a different pack size or
  bundle, or a part versus a module or accessory. Differences only in wording, word order or
  spelling do not matter". Kev: the same text as a question ("Are listing A and listing B the
  same product, so that …? … do not matter.").

**Context ladder.** Each rung adds to the one before. A missing field is left out.

- **L0:** title only.
- **L1:** + department, makhzan category, shop category, brand, part number (the shop's MPN,
  else the identifier today's rules assign), and price in EGP.
- **L2:** + the full spec table (list page merged with product page) and the shop's options.
- **L3:** + the full description, HTML stripped and units kept.

**Few-shot examples.** Four examples (two cross-shop `same`, one `different`, one `variant`),
titles only:

- In the Qwen3 rerankers they are appended to the instruction ("Examples (Query | Document ->
  answer): …").
- In Kev they go in as JSON content in its `instructions` field, with the question beside
  them. Kev renders that content as labelled text.
- The examples come from the other folds of a 5-fold split of validation, so no pair is ever
  judged with itself or its fold as an example. Test pairs were never used as examples.
- No pair outside validation and test exists to draw from.

**Grid.**

| judge | variants |
|---|---|
| bge | L0, L1, L2, L3 (it takes no instruction) |
| Qwen3-Reranker 0.6B and 4B | I1–I4 at L1; I2 at L0, L2, L3; best instruction × best rung if new; then 4-shot on the stage-1 choice |
| Kev | I2–I4 at L1; I2 at L0, L2, L3; I4 × L3 (the new combination); 4-shot on the stage-1 choice |

That is 28 variants in all, 4–8 per model: Kev 8, bge 4, Qwen3-0.6B 8 and Qwen3-4B 8.

**Selection rule.** The leader is the variant with the highest 5-fold cross-validated F1:
each fold is judged at the best-F1 threshold of the other four. Every variant whose
paired-bootstrap 95% interval of the CV-F1 difference to the leader contains 0 counts as tied.
The simplest tied variant is chosen: fewer examples first, then a lower rung, then a shorter
instruction.

### Coverage of the context fields (validation, both sides of a pair)

| field | all 247 | electronics 147 | tools 35 | chemicals 16 | others 49 |
|---|---|---|---|---|---|
| category / shop category | 245 / 239 | 145 / 139 | 35 / 35 | 16 / 16 | 49 / 49 |
| price | 247 | 147 | 35 | 16 | 49 |
| part number | 135 | 116 | 7 | 3 | 9 (bearings) |
| brand | 3 | 3 | 0 | 0 | 0 |
| spec table | 17 | 15 | 0 | 2 | 0 |
| options | 0 | 0 | 0 | 0 | 0 |
| description | 112 | 98 | 5 | 7 | 2 |

- Across the catalogue: description 41% of listings, spec table 18%, brand 3%, options 0.6%.
- Product-page details (`attributes.details`) exist for only 122 listings. The details stage
  has barely run.
- **The spec-table rung is judged on 16 decided pairs with a table on both sides. Nothing can
  be concluded about it.**
- **Truncation.** bge was cut to its card's 512 tokens per pair: at L3 that touched 116 of 247
  validation pairs (105 test), and at L2 1 (2). Qwen3 and Kev were never cut. The longest pair
  is 2,593 tokens, against budgets of 3,328 and 7,424.

### Validation results: every variant

The columns:

- **AP:** average precision.
- **CV-F1:** 5-fold cross-validated F1.
- **Δ vs leader:** CV-F1 difference to the model's leader, with its paired 95% interval.
- **R@P98:** recall at the lowest threshold with precision ≥ 0.98 (in-sample, with tp/fp).
- **desc-subset AP:** AP on the 105 decided pairs with a description on both sides.
- **p/s:** pairs per second at batch 32.

Brackets are 95% intervals. ✔ marks the chosen variant.

| judge | variant | AP | CV-F1 | Δ vs leader | R@P98 | desc-subset AP | p/s |
|---|---|---|---|---|---|---|---|
| bge | L0 ✔ | 0.939 [0.899–0.970] | 0.858 [0.802–0.905] | −0.034 [−0.086, +0.014] | 0.509 (56/1) | 0.971 | 800 |
| bge | L1 | 0.902 [0.837–0.960] | 0.855 [0.805–0.901] | −0.038 [−0.085, +0.006] | 0.009 (1/0) | 0.971 | 326 |
| bge | L2 | 0.914 [0.849–0.966] | 0.862 [0.812–0.910] | −0.030 [−0.078, +0.014] | 0.018 (2/0) | 0.977 | 225 |
| bge | L3 (leader) | 0.921 [0.866–0.962] | 0.893 [0.849–0.931] | 0 | 0.145 (16/0) | 0.951 | 101 |
| Qwen 0.6B | I1-L1 | 0.862 [0.798–0.912] | 0.820 [0.766–0.869] | **−0.068 [−0.127, −0.013]** | 0.209 | 0.959 | 169 |
| Qwen 0.6B | I2-L0 ✔ | 0.950 [0.917–0.974] | 0.862 [0.809–0.908] | −0.026 [−0.078, +0.025] | 0.391 (43/0) | 0.971 | 400 |
| Qwen 0.6B | I2-L0 4-shot | 0.926 [0.875–0.965] | 0.872 [0.824–0.917] | −0.016 | 0.118 | 0.973 | 342 |
| Qwen 0.6B | I2-L1 | 0.929 [0.877–0.973] | 0.879 [0.832–0.923] | −0.009 | 0.191 | 0.932 | 170 |
| Qwen 0.6B | I2-L2 | 0.931 [0.880–0.974] | 0.857 [0.808–0.906] | −0.031 | 0.155 | 0.936 | 120 |
| Qwen 0.6B | I2-L3 (leader) | 0.931 [0.882–0.971] | 0.888 [0.843–0.927] | 0 | 0.164 | 0.936 | 35 |
| Qwen 0.6B | I3-L1 | 0.927 [0.882–0.963] | 0.817 [0.756–0.872] | **−0.071 [−0.134, −0.014]** | 0.245 | 0.950 | 171 |
| Qwen 0.6B | I4-L1 | 0.909 [0.850–0.957] | 0.874 [0.831–0.917] | −0.014 | 0.155 | 0.922 | 166 |
| Qwen 4B | I1-L1 | 0.874 [0.819–0.926] | 0.810 [0.757–0.862] | **−0.098 [−0.148, −0.051]** | 0.173 | 0.949 | 26 |
| Qwen 4B | I2-L0 ✔ (leader) | 0.963 [0.935–0.985] | 0.907 [0.865–0.945] | 0 | 0.491 (54/1) | 0.986 | 62 |
| Qwen 4B | I2-L0 4-shot | 0.961 [0.931–0.985] | 0.874 [0.827–0.916] | −0.034 [−0.077, +0.010] | 0.482 | 0.984 | 61 |
| Qwen 4B | I2-L1 | 0.958 [0.923–0.984] | 0.893 [0.844–0.934] | −0.014 | 0.245 | 0.967 | 26 |
| Qwen 4B | I2-L2 | 0.949 [0.907–0.982] | 0.882 [0.835–0.926] | −0.026 | 0.173 | 0.962 | 18.5 |
| Qwen 4B | I2-L3 | 0.862 [0.805–0.913] | 0.805 [0.753–0.855] | **−0.103 [−0.157, −0.057]** | 0.282 | 0.923 | 5.7 |
| Qwen 4B | I3-L1 | 0.960 [0.931–0.984] | 0.886 [0.838–0.927] | −0.022 | 0.400 | 0.970 | 26 |
| Qwen 4B | I4-L1 | 0.948 [0.912–0.976] | 0.877 [0.827–0.922] | −0.030 | 0.445 | 0.963 | 26 |
| Kev 4B | I2-L0 ✔ | 0.976 [0.957–0.991] | 0.916 [0.877–0.953] | −0.031 [−0.067, +0.006] | 0.782 (86/1) | 0.979 | 12.8 |
| Kev 4B | I2-L0 4-shot | 0.980 [0.962–0.993] | 0.928 [0.892–0.963] | −0.019 | 0.782 | 0.981 | 7.5 |
| Kev 4B | I2-L1 | 0.988 [0.975–0.996] | 0.920 [0.876–0.954] | −0.027 [−0.058, +0.000] | 0.909 (100/2) | 0.990 | 10.6 |
| Kev 4B | I2-L2 | 0.986 [0.973–0.995] | 0.942 [0.907–0.970] | −0.004 | 0.745 | 0.988 | 8.9 |
| Kev 4B | I2-L3 (leader) | 0.985 [0.970–0.995] | 0.946 [0.912–0.975] | 0 | 0.727 | 0.988 | 4.3 |
| Kev 4B | I3-L1 | 0.988 [0.977–0.996] | 0.916 [0.873–0.950] | −0.031 | 0.864 | 0.993 | 10.6 |
| Kev 4B | I4-L1 | 0.989 [0.978–0.997] | 0.945 [0.911–0.972] | −0.001 | 0.845 | 0.992 | 9.3 |
| Kev 4B | I4-L3 | 0.987 [0.975–0.995] | 0.938 [0.900–0.967] | −0.009 | 0.800 | 0.990 | 4.0 |

Rules on validation:

- rules_pair: P 0.965, R 0.755, F1 0.847 (83 tp, 3 fp, 27 fn; Clopper-Pearson lower 0.901).
- rules_full: the same as rules_pair.
- today_stored: P 0.959, R 0.645.

**Reading the prompt study.**

- **Instructions.** The card's web-search default (I1) is the only setting clearly worse, by
  0.07–0.10 CV-F1 on both Qwen3 rerankers. I3 also loses for the 0.6B. Among task
  instructions (I2–I4), nothing separates.
- **Context.**
  - For Kev, adding fields leans upward (AP 0.976 → 0.985–0.989; L1 doubles R@P98 in sample),
    but the CV-F1 gains are within noise.
  - For bge, the full description is the leader on CV-F1 while AP falls.
  - For Qwen3-4B, the full description hurts clearly: AP 0.963 → 0.862, CV-F1 −0.10.
  - On the subset where both sides have a description (105 pairs), L3 is not better than L0
    for any model.
  - Structured fields carry little: brand is present on both sides in 3 pairs, and category
    and price nearly always.
- **Few-shot.** No gain for any model. For Qwen it cut R@P98 (0.6B 0.39 → 0.12). For Kev it
  cost 40% of throughput.
- **Calibration.** Qwen3 scores are saturated: the best thresholds sit at 0.994–0.9996, so a
  threshold carries little margin. Kev's raw P(yes) spreads more (best-F1 threshold 0.26,
  P98 threshold 0.71).
- **Conclusion.** Under the fixed rule, every model's finalist is the plain title with the
  serving instruction (bge: plain title). **Kev with structured fields (I2-L1 or I4-L1) is the
  variant most worth re-testing on a larger set.** Its in-sample R@P98 of 0.85–0.91 is the
  best seen, but the CV evidence for it over title-only is not significant.

**The one combination: today's vetoes on Kev.** A pair any veto fires on (same shop,
conflicting values, conflicting form, price ratio) scores 0. Otherwise it keeps Kev's
title-only score, re-thresholded on validation. Justification: this is exactly the plan's
design ("a model yes only admits a merge; every existing veto still applies"). Kev was picked
as the judge with the best chosen CV-F1. On validation: AP 0.977, CV-F1 0.931, R@P98 0.764.

### Test results: frozen finalists, evaluated once

Agent labels, 232 decided pairs (104 same). Thresholds come from validation. "@best-F1" is
the threshold that maximised F1 on validation; "@P98" is the lowest threshold with precision
≥ 0.98 on validation. CP is the Clopper-Pearson 95% lower bound on precision; Wilson is in
`test.json`.

| judge (variant) | AP | @best-F1: P / R / F1 (tp/fp/fn) | CP | @P98: P / R (tp/fp/fn) | CP |
|---|---|---|---|---|---|
| rules_pair | – | 0.959 / 0.683 / 0.798 (71/3/33) | 0.886 | – | – |
| rules_full | – | 0.935 / 0.692 / 0.796 (72/5/32) | 0.855 | – | – |
| today_stored | – | 0.930 / 0.635 / 0.754 (66/5/38) | 0.843 | – | – |
| bge (L0) | 0.914 | 0.796 / 0.865 / 0.829 (90/23/14) | 0.710 | 0.919 / 0.548 (57/5/47) | 0.822 |
| Qwen3-0.6B (I2-L0) | 0.935 | 0.830 / 0.894 / 0.861 (93/19/11) | 0.748 | 0.982 / 0.529 (55/1/49) | 0.904 |
| Qwen3-4B (I2-L0) | 0.965 | 0.838 / 0.942 / 0.887 (98/19/6) | 0.758 | 0.980 / 0.471 (49/1/55) | 0.894 |
| **Kev-4B (I2-L0)** | **0.983** | 0.922 / 0.913 / **0.918** (95/8/9) | 0.853 | **1.000 / 0.798 (83/0/21)** | **0.957** |
| **Kev-4B + vetoes** | **0.989** | 0.899 / 0.942 / **0.920** (98/11/6) | 0.827 | 0.989 / **0.846** (88/1/16) | 0.939 |

The rules rows' recall is set by how the pairs were sampled (today_multi in, cross_candidate
out by construction), so compare the models with the rules on precision and false merges only,
not on recall. Every precision here is at a 104 : 128 class ratio, not a shortlist's roughly
1 : 9 (see Caveats).

**Cross-shop pairs only** (176, the ones a judge would see in production, since the
same-shop veto removes the rest):

| judge | @best-F1: P / R / F1 | @P98: P / R (tp/fp) |
|---|---|---|
| bge | 0.891 / 0.865 / 0.878 | 1.000 / 0.548 (57/0) |
| Qwen3-0.6B | 0.894 / 0.894 / 0.894 | 1.000 / 0.529 (55/0) |
| Qwen3-4B | 0.925 / 0.942 / 0.933 | 1.000 / 0.471 (49/0) |
| Kev-4B | 0.931 / 0.913 / 0.922 | 1.000 / 0.798 (83/0) |
| Kev-4B + vetoes | 0.899 / 0.942 / 0.920 | 0.989 / 0.846 (88/1) |
| rules_pair | 0.959 / 0.683 / 0.798 | – |

So about half of the rerankers' false merges are same-shop variants, which the existing
same-shop veto already blocks. At the @best-F1 threshold on test, that is 12 of 23 for bge, 8
of 19 for Qwen3-0.6B and 11 of 19 for Qwen3-4B. Across shops, Kev's advantage is at high precision, where it keeps 80%
of recall and the rerankers keep about 50%.

**Per department (test).**

| department | decided pairs | same | rules_pair (tp/fp/fn) | Kev-4B @P98 (tp/fp/fn) | Kev + vetoes @P98 (tp/fp/fn) | Qwen3-4B @best-F1 (tp/fp/fn) |
|---|---|---|---|---|---|---|
| electronics | 138 | 90 | 68/3/22 (P 0.958, R 0.756) | 74/0/16 (R 0.822, CP 0.951) | 79/0/11 (R 0.878, CP 0.954) | 86/5/4 |
| tools | 31 | 8 | 2/0/6 | 5/0/3 | 5/1/3 | 6/1/2 |
| chemicals | 12 | 5 | 1/0/4 | 4/0/1 | 4/0/1 | 5/3/0 |
| seals-bearings | 12 | 0 | 0 fp | 0 fp | 0 fp | 4 fp |
| all other departments (and 1 cross-department pair) | 39 in all | 0 | 0 fp | 0 fp | 0 fp (1 fp, machinery, at @best-F1) | 6 fp (garden, materials, piping, safety, security, welding) |

- Outside electronics there are too few pairs to conclude anything.
- One pattern does repeat: today's rules find only 3 of 13 same pairs in tools and chemicals,
  which have few codes. Kev finds 9.
- Validation (in-sample) shows the same pattern.

**Owner-adjudicated test pairs** (38 decided, 18 same; deliberately oversampled hard cases):

- Kev + vetoes @best-F1: P 0.833, R 0.833 (15/3/3).
- Kev @P98: 10/0/8.
- Qwen3-4B @best-F1: 14/7/4.
- rules_pair: 5/4/13 (P 0.56, R 0.28).

This sample is too small for bounds (CP lower 0.59–0.69). It does say the hard cases are
where today's rules are weakest.

### Error patterns (described generically)

- **Rerankers (all three):** many false merges are variants from one shop. Today's vetoes
  block 11 of the 14 that Qwen3-4B makes on validation, and about half on test. Examples: bearings that differ only in seal suffix, oil seals that differ in profile
  letter, a 2-gang vs 4-gang switch, two receivers vs three in a doorbell kit, sibling model
  codes one digit apart. The same-shop veto removes these. The cross-shop false merges are
  harder:
  - an angled vs a straight PCB connector of the same code;
  - a USB step-up cable with a different output voltage;
  - a panel-mount vs an inline version of a lever connector (today's rules also merge this
    one);
  - TTL vs CMOS logic chips of the same function.
- **Kev:** its few false merges are near-misses of the same kinds:
  - a "compatible" module vs the original;
  - one logic family vs another;
  - two cordless drills of one voltage where one names a brand and one does not (this is
    the brand-only soft spot the owner has since said the AI may merge, so the label itself
    is debatable).

  Its misses are mostly conservative refusals on clear twins: a chip with and without its
  package suffix, a transistor with and without its polarity word, a sensor listed by
  breakout name vs chip name. **Many of Kev's misses are pairs today's rules already merge,**
  and vice versa.
- **Today's rules:** the misses are pairs without a shared extracted code (tools, chemicals,
  modules named differently). The false merges are code-sharing variants (a panel-mount vs an
  inline connector) and a brand pair.

## Throughput (judging)

Measured on the 3060 with each model alone (the small models together), on the 247
validation pairs × 2 orders, 4 requests in flight. Prefix caching was as served (on for vLLM
by default, which is legitimate for a shared instruction prefix).

| judge | text | batch 10 | batch 32 | batch 64 | GPU memory (resident) |
|---|---|---|---|---|---|
| bge | title | 792 | 800 | 1,008 | ~1.3 GB |
| bge | + fields (L1) | 297 | 326 | 333 | |
| Qwen3-0.6B | title | 376 | 400 | 402 | ~3.4 GB (cap) |
| Qwen3-0.6B | L1 / L2 / L3 | 171 / – / – | 170 / 120 / 35 | 171 | |
| Qwen3-4B | title | 58 | 62 | 62 | ~10 GB (cap 0.85) |
| Qwen3-4B | L1 / L2 / L3 | 26 / – / – | 26 / 18.5 / 5.7 | 26 | |
| Kev-4B | title | 12.9 (1 in flight) | 13.1 (8 in flight) | 13.2 (32 in flight) | ~10.3–10.8 GB |
| Kev-4B | L1 / L2 / L3 | | 10.6 / 8.9 / 4.3 | | |
| Kev-4B | title, 4-shot | | 7.5 | | |

- **Throughput at catalogue scale.** Suppose candidate finding gives each listing 10
  cross-shop candidates within its department. Electronics is the only department with many
  cross-shop pairs: about 29k listings, so about 290k ordered pairs, or about 145k unique pairs
  scored in both orders. Kev at 13 pairs/s needs roughly **6 hours** for that one pass, and
  Qwen3-4B about 1.3 hours. Incremental runs (only new or changed listings) are far smaller.
- **Load times** (from up to healthy): about 67 s for Qwen3-4B and 16 s for Kev.
- **Kev runs without CUDA graphs** on this card, so concurrency does not raise its
  throughput.

## Recommendation for Phase E

1. **Judge: Kev-4B, title only, with the serving question (I2), behind every existing veto.**
   It is the only judge that keeps most of its recall at high precision, and the vetoes add
   recall there (test @P98: 88 of 104 with 1 false merge, against 83 with 0 for Kev alone).
   Run it offline on the 3060, store its decisions, and let the regroup read them, as the plan
   requires.
2. **Start as review-queue suggestions, not merges, in every department.**
   - The gate (lower 95% bound ≥ 0.98) is **not met and cannot be measured** on this test set.
     The best observed bound is 0.957. Passing needs at least 183 correct merges with no
     error (two-sided 95% Clopper-Pearson), or 149 (one-sided 95%), depending on how the
     plan's wording is settled.
   - Do not use the frozen P98 threshold (0.71 on raw P(yes); 0.63 with vetoes) as an
     operating point yet. It was set on a test set that is 104 same to 128 not same; a real
     top-10 shortlist is nearer 1 to 9. Precision falls as negatives grow, so re-check both
     precision and the threshold on real shortlist output, sampled and labelled, before using
     either. Until then the score orders the queue; it does not decide anything.
   - Rank suggestions by score and send rejected ones back as labelled pairs (Phase G).
3. **Candidates: today's identifier key plus a top-10 shortlist.** Take the shortlist from
   Qwen3-Embedding-0.6B (title + fields) or plain title-token Jaccard. They are statistically
   indistinguishable here. The embedding costs 2.5 minutes for the catalogue. Either beats the
   identifier key alone, which misses about a fifth of the labelled same pairs.
4. **Keep today's rules.** They are precise (P about 0.96), and their misses and Kev's are
   largely different pairs. Whether "rules OR (Kev and no veto)" beats Kev + vetoes is **not
   tested** (one combination was allowed). It is the obvious next measurement.
5. **Keep prompts simple.** Use title only and no examples. Do not use the card's web-search
   instruction. Do not feed full descriptions to Qwen3-4B. Kev with structured fields is the
   one context variant worth re-testing on a larger set.

**Caveats.**

- **Base rate.** Every precision figure here comes from a set with 104 same pairs to 128 not
  same (45% positive). A production top-10 shortlist is roughly 1 same to 9 not same. At the
  same recall and false-positive rate, precision there would be much lower. The thresholds
  (including P98 = 0.71) do not carry over and must be re-measured on real shortlist output.

- The labels come from a single agent labeller. The owner's check found no agent label to
  overturn, but that is not independent.
- The brand rule changed after labelling, so brand-only pairs are a soft spot.
- Thresholds were tuned on 224 pairs. Kev's raw P(yes) at T = 1 is not calibrated, and a
  temperature fit (`kev.calibrate`) would not change the ranking.
- The data is a snapshot, and the catalogue has moved on since.
- Outside electronics the evidence is a handful of pairs.

## What is NOT established

- **Precision at the gate**, in any department. No test set here can show a lower bound of
  0.98.
- **Recall of candidate finding on lexically dissimilar twins.** No such pairs are labelled.
- Anything about the spec-table rung (16 usable pairs), brand (3), or options (0).
- Per-department performance outside electronics (tools 8, chemicals 5 same pairs on test;
  most departments have none).
- Whether fine-tuning (Phase F) would beat Kev zero-shot. Kev's misses on obvious twins
  suggest headroom.
- How Kev behaves under other temperatures or quantisation (bf16 only; quantisation stays
  rejected), on CPU, or with CUDA graphs.
- A rules-OR-model combination, or a two-judge ensemble.
- The end-to-end effect on products (merges and splits through `make regroup-dry-run`).

## Files

- **Scripts (`ml/bakeoff/`):**
  - `catalogue.py`: dumps the catalogue from the local database.
  - `rules.py`: today's rules via makhzan_schemas.
  - `contexts.py`: the context ladder and coverage.
  - `fit.py`: per-model token budgets.
  - `embed.py`
  - `retrieval.py`
  - `judge.py`: scoring, prompt variants and throughput.
  - `evaluate.py`: the validation grid, selection, and the one test evaluation.
  - `common.py`: prompts, folds and metrics.
- **Results (`ml/out/bakeoff/`, git-ignored):**
  - `grid.json`, `frozen.json`
  - `validation.json`, `test.json`
  - `retrieval.{validation,test}.json`
  - `coverage.json`, `truncation.json`
  - `rules.json`
  - `scores/<service>/<variant>.<split>.json` (pair id → both orders)
  - `prompts/` (every instruction as sent)
  - `embed/`, `throughput/`
