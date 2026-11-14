# Local AI for product matching: plan

**Status (2026-11-13):** in progress. Phases A–C done, B in review (PR #45), D setting up, G being mocked up.
Suppliers are named by role only (see the private configuration's README).

## Goal and constraints
- **One use case at a time.** First: deciding whether two listings from different shops are the same product (grouping). Later candidates: product families (one product, many options), per-listing category for mixed shop tags (issue #44), attribute extraction.
- **Local only.** Models run on the owner's machines — a desktop with an RTX 3060 (12 GB) and several CPU-only servers. Never hosted AI APIs; never the production server. Shop content is never sold, licensed or used to train AI for anyone else (`/how-we-crawl`).
- **Validate before adopting.** Embeddings and decision models are both tested on our own labelled data; plain text similarity and today's rules are the baselines. Off-the-shelf models first; fine-tune only if they fall short. Decisions follow the measurements.
- **A model is evidence, never proof.** A model "yes" only admits a merge; every existing veto (same shop, values, form) still applies. Over-merging (a false price range) is worse than under-merging.
- **Production stays deterministic.** Models run offline; production stores their decisions and the regroup reads them, so `make regroup-dry-run` still previews every change.

## Phases
| Phase | What | State |
|---|---|---|
| A | Survey current local models (decision models, rerankers, embeddings) | Done — `model-shortlist.md` |
| B | Rules first: identifiers for every department, a family guard, grouping that respects existing products | Deployed — PR #45 and #47; regrouped on production 2026-11-13: 264 merges, 1,043 multi-shop products; on the 494 labelled pairs, precision 0.945 → 0.951 and recall 0.640 → 0.720 (PR #45's description; measured before #47's ordering fixes) |
| C | Labelled dataset: 494 pairs (validation/test), owner spot-check of 100, adjudicated test set | Done (data kept out of the repo) |
| D | Validate: Docker model serving on the RTX 3060; bake-off of candidate finding (text similarity vs embeddings) and pair judging (rules vs Qwen3-Reranker vs Kev-4B), precision/recall per department | Model serving merged (PR #49, `ml/README.md`); bake-off in progress |
| E | Integrate the winner: suggestions in the review queue first; automatic merges per department only past a precision gate (lower 95% bound ≥ 0.98 on the frozen test set) | After D |
| F | Fine-tune a small judge on our pairs — only if D shows off-the-shelf models fall short | After D |
| G | Feedback loop: a structured "Report a problem" form (button) on product pages → review queue → reviewed reports become labelled pairs (wrong-merge and missed-match) for training and testing. Unreviewed reports never feed training. | Form, `POST /reports` and review on the server (`./makhzan reports`) built; turning accepted reports into pairs not yet |

## Decisions so far
- Brand is not a hard grouping rule; the AI judge decides brand-only differences.
- Known wrong merges left for the AI judge: CH340 USB-to-RS232 vs USB-to-TTL; TB6560 3-axis board vs single-axis driver; ESP32 Micro-USB vs Type-C; MC-38 normally-open vs normally-closed.
- Labels: agent-labelled (validation) + owner-adjudicated spot-check (test). "Variant" = same product line, one option differs; variant and different both mean "don't merge".
- Matching stays within a department.

## Documents
- `research.md` — the broad research (techniques, decision models, runtimes, risks).
- `model-shortlist.md` — current models, verified against primary sources.
- `phase-b-identifier-measurement.md` — where rule-based identifiers pay off.
