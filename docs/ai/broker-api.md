# AI matching: the broker API contract

Status: phase 1 built the shared core (`packages/schemas/makhzan_schemas/ai/`),
the tables and the regroup's reading side. Phase 2 built the broker
(`apps/api/app/broker/main.py` over `makhzan_schemas.ai.broker` and
`ai.flow`), the triggers (`ai/candidates.py`), the CLI (`./makhzan ai`) and
status; deploying it is `docs/ai/broker-deploy.md`. The worker (phase 3) is
built against this document. Where this contract and the code disagree, the
code in `makhzan_schemas.ai` is the reference for pipelines, the transition
rule, prompts and hashes, and this document must be fixed.

Owner decisions this rests on (2026-11-17, `docs/ai/decision-review.md` §6,
numbered P1–P17 there and in the code, apart from the register's D-numbers):
the broker is a separate service from the API image with its own app object
and port, never under the public `/api` rewrite (P2), reached only over
Tailscale; one bearer token per
worker, stored as sha256 (P3); no shadow period: the mode is `off` until the
owner sets it `live`, after reviewing the backlog's groupings on a local copy
(P4); content hash per listing (P5); a decision stays until re-scored (P6);
named policies in code (P7); separate model and prompt versions (P8); both
reading orders always (P11). **There are no host slots or host groups**: the
broker treats every worker the same, and each worker's own configuration
decides what it runs and when. And the design is extensible: pipelines are
data, so a new model, prompt or pipeline changes the registry, not the broker
or the worker.

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

### 1.1 Two hashes, two jobs

- **The request hash** (`prompt.request_sha256`, over the canonical JSON of
  exactly what a judge is sent) is the identity of a score. `ai_scores` is
  unique on (judge, `request_sha256`). **Whether a pair still needs a score is
  always answered by rendering the request from the current rows and looking
  up (judge, request hash)**, never by content hashes. So a change that does
  not change what the judge would see (for example the rules' identifier
  behind a shop's stated code) re-uses the stored score instead of looping.
- **The content hash** (`hashing.listing_hash`) is provenance and the
  re-score trigger only: it is stored on the job at lease time and on each
  score (the text that was sent), and on each decision as computed at
  decision time (the text the decision stands for, §3.4). A listing whose
  current hash differs from its standing decision's is what makes the
  re-score trigger queue a pair (P5). A re-queued pair whose
  requests are byte-identical to scored ones goes straight to the transition
  with no lease (§3.2).

## 2. Service

- Base path `/ai/v1`, at `http://<server tailscale ip>:<port>`, reachable
  only over Tailscale (owner, 2026-11-17; `docs/ai/broker-deploy.md`). There
  is no public hostname. Tailscale encrypts the link (WireGuard), so plain
  HTTP is acceptable on it; the bearer tokens still authenticate each worker.
- JSON bodies, UTF-8. Times are ISO 8601 UTC. Ids are listing UUIDs and
  integer job ids. Hashes are lowercase hex sha256.
- **Worker auth**: `Authorization: Bearer <token>`. The broker looks up
  `sha256(token)` in `ai_workers.token_sha256`; a revoked worker
  (`revoked_at` set) or an unknown token gets `401`. Every request updates
  `ai_workers.last_seen_at`.
- **Admin auth** (`GET /status` only): a separate bearer token, issued by
  `./makhzan ai admin-token` (prints a fresh 32-byte random token once) and
  stored only as its sha256 in the broker's environment
  (`AI_BROKER_ADMIN_TOKEN_SHA256` in the production env file); issuing a new
  one replaces it (`./makhzan ai admin-token` rewrites that line and
  recreates the broker). A worker token is never an admin token, nor the
  reverse.
- A small body limit of its own: a POST over 256 KiB is refused with 413
  (`AI_BROKER_MAX_BODY`).
- Bodies that fail validation get `422 {"error": "invalid", "detail": [...]}`.
- Production never runs a model. Catalogue text goes only to authenticated
  workers, over Tailscale; workers write none of it to disk and log no
  payloads.

### 2.1 Modes

`worker_state['ai_matching']` (`ai.mode`) is `off` or `live`; there is no
shadow mode. **The mode governs only whether the regroup reads decisions.**
The broker behaves the same in both: it leases jobs, accepts results and
writes decisions, so the backlog can be scored while the mode is off.

- `off` (the default): the regroup reads no decision; `make regroup-dry-run
  ARGS=--ai` previews what reading them would do. Nothing merges.
- `live`: the regroup reads standing "same" decisions, and the broker's
  rebuild after a window (P16, §3.4) fires.
- The backlog is scored on the owner's machines against a local copy, its
  groupings reviewed there with `make regroup-dry-run ARGS=--ai` (which reads
  standing decisions whatever the mode), and its scores and decisions then
  pushed to production (P4). Pushing them is phase 3's tooling.

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
                        "ok": true, "queued_requests": 824,
                        "stages": [{"pipeline": "match", "stage": "kev",
                                    "prompt_version": "K2-150@6aef2c6c"},
                                   {"pipeline": "audit", "stage": "kev",
                                    "prompt_version": "K2-150@6aef2c6c"}]}},
     "lease_s": 900, "heartbeat_s": 60}
```

- **One model per session.** `models` names exactly one model key, else
  `422 {"error": "invalid"}`; a worker serving two keys opens one session
  The key must be one of the worker's `ai_workers.models`, else
  `403 {"error": "model_not_allowed", "model": "…"}`.
- The broker answers the model version the registry uses now
  (`policy.MODELS[key].model_version`). A worker whose `model_version` or
  `weights_revision` differs gets `"ok": false` (and a `version_drift` flag
  is opened, one per worker and model, `subject = "<worker>/<model>"`); it
  must not lease, and §3.2 enforces it.
- `stages` lists every (pipeline, stage) that uses the model and the prompt
  version the broker renders for it now: what the session's leases will
  carry. The broker renders, so the worker only compares or logs these.
- `queued_requests` counts queued requests across every (pipeline, stage)
  that uses that model (`pipelines.stages_for_models`), in either mode: two
  per queued job, whichever judge it was queued at, so it is an upper bound
  (an order already scored is not sent). **A worker loads its model only when
  some `ok` model has work**, which avoids a long load and a large memory
  footprint on an empty night.
- `lease_s` is the worker's `config.lease_s` (default 900), used for every
  lease and heartbeat of the session; `heartbeat_s` is `min(60, lease_s / 3)`.
  It must be an integer from 60 to 7200, else `422 {"error": "invalid"}`.
- Hello also moves any job queued at an old judge to its stage's current
  judge (the judge sweep, §3.2), before counting, so the worker's own leases
  see that work. **Hello therefore carries the sweep's latency**: nothing on
  most days, and after a model or prompt version change one set-based UPDATE
  over the queued jobs (seconds for tens of thousands). A worker should give
  `/hello` a generous timeout; the daily producers usually run the sweep
  first.
- The broker stores a session row (`ai_sessions`: worker, session id, the
  model versions it reported and whether each was `ok`, the rest of the
  hello, `lease_s`, started_at, last_seen_at, ended_at, end_reason, and the
  last lease's request id and lease id) and `ai_workers.last_hello` for
  status. `ended_at` / `end_reason` record how a session last stopped:
  `released` (a graceful `/release`, with or without jobs, of a session not
  already ended) or `empty` (a lease came back empty); a release after
  `empty` keeps that end. A later lease that returns jobs reopens it.

### 3.2 `POST /lease`

```json
{"session": "6f1c…", "model": "kev",
 "model_version": "kev-4b@6cfce5c2fa4b+kev-6b719c3+T1.0",
 "max_jobs": 2, "lease_request_id": "3f2a…"}
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

- **The session's own model only**: a lease for a model the session did
  not say hello for is `409 {"error": "wrong_model", "model": "…",
  "session_model": "…"}` (a session serves one model; open another).
- **Version drift is enforced here**: `model_version` must equal the
  registry's for `model`, and the session must have reported it at hello;
  otherwise `409 {"error": "version", "model": "kev", "current": "…"}` and no
  job is leased. The worker exits and logs it.
- The worker must serve `model` (`ai_workers.models`), else `403`.
- One model per lease. The broker selects queued jobs whose
  `model_version_id` is the current judge of any stage that uses `model`,
  highest `priority` first, then oldest:
  `SELECT … FROM ai_jobs WHERE status = 'queued' AND model_version_id = ANY($ids)
  ORDER BY priority DESC, created_at LIMIT $n FOR UPDATE SKIP LOCKED`
  (index `ix_ai_job_lease`, partial on `status = 'queued'`), then sets
  `status = 'leased'`, `lease_id`, `leased_by`, `leased_at` and
  `lease_expires_at = now() + lease_s`. `SKIP LOCKED` keeps concurrent
  workers, on any machines, from leasing the same job. A lease locks only as
  many rows as it still wants (`LIMIT max_jobs - taken`, a job already
  looked at in this lease excluded by id), so a concurrent lease never finds
  the queue empty because this one holds a wide scan.
- **A session's leases take turns**: /lease locks the session row for its
  transaction. So a retry that arrives while the original is still being
  served waits for it, then replays it (below), instead of making a second
  lease whose first would expire and be charged.
- **Retrying a lease**: `lease_request_id` (optional, the worker's own id
  for this request, at most 64 characters). A /lease whose id equals the
  session's last one gets that lease back: the same `lease_id`, the jobs of
  it still held and not expired, re-rendered (only orders still owed), their
  expiry renewed. A job of it that now owes nothing (scored meanwhile, by
  request hash) is finished there and then, not renewed and left out. So a
  lease whose answer was lost on the way is not orphaned until it expires.
  If none of it is still held (released, completed, or expired: reaped or
  not yet), a fresh lease is made, which reaps first. A session serves one
  model, so a replay is always of that model. A new id, or none, is always a
  fresh lease.
- **Batch size: up to `max_jobs`, in priority order.** There is no time
  fit (owner, 2026-11-17: needless complexity): the broker does not ask how
  long the worker has. A worker whose window ends with a job unfinished
  releases it gracefully (§3.5: no attempt charged, scores already posted
  kept), and another worker or the next window picks it up. Fields an older
  worker may still send (`seconds_left`, `seconds_per_request`) are ignored.
- **Rendering at lease time**, from the current database rows: the stage's
  prompt variant (`pipelines.PIPELINES[p].stage(s).prompt`) through
  `prompt.requests(variant, record(a), record(b))`, where `record` is
  `prompt.record(prompt.listing_row(listing, category_name_en))`. "ab" shows
  the pair's `listing_a` as LISTING A. The broker stores
  `{"ab": hex, "ba": hex}` in `ai_jobs.request_sha256` and both listings'
  current `hashing.listing_hash` in `ai_jobs.content_sha256_a` / `_b`: the
  text the scores will be about.
- **Freshness by request hash.** A job carries only the orders whose
  (judge, request hash) has no score in `ai_scores`. **A job never carries
  zero orders**: one whose two requests are both already scored is not leased
  at all; it is set `done` and handed to the transition (§3.4) in the same
  transaction, then the next job is considered.
- **Eligibility is re-checked** before a job is handed out; if any fails the
  job is set `cancelled` (with `last_error` saying why) and skipped: both
  listings active; no standing override on the pair; the pipeline and stage
  still exist in the registry and the stage still uses this judge (otherwise
  it is queued again at the current judge, keeping its reason). Trigger-specific
  conditions (for example, "not merged by the rules") are the trigger's to
  re-check: the broker asks `TRIGGERS[job.reason].still_wanted(session, job)`
  when the trigger defines it (`triggers.still_wanted`), and otherwise keeps
  the job. A later stage's job keeps the reason, so it is asked too.
- **The judge sweep** (`broker.sweep_judges`) moves every queued job whose
  (pipeline, stage, judge) is not its stage's current judge (a new model or
  prompt version) to the current one, keeping its reason and priority; a job
  whose stage left the registry is only cancelled. Compared per job, not by
  "is this id current anywhere": a judge id can be current for one stage and
  stale for another. Set-based (one UPDATE, batched inserts), and run at
  `/hello` and by the daily producers, **never inside a lease**, so a version
  bump over a large queue neither slows a lease nor holds its rows.
- **Lazy expiry reaper**, at the start of every fresh `/lease`: leases past
  `lease_expires_at` (index `ix_ai_job_lease_expiry`, partial on
  `status = 'leased'`) go back to `queued` with their lease fields cleared.
  **Only the job in hand is charged an attempt**: the one the worker's last
  heartbeat named in `progress.job_id` (§3.3). Its co-leased jobs never
  started and go back free, so one poison job does not take innocent jobs
  down with it. A lease with no job reported in hand (the worker died before
  any heartbeat said) charges every job. At `max_attempts` a job becomes
  `dead` and a `poison_job` flag is opened. No cron is needed.
- Empty queue: `200 {"lease_id": null, "jobs": [], "reason": "empty"}`. A worker with
  `on_empty = "exit"` exits; with `"wait"` it polls until its window ends.
  An empty lease marks the session ended (`end_reason = "empty"`); the
  worker sends no release, and a `"wait"` worker's next lease in the same
  session reopens it. P16 is considered at both session ends: a graceful `/release` and an `empty` lease (§3.4).

### 3.3 `POST /heartbeat`

```json
{"session": "6f1c…", "lease_ids": ["0b7e…"], "job_ids": [81234], "rss_bytes": 19100000000,
 "progress": {"job_id": 81234, "order": "ba"}}
200 {"expires_at": "2026-11-18T01:30:00Z"}
409 {"error": "lease_lost", "job_ids": [81234], "lease_ids": ["0b7e…"], "expires_at": null}
```

Sets `lease_expires_at` to now + `lease_s` for every live job of those
leases held by this worker. `progress.job_id`, when it is one of those jobs,
marks it the job in hand (and no other job of its lease): the one an expiry
is charged to (§3.2). The worker should send a heartbeat as it starts each
job, so a crash is blamed on the right one. A lease that already expired and was re-leased
elsewhere is not extended. `job_ids` (optional) names the jobs the worker
still holds: an expired lease's fields are cleared when it is reaped, so
only the worker can say which jobs it thought it had. The answer is 409 when
any named lease has no live job of the caller left (`lease_ids`) or any named
job is no longer held (`job_ids`); the leases still live **are** extended
regardless, and `expires_at` is their new expiry (null when none was). The
worker drops the lost jobs after finishing its current request.

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

`job` is `leased` while the job still owes an order (then `next` is null),
`done` once both orders are scored. `next` is what the transition did:
`{"action": "score", "stage": …}`, `{"action": "decide", "outcome": "same" |
"not_same"}`, `{"action": "record"}`, or `{"action": "blocked"}` when a
person's revocation keeps the decision from being written (below). The job
is done either way.

**Who may post.** The caller must be the worker that holds the job's lease
(`ai_jobs.lease_id` = `lease_id` and `leased_by` = the caller) and must serve
the job's model; otherwise `409 {"error": "lease_lost"}` or `403`. A late
result for a lease that expired and moved on is refused with `lease_lost`
(the score may already exist under the request hash; if not, the job's new
holder will produce it).

**Idempotency on the request hash.** Each score is inserted into `ai_scores`
with `ON CONFLICT (model_version_id, request_sha256) DO NOTHING`, labelled
with the job's lease-time `content_sha256_a` / `_b`, device, dtype and threads:

- a retried POST is counted as `duplicate` and changes nothing. That holds
  after the job is done too: its lease fields are cleared then
  (`ck_ai_job_leased_has_lease`), so a retry cannot match the lease, and it
  is answered `200 {"accepted": 0, "duplicate": n, "job": "done", "next":
  null}` when every posted hash is one of the job's and already stored;
- a `request_sha256` that is not one the broker rendered for this job
  (`ai_jobs.request_sha256`) is refused with `422 {"error": "request_mismatch"}`
  for the leaseholder (anyone else gets `lease_lost`), and nothing from that
  POST is stored;
- `p` outside [0, 1] is `422`.

A job is `done` when both of its requests have a score under its judge,
whoever submitted them.

**The generic result handling** (one function, `flow.on_scores`, in the same
transaction as the insert; nothing in it names a model or a stage):

```python
def on_scores(session, job):
    p = pipelines.pipeline(job.pipeline)
    scores = current_scores(session, job.listing_a, job.listing_b, p)  # {stage: {"ab", "ba"}}
    step = pipelines.transition(p.name, scores, policy.ACTIVE)
    if step.action == SCORE:
        triggers.enqueue(session, [PairRequest(job.listing_a, job.listing_b, p.name,
                                               max(NEXT_STAGE, job.priority), job.reason)],
                         stage=step.stage)
    elif step.action == DECIDE:
        write_decision(session, p.name, job.listing_a, job.listing_b, step, scores)
    # RECORD: nothing more (the audit's scores are its record)
```

The next stage keeps the job's priority when that is higher than
`NEXT_STAGE` (80), so a re-score of a standing "same" (100) stays first
through every stage (P8). The same step, over many pairs at once, is what a
trigger's pairs go through (`flow.offer`): a pair whose requests are all
scored already is decided (or recorded) there and then, with no job and no
lease, and the rest are queued at the stage they still owe.

`current_scores` renders, for each stage of the pipeline, that stage's
requests from the current rows under its current judge, and reads the
`ai_scores` rows with those (judge, request hash) pairs: freshness by request
hash, as in §1.1. A score is reusable across pipelines: two stages using the
same model and prompt version share it.

`write_decision`:

- **a revocation holds.** If the pair has a revoked decision, nothing is
  written unless at least one score the new decision uses was scored after
  the latest `revoked_at` **and** is for a request no revoked decision
  recorded: a model looked, after the revocation, at text it did not see.
  Old scores (a revert to text scored earlier, a job queued before the
  revocation) and fresh scores of the revoked text (a new model version)
  write nothing, and the step reports `blocked` (`revoked_blocked` in the
  producers' counts). Every path that decides (a trigger's offer, a result,
  a lease finding a job scored, a replay) comes through here, so this is the
  one guard. A revoked decision recorded before request hashes were kept in
  the evidence counts as having seen every text: it is never undone by the
  models (none exist in production, which had nothing deployed then);
- takes a transaction-scoped advisory lock on the pair
  (`pg_advisory_xact_lock` over a hash of pipeline and pair), so two results
  for the same pair arriving at once (two workers, two stages) serialise;
- computes both listings' **current** `hashing.listing_hash` at decision
  time and stores them as the decision's `content_sha256_a` / `_b`. Not the
  hashes on the scores: a stage may reuse a byte-identical score that was
  labelled with an older content hash (§1.1), and a decision labelled with an
  old hash would make the re-score trigger queue the pair forever;
- if a `standing` decision for (pipeline, pair) has the **same outcome**, it
  is kept, same id: its `scores`, `decided_by`, `policy_version` and content
  hashes are updated in place. A re-score that changes nothing therefore
  changes nothing the regroup or the citations see;
- otherwise marks it `stale` and inserts a new `standing` row: `outcome`,
  `decided_by = step.decided_by`,
  `scores = {stage: {"model", "model_version_id", "ab", "ba", "min"}}`,
  `policy_version = policy.ACTIVE`, the current content hashes;
- the partial unique index `uq_ai_decision_standing_pair` is the backstop:
  on a unique violation the transaction is retried once.

**Competing pairs.** When two standing "same" decisions compete for one
listing (X same as M and as N, M and N kept apart by a veto), the regroup
lets the stronger win (`AiSame.rank`: the stages' lower scores, last stage
first; ties by the pair's listing ids, never by decision id). A late Kev "no"
that blocks the winning pair can therefore let the losing pair merge instead.

The regroup reads standing "same" decisions (`decisions.load_ai_same`) at the
next rebuild, only when the mode is `live`.

**Rebuild after a window (P16).** The broker cannot see worker windows, so it
uses what it can see: when a worker ends a session, by a graceful `/release`,
or by a lease that came back empty, and new standing decisions were written
since the last rebuild the broker queued, it queues
`rebuild_and_reindex` through the existing `request_rebuild` job-id scheme
(deduplicated by window; the scheme is `makhzan_schemas.rebuild`, shared
with the worker). Only in mode `live`; in `off` nothing is queued, since the
regroup would read nothing. "Since the last rebuild the broker queued" is
`worker_state['ai_rebuild']`: `{"through_id": N}`, the highest decision id a
rebuild was queued for. The id, not `created_at`: that is the writing
transaction's start, which can lag well behind a long lease's commit. The
id is allocated at the insert, not the commit, so one case is passed over
for certain: the daily producers write decisions (pairs settled from stored
scores) inside a transaction that can run for minutes; a worker's session
that ends meanwhile records a higher id from a /results, and the producers'
lower ids, committed after, are never newer than the watermark. They take
effect at the next rebuild, the next day's at the latest. A same-outcome
re-score updates its row in place and so queues nothing. Any new standing
decision counts, "not same" included, so a "same" turned "not same" (an AI
merge to undo) is applied at the window's end (`broker.REBUILD_ON_UNMERGE =
True`, owner, 2026-11-17).

### 3.5 `POST /release`

```json
{"session": "6f1c…", "lease_id": "0b7e…", "job_ids": [81235],
 "reason": "graceful" | "error", "error": "CUDA out of memory"}
200 {"released": 1}

{"session": "6f1c…"}
200 {"released": 0}
```

**Ending a session.** A graceful release with no jobs (`job_ids` empty or
absent, `lease_id` optional) is how a worker that holds nothing ends its
session: window over, a stop signal between leases, or done after its last
results. It marks the session ended and considers the P16 rebuild, as a
release with jobs does. A worker that stops between leases should always send
it. **After an `empty` answer the broker has already ended the session, and
the worker sends no release** (§3.2; an `on_empty = "wait"` worker leases
again in the same session). A release that comes anyway keeps the recorded
end and only considers P16. An `error` release must name its jobs (422
otherwise).

The caller must hold the lease and serve the jobs' model (as for `/results`).
`graceful` (window end, SIGTERM) re-queues with no attempt counted; `error`
re-queues with `attempts + 1` and stores `last_error`; at `max_attempts`, the
job is `dead` and a `poison_job` flag is opened. Lease fields are cleared.
Scores already submitted are kept: half a job is not lost, and the next
lease carries only the order still owed. A graceful release marks the
session ended (`end_reason = "released"`), except one that comes after the
broker already ended it with `empty`, which keeps that end. P16 is considered at both session ends: a graceful `/release` and an `empty` lease (§3.4).

### 3.6 Errors

| Status | Body | Meaning |
|---|---|---|
| 401 | `{"error": "unauthorized"}` | missing, unknown or revoked token |
| 403 | `{"error": "model_not_allowed", "model": "…"}` | not in `ai_workers.models` |
| 409 | `{"error": "wrong_model", "model": "…", "session_model": "…"}` | a lease for a model the session did not say hello for (one model per session) |
| 409 | `{"error": "version", "model": "kev", "current": "…"}` | the worker's model version is not the registry's |
| 409 | `{"error": "lease_lost", "job_ids": […]}` | the caller does not hold the lease (expired, moved on, or never its own) |
| 422 | `{"error": "request_mismatch"}` / `{"error": "invalid", "detail": …}` | integrity or validation |

## 4. Lease semantics, in one place

- A job is in exactly one of `queued`, `leased`, `done`, `cancelled`, `dead`.
- Enqueueing is idempotent: one open (`queued` or `leased`) job per
  (pipeline, stage, judge, pair), enforced by `uq_ai_job_open_pair`.
- A job is leased only if at least one of its requests is unscored.
- A lease is held until `lease_expires_at`; heartbeats extend it. Only its
  holder may post results for it or release it. An expired lease counts an
  attempt against the job in hand (the worker died, for example killed for
  memory), or against every job of it when none was reported in hand; a
  graceful release does not.
- `max_attempts` (3) explicit failures or expiries make a job `dead`; it shows
  in status and is retried by hand (`./makhzan ai jobs retry ID`, which also
  closes its poison flag). A trigger never queues a pair again at a stage and
  judge where its job is dead (`triggers.enqueue`): that is the "handled by
  hand" of P6, rather than three more attempts every day.
- Flags are listed and closed by hand with `./makhzan ai flags list` and
  `./makhzan ai flags dismiss ID [ID ...] --note "why"`. Given several ids
  it dismisses the open ones, commits them, and exits 1 if any was missing
  or already closed. It always sets `resolved_at`; a flag closed by hand
  in SQL should set it too.
- Any number of workers, on any machines, may lease at once; `SKIP LOCKED`
  and the request-hash idempotency make overlap harmless.

## 5. Versions and re-scoring

- A judge is a (model key, model version, prompt version) row in
  `ai_model_versions`, created on first use from the registry
  (`triggers.model_version_id`). Device and dtype are recorded on each score,
  not in the version: GPU and CPU are one version (P8).
- A re-score is queued (by the re-score trigger, `reason = "rescore"`, into
  the pipeline the pair was in) when a listing's content hash changed or the
  judge of a stage the decision holds scores for changed. Priorities: a
  standing "same" 100; a "not same" whose text changed 60; a "not same" whose
  judge alone changed 30. If the rendered requests turn out byte-identical
  to scored ones, no model runs (`flow.offer`, §3.4). The old decision stays
  in force until the new one is written (P6); one that is due and never
  completes shows in status ("re-score due", with an open, dead or no job)
  and is handled by hand.
- A new policy (`policy.POLICIES`, `ACTIVE`) recomputes decisions from stored
  scores with `pipelines.decide(pipeline, scores, policy)`, with no model call
  (`./makhzan ai redecide --dry-run [--policy NAME]` shows what would change;
  it writes nothing).

## 5.1 The triggers (phase 2)

`ai_candidates` runs after every `rebuild_and_reindex` (job id per rebuild
window): the judge sweep, then candidates, re-scores and the audit
(`candidates.daily`). One producer run at a time (a transaction-scoped
advisory lock): a second run, daily or by hand, is skipped and says so.
`ai_listing_state` is written with upserts, and a listing that leaves the
scope (archived, or out of electronics) loses its row. The owner decisions
of 2026-11-17 are named constants: `candidates.BASELINE_FIRST_RUN`,
`candidates.REOFFER_REVOKED_ON_TEXT_CHANGE`, the `triggers.*` priorities,
`broker.REBUILD_ON_UNMERGE` and `policy.DOMAINS` (a decision acts only while
both listings are in electronics; `decisions.load_ai_same`).

- **candidates** (`match`, priority 60): electronics only (P15). A listing
  whose content hash differs from the one its candidates were last found for
  (`ai_listing_state`) gets its K = 10 nearest other-shop listings by
  title-token Jaccard (the experiments' method), plus the identifier-key
  pairs the rules split. Dropped: today's vetoes (P13), pairs the rules
  merged, pairs with an override, pairs with a standing decision in `match`
  (the re-score's), and pairs whose decision a person revoked while the
  requests they would render now are those the revoked decision recorded
  (each stage's two request hashes, kept in its evidence). A change the
  models would see offers the pair again, so they are asked again (owner,
  option (b)); a change they would not (an Arabic title under an English
  one, a `HASH_VERSION` bump) does not. A re-offered pair still cannot be
  decided from scores its revocation already saw (`write_decision`'s guard,
  §3.4). A revoked decision with no request hashes in its evidence keeps its
  pair out for good. `./makhzan ai revoke` cancels the pair's queued jobs; a
  leased one finishes and decides nothing the guard refuses. One-directional; `./makhzan ai candidates
  --mutual` also takes listings whose own top K now holds a changed one. **The
  first run on a database with no `ai_listing_state` records a baseline and
  queues nothing**: the existing catalogue is the backlog's.
- **backlog** (`match`, priority 40): `./makhzan ai backlog`, every
  listing's top K. With every listing a query, the union already holds both
  directions, so it is mutual (P1) with or without `--mutual`.
- **audit** (`audit`, priority 10, P12): every pair of listings from two
  shops in one product by the rules (neither joined by AI) never audited;
  recorded, nothing decided. Status counts those below 0.8 and below 0.05.
- **rescore**: above.

## 6. Worker configuration (phase 3)

**The worker's own documentation is `docs/ai/worker.md`, and its TOML format
(`[compute]`, `[schedule]`, ...) is defined there.** The sketch below shows
only what the broker relies on: a worker serves model keys, has a token, and
decides its own window and lease size.

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

- The worker (phase 3) and its images, and the tooling that pushes a locally
  reviewed backlog's scores and decisions to production.
- Applying a new policy: `redecide` is a dry run only.
- Writing `ai_decisions.effect` after each regroup (the columns exist; nothing
  writes them yet), and citing revoked decisions on the regroup that undoes
  them (`revoked_ai_decisions`).
- Flags other than `poison_job` and `version_drift`: P12's rules-merged
  audit is counted in status, not flagged, since no threshold is chosen; no
  `blocked_same` is written until `effect` is.
