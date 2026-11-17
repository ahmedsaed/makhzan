# AI matching: decision review (2026-11-16, updated 2026-11-17)

Every design decision in the AI matching work so far, who made it, what rests on
it, and what the owner needs to decide. Written after the owner found that the
judges had been prompted with one generic sentence that carried none of the
labelling rules. That one unreviewed choice touches most results below, so they
are marked **confounded** where it applies.

"Owner" = decided by the owner. "Session" = chosen by Claude or an agent and not
put to the owner. Results that rest on a session choice are not settled.

## Labelling rules in force (summary)

The full text, with examples, is in `ml/out/labels/README.md` (git-ignored with
the labels). Labels are same / different / variant / unsure; for matching,
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
| D20 | Quantisation | Rejected unless proven harmless | Owner | serving | settled |
| D21 | Serving | Workers on CPU servers (the CPU worker 03:00–06:00, 6 threads, Kev phase then pplx phase, no mmap, 20 GB); desktop for backlogs. Refined 2026-11-17 (§6, Global, P9, P10): one worker per model if wanted, each worker's own config sets its window, threads and models; no broker rule against two models on one machine | Owner | pipeline | settled |
| D22 | Data | Labels kept in git-ignored `ml/out/labels/` | Owner rule, after loss | — | settled |
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

New labelling rules (also in `ml/out/labels/README.md`):

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
| Re-score priorities: a standing "same" 100; a "not same" whose text changed 60; one whose judge alone changed 30. Approved. | `triggers.RESCORE_SAME` / `RESCORE_CHANGED` / `RESCORE_VERSION` |
| **Revoked pairs: option (b).** A pair whose decision a person revoked is offered again when what the models see changes: its rendered requests differ from those the revoked decision recorded, so the models are asked again. A change they would not see (an Arabic title under an English one, a hash version) keeps it out. One guard in `flow.write_decision` refuses any decision for a revoked pair unless a model scored, after the revocation, text the revocation did not see (old scores, a reverted text, a job queued before, or a new model on the same text write nothing). Revoking cancels the pair's queued jobs. A revoked decision recorded without request hashes keeps its pair out for good (none exist in production). | `candidates.REOFFER_REVOKED_ON_TEXT_CHANGE = True` |
| **P16 also on an unmerge.** A session end queues the rebuild for any new standing decision, so a "same" turned "not same" is applied at the window's end, not the next daily rebuild. Approved. | `broker.REBUILD_ON_UNMERGE = True` |
| **A listing that leaves electronics.** AI decisions act only while both listings are in electronics: the regroup ignores a decision when either listing is outside the served departments, so its merge comes apart at the next regroup. (Record this with the cross-department experiment's tracker note.) | `policy.DOMAINS`, `decisions.load_ai_same` |
| **No time fit.** A lease returns up to `max_jobs` in priority order; the broker does not size it to the worker's remaining window. A worker that runs out of window releases its unfinished job gracefully (no attempt charged) and another worker or window picks it up. The `none_fit` answer and the `nothing_fits` flag are gone. | `broker.lease` |
| **The broker is reached only over Tailscale**, by the server's Tailscale IP and a port (`BROKER_BIND`); no public reverse-proxy hostname. Plain HTTP on the tailnet (WireGuard encrypts it). This replaces P2's "own reverse-proxy hostname"; the rest of P2 (a separate service, never under `/api`) stands. | `docker-compose.prod.yml`, `docs/ai/broker-deploy.md` |
