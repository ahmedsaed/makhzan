# Local model shortlist for product-pair matching (makhzan)

Date: 2026-11-13. Research only. Every row below was read from the Hugging Face model card or
GitHub README unless marked. **UNVERIFIED** = no primary source read. **[est]** = my own estimate
(params x bytes), not a measurement. Dates: HF cards often give none; where so, the paper date is
used and labelled "paper".

Hardware target: RTX 3060 12 GB, 30 GB RAM, CPU-only servers. Licence must allow commercial self-hosting.

## Key findings first

1. **No model is verified on product matching.** All "decision model" accuracy numbers are the
   vendors' own, on general sets (Jev Decision Index, ticket triage, MASSIVE, XNLI). Nothing
   reports WDC Products / Abt-Buy / Amazon-Google. Same for the MTEB numbers (not product pairs).
2. **Nothing open and product-matching-specific is worth using.** HF search for "product matching" /
   "entity matching" returns only old or tiny community fine-tunes (RIOLITE/products_matching_aumet 2023,
   surazbhandari/all-MiniLM-L6-v2-ProductMatching 22M, Berketarak/Product-Matching-Classifier 0.1B,
   yleo/sdx-matching-products 2024). No licence, data or benchmark checked: treat as UNVERIFIED, skip.
3. **"Laya" and "THX-01" are real** (cards found, Apache-2.0), but **Laya zero-shot is below the
   majority-class baseline** (own card) and both are meant to be fine-tuned. THX-01's card gives no
   release date and its test sets were partly written/labelled by its teacher LLMs.
4. **Kev needs more than 12 GB as shipped** (no GGUF, no quantisation documented). Kev-4B: 8.4 GB
   weights, but card says 14.3 GB resident when serving on CUDA. Fits a 3060 only if you drop the
   serving buffers (UNVERIFIED) or run fp32/bf16 on CPU RAM (slow).
5. **Licence traps:** jina-reranker-v3, jina-embeddings-v5 = CC BY-NC 4.0 (excluded). EmbeddingGemma 1
   = Gemma terms, gated (excluded from top 3; v2 is Apache-2.0). jina-reranker-v3.5 licence: UNVERIFIED.
6. **No Qwen3.5-based Qwen embedder/reranker exists yet** (GitHub issue #192 on QwenLM/Qwen3-Embedding
   asks; text line still Qwen3, June 2025). Qwen3-Reranker/Embedding are therefore still the open
   baseline, now ~17 months old but still current.
7. Strongest general evidence for our task type: Zhang et al., arXiv 2607.24688 (2026-07-27), 1,215
   fine-tuning runs on 9 EM datasets with Qwen3 backbones: **cross-encoders consistently beat
   bi-encoders; embedding-initialised variants init better; bigger models lean on shortcuts.**
   Supports: fine-tune a small Qwen3-Reranker/Embedding as the judge rather than buy a bigger one.

## Group 1: Decision models (yes/no or choice with probabilities, one pass)

Call pattern for all: state = "A: <title> | B: <title>", question type `noul` (yes/no), instruction e.g.
"Are A and B the same product, same variant and pack size?". Output = P(yes). Score both orders (A,B)
and (B,A), take the minimum. Calibrate a temperature on owner-labelled pairs.

| Rank | Model (HF id) | Date | Size / base | Licence | Context | Memory | Runtime | Arabic | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `jaredpalmer/kev-4b` (family: kev-0.8b, kev-9b, kev-27b) | 2026-09-24 (card) | 4B; LoRA r16 (33.8M) + pointer head on frozen Qwen3.5-4B-Base | Apache-2.0 | validated 8,192; serves 65,536 state | bf16 weights 8.4 GB; **14.3 GB resident when serving** (card); fp32 CPU ~17 GB [est]; 0.8B fits any 4 GB GPU | Own `kev.serve` (`/v1/systemone`), CUDA bf16, MLX, CPU. **No GGUF/llama.cpp/ONNX documented.** Hub tree lists 14 quantised derivatives (unexamined) | No: card says English only | Self-reported: breadth-v1 0.690 (Jev 0.757), transfer-v4 0.838, hard-v1 0.803; ECE 0.017-0.101; MMLU-Pro 0.565 vs Jev 0.840. Nothing on matching |
| 2 | `convaiinnovations/laya-multilingual` (English: `convaiinnovations/laya`) | Sept 2026 (HF listing Sep 19-20; card undated) | 322M: mmBERT-base 307M + decision head; English one 421M ModernBERT-large | Apache-2.0 | 1,024 (8,192 with `max_len`) | ~0.7 GB fp16 [est]; GGUF Q8_0 449 MB / BF16 844 MB (English, `ggml-org/Laya-GGUF`) | `laya` pip pkg (`laya.load`), ONNX exports (community), llama.cpp `/v1/systemone` (ggml-org GGUF) | Yes, but weak: MASSIVE Arabic 0.110 -> 0.400 macro acc | **Zero-shot typed-decisions 0.342 < majority baseline 0.461; needs fine-tuning.** XNLI en 0.843, other-14 0.731. `noul` can under-report true. ECE 0.314 -> 0.106 with per-question temperature |
| 3 | `doofz/THX-01` | Oct 2026 (blog "Oct 10"; card undated) | 322M: mmBERT-base 307M + 15M head | Apache-2.0 | 1,024 per question | ~0.7 GB fp16 [est] | `pip install thx01`, REST `thx01.server`; not Ollama | 18 post-trained languages incl. Arabic; encoder 100+ | Self-reported: 39-task suite mean acc 58.3 -> 84.2; tickets 98.4, ECE 0.003. Test sets partly made by teacher LLMs; public-set train splits included. Nothing on matching |
| (runner-up) | `vllm-sr/d3-mini` (d3-lite 0.85B, d3-nano 2.2B, d3-flash 8.4B, d3 27B) | 2026-10-12 (article) | 4.54B incl. 0.33B vision; Qwen3.5-4B | Apache-2.0 | not stated | 14.8 GiB peak AutoModel (MI325X) | transformers 5.17 + `trust_remote_code`, vLLM engine mode (dev) | not stated | Team's own Jev index 54.9 (d3-mini), 57.8 (d3-flash). Bigger than Kev-4B memory-wise |
| (note) | `shisa-ai/shisa-de-2` (26B-A4B, Gemma 4 base, Apache-2.0, 2026-10-09) | | 25.2B total / 3.8B active | | | FP8 quant exists; too big for 12 GB VRAM | vLLM | English + Japanese | Own Decision Index 59.0 | Skip |
| (note) | Cloudflare Clef / Clef-flash (27B / 9B, Apache-2.0 per search snippet) | 2026-10-01 | | | | | | | UNVERIFIED: the marktechpost page returned 403, no card read |

Notes
- Fine-tuning path (recommended by evidence, not by any vendor number): Kev ships `kev.train --init_from
  jaredpalmer/kev-4b` with JSONL labelled questions (their card: init from the checkpoint, not the base).
  Laya/THX-01 are encoders: cheap to fine-tune, ~10 ms/question on GPU (vendors' T4 / own figures).
- Honest ranking logic: Kev-4B is the only one with a usable zero-shot claim, but the model is
  4B and English-only; Laya/THX are cheap CPU-friendly bases that must be trained. If you are going to
  fine-tune anyway, a Group 2 reranker is the better-supported starting point (it is already a pair judge).
- Kev's `noul` returns calibrated P(yes) with T = 2.41 by default; `KEV_TEMPERATURE=1.0` for raw.
  `python -m kev.calibrate` refits on your labels (card).

## Group 2: Rerankers / cross-encoders as pair judges

Call: pair = (listing A as "query", listing B as "document"). Qwen3 rerankers take an `<Instruct>`
line, so tell it the task. Symmetrise with both orders.

| Rank | Model (HF id) | Date | Size | Licence | Context | Memory | Runtime | Arabic | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `Qwen/Qwen3-Reranker-4B` | paper 2025-06-05 (card undated) | 4B (BF16) | Apache-2.0 | 32k | fp16 ~8 GB [est]; 4-bit ~2.5-3 GB [est]; fits 3060 | transformers >=4.51, vLLM >=0.8.5, sentence-transformers `CrossEncoder` | 100+ languages | MTEB-R 69.76, MMTEB-R 72.74, FollowIR 14.84 (self-reported, top-100 from Qwen3-Embedding-0.6B) |
| 2 | `Qwen/Qwen3-Reranker-0.6B` (also `-8B`) | same | 0.6B | Apache-2.0 | 32k | fp16 ~1.2 GB [est]; trivial on CPU | same | 100+ | MTEB-R 65.80, MMTEB-R 66.36; 8B: 69.02 / 72.94 (not better than 4B on English) |
| 3 | `BAAI/bge-reranker-v2-m3` | papers 2023-12 / 2024-02 | 0.6B (XLM-R/bge-m3 base) | Apache-2.0 | card max_length 512 | fp16 ~1.2 GB [est] | sentence-transformers `CrossEncoder`, FlagEmbedding, transformers | Multilingual (bge-m3 base) | No numbers in text (charts only); older, but sigmoid score in [0,1] is easiest to threshold |
| alt | `mixedbread-ai/mxbai-rerank-base-v2` (0.5B) / `-large-v2` (2B) | paper 2025-06-04 | 0.5B / 2B, qwen2-tagged | Apache-2.0 | not stated | fp16 1-4 GB [est] | sentence-transformers `CrossEncoder`, `mxbai-rerank` pkg | 100+ tags, but multilingual score 28.6/29.8 (weak) | BEIR 55.6 / 57.5 (self-reported) |
| excluded | `jinaai/jina-reranker-v3` (0.6B, 131k, BEIR 61.94, MIRACL 66.83) | paper 2025-09-29 | 0.6B | **CC BY-NC 4.0** | | | | | Licence blocks commercial use. v3.5 (2026-08-03 post) licence UNVERIFIED |

Notes
- Qwen3-Reranker-0.6B vs 4B: the 4B gains ~4 MTEB-R points but costs ~7x compute. On CPU servers
  use 0.6B (fine-tuned); on the 3060 use 4B zero-shot for labelling/triage.
- Score = softmax(P("yes"), P("no")) at the final token, i.e. it is a decision model in all but name.
- **I found no 2026 open reranker that tops reranking leaderboards.** Searches returned only blogs.
  A "Cohere Rerank v3.5 open Apache" claim from an OpenRouter snippet is implausible and UNVERIFIED.
  Treat Qwen3-Reranker as still current. Check the MTEB leaderboard directly before committing.
- ModernBERT/mmBERT rerankers: no ready-made open pair-judge found; use them as fine-tuning bases
  (that is what Laya/THX-01 effectively are).
- None of these has product-matching numbers. Typed corner cases (30 vs 38 pin, 1 kg vs 250 g) need
  your own test set. For reference, general LLMs are weak here: fine-tuned Llama-3.1-8B scored 69 F1
  and GPT-4o 87 on WDC Products (arXiv 2409.08185, from the prior report, not re-read).

## Group 3: Embeddings for candidate retrieval

Use symmetric task prompts where offered (title vs title is not query-vs-document). Recall tool only.

| Rank | Model (HF id) | Date | Size | Licence | Context / dims | Memory | Runtime | Arabic | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `Qwen/Qwen3-Embedding-0.6B` (also 4B, 8B) | paper 2025-06-05 | 0.6B | Apache-2.0 | 32k / up to 1024 (32-1024 MRL) | fp16 ~1.2 GB [est]; CPU fine | sentence-transformers (`prompt_name="query"`), transformers; GGUF not confirmed | 100+ languages | MTEB multilingual 64.33, English v2 70.70 (self-reported). 4B: 69.45 / 74.60, dims up to 2560 |
| 2 | `google/embeddinggemma-2` (text-only: set `vision_config=None, audio_config=None`) | ~2026-10-06 (press; card says paper 18 days old) | text part 270M (full 740M with vision/audio) | **Apache-2.0** (v1 was Gemma terms, gated) | 8,192 / 768 (MRL 512/256/128) | BF16 or fp32 only, **no fp16** | sentence-transformers, transformers, TEI; GGUF not mentioned | 100+ per press (card does not list) | MTEB multilingual v2 61.36, English v2 68.46. Prompts: `task: sentence similarity \| query: ...` or `task: classification \| query: ...` |
| 3 | `ibm-granite/granite-embedding-311m-multilingual-r2` | 2026-04-29 | 311M (ModernBERT-style) | Apache-2.0 | 32,768 / 768 (MRL to 128) | ~0.6 GB fp16 [est] | sentence-transformers incl. ONNX + OpenVINO INT8, llama.cpp convertible (not Ollama) | Arabic among 52 enhanced languages | MTEB multilingual retrieval 65.2 (card also shows 63.9 in MRL table: inconsistent) |
| alt | `microsoft/harrier-oss-v1-270m` (0.6B, 27B siblings) | 2026 (undated card) | 270M, 640 dims | **MIT** | 32,768 | small | sentence-transformers, transformers, TEI | 94 languages incl. Arabic | MTEB v2 multilingual 66.5 (0.6B: 69.0). Best small number I verified. Needs `Instruct: {task}\nQuery: {q}` on the query side |
| alt | `BAAI/bge-m3` | paper 2024-02-05 | ~568M | MIT | 8,192 / 1024 | ~1.1 GB fp16 [est] | FlagEmbedding (dense+sparse+ColBERT), sentence-transformers | 100+ | Mature; sparse lexical output helps part numbers (HC-SR04) |
| alt | `nomic-ai/nomic-embed-text-v2-moe` | paper 2025-02-11 | 475M (305M active) | Apache-2.0 | **512** / 768 | ~1 GB [est] | sentence-transformers | ~100 | BEIR 52.86, MIRACL 65.80 |
| alt | `Snowflake/snowflake-arctic-embed-l-v2.0` | paper arXiv 2412.04506 | not read | Apache-2.0 | not read | | sentence-transformers, ONNX | 74 languages | numbers not read: UNVERIFIED |
| excluded | `jinaai/jina-embeddings-v5-text-small / nano` (677M / 239M, 2026-02-18) | | | **CC BY-NC 4.0** | | | | | non-commercial |
| UNVERIFIED | Octen-Embedding-8B (Qwen3-8B derived, "Apache"), mentioned only by an aggregator | | | | | | | | no card read |

Notes
- **E-commerce evidence is thin.** No source I found ranks any of these on product titles or ESCI.
  Closest: an AIMultiple Amazon-reviews ASIN-match test (Dec 2025) found bge-m3 behind smaller
  models with higher latency (snippet only; not independently read). Test recall@k on your own
  labelled pairs.
- MTEB numbers are across different leaderboard versions and mostly self-reported: compare only
  within one version. Harrier 66.5 vs Qwen3-0.6B 64.33 vs EmbeddingGemma-2 61.36 are all "v2 multilingual"
  per their cards, but task means differ by who ran them.
- For short titles with part numbers, pair a dense model with lexical matching (bge-m3 sparse, or Meilisearch):
  dense models blur "38 pin" vs "30 pin" by design.
- Cheapest strong default for CPU servers: Qwen3-Embedding-0.6B or granite-311m (int8 ONNX/OpenVINO).

## Recommended pick per group (given 3060 12 GB + CPU servers)

1. Decision: **Kev-4B** for zero-shot triage and label pre-screening (English-only, memory tight on 12 GB);
   for a trained production judge prefer Group 2 or a fine-tuned Laya-multilingual/THX-01.
2. Reranker: **Qwen3-Reranker-4B** on the 3060 for triage and gold-set labelling; **Qwen3-Reranker-0.6B
   fine-tuned** as the CPU batch judge.
3. Embedding: **Qwen3-Embedding-0.6B** (Apache, Arabic, 32k, sentence-transformers); try Harrier-270M (MIT)
   and EmbeddingGemma-2 as bake-off entries.

## Sources (accessed 2026-11-13)

Decision models
- Kev-4B card https://huggingface.co/jaredpalmer/kev-4b ; repo https://github.com/jaredpalmer/kev
- Laya multilingual https://huggingface.co/convaiinnovations/laya-multilingual ; GGUF https://huggingface.co/ggml-org/Laya-GGUF ;
  HF search listing https://huggingface.co/models?search=laya&sort=trending ; secondary https://aiweekly.co/node/13777
- THX-01 https://huggingface.co/doofz/thx-01
- vllm-sr d3-mini https://huggingface.co/vllm-sr/d3-mini ; summary article https://ccleaks.com/news/decision-3-0-open-weights-oct-2026 (low-trust outlet)
- Shisa DE-2 https://blog.shisa.ai/posts/shisa-de-2/
- Clef (not read, 403) https://www.marktechpost.com/2026/10/01/cloudflare-releases-clef-and-clef-flash/
- Landscape (secondary) https://runware.ai/blog/jev-laya-and-the-emerging-role-of-decision-models ; https://www.respan.ai/articles/jev-alternatives
Rerankers
- https://huggingface.co/Qwen/Qwen3-Reranker-4B ; paper arXiv 2506.05176
- https://huggingface.co/BAAI/bge-reranker-v2-m3
- https://huggingface.co/mixedbread-ai/mxbai-rerank-base-v2 ; https://huggingface.co/mixedbread-ai/mxbai-rerank-large-v2
- https://huggingface.co/jinaai/jina-reranker-v3 (CC BY-NC 4.0)
Embeddings
- https://huggingface.co/Qwen/Qwen3-Embedding-0.6B ; https://huggingface.co/Qwen/Qwen3-Embedding-4B
- https://huggingface.co/google/embeddinggemma-2 ; v1 https://huggingface.co/google/embeddinggemma-300m ; press https://aiweekly.co/alerts/google-ships-embeddinggemma-2-740m-multimodal-embedder-apache-20
- https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2
- https://huggingface.co/microsoft/harrier-oss-v1-270m
- https://huggingface.co/BAAI/bge-m3 ; https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe ; https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0
- jina v5 licence (search snippet) https://huggingface.co/jinaai/jina-embeddings-v5-text-small
- Qwen embedding successor issue https://github.com/QwenLM/Qwen3-Embedding/issues/192 (snippet only)
Entity matching evidence
- Zhang et al. https://www.alphaxiv.org/abs/2607.24688 (2026-07-27)
- Steiner & Bizer https://arxiv.org/abs/2606.28823 (2026-06-27, rev. 2026-10-05): LLM-labelled training data gives PLM students near benchmark-trained quality
- Fine-tuning LLMs for EM https://arxiv.org/abs/2409.08185 ; WDC Products https://arxiv.org/abs/2301.09521
- HF searches (product / entity matching): https://huggingface.co/models?search=product%20matching&sort=downloads
