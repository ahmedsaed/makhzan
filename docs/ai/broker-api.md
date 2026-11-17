# AI matching: the broker API contract

Status: **contract only.** Phase 1 built the shared core
(`packages/schemas/makhzan_schemas/ai/`), the tables and the regroup's reading
side. The broker (phase 2), the worker (phase 3) and the candidates trigger are
built against this document, in parallel. Where this contract and the code
disagree, the code in `makhzan_schemas.ai` is the reference for pipelines, the
transition rule, prompts and hashes, and this document must be fixed.

Owner decisions this rests on (2026-11-17, `docs/ai/decision-review.md` §6,
numbered P1–P17 there and in the code, apart from the register's D-numbers):
the broker is a separate service from the API image with its own app object
and hostname, never under the public `/api` rewrite (P2); one bearer token per
worker, stored as sha256 (P3); shadow first (P4); content hash per listing
(P5); a decision stays until re-scored (P6); named policies in code (P7);
separate model and prompt versions (P8); both reading orders always (P11).
**There are no host slots or host groups**: the broker treats every worker the
same, and each worker's own configuration decides what it runs and when. And
the design is extensible: pipelines are data, so a new model, prompt or
pipeline changes the registry, not the broker or the worker.

## 1. The moving parts

```text
triggers (producers)           broker (generic)                 workers (generic per model key)
  candidates -> "match"  --->  ai_jobs (pipeline, stage)  <----  lease: jobs whose stage's model
  audit      -> "audit"          |                               is one of my model keys
  rescore    -> same pipeline    |  results  ---------------->   score both orders, POST results
                                 v
                       pipelines.transition(pipeline, scores, policy)
                         SCORE  -> enqueue the next stage
                         DECIDE -> write ai_decisions (same / not_same)
                         RECORD -> done (a non-deciding pipeline, e.g. audit)
```

- **Pipelines** (`makhzan_schemas/ai/pipelines.py`) are a registry of named,
  ordered stages. A stage is a model key (`policy.MODELS`), a prompt variant
  (`prompt.VARIANTS`) and a threshold key (into `policy.POLICIES`). Today:
  `match` = Kev (K2-150) then pplx (K1-full); `audit` = Kev only, recording
  (P12), no decision.
- **One transition rule** (`pipelines.transition`): a stage below its
  threshold decides `not_same`; a pass moves to the next stage; passing the
  last decides `same`; a non-deciding pipeline only records. The broker never
  branches on a model or stage name.
- **Triggers** (`makhzan_schemas/ai/triggers.py`) are producers yielding
  `PairRequest(listing_a, listing_b, pipeline, priority, reason)`;
  `triggers.enqueue` puts a pair into its pipeline's first stage. A trigger
  must not offer a pair with a standing override (`overrides.load_overrides`).
- **Workers** name the model keys they serve. They never see pipelines; they
  receive rendered requests for their model and return scores.
- **Tables** store pipeline, stage and model keys as strings validated
  against the registry, never as database enums: no migration for a new model
  or pipeline.

## 2. Service

- Base path `/ai/v1`, on its own hostname behind the reverse proxy, TLS only.
- JSON bodies, UTF-8. Times are ISO 8601 UTC. Ids are listing UUIDs and
  integer job ids. Hashes are lowercase hex sha256.
- Auth: `Authorization: Bearer <token>`. The broker looks up
  `sha256(token)` in `ai_workers.token_sha256`; a revoked worker
  (`revoked_at` set) or an unknown token gets `401`. Every request updates
  `ai_workers.last_seen_at`.
- A small body limit of its own (results are small).
- Production never runs a model. Catalogue text goes only to authenticated
  workers, over TLS; workers write none of it to disk and log no payloads.

## 3. Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | `{"ok": true, "broker": "<git sha>"}`. Nothing about queues. |
| `POST /hello` | worker | Session start: versions and whether there is work. |
| `POST /lease` | worker | Up to `max_jobs` jobs with rendered requests. |
| `POST /heartbeat` | worker | Extends this session's leases; reports progress. |
| `POST /results` | worker | One job's scores, one or both orders. Idempotent. |
| `POST /release` | worker | Hands leases back, gracefully or with an error. |
| `GET /status` | admin | The same numbers as `make status`'s AI section. |

### 3.1 `POST /hello`

```json
{"worker": "cpu-kev",
 "models": {"kev": {"model_version": "kev-4b@6cfce5c2fa4b+kev-6b719c3+T1.0",
                    "weights_revision": "6cfce5c2fa4b4bd64026336ab649c5ca78857d52"}},
 "image": "<digest>", "device": "cpu", "dtype": "fp32", "threads": 6,
 "config": {"window": "00:30-04:30", "max_jobs": 2, "lease_s": 900, "on_empty": "exit"}}
```

```json
200 {"session": "6f1c…",
     "models": {"kev": {"model_version": "kev-4b@6cfce5c2fa4b+kev-6b719c3+T1.0",
                        "ok": true, "queued_requests": 824}},
     "lease_s": 900, "heartbeat_s": 60}
```

- `models` keys must be a subset of the worker's `ai_workers.models`; any
  other key is `403 {"error": "model_not_allowed", "model": "…"}`.
- For each model key the broker answers the model version the registry uses
  now (`policy.MODELS[key].model_version`). A worker whose `model_version`
  or `weights_revision` differs gets `"ok": false` for that key and must not
  lease it (a `version_drift` flag is opened).
- `queued_requests` counts queued requests across every (pipeline, stage)
  that uses that model (`pipelines.stages_for_models`). **A worker loads its
  model only when some `ok` model has work**, which avoids a long load and a
  large memory footprint on an empty night.
- `last_hello` is stored for status.

### 3.2 `POST /lease`

```json
{"session": "6f1c…", "model": "kev", "max_jobs": 2,
 "seconds_left": 10450, "seconds_per_request": 86}
```

```json
200 {"lease_id": "0b7e…", "expires_at": "2026-11-18T01:15:00Z",
     "jobs": [{"job_id": 81234,
               "prompt_version": "K2-150@6aef2c6c",
               "requests": [
                 {"order": "ab", "request_sha256": "9d…", "payload": {"state": "[LISTING A]\nTitle: …",
                  "questions": {"same": {"type": "noul", "instructions": "You compare two product listings …"}}}},
                 {"order": "ba", "request_sha256": "41…", "payload": {"…": "…"}}]}]}
```

- One model per lease. The broker selects queued jobs whose
  `model_version_id` is the current judge of any stage that uses `model`,
  highest `priority` first, then oldest:
  `SELECT … FROM ai_jobs WHERE status = 'queued' AND model_version_id = ANY($ids)
  ORDER BY priority DESC, created_at LIMIT $n FOR UPDATE SKIP LOCKED`, then
  sets `status = 'leased'`, `lease_id`, `leased_by`, `leased_at` and
  `lease_expires_at = now() + lease_s`. `SKIP LOCKED` keeps concurrent
  workers, on any machines, from leasing the same job.
- **Batch size:** jobs are added while `requests × seconds_per_request` fits
  in `seconds_left` minus a margin; at most `max_jobs`.
- **Rendering at lease time**, from the current database rows: the stage's
  prompt variant (`pipelines.PIPELINES[p].stage(s).prompt`) through
  `prompt.requests(variant, record(a), record(b))`, where `record` is
  `prompt.record(prompt.listing_row(listing, category_name_en))`. "ab" shows
  the pair's `listing_a` as LISTING A. The broker stores
  `{"ab": hex, "ba": hex}` in `ai_jobs.request_sha256`, and the two
  listings' `hashing.listing_hash` for the scores.
- A job carries **only the orders with no score yet** for that judge and
  request hash, so a stop after one order loses nothing.
- **Eligibility is re-checked** before a job is handed out; if any fails the
  job is set `cancelled` and skipped: both listings active; no standing
  override on the pair; the pipeline and stage still exist in the registry and
  the stage still uses this judge (otherwise it is re-queued as a re-score at
  the current judge). Trigger-specific conditions (for example, "not merged by
  the rules") are the trigger's to re-check: the broker asks
  `TRIGGERS[job.reason].still_wanted(...)` when the trigger defines it, and
  otherwise keeps the job.
- **Lazy expiry reaper**, at the start of every `/lease`: leases past
  `lease_expires_at` go back to `queued` with `attempts + 1`; at
  `max_attempts` the job becomes `dead` and a `poison_job` flag is opened. No
  cron is needed.
- Empty queue: `200 {"lease_id": null, "jobs": []}`. A worker with
  `on_empty = "exit"` exits; with `"wait"` it polls until its window ends.

### 3.3 `POST /heartbeat`

```json
{"session": "6f1c…", "lease_ids": ["0b7e…"], "rss_bytes": 19100000000,
 "progress": {"job_id": 81234, "order": "ba"}}
200 {"expires_at": "2026-11-18T01:30:00Z"}
```

Extends `lease_expires_at` by `lease_s` for every live job of those leases.
A lease that already expired and was re-leased elsewhere is not extended
(`409 {"error": "lease_lost", "job_ids": […]}`); the worker drops those jobs
after finishing its current request, and may still submit what it scored
(see idempotency).

### 3.4 `POST /results`

```json
{"session": "6f1c…", "lease_id": "0b7e…", "job_id": 81234,
 "scores": [{"order": "ab", "request_sha256": "9d…", "p": 0.9131,
             "seconds": 85.7, "extra": {"margin": null}},
            {"order": "ba", "request_sha256": "41…", "p": 0.8722, "seconds": 86.4}],
 "device": "cpu", "dtype": "fp32", "threads": 6}
```

```json
200 {"accepted": 2, "duplicate": 0, "job": "done", "next": {"action": "score", "stage": "pplx"}}
```

**Idempotency on the request hash.** Each score is inserted into `ai_scores`
with `ON CONFLICT (model_version_id, request_sha256) DO NOTHING`:

- a retried POST, or a late result from an expired lease someone else
  re-leased, is counted as `duplicate` and changes nothing;
- a `request_sha256` that is not one the broker rendered for this job
  (`ai_jobs.request_sha256`) is refused with `422 {"error": "request_mismatch"}`,
  as an integrity check, and nothing from that POST is stored;
- `p` outside [0, 1] is `422`.

A job is `done` when both orders have a score under the job's judge and
request hashes, whoever submitted them.

**The generic result handling** (one function, in the same transaction as the
insert; nothing in it names a model or a stage):

```python
def on_scores(session, job):
    p = pipelines.pipeline(job.pipeline)
    scores = stored_scores(session, job.listing_a, job.listing_b, p)   # {stage: {"ab", "ba"}}
    step = pipelines.transition(p.name, scores, policy.ACTIVE)         # for each stage, under
    if step.action == SCORE:                                           # its current judge and
        triggers.enqueue(session, [PairRequest(job.listing_a,          # the listings' current
            job.listing_b, p.name, NEXT_STAGE_PRIORITY, job.reason)],  # content hashes
            stage=step.stage)
    elif step.action == DECIDE:
        write_decision(session, job, p, step, scores)
    # RECORD: nothing more (the audit's scores are its record)
```

`stored_scores` reads, for each stage of the pipeline, the `ai_scores` rows of
that stage's current judge whose content hashes are the listings' current
ones. A score is reusable across pipelines: two stages using the same model and
prompt version share it.

`write_decision`:

- marks any `standing` decision for (pipeline, pair) `stale`;
- inserts a new `standing` row: `outcome`, `decided_by = step.decided_by`,
  `scores = {stage: {"model", "model_version_id", "ab", "ba", "min"}}`,
  `policy_version = policy.ACTIVE`, both content hashes, and
  `shadow = (mode != "live")` (`ai.mode.ai_mode`).

The regroup reads standing, non-shadow "same" decisions
(`decisions.load_ai_same`) at the next rebuild. Once live, when a worker's
window closes with new "same" decisions, the broker queues
`rebuild_and_reindex` through the existing `request_rebuild` job-id scheme
(P16); in shadow it queues nothing.

### 3.5 `POST /release`

```json
{"session": "6f1c…", "lease_id": "0b7e…", "job_ids": [81235],
 "reason": "graceful" | "error", "error": "CUDA out of memory"}
200 {"released": 1}
```

`graceful` (window end, SIGTERM) re-queues with no attempt counted. `error`
re-queues with `attempts + 1` and stores `last_error`; at `max_attempts`, the
job is `dead` and a `poison_job` flag is opened. Scores already submitted are
kept: half a job is not lost.

### 3.6 Errors

| Status | Body | Meaning |
|---|---|---|
| 401 | `{"error": "unauthorized"}` | missing, unknown or revoked token |
| 403 | `{"error": "model_not_allowed", "model": "…"}` | not in `ai_workers.models` |
| 409 | `{"error": "version", "model": "kev", "current": "…"}` | the worker's model version is not the registry's |
| 409 | `{"error": "lease_lost", "job_ids": […]}` | the lease expired and the job moved on |
| 422 | `{"error": "request_mismatch"}` / `{"error": "invalid", "detail": …}` | integrity or validation |

## 4. Lease semantics, in one place

- A job is in exactly one of `queued`, `leased`, `done`, `cancelled`, `dead`.
- Enqueueing is idempotent: one open (`queued` or `leased`) job per
  (pipeline, stage, judge, pair), enforced by `uq_ai_job_open_pair`.
- A lease is held until `lease_expires_at`; heartbeats extend it. An expired
  lease counts an attempt (the worker died, for example killed for memory);
  a graceful release does not.
- `max_attempts` (3) explicit failures or expiries make a job `dead`; it shows
  in status and is retried by hand (`./makhzan ai jobs retry ID`, phase 3).
- Any number of workers, on any machines, may lease at once; `SKIP LOCKED`
  and the request-hash idempotency make overlap harmless.

## 5. Versions and re-scoring

- A judge is a (model key, model version, prompt version) row in
  `ai_model_versions`, created on first use from the registry
  (`triggers.model_version_id`). Device and dtype are recorded on each score,
  not in the version: GPU and CPU are one version (P8).
- A re-score is queued (by the re-score trigger, `reason = "rescore"`, into
  the pipeline the pair was in) when a listing's content hash changed or a
  stage's judge changed. Standing "same" decisions go first. The old decision
  stays in force until the new one is written (P6); one that is due and never
  completes shows in status and is handled by hand.
- A new policy (`policy.POLICIES`, `ACTIVE`) recomputes decisions from stored
  scores with `pipelines.decide`, with no model call
  (`./makhzan ai redecide --dry-run`, phase 3).

## 6. Worker configuration (phase 3)

Each worker's TOML decides everything the broker does not: which model keys it
serves, its window, threads, memory, `max_jobs` per lease, `lease_s`, device
(cpu or gpu), dtype, `on_empty` (`exit` or `wait`), the broker URL and its
token file. Two workers may serve two models on one machine at once if their
configurations say so; the broker does not arbitrate. Scores are one request
per forward call (pplx is bit-stable only that way); "batch" means jobs per
lease, never batched inference.

```toml
[worker]
name       = "cpu-kev"            # = ai_workers.name
models     = ["kev"]              # model keys from policy.MODELS
broker_url = "https://<broker host>/ai/v1"
token_file = "/run/secrets/makhzan-ai-token"

[model.kev]
expect_version = "kev-4b@6cfce5c2fa4b+kev-6b719c3+T1.0"
device = "cpu"
dtype  = "fp32"
threads = 6

[window]
start = "00:30"
end   = "04:30"
on_empty = "exit"

[leases]
max_jobs = 2
lease_s  = 900
heartbeat_s = 60
```

## 7. What is not here yet

- The broker service itself, its app object, compose service and proxy
  hostname (phase 2).
- The worker (phase 3) and its images.
- The candidates, audit and re-score triggers (later phases; the interface is
  `triggers.Trigger`, and `TRIGGERS` is empty today). `still_wanted` in §3.2
  is a proposed optional method on that interface, not yet in the code.
- `./makhzan ai …` and the status section.
- Writing `ai_decisions.effect` after each regroup (the columns exist; nothing
  writes them yet), and citing revoked decisions on the regroup that undoes
  them (`revoked_ai_decisions`).
