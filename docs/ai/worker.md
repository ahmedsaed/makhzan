# AI matching: the worker

Status: **built, tested against a contract-following fake broker, and checked against the
phase 2 broker app** (six end-to-end sessions, below, run while the broker's time-fit
removal was in progress). Nothing has run on the home server yet. What is not here yet is
listed at the end.

A worker is one process that serves the one model key its configuration names: the broker
takes exactly one model per session, so two models are two workers (for example `home-kev`
and `home-pplx`, each with its own window). It talks only to the broker, with its own
bearer token, over Tailscale (`http://<tailscale-ip>:<port>`, inside the tailnet's encrypted
WireGuard tunnel; there is no public HTTPS endpoint). It loads its model once, scores the
requests the broker renders, one request per forward call, and posts the scores back. The
broker treats every worker the same. Each worker's TOML file decides what it runs, on what
hardware, and when, so two workers on one machine overlap only if their windows say so (owner
decision, 2026-11-17).

The code is `ml/makhzan_ml/worker/`, and its tests are `ml/tests/` (`make test-worker`).

The worker images build on the lean CPU images and the pplx shim from PR #57
(`ml/kev/Dockerfile.cpu-lean`, `ml/pplx/`), now on main.

| Module | What it does |
|---|---|
| `config.py` | the TOML file: parsing, validation, windows |
| `broker.py` | the HTTP client: bearer token, typed errors, retry with backoff |
| `judges.py` | loads a model in-process on the validated scoring path; no mmap; pin checks |
| `pins.py` | what each model key is pinned to (a copy of `makhzan_schemas.ai.policy.MODELS`, held equal by a test) |
| `run.py` | one session, from hello to the last release |
| `supervisor.py` | with `outside_window = "wait"`: stays up, sleeps until each window, runs that window's session in a child process |
| `proxy.py` | the broker proxy: a TCP forwarder to one fixed address, the compose stack's only way out |
| `smoke.py` | the image check CI runs before pushing (no weights, no network) |
| `fake_broker.py` | an in-process broker that follows the contract, for the tests and the parity check |
| `parity.py` | the worker's scores, end to end, against stored validated scores |

## Why it lives in `ml/` and runs the model in-process

The worker's job is to score exactly as the validated setup scored. The images that hold each
model's code and pinned packages already exist (`ml/kev`, `ml/pplx`). The CPU benchmark
(`ml/models/bench_cpu.py`) already scores in-process in those images, through each server's
own scoring function. So the worker is a thin standard-library layer
(`ml/worker.Dockerfile`) on those images, next to the other `makhzan_ml` code. It needs
neither SQLAlchemy nor the schema package.

The other way would have been to call a local serving container over HTTP. That means a
second container, a second port to keep off the network, and a second process to start and
stop with the window, for the same function calls. In-process is simpler and scores
identically:

- **Kev** goes through `kev.serve.Server.answer`, which is what `POST /v1/systemone` calls.
- **pplx** goes through the shim's `serve.build()`, then `Decider.logits` divided by the
  checkpoint's temperature, then `protocol.answer`. That is what `POST /v1/decide` computes.

The parity check below confirms it on stored GPU scores.

## Lifecycle

1. **Window.** Outside every window, what happens is `outside_window`: with `"exit"` (the
   default) the worker exits 0 and sends nothing, for something else to start it at the
   window's start. With `"wait"` it stays up and waits for the window itself (below,
   "Waiting for the window"): this is how the home server runs it, as a compose service.
2. **Pre-flight.** The model key must be loadable in this image. Each model image holds
   one model's code, so naming a key the image lacks is refused before anything is sent. If
   the container's memory limit (cgroup v2 `memory.max`) is below `memory_gib`, the worker
   refuses to start, because it would be killed mid-job and the broker would count an
   attempt. When no limit is visible (no `--memory`, or cgroup v1), the check is skipped and
   the log says so. The worker then lowers its own priority by `nice`.
3. **`POST /hello`** sends the worker's name, its one model key with its model version and
   weights revision, the image, device, dtype, threads and its configuration. The broker
   answers `ok` for the key, and the `stages` that use it: each (pipeline, stage) and the
   prompt version its leases will carry, which the worker logs. If the key is answered
   `ok: false` (version drift), nothing is leased and the worker exits 3.
4. **Lease, load, score, submit.** The worker drains its model's queue:
   - `POST /lease` carries a fresh `lease_request_id` per lease. The client's retries of
     that call send the same id, so a lease whose answer was lost on the way comes back as
     the same lease instead of being orphaned until it expires.
   - A lease asks for up to `max_jobs` jobs and sends no time (owner decision, 2026-11-17):
     the worker takes what it is given and works until its window ends. What the window's
     end interrupts goes back gracefully (step 5) for another worker or a later window.
   - Each job's `prompt_version` is compared with the ones hello announced. A mismatch is
     logged, not refused: the broker renders, so it means the registry moved since hello.
   - The model is **loaded on the first lease that brings jobs**, never on an empty night.
     Once loaded, it is checked against its pins: the snapshot revision, the temperature it
     scores at, and the prefix cache off. Then every weight file is checked to be unmapped
     (CPU). The Kev code commit is checked only where the image records it, and today's base
     images do not (see "Not done yet").
   - Each job's requests are scored **in the order the broker sent them, one per call: no
     batching, no reordering** (owner decision, 2026-11-17). Before scoring a request, the
     worker recomputes `request_sha256` over its payload. A mismatch is never scored; the job
     goes back as an error.
   - A request that fails goes back as an error, which costs the job one attempt. A job that
     fails on every lease reaches the broker's `max_attempts` and is dead (a poison job), and
     the worker carries on. If the model fails on 3 different jobs in a row, it is broken: the
     worker stops, and the jobs it never started go back without costing an attempt.
   - The worker sends `POST /results` once per job.
   - As each job starts, a heartbeat names it in `progress.job_id`, the job in hand. If the
     worker then dies (a crash, a kill for memory), the expired lease charges an attempt to
     that job alone; the lease's other jobs never started and go back free.
   - While a lease is held, a background thread also sends `POST /heartbeat` every `heartbeat_s`
     with the lease ids, the job ids it still holds, the resident memory and the request in
     progress. A `409 lease_lost` names the jobs and leases that moved on. The worker drops
     those after its current request, without posting them, and keeps the rest. If the broker
     queues a dropped job again, it is scored afresh whenever it comes back.
5. **Graceful stop** happens at the window's end, on SIGTERM or on SIGINT: the current job
   is dropped. A timer enforces
   the window's end, and it is also checked between retries, with no backoff sleeping past
   it. So a call retrying through a broker outage cannot keep the model loaded past the
   window while the next worker on the machine loads its own:
   - no new request is started, and the one in flight finishes (a forward pass cannot be
     interrupted);
   - finished orders are submitted, so half a job is kept;
   - the rest of the lease, the current job's unscored orders included, goes back with
     `POST /release`, reason `graceful`, which counts no attempt; another worker or a later
     window picks it up;
   - the model is unloaded.
6. **Empty queue.** With `on_empty = "exit"`, the session ends (and with `outside_window =
   "exit"` the worker exits). With `"wait"`, it polls every `poll_s` until the window ends.
7. **Session end, exactly once.** The broker records a session's end at an empty lease
   ("empty") or at a graceful release, with jobs or without ("released"). The worker ends
   every session it opened exactly once:
   - when one of those already ended it, nothing more is sent (a session release would
     overwrite "empty" with "released");
   - otherwise (stopped between leases with nothing held: the window's end, a signal, an
     error, a 403 for a model key) it sends `POST /release {"session"}`, a
     graceful release naming no jobs (broker-api.md §3.5);
   - nothing is sent to a broker that is unreachable or refused the token (401);
   - a stop that comes before hello opens no session at all.

### Waiting for the window

With `[schedule] outside_window = "wait"` the process never exits on its own. It becomes a
supervisor (`supervisor.py`) that loads no model and runs no thread of its own:

1. Outside every window it logs `sleeping until 01:00 (Africa/Cairo)` and sleeps until the
   next window opens, re-measuring against the wall clock at least every 15 minutes.
2. When the window opens it logs `window open` and forks a child that runs one ordinary
   session, steps 2 to 7 above, exactly what a worker started at the window would run: hello,
   leases, the model loaded on the first lease with jobs, and at the window's end the
   graceful stop (the request in flight finished, its scores submitted, the rest of the lease
   released, the session ended, the model unloaded).
3. The child then exits, and with it every byte the model, torch and the allocator held:
   nothing depends on `free()` returning memory to the system. The supervisor logs `window
   closed; model unloaded` and sleeps until the next window. Between windows the container
   holds the supervisor's few tens of MB.
4. It loops until SIGTERM or SIGINT. While asleep, it exits 0 at once. During a window, it
   forwards the signal to the child, which stops gracefully, and exits with the child's code.

The combinations with `on_empty`:

- `on_empty = "exit"`: an empty queue ends that window's session early, the model is freed,
  and the supervisor sleeps until the next window (not the rest of this one; touching windows
  count as one).
- `on_empty = "wait"`: the child keeps polling every `poll_s` until the window's end, with
  the model held once loaded.

A session that fails is logged and the supervisor sleeps until the next window: a model that
will not load, version drift, a refused token or a child killed (for memory, say) would only
fail again if retried at once, and a compose `restart: unless-stopped` would turn an exit into
a loop. Only an unreachable broker (exit 4) is tried again inside the window, every
`poll_s`. With `windows = "always"` there is no next window: a session that ended is started
again after `poll_s`.

The child is a fork rather than a new interpreter so that it starts at once and shares the
supervisor's configuration; the parent has imported nothing but the worker's
standard-library modules (torch is imported in the child, by the load), and SIGTERM and
SIGINT are blocked across the fork, so a signal arriving meanwhile reaches the child once its
handlers are in place. `nice` is applied in each child, so it does not accumulate across
windows.

**Retries.** A network failure, a 5xx or a 429 is retried with exponential backoff: 1 s, 2 s,
4 s and so on, capped at 60 s, and never shorter than a `Retry-After`. Retries continue for
up to `retry_max_s` in all. A 4xx is the broker's answer and is not retried. Redirects are
refused rather than followed, so the token is never sent anywhere else.

Proxy settings in the environment are ignored: the only peer is the broker.

**A stop sets one deadline for the rest of the session.** No retry starts more than 60 s
after the stop (`STOP_GRACE_S`), each attempt then times out after 10 s (`STOP_TIMEOUT_S`),
and a call in backoff wakes at once. Every call still makes one attempt. So after SIGTERM
the worker exits within:

| Part | At most |
|---|---|
| what is in flight at the stop, which cannot be interrupted: a request | 86 to 104 s on the home server's CPU, under 1 s on the GPU |
| or a model load | about 150 s on the home server's CPU (Kev 130 s, pplx 73 to 95 s measured), under 10 s on the GPU |
| or, on the GPU, a first request that compiles Kev's Triton kernels | about 60 s, unless the Triton cache is mounted (it must be, see below) |
| retries (`STOP_GRACE_S`) | only within 60 s of the stop, so they overlap what is in flight |
| one last attempt each for the calls still due: results, the lease release, the session release (`STOP_TIMEOUT_S`) | 10 s each, at most 3 × 10 s |
| joining the heartbeat thread | 10 s |

The 60 s for retries starts at the stop, not after what is in flight. So the bound is the
longer of the two (in flight, or 60 s), plus one 10 s attempt per call still due, plus 10 s
for the heartbeat join:

- the slowest measured CPU request: 104 s, then results, the lease release and the session
  release, 3 × 10 s, then the join: about 144 s;
- a CPU model load: about 150 s, then only the lease's release (no results to post; that
  release ends the session, so no session release follows), then the join: about 170 s;
- the GPU: the 60 s of retries outlast any request, then 3 × 10 s and the join: about 100 s.

Anything still undelivered is logged before the process exits. Set the stop timeout above
the bound: 240 s on the home server's CPU (`stop_grace_period: 240s` in its compose stack),
120 s on the GPU (`--stop-timeout 120`).

**Never drop a result silently.** A score is logged at ERROR as `UNDELIVERED`, with its job,
order, request hash and score (never the payload), the moment it is known not to have
arrived: the broker unreachable past the retry budget or the stop deadline, the broker
refusing it (a 409 lease_lost, a 422, any other 4xx), or an unexpected error while posting.
A summary is logged at exit on every path. When the session would otherwise have exited 0,
the exit code says so (6); otherwise the code names what ended the session (for example 4).
A score never posted because a heartbeat found its lease lost is dropped with a WARNING: the
job's new holder scores it again.

**Unexpected errors** end the session with exit 1. These are a broker answer with no
handling (400, 404, 413), a malformed reply, or a bug. The jobs still held go back
gracefully first, unless the broker is unreachable; in that case they return when their
leases expire.

Payloads are never logged or written to disk. The token is sent only in the Authorization
header.

### Exit codes

With `outside_window = "wait"` these are each window's session's codes, which the supervisor
logs; the process itself exits only on a signal (0 while asleep, else the session's code) or
for a configuration it cannot read (2).

| Code | Meaning |
|---|---|
| 0 | the window ended, the queue was empty (`on_empty = "exit"`), or the worker started outside its window; with `outside_window = "wait"`, a SIGTERM while asleep |
| 1 | the model failed on 3 different jobs in a row, or an unexpected error |
| 2 | configuration error, memory limit below `memory_gib`, or a model that will not load as pinned. Its lease goes back gracefully: the fault is the worker's, so the jobs are charged no attempt |
| 3 | version drift: the broker's registry runs another model version (at hello, or 409 at lease) |
| 4 | the broker could not be reached for `retry_max_s`; undelivered scores are logged |
| 5 | 401 or 403: the token is wrong or revoked, or the worker is not registered for a model key |
| 6 | the session ended, but the broker refused some scores; they are logged |

## Configuration reference

The configuration is one TOML file, by default `/etc/makhzan-ai/worker.toml` inside the
container. Unknown sections and keys are errors. Relative paths resolve against the file's
directory. `python -m makhzan_ml.worker --config FILE --check` validates a file, checks that
this image can load the model key, and exits.

### `[worker]`

| Key | Default | Meaning |
|---|---|---|
| `name` | required | the worker's name, as registered (`ai_workers.name`) |
| `broker_url` | required | the broker's base URL over Tailscale, `http://<tailscale-ip>:<port>/ai/v1`, or the compose stack's proxy, `http://broker-proxy:8100/ai/v1` (with `broker_via_proxy`). Plain `http://` is accepted only to a Tailscale address (100.64.0.0/10, fd7a:115c:a1e0::/48) or a loopback one (127.0.0.0/8, ::1: the tests, the parity check, a broker on the same machine), and only as an address, never a name (not even `localhost`) and with no zone id, unless `broker_via_proxy` is set; a malformed port is refused at load; anything else must be `https://` |
| `broker_via_proxy` | `false` | `true` also accepts plain `http://` to a compose service name: one DNS label with a letter in it, no dots, nothing the resolver reads as an address (`1234`, `0x7f000001`). For the broker proxy on the worker's internal Docker network, which has no other route out and forwards only to the broker's Tailscale address. Off, a name is refused as before |
| `token_file` / `token` | exactly one | the bearer token, preferably as a file (a Docker secret or a read-only mount) |
| `ca_file` | system CAs | for an `https://` broker only: a CA bundle to trust instead, for a privately signed certificate |
| `model` | required | the one model key served, from `policy.MODELS`: `"kev"` or `"pplx"`. The broker takes one model per session, so two models are two workers. A key the image cannot load is refused at start and by `--check`. The older `models = ["kev"]` is still read when it names exactly one key |

### `[model.<key>]` (optional)

| Key | Meaning |
|---|---|
| `expect_version` | the model version this configuration was written for. The file is refused if the image serves another version: the image or the configuration is stale |

### `[compute]`

| Key | Default | Meaning |
|---|---|---|
| `device` | `"cpu"` | `"cpu"` or `"gpu"` |
| `dtype` | `fp32` on CPU, `bf16` on GPU | only the validated pairing is accepted. GPU bf16 and CPU fp32 are one model version (P8), and each score records its device and dtype |
| `threads` | the container's CPU quota | the CPU cap: `torch.set_num_threads` and `set_num_interop_threads`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS`. Unset on CPU, it is the cgroup quota (`--cpus=6` gives 6), else the CPUs the process may run on, never the host's core count |
| `nice` | 10 on CPU, 0 on GPU | how much the worker lowers its own priority (0 to 19) |
| `memory_gib` | unset | the expected peak resident memory. The worker refuses to start under a smaller container limit and warns if a load peaks above it. Measured on CPU fp32: Kev 17.5 GiB, pplx 18.4 GiB |
| `mmap` | `false` on CPU, `true` on GPU | `false` reads every weight file with pread(2) and fails the load if any weight file is still mapped afterwards |
| `weights_cache` | the image's `HF_HOME` | the Hugging Face home holding `hub/`, mounted read-only. The worker always runs offline |

### `[schedule]`

| Key | Default | Meaning |
|---|---|---|
| `windows` | `"always"` | `"always"`, or one or more `"HH:MM-HH:MM"` in local time. A window may cross midnight (`"22:00-02:00"`). Windows that touch or overlap run on as one |
| `timezone` | required with windows | an IANA zone such as `"Africa/Cairo"`. Required whenever `windows` is not `"always"`: a container's local time is UTC unless told otherwise, so a window without a zone would run at the wrong hours |
| `on_empty` | `"exit"` | `"exit"` or `"wait"` |
| `outside_window` | `"exit"` | `"exit"`: outside every window, exit 0 (started by something else at the window). `"wait"`: stay up, sleep until each window, run its session in a child process that exits at the window's end ("Waiting for the window") |
| `poll_s` | 600 | with `"wait"`, how often to ask for work again; at least 5 |

### `[leases]`

| Key | Default | Meaning |
|---|---|---|
| `max_jobs` | 2 | jobs per lease (a job is one pair, up to two requests). "Batch" means this, never batched inference |
| `lease_s` | 900 | the lease length the worker reports at hello, an integer from 60 to 7200 (the broker refuses any other) |
| `heartbeat_s` | 60 | at least 5, and at most half of `lease_s`. If the broker's hello answers a shorter interval, that one is used |
| `retry_max_s` | `lease_s` | how long to retry a call through network failures before giving up |

## Example configurations

These four are examples. The home server's windows are the owner's (Kev 01:00–05:00, pplx
05:05–07:00, Cairo time); the desktop's run until their queue is empty. Hosts and tokens are
placeholders. The worker's tests parse every block below, and the compose stack's two files.

The home server's Kev worker, as `ml/deploy/home-server/home-kev.toml` has it: through the
compose stack's broker proxy, waiting for its window:

```toml
# home-kev.toml
[worker]
name = "home-kev"
broker_url = "http://broker-proxy:8100/ai/v1"
broker_via_proxy = true
token_file = "/run/secrets/makhzan-ai-token"
model = "kev"

[model.kev]
expect_version = "kev-4b@6cfce5c2fa4b+kev-6b719c3+T1.0"

[compute]
device = "cpu"
dtype = "fp32"
threads = 6
nice = 10
memory_gib = 20
mmap = false
weights_cache = "/models"

[schedule]
windows = ["01:00-05:00"]
timezone = "Africa/Cairo"
outside_window = "wait"
on_empty = "exit"

[leases]
max_jobs = 2   # 4 requests, about 6 minutes on this CPU (about 86 s a request)
lease_s = 900
heartbeat_s = 60
```

The home server's pplx worker. Its window follows Kev's, so the two never share the memory
and starts 5 minutes after Kev's ends, since Kev's graceful stop can run about 4 minutes past
05:00:

```toml
# home-pplx.toml
[worker]
name = "home-pplx"
broker_url = "http://broker-proxy:8100/ai/v1"
broker_via_proxy = true
token_file = "/run/secrets/makhzan-ai-token"
model = "pplx"

[model.pplx]
expect_version = "pplx-decider-flash-v1.3@d06fb3f2d97e+T1.3303"

[compute]
device = "cpu"
dtype = "fp32"
threads = 6
nice = 10
memory_gib = 20
mmap = false
weights_cache = "/models"

[schedule]
windows = ["05:05-07:00"]
timezone = "Africa/Cairo"
outside_window = "wait"
on_empty = "exit"

[leases]
max_jobs = 2
lease_s = 900
heartbeat_s = 60
```

The desktop's GPU workers, for a backlog. They run until the queue is empty. Run one at a
time: each 4B model needs most of the 12 GB card.

```toml
# desk-kev.toml
[worker]
name = "desk-kev"
broker_url = "http://<tailscale-ip>:<port>/ai/v1"
token_file = "/run/secrets/makhzan-ai-token"
model = "kev"

[model.kev]
expect_version = "kev-4b@6cfce5c2fa4b+kev-6b719c3+T1.0"

[compute]
device = "gpu"
dtype = "bf16"
weights_cache = "/models"

[schedule]
windows = "always"
on_empty = "exit"

[leases]
max_jobs = 32
lease_s = 600
heartbeat_s = 60
```

```toml
# desk-pplx.toml
[worker]
name = "desk-pplx"
broker_url = "http://<tailscale-ip>:<port>/ai/v1"
token_file = "/run/secrets/makhzan-ai-token"
model = "pplx"

[model.pplx]
expect_version = "pplx-decider-flash-v1.3@d06fb3f2d97e+T1.3303"

[compute]
device = "gpu"
dtype = "bf16"
weights_cache = "/models"

[schedule]
windows = "always"
on_empty = "exit"

[leases]
max_jobs = 32
lease_s = 600
heartbeat_s = 60
```

## Images

`ml/worker.Dockerfile` adds the worker to a model image. Its build context is `ml/`, whose
`.dockerignore` sends only the worker's code, never the weights cache or `ml/out/`. No image
holds model weights: they are mounted from the host at run time.

**The CPU workers come from GHCR.** `.github/workflows/ai-worker-images.yml` builds
`kev-worker-cpu` and `pplx-worker-cpu` on every push to `main` that touches `ml/` (and on
demand); the steps are in `ai-worker-image-build.yml`. Each is one chain, from
`ml/docker-bake.hcl`: the lean model image (`ml/kev/Dockerfile.cpu-lean`,
`ml/pplx/Dockerfile.cpu-lean`), then the worker layer on exactly that build, through a named
context, so no registry tag or local image comes between them.

One build both loads the image on the runner and, on `main`, pushes it to GHCR by digest,
untagged, in the same step: the push comes **before** the checks below, which run on the
loaded copy of that same build:

- `python -m makhzan_ml.worker.smoke --model <key> --expect-revision <commit>` runs in it
  with `--network none`, read-only, all capabilities dropped: torch sees no CUDA device and
  `fla` is absent, the model's code and (for Kev) its pinned commit are present, no
  weight-named file is in the image, the entrypoint's `--check` passes, a whole session runs
  against the fake broker with a fake judge, the same runs through the supervisor's forked
  child, the broker proxy forwards over loopback to a test listener (a `CONNECT` to another
  host included) and refuses a name as its target, and the image records the commit built;
- a scan of the exported filesystem fails on any file over 100 MB that is not a shared
  library, whatever it is called.

When both pass, the run checks that the registry's image is the one tested (same config), puts
the `sha-<commit>` tags (long and short) and `latest` on that digest, and prints the digest in its summary.
`latest` is attached by that same step, on `main` only, so it only ever points at a digest that
passed every check; a pull request or other branch tags nothing.
Only runs on `main` push, and only they hold `packages: write`; pull requests touching
`ml/`, and manual runs from other branches, build and test without pushing.

**A failed run on `main` leaves an untagged image in GHCR.** It was pushed before the checks
failed, and nothing deletes it: it carries no tag and appears in no summary. That is accepted
because the build context of each image is an allow-list that never holds weights (`ml/kev`,
`ml/pplx`, and `ml/` through its `.dockerignore`), and because the server only ever runs
`latest`, which points only at a tested digest, and records the digest it resolved to. Deleting
it from CI was considered and left out.
It is not known that `GITHUB_TOKEN` may delete versions of a user-owned package. And the pushed
digest is an index whose platform manifest is its own package version, shared with any earlier
build of the same content, so deleting it could break an image already in use.

```bash
docker pull ghcr.io/ahmedsaed/makhzan/kev-worker-cpu@sha256:<digest>
docker pull ghcr.io/ahmedsaed/makhzan/pplx-worker-cpu@sha256:<digest>
```

**Each image names itself at hello.** A container cannot see its own digest, so the build
bakes in what it is: CI passes the commit it builds and the GHCR repository into the bake
(`REVISION`, `IMAGE_REPO`), and the worker layer records them as `MAKHZAN_IMAGE_REVISION` and
`MAKHZAN_IMAGE_REPO`, last, so a new commit rebuilds only that layer. At hello the worker
reports `ghcr.io/ahmedsaed/makhzan/<image>:sha-<commit>`, the tag CI puts on exactly the
tested build of that commit, and the broker keeps it with the session (`ai_sessions.hello`,
free text). `MAKHZAN_IMAGE`, when set, overrides it (a digest, or a local build's id). A local
build without a revision says `makhzan-ml/<image>:local`. The smoke test checks, in CI, that
the image records the commit being built. The home server runs `:latest` through compose,
and the broker's record names the commit `latest` was when it was pulled.

A build whose pins changed (a new model version) is refused by the worker's `expect_version`
check until its configuration is updated, so a `latest` that moved never scores under a stale
configuration. To roll back, run an older `sha-<commit>` tag of the same image.

Both are public. The upstream code is
Apache-2.0: Kev's source (github.com/jaredpalmer/kev) ships its `LICENSE` in `/opt/kev`, and
the pplx-decider package's `LICENSE` and `NOTICE` come from the pinned Hub revision into
`/opt/pplx`. The images carry `org.opencontainers.image.licenses`, `.source` and `.revision`
labels, and the Kev images `dev.makhzan.kev.commit`.

The same chain builds locally, from the repository root:

```bash
docker buildx bake -f ml/docker-bake.hcl kev-worker-cpu --load    # makhzan-ml/kev-worker-cpu:local
docker run --rm --network none --entrypoint python makhzan-ml/kev-worker-cpu:local \
  -m makhzan_ml.worker.smoke --model kev
```

**The GPU workers (~26 GB) stay local builds.** Build the base images first (`ml/kev`,
`ml/pplx`; see `ml/README.md`), then build from the `ml/` directory:

```bash
docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/kev:1.0 \
  --build-arg IMAGE_REPO=makhzan-ml/kev-worker-gpu --build-arg REVISION="$(git rev-parse HEAD)" \
  -t makhzan-ml/kev-worker-gpu:1.0 ml
docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/pplx-decider:1.3 \
  --build-arg IMAGE_REPO=makhzan-ml/pplx-worker-gpu --build-arg REVISION="$(git rev-parse HEAD)" \
  -t makhzan-ml/pplx-worker-gpu:1.0 ml
```

A local base is referenced by tag, so `FROM` cannot pin it by digest. The desktop run command
passes the built image's id as `MAKHZAN_IMAGE`, which the worker reports at hello.

The Kev images record the Kev code commit they were built from as `MAKHZAN_KEV_COMMIT`
(`ml/kev/Dockerfile*`), and the worker refuses to load Kev if it differs from its pin. A Kev
base built before that change records none, and the worker only logs that.

## Running on the home server (CPU, capped)

The home server runs both CPU workers as one compose stack, `ml/deploy/home-server/`: a
folder with `compose.yml`, a `.env` (from `.env.example`), the two worker TOMLs and their token
files. No systemd timers and no host firewall rules. Its README says how to set it up.

```bash
docker compose up -d                            # start, and after any change
docker compose pull && docker compose up -d     # update to the latest tested images
docker compose logs -f kev                      # sleeping until 01:00, window open, ...
```

- **Scheduling.** Each worker stays up with `outside_window = "wait"` ("Waiting for the
  window") and `restart: unless-stopped`: Kev 01:00–05:00, pplx 05:05–07:00, Africa/Cairo.
  **One model at a time on the machine** (the owner's rule: 31 GB in all, other services
  running) is guaranteed by the two windows not overlapping, by a 5-minute gap after Kev's
  window, which covers its graceful stop running about 4 minutes past 05:00 (a request in
  flight, up to about 104 s, or a model load, about 150 s, then its last posts), and by each
  window's session running in a child process that exits at the window's end, so the memory
  is back before the next window. `ml/tests/test_worker_deploy.py` holds the gap.
- **The caps**, per worker: `cpus: 6` with `threads = 6`, `cpu_shares: 256` (anything else on
  the machine wins contention) and `nice = 10` (applied by each session), `mem_limit: 20g`
  with `memswap_limit: 20g` (no swap), `read_only: true` with a 256 MB tmpfs `/tmp` and
  `HOME=/tmp`, `cap_drop: [ALL]`, `no-new-privileges`, `user` from `.env`, `init: true`, and
  `stop_grace_period: 240s`, which covers the bound under "A stop sets one deadline": about
  144 s for the slowest CPU request in flight, about 170 s for a model load in flight.
- **Mounts**, read-only: the weights at `/models` (a Hugging Face home whose `hub/` holds the
  pinned snapshots as real files, copied with `rsync -L`), the worker's TOML at
  `/etc/makhzan-ai/worker.toml`, and its token at `/run/secrets/makhzan-ai-token`.
  `--user` must be able to read all three.
- **`TZ=Africa/Cairo`** sets the log's timestamps only; the windows are read in the TOML's
  `timezone`.
- **Updates.** `docker compose pull && docker compose up -d` recreates a worker whose image
  changed; a recreated worker stopping mid-window does the graceful stop. A build whose pins
  changed is refused by `expect_version` until the TOMLs follow. To roll back, set `KEV_IMAGE`
  or `PPLX_IMAGE` in `.env` to an older `sha-<commit>` tag (the digest is in that run's
  summary).

**Egress to the broker only, inside compose.** The workers are on `broker-only`, a Docker
network with `internal: true`: no route out, no DNS beyond the stack's service names. Their
one way out is `broker-proxy`, which sits on that network and on an ordinary bridge and
forwards one TCP port to the broker's Tailscale address (`BROKER_TARGET`), and nothing else.
It is our own code, `python -m makhzan_ml.worker.proxy --listen 0.0.0.0:8100 --to <ip>:8100`
(standard library asyncio), run from the Kev worker image with no model loaded, read-only,
no capabilities, non-root, 128 MB. It reads no request, so nothing a worker sends can name
another destination (a `CONNECT` or an absolute URL is only bytes delivered to the broker,
which refuses them), and its target must be an IP, never a name. The host's Tailscale client
carries its traffic to the broker, encrypted. The workers' `broker_url` is
`http://broker-proxy:8100/ai/v1` with `broker_via_proxy = true`.

`internal: true` alone leaves the host an address on the network's bridge, and a container
could reach host services listening on all interfaces through it (the end-to-end run below
reached sshd that way). The network therefore sets `com.docker.network.bridge.inhibit_ipv4`,
which leaves the host without one; it needs a recent Docker Engine, and the stack's README
has the check to run after `up -d`.

**End to end, with fake components (2026-11-19).** The stack was run on the desktop from
local bake builds (`makhzan-ml/{kev,pplx}-worker-cpu:e2e`), unchanged but for an override that
added a fake broker container (`fake_broker`, on the proxy's bridge at a fixed address standing
in for the broker's Tailscale address) and wrapped the workers' own entrypoint with a fake
judge that holds 1.5 GB while loaded and takes 20 s a request; windows a few minutes long.
Kev had two windows (03:38–03:40, 03:43–03:44) and pplx one (03:40–03:42):

- **The cycle**, in each worker's log: `sleeping until 03:38 (Africa/Cairo)`, then `window
  open` at 03:38:00.000, hello through the proxy, the model loaded in a child (pid 14). At
  03:40:00 the window ended mid-job: the request in flight finished, its job was submitted,
  the next job went back with a graceful release, the model was unloaded, the session ended
  "released", and the supervisor logged `window closed; model unloaded` and `sleeping until
  03:43`. The second window ran in a new child (pid 17) and ended the same way, then
  `sleeping until Fri 03:38`. pplx opened at 03:40:00, as Kev's closed, and did the same. The
  broker's record had three sessions, each ended once, no attempt charged, and hello's image
  `makhzan-ml/kev-worker-cpu:sha-<commit>` from the baked revision.
- **Memory** (`docker stats` every 10 s): 14.7 MiB per worker while asleep, 1.53 GiB while
  the fake model was loaded, back to 14.7 MiB within 10 s of each window's end, and never
  both workers loaded at once. The proxy used 12.5 MiB.
- **Stop**: `docker compose stop kev` while it slept took 0.16 s, exit code 0.
- **Egress**, from inside the Kev container: the proxy connected, and a POST through it got
  the broker's 401. The broker's address directly, 1.1.1.1:443, docker0 and DNS for any
  outside name all failed (network unreachable, no resolution). With `internal: true` alone,
  the network's gateway (the host's address on the bridge) accepted a connection to sshd;
  with `inhibit_ipv4` the network has no gateway address and ports 22, 5432 and 6379 there
  were refused.

## Running on the desktop (GPU) for a backlog

The owner decides when a backlog runs (P10). A desktop GPU worker connects to the broker and
drains the queue. Only one 4B model fits on the 12 GB card, so run Kev first, then pplx:

1. Make sure nothing else holds the card: `docker ps` and `nvidia-smi`. Stop any
   `ml/docker-compose.yml` model services.
2. Start `desk-kev`. It exits by itself when the Kev queue is empty (`on_empty = "exit"`):

   ```bash
   NAME=desk-kev IMAGE=makhzan-ml/kev-worker-gpu:1.0   # then desk-pplx, makhzan-ml/pplx-worker-gpu:1.0
   docker run --rm --name "makhzan-ai-$NAME" --init --stop-timeout 120 --gpus all \
     --user "$(id -u):$(id -g)" --tmpfs /tmp -e HOME=/tmp \
     -e MAKHZAN_IMAGE="$(docker image inspect -f '{{.Id}}' "$IMAGE")" \
     -v "<ml cache>/huggingface:/models:ro" \
     -v "<ml cache>/triton:/tmp/.triton" \
     -v "<config dir>/$NAME.toml:/etc/makhzan-ai/worker.toml:ro" \
     -v "<config dir>/$NAME.token:/run/secrets/makhzan-ai-token:ro" \
     "$IMAGE"
   ```

   `<ml cache>` is the main checkout's `ml/.cache`. The Triton cache must be writable;
   without it, the first request spends about 60 s compiling Kev's fused kernels.
   `--stop-timeout 120` covers the stop bound on the GPU, about 100 s: the 60 s of retries
   outlasts any GPU request, then 3 × 10 s of last attempts and the 10 s heartbeat join.
3. When it has exited, start `desk-pplx` the same way. Each Kev pass queues its pplx stage
   at the broker, so pplx work appears as Kev drains.
4. `docker stop makhzan-ai-desk-kev` stops it gracefully at any time. Its leased jobs go back
   with no attempt counted, and a later run carries on.

The home server's workers may run at the same time. Leasing skips locked jobs, so two
workers never get the same job (P16).

For a backlog scored against a local copy (P4), the broker runs on the desktop too. Add
`--network host` and set `broker_url = "http://127.0.0.1:<port>/ai/v1"`. Plain HTTP is
accepted for a loopback address only.

## Parity with the validated scores

`python -m makhzan_ml.worker.parity` checks the worker end to end against stored scores. It
serves real requests from the CPU benchmark's request files (`ml/out/bench-cpu/requests/`,
git-ignored, each line carrying its desktop GPU score) through `fake_broker` on 127.0.0.1. A
real worker then runs the whole protocol (hello, lease, request-hash check, scoring, results,
release) with the real model loaded by `judges.load`. It needs no network, so it runs with
`--network none`, and its report carries no catalogue text:

```bash
docker run --rm --network none --gpus all --user "$(id -u):$(id -g)" --tmpfs /tmp -e HOME=/tmp \
  -v "<ml cache>/huggingface:/models:ro" -e HF_HOME=/models -v "<ml cache>/triton:/tmp/.triton" \
  -v "<ml>/out/bench-cpu/requests:/req:ro" -v "<out dir>:/o" \
  --entrypoint python makhzan-ml/kev-worker-gpu:1.0 -m makhzan_ml.worker.parity \
  --model kev --device gpu --requests /req/kev-K2-150.jsonl --n 20 --out /o/parity-kev.json
# and the same for pplx: makhzan-ml/pplx-worker-gpu:1.0, --model pplx, /req/pplx-K1-full.jsonl
```

**Result (2026-11-17, desktop RTX 3060, GPU bf16).** The first 20 requests (10 pairs, both
orders) of each model's benchmark file were compared with the GPU scores stored in that file.
Those scores were made by the compose services over HTTP when the prompt grid was run.

| Model | Requests | Equal to the stored score | Max abs. difference | Decision flips | Scores span | At or above threshold |
|---|---|---|---|---|---|---|
| Kev (K2-150, threshold 0.80) | 20 | 20 | 0.0 | 0 | 0.0002 to 0.9896 | 7 |
| pplx (K1-full, threshold 0.95) | 20 | 20 | 0.0 | 0 | 0.0062 to 0.9863 | 4 |

All 40 scores are bit-identical to the stored ones. Both loads checked out against the pins:

- Kev: snapshot `6cfce5c…`, temperature 1.0, fused kernels on, prefix cache off. (The first run
  also reported code `6b719c3`, but that came from the worker image's own default and proved
  nothing; the default is gone, see "Not done yet".)
- pplx: snapshot `d06fb3f…`, temperature 1.3303.

Both loaded offline from the read-only cache, and each session ended with exit 0. The GPU
time was under a minute in all. These runs came before the review fixes (a later commit),
which do not touch the scoring calls; Kev was run again on the GPU after them, with the same
result.

**On CPU, through the worker.** Run the same day on the desktop's CPU under the home
server's caps: `--cpus=6 --memory=20g --memory-swap=20g`, 6 threads, fp32, no mmap,
read-only cache, `--network none`. The first 4 requests (2 pairs) of each file were scored.

| Model | Against the CPU benchmark's CPU scores | Against the GPU scores | Peak RSS | Seconds a request |
|---|---|---|---|---|
| Kev | equal to the stored digit (desktop runs; the home server's run where it overlaps) | max 0.024, no flips | 16.8 GiB | 17 to 20 |
| pplx | within 6e-7 (desktop runs) | max 0.0022, no flips | 17.6 GiB | 21 to 30 |

- No weight file was mapped after either load.
- The differences from the GPU scores are the known fp32/bf16 difference, which P8 counts as
  one model version.
- pplx's 6e-7 against its own earlier CPU run is fp32 rounding noise. It is not
  bit-identical, as Kev is; why is not known, and it changes no decision.

## Against the phase 2 broker

The worker was also run against the real broker app (`app.broker.main`, branch
`feat/ai-broker`, PR #59), on a test database seeded with fictional listings. The broker was
served by uvicorn on the test's event loop, and the real worker ran with a fake judge in a
thread, over HTTP. Run last on 2026-11-17 against the broker worktree's state while its
time-fit removal was in progress (its committed tip, `91f1f99`, still had time fit); six
sessions:

- **Kev, then pplx, as two workers.** A Kev worker leased, scored and posted two match
  pairs; the broker queued their pplx stage, and a pplx worker drained it. The result was
  two standing "same" decisions and 8 score rows carrying the device, dtype and threads.
  Each hello named one model and got its stages back; each session ended at its empty lease
  ("empty"), with no release after it.
- **The broker refuses a hello naming two models** (422).
- **A graceful stop.** A heartbeat with `job_ids` and an integer `progress.job_id` was sent
  mid-job. SIGTERM on the third request kept the finished order, and the two jobs not
  finished went back with no attempt counted. The session ended "released".
- **Session end between leases.** SIGTERM right after a job's results, with nothing held:
  the session release ended the session.
- **A lease whose answer is lost.** The broker leased two jobs and the answer was dropped.
  The client's retry, with the same `lease_request_id`, got the same lease back. Both jobs
  were scored once, none charged an attempt.
- **The window's end drops the current job.** A lease with no time fields got both queued
  jobs. A 90 s request started a minute before the window's end; when it finished, its
  order was posted, both jobs went back gracefully (no attempt), and the session ended
  "released".

No heartbeat was refused in any session.

That test lives outside this branch: it uses the broker suite's fixtures, so it belongs with
them once both branches are merged.

## Tests

`make test-worker` runs `ml/tests/` with the ingestion environment. It needs no database and
no model. CI runs it with the ingestion suite.

- **Configuration**: defaults, every refusal (empty strings included), windows (crossing
  midnight, touching windows, boundaries, UTC and no time zone), and every example in this
  document.
- **Lifecycle**, against the fake broker with a fake judge and clock:
  - a full session, and the payloads scored exactly as sent, in order;
  - an empty queue with `exit` and with `wait`, and starting outside the window;
  - a window closing across midnight, a half-scored job, SIGTERM, and a request that would
    overrun;
  - retries with backoff and `Retry-After`, a broker that stays down, and a refused result;
  - heartbeats that keep a lease alive past its length, that name their jobs, and that
    drop a lost lease; a lost job scored again when it comes back;
  - undelivered scores logged at once, and when a fatal error ends the session; one stop
    deadline for the session, with short socket timeouts; the window's end stopping a session
    that is retrying through an outage, and unloading the model; an unexpected broker answer,
    a malformed hello, an unexpected error mid-lease, each handing the jobs back; heartbeats
    that never name a finished job; a redirect refused; proxy settings ignored; a model the
    image cannot load; threads from the CPU quota; seconds left counted in real time across
    a DST change;
  - version drift at hello and at lease;
  - a tampered payload, a failing request, a model that keeps failing, and a model that
    will not load;
  - a wrong token, a key not granted, a memory limit too small, and two models run as two
    workers (one session each);
  - every session ending exactly once (window end, SIGTERM, empty queue, a fatal error,
    SIGTERM mid-lease, a 403 at lease), none sent to a broker that is down or refused the
    token, and none opened by a stop before hello;
  - the window's end dropping the current job (its finished order posted, the rest released
    gracefully); leases asking for `max_jobs` only, with no time fields; a lost lease
    answer retried into the same lease, and a retry keeping its request id;
  - heartbeats that keep naming a job whose final results are retrying; results refused
    with a 409 logged as undelivered; no release naming a job found lost; no lost warning
    for a job being settled; a heartbeat naming each job as it starts, before its results,
    with an integer job id; a crash charged to the job in hand alone; an unannounced prompt
    version logged.
- **Waiting for the window** (`test_worker_supervisor.py`), with a fake clock across several
  windows and days: the model loaded only inside a window and unloaded by its end, never two
  loads without an unload, nothing held while asleep, one session per window ended once at
  the broker; the sleep messages; sleeps chunked and landing on the window's start; an empty
  queue with `on_empty = "exit"` sleeping until the next window, touching windows counted as
  one; a stop during a window graceful and final; an unreachable broker retried inside the
  window, other failures (and a child killed by a signal) waiting for the next; `always`
  restarting after `poll_s`; SIGTERM while asleep exiting at once with 0 (a real signal);
  and, forking for real, the model loaded and freed in the child, not the supervisor, and a
  SIGTERM during a window forwarded to the child, which stops gracefully. The entrypoint runs
  the supervisor only for `"wait"`, and imports neither torch nor a thread.
- **The broker proxy** (`test_worker_proxy.py`): bytes forwarded both ways, a `CONNECT` or
  an absolute URL delivered to the target all the same, an unreachable target, the
  connection limit, idle connections closed, targets as IP addresses only.
- **Configuration and image**: `outside_window`, `broker_via_proxy` (service names only with
  it, never dotted or numeric ones), the compose examples parsing, their windows never
  overlapping, and the image reported at hello.
- **Pins**: `pins.PINS` equals `policy.MODELS`, the worker's request hash equals
  `prompt.request_sha256` on rendered requests, the mapped-weights check can fire, and scores
  outside [0, 1] are refused.

## Not done yet

- **A lease taken just before the window ends can still start a model load.** The window
  is checked before loading: if it has already ended (or a stop has come), the lease goes
  back gracefully with nothing loaded. But a lease taken seconds before the end starts the
  load (about 150 s on CPU), which runs past the window; the window is checked again
  right after the load, so nothing is scored, and the lease goes back gracefully, but the
  model was loaded for nothing and the worker overstays its window by the load's length.
- **Freeing Kev's memory on unload** inside a long-lived process is coded (the atexit hook
  that held it is removed, then `gc.collect()` and `malloc_trim`) but has not been measured
  with real models. A worker that waits for its window does not depend on it: each window's
  session is a child process that exits.
- **The compose stack has not run on the home server.** It ran end to end on the desktop
  with fake components only ("Running on the home server"). Setting it up there, with the
  real broker and weights, is a separate, supervised step; the old timers and the
  `DOCKER-USER` rules, if they were ever installed, are to be removed by hand then.
- **The 5-minute gap after Kev's window is an estimate from the measured worst cases** (a
  request of about 104 s or a load of about 150 s, then up to 3 × 10 s of last posts and a
  10 s join: about 4 minutes), not a guarantee: a stop slower than that would still overlap
  pplx's first load. The supervisor does not check that the other worker has unloaded.
- **`inhibit_ipv4` depends on the Docker Engine.** Without it an `internal` network still
  lets a container reach the host's own services; an engine that ignores the option leaves
  that open. The stack's README has the check; the desktop's engine (29.x) honours it.
- **The end-to-end compose run is not in CI.** CI's smoke test covers the supervisor's fork
  and the proxy inside the image; the stack itself (networks, caps, the proxy as the only
  route) was checked once by hand.
- **A failed run on `main` leaves an untagged image in GHCR** (see "Images"). The full fix is
  to push only after the checks, from a copy kept byte for byte, for example an OCI layout
  exported by the same bake and copied with `skopeo copy --preserve-digests`.
- **The GHCR packages start private.** The first push creates `makhzan/kev-worker-cpu` and
  `makhzan/pplx-worker-cpu` as private packages; the owner sets each public once (the
  package's settings, "Change visibility"). Until then an anonymous `docker pull` is refused.
- **Hash-pinned wheels** are still not done for the lean bases (`ml/README.md`, "Lean CPU
  images"): CI installs the same version-pinned packages a local build does.
- **The GPU images are local builds**, referenced by tag (about 26 GB each; not published).
- **A Kev base image built before `MAKHZAN_KEV_COMMIT` was recorded** (a local GPU image, until
  it is rebuilt) leaves the commit unchecked; the worker logs it. The GHCR images record it.
- **Nothing has run on the home server through the worker.** Both models were checked on
  CPU on the desktop, under the same caps (above). The next check is one supervised run of
  each worker on the home server, against the real broker.
- **Pushing a locally reviewed backlog to production** (P4) is separate tooling, not part of
  the worker.
