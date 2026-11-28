# AI matching: decision review (2026-11-16, updated 2026-11-19)

Every design decision in the AI matching work so far, who made it, what rests on
it, and what the owner needs to decide. Written after the owner found that the
judges had been prompted with one generic sentence that carried none of the
labelling rules. That one unreviewed choice touches most results below, so they
are marked **confounded** where it applies.

"Owner" = decided by the owner. "Session" = chosen by Claude or an agent and not
put to the owner. Results that rest on a session choice are not settled.

## Labelling rules in force (summary)

The full text, with examples, is in the private configuration's `labels/README.md`
(versioned with the labels, never only in a session's scratch folder or the public
repo). Labels are same / different / variant / unsure; for matching,
variant and different both count as not same, and unsure is excluded.

1. **Brands:** a different brand alone never makes a different product.
2. **Silence:** a detail only one listing states is compatible; only a stated
   contradiction separates two listings.
3. **What "same" means:** a buyer could take either as the identical part.
   Drop-in revisions are the same (IRF630 / IRF630N); a suffix that changes
   package, pinout, rating or function is different (ATmega328 / 328P); stated
   contradictions (NC/NO, module vs bare IC, size, rating, pins, connector) and
   different chip families (CD4011 / 7400) are different.
4. **Size tolerance:** measurements within about 5% are the same.
5. **Implied package:** a bare standard part number implies its standard
   package (1N4007 vs the SMD M7 are different).
6. **Bundles:** "with" another component (an I2C adapter, a cable, a case) is
   different; a gray zone, so a wrong merge there is a soft error.
7. **Confirmed calls:** 7476 = 74LS76 (no family named); BZX55 = BZX79 (drop-in).
8. **Pack size:** a different stated pack size is different; an unstated one is
   compatible.

## 1. What the judges actually saw

Every judge result since the bake-off (Kev, pplx, Qwen3.5, the context test)
used this request. Nothing else was sent: no instructions, no rules, no examples.

```json
{
  "state": "Listing A: Ceramic Capacitor 33pF 50V\nListing B: Ceramic Capacitor 33pF 50v",
  "questions": {"same": {"type": "noul",
    "instructions": "Are listing A and listing B the same product: the same item, the same variant and the same pack size?"}}
}
```

**Correction (2026-11-17).** "Nothing else was sent" is wrong for one run. On
2026-11-14 the Phase E bake-off (`ml/models/judge.py --judge kev-rules`) scored
Kev-4B on the 900 Phase E pairs (answer key v1), titles only, both orders (1,800
requests), with I2 plus a list of rules a session wrote from the error classes
it had found in those same labelled pairs (`RULES_QUESTION`):

```text
... They are different products if they differ in package or package suffix (e.g.
TO-220 vs TO-247, SMD vs through-hole, IRF vs IRFP), NC vs NO, standard vs
long/short versions, module/board vs bare IC, a model-number digit or suffix that
denotes a different chip (MPU-6050 vs MPU-6500), or a stated range/rating; the same
part number written differently (74HC164 vs 74164 only if the family matches;
TEC1-12706 vs TEC-12706) is the same product.
```

Those rules were never put to the owner. They carry none of the silence, brand
or drop-in rulings, and "74HC164 vs 74164 only if the family matches" contradicts
ruling 7 (7476 = 74LS76). Results (`ml/out/models/results.json`): alone at 0.9,
218 accepted with 6 errors (Kev with I2: 215 and 3); at its best in-sample
threshold, 0.975, 92 accepted with 0 errors (I2: 90 and 0); held out, 115 with 1
error (I2: 112 and 1). As a second judge beside I2 Kev it did no better than
pplx (in-sample 165 accepted with 0 errors, held out 192 with 2; pplx: 176 with
0, held out 192 with 2). It lowered the KSD301 NC/NO and MPU-6500/6050 scores
(0.91 to 0.29, 0.85 to 0.16), but those are among the pairs its rules were
written from, so that is in-sample. It was not carried forward: pplx became the
second judge (D13), and the context test went back to I2 alone. Nothing below
rested on it, and no decision changes. The rest of this section stands: every
other judge result in it used I2 with no rules.

With "full context" the same two lines carried each listing's text as one blob:

```text
Listing A: Ceramic Capacitor 33pF 50V
Category: Capacitors | Price: 0.5 EGP
Specs: Pitch: 5mm; Package: Through Hole; Tolerance: ±10%; ...
Description: Ceramic Capacitor 33pF 50V A compact 33pF, 50 VDC multi-layer ...
Listing B: Ceramic Capacitor 33pF 50v
Category: Capacitors | Price: 0.5 EGP
Description: Stable, Low Cost Ceramic Capacitor , Accuracy: ?20% , ...
```

What is wrong with it, all session choices:

- **None of the owner's rulings are in it.** Brand alone doesn't matter, silence
  is compatible, drop-in revisions are the same: the judges were never told.
  "The same variant" invites the model to apply its own idea of a variant.
- **Missing fields are invisible.** A field a listing lacks is simply left out,
  so one listing with specs and one without looks like a difference.
- **Price is included**, though price is not evidence of identity (CLAUDE.md).
  In the context test one pair of identical LEDs differed only by price
  (1 vs 0.5 EGP) and pplx's score fell from passing to 0.31.
- **Shop boilerplate is passed as a "description"** (e.g. "stocked at ... in
  Cairo with shipping to every governorate"), against the other shop's datasheet.
- **The two listings run together** in one string, with no field labels.

### What the bake-off tested (it was not nothing)

The bake-off's prompt grid (`ml/bakeoff/common.py`) had four instructions,
fixed before scoring. The richest, I4, stated the then-current Phase C policy:

```text
Are listing A and listing B the same product, so that a buyer could buy either and
receive the same item? Listings from the same product line that differ in one option
(colour, size, length, capacity, rating or value) are NOT the same product; neither are
a different model, a different package, a different pack size or bundle, or a part
versus a module or accessory. Differences only in wording, word order or spelling do
not matter.
```

None beat the one-sentence I2 beyond noise, so the pre-declared "simplest
within noise" rule chose I2. But I4 predates the owner's rulings (it has no
silence, brand or drop-in rule and nothing on missing fields), was tested on the
Phase C pairs (mostly titles, few descriptions), and **I2 then carried into every
later experiment unreviewed** after the rulings changed what "same" means. That
is the decision that should have come back to the owner.

## 2. Decision register

| # | Area | Decision | Who | Rests on it | Status |
|---|---|---|---|---|---|
| D1 | Scope | Local models only; one use case (cross-shop matching); validate before adopting | Owner | everything | settled |
| D2 | Scope | Electronics only for the gate; other departments suggestions-only until more shops | Owner | gate, pipeline | settled |
| D3 | Labels | same / different / variant / unsure; variant and different both count as not same; unsure excluded | Session (Phase C), accepted | all metrics | **confirm** |
| D4 | Labels | Rulings: brand alone doesn't matter; silence compatible; drop-in revisions same; stated contradiction different; families differ | Owner | all labels | settled |
| D5 | Labels | Final label: owner's answer, except 9 part-number cases deferred to ruling 3; else Opus+Sonnet consensus; else Sonnet | Session | all phase E metrics | **confirm** |
| D6 | Labels | Opus+Sonnet consensus trusted where they agree (matched the owner ~94% on general-spec pairs) | Session, owner agreed in practice | 103 review pairs | confirm |
| D7 | Prompt | Judge question = I2, one sentence, no rules (one exception, the kev-rules run: see the correction in section 1) | Session (bake-off rule, then carried) | model choice, thresholds, context verdict, gain | **confounded, reopen** |
| D8 | Prompt | Listing injection: `Listing A: …\nListing B: …`, unlabelled, missing fields omitted | Session | all judge results | **reopen** |
| D9 | Context | Full context = title + category/brand/part number/price + specs + description, price included, boilerplate kept | Session | context verdict ("titles only") | **confounded, reopen** |
| D10 | Scoring | Each pair scored A→B and B→A; the lower score counts | Session | thresholds | confirm |
| D11 | Scoring | Kev: raw P(yes). pplx: P(true) at the checkpoint's own temperature | Session | thresholds | confirm |
| D12 | Models | Kev-4B best; rerankers, Qwen3.5-4B, pplx alone worse | Session-run bake-offs | judge choice | **confounded** (all prompted with I2-style text) |
| D13 | Models | pplx kept as second judge | Owner | pipeline | settled, may change after re-test |
| D14 | Rule | Merge if Kev ≥ 0.9 AND pplx ≥ 0.5 | Session thresholds, owner approved | gain, pipeline | **re-derive after prompt work** |
| D15 | Gate | One-sided 95% CP ≥ 0.98, then dropped for option B (auto-merge with safety nets) | Owner | rollout | settled |
| D16 | Candidates | Identifier key + top-10 title-token Jaccard, other shops, within one department | Session (bake-off recommendation) | recall, bearings case | **confirm** |
| D17 | Pre-filter | ~~Today's vetoes for rules; relaxed price/form vetoes only in front of the AI~~ Superseded by P13 (2026-11-17): today's vetoes for merges *and* for AI candidates; the relaxed set is parked | Owner | AI candidates | superseded |
| D18 | Group check | Complete-link; one best match per other shop; Kev < 0.05 inside a group blocks it | Session, concept approved | gain (2,336 merges) | confirm thresholds |
| D19 | Sampling | 900 pairs: 400 Kev-positive, 120 borderline, 120 confident-no, 260 veto strata, inclusion-weighted | Session | precision estimates | confirm |
| D20 | Quantisation | Rejected unless proven harmless. Amended 2026-11-26: Kev-4B Q4_K_M and pplx-decider-flash-v1.3 Q4_K_S (llama.cpp) accepted on the label test (see "Kev quantisation" and "pplx quantisation" below) | Owner | serving | settled |
| D24 | Serving | Production switch 2026-11-27: both judges served by llama.cpp (Kev-4B Q4_K_M, pplx Q4_K_S) on the home server's AMD card, taking turns (Kev 01:00–05:00, pplx 05:05–07:00), the card held to clock states 0–2; the judge-version catch-up drained by the owner (see "Production switch" below) | Owner | serving | settled |
| D25 | Models | First judge: H2O-Lightning-4B Q4_K_M (llama.cpp) replaces Kev, at 0.578 on its raw scale; pplx Q4_K_S ≥ 0.95 stays second, same K2 payload; policy p2. Its group-check floor (P14's role) is 0.19, proposed by the session and confirmed by the owner, 2026-11-27 (see "H2O first" below) | Owner | pipeline, group check, audit | settled |
| D26 | Serving | A llama.cpp judge is the GGUF (sha256), the llama.cpp build (b12767) and the temperature. Any official image of that build (Vulkan, CUDA, CPU) serves the same judge; the serving image is recorded with every score (`extra.serving`), as device and dtype are (P8). The image digest in the version strings stays as a historical label, byte-identical, so nothing re-scores. Owner, 2026-11-28 (see "The backend is not the judge" below) | Owner | worker, desktop backlog | settled |
| D21 | Serving | Workers on CPU servers (the CPU worker 03:00–06:00, 6 threads, Kev phase then pplx phase, no mmap, 20 GB); desktop for backlogs. Refined 2026-11-17 (§6, Global, P9, P10): one worker per model if wanted, each worker's own config sets its window, threads and models; no broker rule against two models on one machine | Owner | pipeline | settled |
| D22 | Data | Labels kept in git-ignored `ml/out/labels/`; now in the private configuration's `labels/` (versioned) | Owner rule, after loss | — | settled |
| D23 | Benchmark | CPU benchmark of the chosen setup (`ml/models/bench_cpu.py`): 60 pairs drawn (`N_PAIRS`); CPU/GPU parity holds when every request is within 0.05 (`--tolerance`) and no pair flips at its threshold | Session | the CPU-worker parity verdict | **owner review** (measurement parameters, not merge rules) |

### What still holds, whatever the prompt

- Candidate finding: title similarity and embeddings both keep ~96–99% of true
  matches in a listing's top 10 (no prompt involved).
- Vetoes: values and multiple are reliable; price and form leak (measured on
  labels, not on prompts).
- Labels: the 900 phase E labels and the owner's answers.
- Serving facts: CPU throughput, memory, windows.
- RPM fix (shipped): independent of the AI work.

### What must be re-measured once the prompt is designed

D7–D9, D12 and D14: which judge is best, which threshold, whether context
helps, and therefore the gain figure (1,048 → 2,885 multi-shop products) and
the 2,336 proposed merges.

## 3. Proposed prompt design (options for the owner)

### 3a. Structure

```text
[INSTRUCTIONS]
You compare two product listings from different Egyptian electronics shops and
decide whether a buyer could take either one and receive the identical part.

How to compare:
1. Identify what each listing is: product type, model or part number, form
   (bare chip, module, board, kit, cable, accessory) and pack size.
2. Compare only what both listings state. A field that one listing does not
   state is unknown, not different.
3. They are the same product unless a stated fact contradicts.

Same product:
- The same part, even if the brands differ or one listing names no brand.
- Drop-in revisions in the same package and pinout (IRF630 / IRF630N).
- The same model from a different factory or origin, unless a rating differs.
- Different wording, order, spelling or language.

Different product (only when stated):
- A different value or rating: capacitance, resistance, voltage, current,
  power, temperature, speed, size, length, pin count.
- NC vs NO; module vs bare IC; a different package (TO-220 vs TO-247, SMD vs
  through-hole); a different chip in the same family (MPU-6050 vs MPU-6500);
  a different logic family (74LS vs 74HC).
- A different pack size (a 10-pack vs one).
- One listing is an accessory or part for the other.

Ignore price, shop name, stock, and marketing text.

[LISTING A]
Title: Ceramic Capacitor 33pF 50V
Category: Capacitors
Brand: not stated
Part number: not stated
Pack size: not stated (1)
Specifications: Capacitance 33 pF; Rated voltage 50 VDC; Tolerance ±10%; ...
Description: (shown | omitted, see 3c)

[LISTING B]
Title: Ceramic Capacitor 33pF 50v
Category: Capacitors
Brand: not stated
...

[QUESTION]
Could a buyer take listing A and listing B as the identical part?
```

### 3b. Where it goes, per model

Decision models (Kev, pplx) take a `state` (the facts) and short `instructions`
(the question). Two ways to fit the design:

- **Option K1:** rules and both listings in `state`; the question in
  `instructions`.
- **Option K2:** rules in `instructions` (as JSON, which Kev renders as
  labelled text), listings in `state`.

An instruction model (Qwen3.5-4B) takes it naturally as a system prompt plus
user turn, scored by P(yes). It lost the bake-off under I2; it should be
re-tested with this prompt, since a full instruction model may use rules better
than a decision model.

### 3c. Decisions for the owner

1. **The rules text** above: wording, anything to add or remove.
2. **Fields injected:** title, category, brand, part number, pack size, specs;
   **price excluded** (recommended). Description: include, include only when
   short, or exclude (recommended: exclude for now; most of it is boilerplate).
3. **Missing fields:** written as "not stated" (recommended) or omitted.
4. **Placement for Kev and pplx:** K1 or K2 (recommended: test both, it's cheap).
5. **Models to re-test:** Kev, pplx, Qwen3.5-4B (recommended), others.
6. **Experiment protocol:** all on the 900 labelled pairs, both reading orders,
   fixed rule first (Kev ≥ 0.9 AND pplx ≥ 0.5) then thresholds re-derived on a
   2-fold split; report precision, recall, the error pairs, and cost per pair.
7. **What to reopen afterwards:** D14 thresholds, D12 judge choice, the gain
   figure and the 2,336 merges, the CPU-window sizing (longer prompts are slower).

Nothing runs until these are decided.

## 4. Owner decisions (2026-11-16)

Prompt and context (section 3):

- **Rules text:** the draft in 3a, as written for now; optimise later.
- **Fields:** product information only. **Price excluded.** Description included,
  with the instruction to ignore marketing text.
- **Missing fields:** written as "not stated".
- **Placement for Kev and pplx:** test both K1 (rules in the state) and K2
  (rules in the instructions). Both models' docs favour K1.
- **Answer definitions:** use the models' `criteria` feature (what "true" and
  "false" mean), as a variant.
- **Description length:** test both full and capped (~150 words). Kev was
  trained mostly on states of at most 384 tokens.
- **Models:** re-test Kev, pplx and Qwen3.5-4B.
- **Protocol:** the 900 labelled pairs, both reading orders, the fixed rule
  first, then thresholds re-derived on a held-out split. Final comparisons run
  one request per call (pplx is bit-stable only that way); record the noise.

Register:

- D3 kept (variant = not same); variant experiments later.
- D5 kept; Opus re-labelled the 740 non-owner pairs under the rulings with
  descriptions and specs (39 labels, 5%, changed), and a Sonnet second pass
  under the same rules checks it; disagreements are re-judged.
- D6, D10, D18, D19 kept.
- D11 kept, verified against the docs: both models say to set thresholds on
  your own data. pplx's served temperature is 1.3303 (v1.3); Kev runs raw
  (`KEV_TEMPERATURE=1.0`), calibrated default 2.41.
- D16 kept; cross-department candidates (e.g. bearings) later.

New labelling rules (also in the labels' README: then `ml/out/labels/README.md`, now the private configuration's `labels/README.md`):

4. Sizes within about 5% are the same (rounding or typos).
5. A bare standard part number implies its standard package (1N4007 vs the SMD
   "M7"; 1N5819 vs SS14 are different).
6. Bundles ("with" another component: an I2C adapter, a cable, a case) are
   different; a gray zone, so a wrong merge here is a soft error.
7. Confirmed: 7476 = 74LS76 (no family named), BZX55 = BZX79 (drop-in).
8. Pack size ("A for now"): a different *stated* pack size is different; an
   unstated pack size is compatible. Later (B): pack size never separates, once
   product pages show pack size and price per unit.

Buyers verify on the shop's own page before buying, which is why rare
gray-zone merges are tolerable under option B.

## 5. Results and the judge setup (owner, 2026-11-16)

The prompt grid (14 configurations, the rules-based prompt, 900 pairs scored on
answer key v2, both orders, one request per call, bit-identical repeats) and
the offline combination analysis (`ml/out/prompt-grid/`):

- The rules roughly double Kev's recall at the same precision (title-only 29%
  vs K1-capped 60%, ~94.5% precision each, without vetoes).
- `criteria` lowered precision (86%); pplx with the rules accepts almost
  everything at 0.5 and is only useful at ≥ 0.95.
- Each judge does best with its own layout: Kev K2, pplx K1.
- New prompts fixed KSD301 NC/NO, IRF250/IRFP250, MPU-6500/6050 and the 33 pF
  pair; ATmega328 vs 328P regressed (every model now calls it the same).

Owner decisions:

- **Operating point "safest":** merge when Kev (K2, description capped at 150
  words) ≥ 0.8 **and** pplx (K1, full description) ≥ 0.95, behind today's
  vetoes. In-sample: 209 accepted, 0 errors; held-out halves 100% / 100%;
  about 6,800 estimated matches. For comparison, the earlier title-only plan
  (Kev ≥ 0.9 AND pplx ≥ 0.5 on titles, measured on answer key v1) was
  estimated at about 5,100; on key v2 the title-only Kev baseline alone is
  about 5,400.
- **No two-stage screening.** Review in a few weeks whether the CPU worker keeps
  up with the full prompt.
- **Report-driven overrides** (never-merge / must-merge pairs keyed by listing
  id, honoured by the regroup) are the safety net for regressions such as
  ATmega328/328P.
- CPU-worker benchmark of the chosen setup: prepared on the desktop while the
  server is down for maintenance; run when it is back.

## 6. Owner decisions on the production pipeline (2026-11-17)

**Owner decisions**, made on the production pipeline design (v1, kept with the
labels outside the repository). The owner's decisions win wherever they differ
from the design. They are numbered **P1–P17** here and in the code, after the
design's own D1–D17, so they are not confused with this register's D-numbers.
The contract built on them is `docs/ai/broker-api.md`; the shared code is
`packages/schemas/makhzan_schemas/ai/`.

Global:

- **No broker rule against two models on one machine.** No host slots and no
  host groups. Each worker's configuration decides what it runs and when:
  model, windows, threads, memory, batch and lease size, device (cpu or gpu),
  `on_empty` (exit or wait), broker URL and token. The broker treats every
  worker the same.
- **Keep it simple.** No tiers, timeouts or optimisations the owner has not
  asked for.
- **Extensible by design** (owner requirement, relayed the same day). The
  architecture must not hard-code today's two paths. Pipelines are declared as
  data (`ai/pipelines.py`: named, ordered stages of model + prompt variant +
  threshold key, one transition rule); tables store pipeline, stage and model
  as strings validated against that registry, never as database enums;
  triggers are separate producers that enqueue pairs into a named pipeline;
  the broker's result handling is one generic function; workers are generic
  per model key. A new model or pipeline is a registry change, with no
  migration and no broker or worker change.

Decisions:

| # | Decision | Status |
|---|---|---|
| P1 | K = 10 candidates per listing, one-directional for the daily run, mutual for the backlog. Revisit after 4 weeks of measured survival and pass rates. | approved |
| P2 | The broker is a separate service built from the API image, with its own app object and its own reverse-proxy hostname, never under the public `/api` rewrite. **Changed by the owner the same day: no hostname; reached only over Tailscale by IP and port** (below). | owner |
| P3 | One bearer token per worker, stored as sha256 in `ai_workers`, issued and revoked by `./makhzan ai worker`. An address allowlist at the proxy is optional. | approved |
| P4 | ~~Shadow mode first.~~ **Changed by the owner the same day: no shadow mode.** The mode is `off` or `live` only, `off` by default; there is no per-decision shadow flag. The backlog run's decisions are reviewed locally: the owner reviews the resulting groupings on a local copy (`make regroup-dry-run ARGS=--ai`, which reads standing decisions while off), including the 20 fresh examples (none from the 900 labelled pairs; proposed mix, a parameter: 10 at random, 5 near a threshold, 5 sharing no identifier), and only then are they pushed to production and the mode set `live`. | owner |
| P5 | A content hash per listing over every field that can reach a prompt: title (both languages), brand, part number, category, specs, description. Never price. A changed hash, or a new model or prompt version, triggers a re-score. The hash is stored with each score. | owner |
| P6 | A decision stays in effect until it is re-scored; no timeout. A re-score that is expected but does not complete is flagged in status and handled by hand. | owner |
| P7 | Named policy versions in code (`POLICIES`, `ACTIVE`); a change goes through a PR. `./makhzan ai redecide --dry-run` recomputes from stored scores. | approved |
| P8 | Separate model version (weights revision, code commit, scoring parameters) and prompt version (layout, cap, a hash of the rules and the renderer). GPU and CPU are the same version, device and dtype recorded on each row. On a version change, re-score standing "same" decisions first and keep old decisions until each is re-scored. | approved |
| P9 | pplx against the Kev backlog: settled through worker configuration only, with no broker arbitration. | owner |
| P10 | Fixed windows set in each worker's config. During a long backlog the owner starts a GPU worker on the desktop; it connects to the broker and drains the queue. | approved |
| P11 | Always score both reading orders. No skipping. | owner |
| P12 | Record a Kev score for every pair the rules merged, and list the counts below 0.8 and below 0.05. No threshold is chosen yet (tracked in the private configuration's tracker). The "40%" figure was an inference from recall, not a measurement. | owner |
| P13 | Option (a): merges must pass today's vetoes, and the candidates job filters with **today's** vetoes too, so pairs only the relaxed vetoes pass are skipped. The relaxed-vetoes branch stays parked and is not refactored. **Supersedes D17's "relaxed only in front of the AI".** | owner |
| P14 | A Kev minimum below 0.05 between a listing and any existing member blocks a join that rests on an AI decision. It never splits what the rules merged. Only the best "same" match per other shop counts. **Owner decision (2026-11-17): "best per other shop" is option (a), best on both sides (mutual best)**: a pair counts only when it is each listing's strongest "same" decision in the other's shop. | approved |
| P15 | Electronics only. The owner did not object to the recommendation; confirm at the 20-example review. | owner, to confirm |
| P16 | Once live, the broker queues a rebuild through `request_rebuild` when a window closes with new "same" decisions. The backlog runs through the broker with a desktop GPU worker; desktop and CPU-server workers may run at the same time, which exercises leases and both queues. | approved |
| P17 | `listings.matched_via` and `matched_ai_decision_id`, written only by the regroup; `matched_by` reads them. | approved |

What phase 1 built on them (2026-11-17): the renderer ported verbatim with a
byte-identity test on synthetic listings (P8's prompt version is pinned there);
the content hash over what the renderer shows (P5); the policy `p1` and the
pinned Kev and pplx revisions (P7, P8); the pipeline registry and transition
rule; the tables, with no host slots (Global, P3); the regroup reading
standing "same" decisions only in `live` mode (or a dry run's preview, P4),
joining them in a final phase after the rules so the P14 group check does not
depend on placement order, with every one of today's vetoes and the P17
columns; and the mode, `off` by default (P4). The broker, worker, triggers,
CLI and status come in later phases.

### Defaults chosen by the phase 2 session, awaiting owner review

The broker (phase 2, `docs/ai/broker-api.md`) needed protocol choices the
owner has not made. Each was chosen by the building session and is recorded
here as a default, **not** an owner decision; each is one place in the code
to change.

| Choice | Default in force | Where |
|---|---|---|
| Blame on a crash | An expired lease charges an attempt only to the job the worker's last heartbeat named in hand (`progress.job_id`); its other jobs go back free. With none reported, every job of the lease is charged. | `broker.reap` |
| One model per session | `/hello` names exactly one model (422 otherwise); a lease for another model is `409 wrong_model`. A machine still serves two models by running two workers. A protocol rule chosen by the session. | `broker.hello`, `broker.lease` |
| Retrying a lease | `lease_request_id`: the same id gets the same lease back (still-held, unexpired jobs, re-rendered); a session's leases take turns on its row lock. | `broker._replay` |

### Owner decisions on phase 2 (2026-11-17)

| Decision | In the code |
|---|---|
| The daily trigger's first run records content hashes and queues nothing; the existing catalogue is the backlog, scored locally (P4). Approved. | `candidates.BASELINE_FIRST_RUN = True` |
| The rules-merged audit runs at the lowest priority, 10. Approved. | `triggers.AUDIT = 10` |
| Re-score priorities: a standing "same" 100; a "not same" whose text changed 60; one whose judge alone changed 30. Approved. **Amended 2026-11-26 (owner):** a standing "same" whose judge alone changed drops to 35, below new pairs (60) and the backlog (40), above the "not same" (30), so a new judge version re-scores the standing decisions only once newer work is done; a "same" whose text changed stays at 100. | `triggers.RESCORE_SAME` / `RESCORE_SAME_VERSION` / `RESCORE_CHANGED` / `RESCORE_VERSION` |
| **Revoked pairs: option (b)** (owner). A pair whose decision a person revoked is offered again when what the models see changes: its rendered requests differ from those the revoked decision recorded, so the models are asked again; a change they would not see (an Arabic title under an English one, a hash version) keeps it out. *Implemented by the session (not separate owner decisions):* one guard in `flow.write_decision` refuses a decision for a revoked pair unless a model scored, after the revocation, text the revocation did not see (old scores, a job queued before, or a new model on the requests the revoked decision recorded write nothing); revoking takes the pair's lock and cancels its queued jobs; a revoked decision with no request hashes keeps its pair out for good (none exist in production). **Consequence for the owner:** text reverted to a version scored before the revocation stays blocked until it changes to something new. | `candidates.REOFFER_REVOKED_ON_TEXT_CHANGE = True` |
| **P16 also on an unmerge.** A session end queues the rebuild for any new standing decision, so a "same" turned "not same" is applied at the window's end, not the next daily rebuild. Approved. | `broker.REBUILD_ON_UNMERGE = True` |
| **A listing that leaves electronics.** AI decisions act only while both listings are in electronics: the regroup ignores a decision when either listing is outside the served departments, so its merge comes apart at the next regroup. (Record this with the cross-department experiment's tracker note.) | `policy.DOMAINS`, `decisions.load_ai_same` |
| **No time fit.** A lease returns up to `max_jobs` in priority order; the broker does not size it to the worker's remaining window. A worker that runs out of window releases its unfinished job gracefully (no attempt charged) and another worker or window picks it up. The `none_fit` answer and the `nothing_fits` flag are gone. | `broker.lease` |
| **The broker is reached only over Tailscale**, by the server's Tailscale IP and a port (`BROKER_BIND`); no public reverse-proxy hostname. Plain HTTP on the tailnet (WireGuard encrypts it). This replaces P2's "own reverse-proxy hostname"; the rest of P2 (a separate service, never under `/api`) stands. | `docker-compose.prod.yml`, `docs/ai/broker-deploy.md` |

### Backlog groupings review (owner, 2026-11-19)

The overnight backlog (92,833 pairs, policy p1) was imported into a local copy of the 2026-11-17 production database and regrouped with AI decisions read (`regroup-dry-run --ai`): 4,532 of 6,311 standing "same" decisions take effect; multi-shop products go from 1,048 to 3,143, all in electronics; no rules-made product splits.

The owner reviewed a sample of 40 AI-made groups (20 random, the 10 largest, 10 joining listings that share no identifier; 142 listings), each shown with every member, its photos, specs, and both judges' scores. **Verdict: 40 of 40 all correct.** The weakest, a membrane 4x4 keypad grouped with hard-key 4x4 keypads, was judged acceptable to merge (owner). With the 40/40 validation of 2026-11-17, 80 of 80 checked merges are correct (95% lower bound about 96%).

Answers: `ai-groups-review/answers.json` under the labels (then `ml/out/labels/`, git-ignored; now the private configuration's `labels/`).

**Owner decision:** import the backlog into production and preview the regroup there; switching `ai_matching` to `live` waits for a separate owner OK.

### Go-live (owner, 2026-11-19)

- **Backlog imported into production** with `./makhzan ai import` (#69): 201,223 scores stored and 91,199 decisions written under p1 (6,249 "same", 84,950 "not same"); `--verify` found 0 mismatches. 1,634 pairs were left undecided because 155 listings had changed since the 2026-11-17 snapshot; `./makhzan ai backlog` then found candidates for every listing afresh (these pairs and listings new or changed since the snapshot) and queued 1,571 pairs at backlog priority, with 121 more already queued.
- **Production preview** (`worker.regroup --dry-run --ai`): 3,413 products merged, 0 split, 0 new ids; 4,491 of 5,104 "same" pairs in effect (the regroup reads only each listing's mutual best match per shop, hence 5,104 of 6,249; the rest of the gap is the vetoes against other members of the two products); multi-shop products 1,048 → 3,130.
- **Owner OK: `ai_matching` switched to `live`** and the regroup applied, matching the preview exactly (56,255 products, 3,130 multi-shop). Absorbed product ids redirect (308) to the product they merged into.
- **Workers:** the home server runs `home-kev` (01:00–05:00) and `home-pplx` (05:05–07:00, Africa/Cairo) as a compose stack that waits for its own windows, egress through a broker-only proxy (#72). First window: Kev scored 12 requests at about 123 s each, stopped and unloaded cleanly; pplx found its queue empty. The owner approved draining the backlog once on the desktop GPU (`desk-kev`, `desk-pplx`).

### Kev quantisation (owner, 2026-11-26)

**Kev-4B Q4_K_M, served by llama.cpp, is accepted, although it fails D20's agreement rule.**
The agreement rule asks for at least 99% at 0.5 and 0.9 and Spearman 0.99; Q4_K_M got
97.3–97.6% and 0.9955. The test that passed it is a label test, on the labelled Phase E set
under the production rule (p1: Kev ≥ 0.8 and pplx ≥ 0.95, pairs that pass the vetoes):

- no wrong merges;
- a net 3 of 209 correct merges lost;
- Kev-only precision 0.965 / recall 0.725, against bf16's 0.962 / 0.717.

The 900 pairs can show "not worse", not "equal": a difference of 1–2% would not be visible.

**Scope.** The acceptance covers this one variant. Any other variant still needs either the
agreement rule, or the same label test plus the owner's sign-off. Q8_0 passes the agreement rule
(99.3–99.6%, Spearman 0.9993).

Measurements: `docs/ai/kev-llamacpp.md`. Not yet in production: the worker's llama.cpp backend
is built but not switched on (an owner step), and the AMD card needs a passing soak test first.
*Since done: soaked and switched on 2026-11-27 ("Production switch" below).*

### pplx quantisation (owner, 2026-11-26)

pplx-decider-flash-v1.3 Q4_K_S (our own llama.cpp conversion, imatrix calibrated off the Phase E
set) accepted (owner, 2026-11-26), despite failing the agreement rule (97.8–98.3%). Combined with
Kev Q4 under the production rule it made 216 correct merges against bf16's 209, plus one labelled
"not" that the owner judged grey-area (ATmega328-PU vs ATmega328P). The variant leans toward
higher scores, so it merges more grey-area pairs.

The other two 4-bit "not" merges seen in the experiment (IQ4_XS: the 47 kΩ resistor with no
stated wattage vs 47 kΩ 1 W, and 18650 2800 mAh vs "2800 to 3200 mAh") were also judged
grey-area; IQ4_XS was not chosen. Q8_0 passes the agreement rule (99.8–99.9%, Spearman 0.9998)
but needs 5.4 GB, more than the home server's card.

**Scope.** As for Kev: this one variant (pinned by its sha256 in `worker/pins.py`); any other
needs the agreement rule, or the label test plus the owner's sign-off. Measurements:
`docs/ai/pplx-llamacpp.md`. Not yet in production: the worker's llama.cpp backend for pplx is
built but not switched on (an owner step), and its speed on the home server's CPU is estimated,
not measured. *Since done: on the card, soaked and switched on 2026-11-27 ("Production switch"
below).*

### Production switch (owner, 2026-11-27)

**Both judges move to llama.cpp, on the home server's AMD card, taking turns.**

- **The versions:** `policy.MODELS` names
  `kev-4b-Q4_K_M@33ae6b189265+llama.cpp-b12767-87d189d403fd+T1.0` and
  `pplx-decider-flash-v1.3-Q4_K_S@819a9ad0f8f4+llama.cpp-b12767-87d189d403fd+T1.3303` (D20 as
  amended), and the worker's `pins.ACTIVE_BACKEND` is `llamacpp` for both.
  - The torch versions stay as `policy.TORCH_MODELS` and `pins.PINS`, the rollback.
  - The llama.cpp image digest is part of each version, so any machine serving them, the desktop
    included, runs that one image. *Superseded 2026-11-28 by D26: the build, not the image, is
    the judge.*
- **The card:** the 4 GB card holds one model, so the two judges take turns on it (option (b) of
  three; the others were pplx on the CPU, and llama.cpp's router mode, then set aside for an open
  concurrency bug).
  - **Amended 2026-11-27 (owner): containers only, so llama.cpp's router.** The first build
    started and stopped each sidecar with host systemd timers. The owner's rule for the home
    server is a compose-only stack (no host timers or scripts), so one llama.cpp router (compose
    service `llamacpp`) now serves both models, one at a time (`--models-max 1`). Each worker loads
    its own on its window's first lease with jobs, and an idle model sleeps after 10 minutes.
  - **The concurrency bug does not apply here:** the windows never overlap, so the router never
    serves both at once.
  - **Tested on the desktop:** Kev within 0.016, pplx bit-identical, swaps in 6–9 s
    (`docs/ai/worker.md`, "The llama.cpp router").
  - **The host keeps one setting:** the udev clock-limit rule (kernel settings only the host can
    make). The router refuses to start without it.
- **The clock limit:** the card is held to clock states 0–2 by a udev rule
  (`99-amdgpu-clock-limit.rules`). At higher states its power feed, a SATA adapter on the
  original 320 W supply, resets the server on a job's first load step (captured live; state 3
  gained 1%, state 4 reset). At states 0–2:
  - **Kev:** 1,800 requests, 4.4 s each.
  - **pplx:** 1,800 requests, 4.6 s each.
  - **Both:** within 0.038 of the 3060's scores (`kev-llamacpp.md`).
- **The catch-up.** The switch makes every standing decision's judge stale, so they are re-queued
  at the amended P8 priorities (35 "same", 30 "not same"), after new pairs and the backlog. The
  owner drains them, with wider windows and the desktop (whose workers must now run the
  llama.cpp backend with the same image digest; `worker.md`). *Since D26 (2026-11-28), any
  official image of build b12767.*
- **Not done:**
  - **A proper power supply** for the card (the clock limit is the workaround).
  - ~~A CPU route for pplx requests over 4,096 tokens~~, about 1 pair in 3,000: superseded the
    same day by cutting their descriptions to fit ("Over-long requests are cut, not failed").

### H2O first (owner, 2026-11-27, D25)

**H2O-Lightning-4B Q4_K_M replaces Kev as the first judge, at 0.578; pplx Q4_K_S ≥ 0.95 stays
the second.** Policy **p2** = {h2o: 0.578, pplx: 0.95} is active; p1 (Kev ≥ 0.80, pplx ≥ 0.95)
stays in `policy.POLICIES`, never edited, as history and the rollback.

- **Accepted on the label test (D20).** With pplx Q4 under p2, on the labelled Phase E set:
  229 merges, 227 correct and 2 wrong, both grey-area (E0098, E0639). Q8 makes as many, with
  the same two wrong ones, but not the same correct ones (Q4 merges E0486 and not E0693); AUC
  0.951 (`docs/ai/decision-models.md`).
- **The scale.** H2O's GGUF bakes in T = 0.8 (`qwen35.decision.temperature.noul`). The worker
  undoes it like Kev's, so the stored score is the raw one: raw = sigmoid(0.8 · logit p). The
  threshold 0.578 is on that raw scale. The pin is the GGUF's sha256 (`5ec969c6edba…`, the Hub's
  own etag) at revision `61f8d8b7a8c2`, served by the same pinned llama.cpp image as pplx.
- **Same prompt.** The stage reads layout K2-150 (`kev_payload`, the name kept so the prompt
  version stays `K2-150@6aef2c6c`).
- **The switch.**
  - The stage is a new one, `h2o`. Kev's stage leaves `match`.
  - A queued Kev job is re-offered to the pipeline at the next sweep (hello, or the daily
    producers). It is queued at `h2o` with the same reason and priority, never cancelled.
  - Standing decisions carrying a Kev score are re-scored at the amended P8 priorities: 35 for
    "same", 30 for "not same", 100 for a "same" whose text changed.
  - Until a decision is re-scored, its Kev score is read at Kev's floor (0.05), not H2O's.
- **The audit (P12)** records H2O from now on. Pairs Kev already audited stay as they were (the
  audit re-offers no pair it has seen), so `ai status` shows the audit per model, each at its own
  bands: H2O below 0.578 and below 0.19; Kev below 0.8 and below 0.05.

**H2O's group-check floor: 0.19, confirmed by the owner, 2026-11-27** (proposed by the session). P14 blocks an AI join when the
first judge's minimum between any two members is below a floor. Kev's was 0.05. H2O's raw
scores are compressed (none go below about 0.10), so 0.05 would block nothing. The proposal
keeps P14's strength rather than its number, matching how many labelled "not same" pairs the
floor catches (all 882 labelled Phase E pairs, vetoed ones included, H2O Q4 against Kev BF16;
`ml/models/decision_models_floor.py`):

| Floor | "Not same" blocked (of 463) | "Same" wrongly blocked |
|---|---|---|
| Kev bf16 < 0.05 (today) | 358 (77.3%) | 16 |
| H2O raw < 0.185 | 351 (75.8%) | 11 |
| **H2O raw < 0.19** | **358 (77.3%)** | **12** |
| H2O raw < 0.195 | 365 (78.8%) | 16 |

At 0.19 the floor catches the same share of "not same" pairs as Kev's did, and wrongly
catches 4 fewer "same" pairs. It is in `policy.JUDGE_FLOORS`, read per model by the group
check (`decisions.load_ai_same`); the audit's bands (`status.AUDIT_BELOW`) derive from it and
the policies. A floor only ever blocks an AI join, never a rules merge. A different number is a
one-line change to `JUDGE_FLOORS`.

**Not done:**

- **Old audit pairs.** Pairs Kev audited are not re-audited by H2O, so the H2O audit grows only
  with new rules merges. Re-auditing them all is an owner call: one producer run with the audit
  filter keyed on the judge.

### Over-long requests are cut, not failed (owner, 2026-11-27)

**A request too long for the llama.cpp context is truncated to fit rather than failed.** About 1
pair in 3,000 of the backlog exceeds pplx's 4,096 tokens. The owner judges the tail of a very
long description irrelevant, so:

- the worker, not the broker's renderer, cuts words from the end of the longest `Description:`
  first and appends `[…]`;
- titles, specifications, the rules and the question are never touched;
- the cut is recorded in the score's `extra.truncated`;
- the job fails only if even empty descriptions do not fit.

Request hashes and prompt versions are unchanged. Details: `worker.md`, "Requests too long for
the context".

### The backend is not the judge (owner, 2026-11-28, D26)

**A llama.cpp judge is its GGUF, its llama.cpp build and its temperature; the image that serves
it is recorded, not versioned.** The owner asked: "why are we locking versions on backend? I
believe the backend shouldn't change the results", and approved aligning the llama.cpp versions
with P8 ("GPU and CPU are the same version, device and dtype recorded on each row").

- **How it got there.** Putting the image digest into the version (Production switch, above)
  was the session's choice, not an owner decision. It over-tightened P8: P8 already treats a
  device and a precision of the same weights and code as one version, and a Vulkan or CUDA build
  of the same llama.cpp source is the same code on another backend.
- **What changes:**
  - The version strings are kept byte-identical, so no decision re-scores and nothing changes on
    the broker or in the policy. Their `-87d189d403fd` is now a historical label.
  - The worker already checked only the build (`build_info` from the sidecar's `/props` must be
    `b12767-…`); it no longer claims an image it cannot see. b12767's `/props` does not name its
    backend, so the image comes from the worker's configuration (`[compute] llamacpp_image`) and
    is recorded with every score as `extra.serving` (`backend`, `build`, `image`), next to the
    device and dtype the results already carry.
- **The backend noise, measured** (raw scale; h2o's GGUF temperature undone, pplx as served):

  | Comparison | Requests | max \|Δp\| | mean \|Δp\| | Stage decisions moved |
  |---|---|---|---|---|
  | AMD card (Vulkan) vs 3060 (Vulkan), Kev and pplx Q4 | 1,800 each | ≤ 0.038 | | not counted |
  | Batch 512 vs 2048, h2o Q4 on the 3060 (Vulkan) | 500 | 0.023 | 0.0015 | 0 |
  | CUDA vs Vulkan, h2o Q4, 3060, batch 2048 | 500 | 0.035 | 0.0043 | 2 of 250 at 0.578 |
  | CUDA vs Vulkan, pplx Q4_K_S, 3060 | 500 | 0.045 | 0.0034 | 1 of 250 at 0.95 |

  - The three moved pairs sat at the threshold: h2o E0154 0.5766 → 0.5888 and E0226
    0.5798 → 0.5728; pplx E0141 0.9500 → 0.9486. All three are labelled "same".
  - **The two-judge rule (p2) decides the same 63 of 250 pairs** on both backends, the same
    merges exactly, so no final decision moved on this sample.
  - Speed on the 3060: h2o 3.50 requests/s on CUDA against 3.07–3.11 on Vulkan (two of five
    Vulkan runs fell to 0.95, unexplained; Vulkan's scores are deterministic, bit-identical
    between a slow and a fast run); pplx 2.99 against 2.70. Parallel slots gained nothing
    (`ml/out/desktop-speed`, 2026-11-28).
  - The session's bar for moving the desktop to CUDA (no stage decision moved, more than 15%
    faster) is not met on this sample: 3 borderline stage moves, 14% and 11% faster. So the
    desktop runs the Vulkan image until the owner says otherwise. D26 itself does not depend on
    that bar.
- **Scope:** any machine. Today that is the desktop's backlog runs; the home server's AMD card
  stays on the Vulkan image (CUDA does not run there).

