# AI matching: the worker

Status: **built, tested against a contract-following fake broker, and checked against the
phase 2 broker app** (six end-to-end sessions, below, run while the broker's time-fit
removal was in progress), and **in production since 2026-11-19**: the home server runs
`home-kev` and `home-pplx` as a compose stack against the real broker (its first window:
Kev scored 12 requests at about 123 s each, stopped and unloaded cleanly; pplx found its
queue empty; `docs/ai/decision-review.md`, "Go-live"). What is not here yet is listed at
the end.

A worker is one process that serves the one model key its configuration names: the broker
takes exactly one model per session, so two models are two workers (for example `home-h2o`
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

**One model at a time, enforced.** Each session takes no new lease and starts no model load
in its window's last `no_new_lease_s` (300 s on CPU). If a session is still running
`KILL_AFTER_S` (4.5 minutes) after its window's end all the same, the supervisor SIGKILLs it
and logs `KILLING the session` at ERROR, so the next worker's window (5 minutes later on the
home server) never finds its model in memory. 4.5 minutes is above the graceful stop's bound
on the home server's CPU (about 170 s) and below the gap. A killed session cannot release
its lease: it expires at the broker and charges the job in hand one attempt. The supervisor
waits for its child with a polling `waitpid` against that deadline, never a blocking one.

**Signals, safely.** The supervisor's SIGTERM/SIGINT handler only records the signal; Python
also writes it to a wakeup pipe, so any sleep ends at once (`select`), and the main loop
turns the record into a stop and forwards it to a running child. SIGTERM and SIGINT are
blocked across the fork and the stop flag is read right after blocking them, so a signal
that came just before is seen and nothing is forked, and one during the fork is forwarded as
soon as the child's pid is known. The session (`run.Worker`) does the same with a watcher
thread: its handler does nothing, the wakeup pipe carries the signal, and the thread calls
`request_stop`, which now lands even while the main thread is inside a forward pass. Neither
handler takes a lock.

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
| what is in flight at the stop, which cannot be interrupted: a request | 86 to 104 s on the home server's CPU, under 1 s on the GPU; on a llama.cpp sidecar at most its timeout, 60 s on a GPU (measured 0.5 s on the 3060, 4.4–6.1 s on the AMD card), 120 s for Kev on a CPU, 225 s for pplx on a CPU (its longest request estimated at about 193 s on the home server) |
| or a model load | about 150 s on the home server's CPU (Kev 130 s, pplx 73 to 95 s measured), under 10 s on the GPU; on a llama.cpp sidecar the load (hashing the GGUF, then up to 180 s waiting for the sidecar and, on a router, for its model to load) checks the stop between steps, so it ends within about 2 s |
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
- the GPU: the 60 s of retries outlast any request, then 3 × 10 s and the join: about 100 s;
- a llama.cpp sidecar: a request's timeout (60 s on a GPU, 120 s for Kev on a CPU, 225 s for
  pplx on a CPU), then 3 × 10 s and the join: at most about 100 s, 160 s or 265 s. The pplx
  worker's compose service therefore has `stop_grace_period: 300s` (240 s would kill it before
  its last posts); the others keep 240 s.

**The window's end has its own kill bound.** With `outside_window = "wait"`, a session's held jobs
keep scoring up to the window's end, so a last request may start just before it. The supervisor
kills a session still running `KILL_AFTER_S` (270 s) after the window's end, a bound that must stay
under the 5-minute gap before the next window. Every bound above stays under it, the longest being
pplx on a CPU at 265 s; a test checks every llama.cpp timeout plus 40 s against it.

Anything still undelivered is logged before the process exits. Set the stop timeout above
the bound: 240 s on the home server's CPU (`stop_grace_period: 240s` in its compose stack;
300 s for the pplx worker, for its llama.cpp backend), 120 s on the GPU (`--stop-timeout 120`).

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
| `broker_via_proxy` | `false` | `true` also accepts plain `http://` to the broker proxy's name, exactly, and no other name. Safe only inside the compose stack: on the worker's internal Docker network, which has no other route out, the name can only be the proxy, which forwards only to the broker's Tailscale address. Never set it for a worker on an ordinary network. Off, a name is refused as before |
| `broker_proxy_hosts` | `["broker-proxy"]` | with `broker_via_proxy`: the exact names allowed, each a compose service name (one DNS label with a letter in it, no dots, nothing the resolver reads as an address such as `1234` or `0x7f000001`) |
| `token_file` / `token` | exactly one | the bearer token, preferably as a file (a Docker secret or a read-only mount) |
| `ca_file` | system CAs | for an `https://` broker only: a CA bundle to trust instead, for a privately signed certificate |
| `model` | required | the one model key served, from `policy.MODELS`: `"h2o"` or `"pplx"` (`"kev"` until D25, 2026-11-27, and for its rollback). The broker takes one model per session, so two models are two workers. A key the image cannot load is refused at start and by `--check`. The older `models = ["kev"]` is still read when it names exactly one key |

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
| `backend` | `"torch"` | `"torch"`: the model's own code in this process. `"llamacpp"`: the model on a llama.cpp sidecar (see "Kev on a llama.cpp sidecar" and "pplx on a llama.cpp sidecar") |
| `llamacpp_url` | none | `backend = "llamacpp"` only, and required there: the sidecar's base URL, plain `http://` to a compose service name or a loopback address |
| `gguf_path` | none | `backend = "llamacpp"` only, and required there: the GGUF the sidecar serves, mounted read-only into the worker too, which checks it against the pin before scoring |
| `require_clock_limit` | `true` on a GPU | `backend = "llamacpp"` only: refuse to load unless every AMD card's `power_dpm_force_performance_level` reads `manual` (the home server's udev clock limit), re-read at every load. Set `false` on a machine whose GPU is not that card (the desktop's NVIDIA card) |

With `backend = "llamacpp"`, `dtype` is the pinned GGUF's: `"q4_k_m"` for H2O and Kev, `"q4_k_s"`
for pplx (the only accepted values), and `mmap` and `weights_cache` are refused (the worker holds no
weights).

### `[schedule]`

| Key | Default | Meaning |
|---|---|---|
| `windows` | `"always"` | `"always"`, or one or more `"HH:MM-HH:MM"` in local time. A window may cross midnight (`"22:00-02:00"`). Windows that touch or overlap run on as one |
| `timezone` | required with windows | an IANA zone such as `"Africa/Cairo"`. Required whenever `windows` is not `"always"`: a container's local time is UTC unless told otherwise, so a window without a zone would run at the wrong hours |
| `on_empty` | `"exit"` | `"exit"` or `"wait"` |
| `no_new_lease_s` | 300 on CPU, 0 on GPU | no new lease and no model load this close to a window's end (seconds), so a CPU load (about 150 s) cannot start at 04:59 and hold a model past the window. A session that would start inside it does nothing; a lease taken just before it goes back whole, gracefully, with nothing loaded. Must be shorter than every window |
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

These four are examples, as production runs them since the owner's switch of 2026-11-27: both
judges through llama.cpp (H2O-Lightning-4B Q4_K_M since D25, Kev-4B Q4_K_M before it, pplx
Q4_K_S; "Kev on a llama.cpp sidecar", "pplx on a llama.cpp sidecar" below). The home server's
windows are the owner's (first judge 01:00–05:00, pplx 05:05–07:00, Cairo time); the desktop's run until their queue is empty. Hosts
and tokens are placeholders. The worker's tests parse every block below, and the compose stack's
files. The torch configurations production ran until then are kept as
`ml/deploy/home-server/torch-kev.toml` and `torch-pplx.toml`, the rollback (the broker refuses
them while the policy names the llama.cpp versions).

The home server's first-judge worker, H2O-Lightning since D25 (2026-11-27; Kev before it), as
`ml/deploy/home-server/home-h2o.toml` has it: through the compose stack's broker proxy, waiting
for its window, its judge the `h2o` model of the stack's llama.cpp router on the AMD card (service
`llamacpp`; the worker loads its model on its window's first lease with jobs, "The llama.cpp
router" below). H2O's GGUF bakes in a temperature of 0.8, which the worker undoes (raw P(yes), the
scale of the policy's 0.578), as it undoes Kev's 2.406. Parity on the 3060 (2026-11-27), the
worker's own `parity` tool through the whole protocol against the pinned server-vulkan image
with the home server's preset (`-dev Vulkan0`, batch 512): 20 requests, every one within
3.4e-9 of the stored H2O Q4 scores from the label test (raw, read at T 0.8), no decision moved
(`ml/out/models-compare/parity-h2o-llamacpp-3060.json`):

```toml
# home-h2o.toml
[worker]
name = "home-h2o"
broker_url = "http://broker-proxy:8100/ai/v1"
broker_via_proxy = true
token_file = "/run/secrets/makhzan-ai-token"
model = "h2o"

[model.h2o]
expect_version = "h2o-lightning-4b-Q4_K_M@5ec969c6edba+llama.cpp-b12767-87d189d403fd+T1.0"

[compute]
backend = "llamacpp"
device = "gpu"
dtype = "q4_k_m"
llamacpp_url = "http://llamacpp:8080"
gguf_path = "/models/h2o-lightning-4b-Q4_K_M.gguf"
require_clock_limit = true
nice = 10

[schedule]
windows = ["01:00-05:00"]
timezone = "Africa/Cairo"
outside_window = "wait"
on_empty = "exit"

[leases]
max_jobs = 2
lease_s = 900
heartbeat_s = 60
```

The home server's pplx worker. Its window follows H2O's: the 4 GB card holds one model, and on its
window's first lease with jobs its worker asks the same router for `pplx`, which unloads H2O's
first:

```toml
# home-pplx.toml
[worker]
name = "home-pplx"
broker_url = "http://broker-proxy:8100/ai/v1"
broker_via_proxy = true
token_file = "/run/secrets/makhzan-ai-token"
model = "pplx"

[model.pplx]
expect_version = "pplx-decider-flash-v1.3-Q4_K_S@819a9ad0f8f4+llama.cpp-b12767-87d189d403fd+T1.3303"

[compute]
backend = "llamacpp"
device = "gpu"
dtype = "q4_k_s"
llamacpp_url = "http://llamacpp:8080"
gguf_path = "/models/pplx-flash-v1.3-Q4_K_S.gguf"
require_clock_limit = true
nice = 10

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

The desktop's GPU workers, for a backlog. They run until the queue is empty. Each needs its
sidecar on the desktop first, run from **the same image digest** as the home server's: the
digest is part of the model version, so a CUDA build would be a different version and the broker
would refuse its scores. The server-vulkan image runs on the 3060 too (H2O Q4 at batch 2048:
2.72 requests/s there). One at a time:

```bash
docker run -d --name desk-h2o-llamacpp --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -v <models dir>:/models:ro -p 127.0.0.1:8130:8080 \
  ghcr.io/ggml-org/llama.cpp@sha256:87d189d403fda2a612a23c9dcd35c482967f48586e93d812a01e7a1f5e3a1486 \
  -m /models/h2o-lightning-4b-Q4_K_M.gguf -ngl 99 -dev Vulkan0 -np 1 -c 4096 -b 2048 -ub 2048 \
  --host 0.0.0.0 --port 8080
# pplx: -m /models/pplx-flash-v1.3-Q4_K_S.gguf -ngl 99 -dev Vulkan0 -np 1 -c 4096 -b 4096 -ub 4096 -fa on
```

`-dev Vulkan0` makes a missing card a startup error rather than a silent CPU run. H2O runs here at
batch 2048, where the home server's preset uses 512 (2048 not yet tested on the 4 GB card). H2O is
causal, like Kev, so the batch changes speed (3.1x on the 3060), not scores: measured for Kev on
the 3060, Q4 at 2048 against 512 over 200 requests differed by at most 0.014 (calibrated; 0.030
raw) with no decision moved (`kev-llamacpp.md`).
pplx needs 4096 everywhere (non-causal).

The worker container then runs with `--network host`, so `127.0.0.1:8130` is the sidecar, and
the same models directory mounted at `/models` (the worker hashes the GGUF it is pinned to).

```toml
# desk-h2o.toml
[worker]
name = "desk-h2o"
broker_url = "http://<tailscale-ip>:<port>/ai/v1"
token_file = "/run/secrets/makhzan-ai-token"
model = "h2o"

[model.h2o]
expect_version = "h2o-lightning-4b-Q4_K_M@5ec969c6edba+llama.cpp-b12767-87d189d403fd+T1.0"

[compute]
backend = "llamacpp"
device = "gpu"
dtype = "q4_k_m"
llamacpp_url = "http://127.0.0.1:8130"
gguf_path = "/models/h2o-lightning-4b-Q4_K_M.gguf"
# The desktop's NVIDIA card is not the home server's clock-limited AMD card.
require_clock_limit = false

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
expect_version = "pplx-decider-flash-v1.3-Q4_K_S@819a9ad0f8f4+llama.cpp-b12767-87d189d403fd+T1.3303"

[compute]
backend = "llamacpp"
device = "gpu"
dtype = "q4_k_s"
llamacpp_url = "http://127.0.0.1:8130"
gguf_path = "/models/pplx-flash-v1.3-Q4_K_S.gguf"
# The desktop's NVIDIA card is not the home server's clock-limited AMD card.
require_clock_limit = false

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

**The production worker is `worker-llamacpp`** (since 2026-11-27): `ml/worker-llamacpp.Dockerfile`,
the worker alone on the same pinned python-slim base, about 180 MB, with no torch and no model
code, since the llama.cpp sidecar does the compute. It runs both home-server workers and the
broker proxy. Its smoke test is `python -m makhzan_ml.worker.smoke --backend llamacpp --model
kev` (and `pplx`):
- torch, transformers, fla and the model code are absent;
- the llama.cpp loader refuses a file that is not a GGUF without importing torch;
- then the same weight scan, `--check`, session, supervisor, proxy and revision checks as below,
  under the llama.cpp configuration and version.

Verified locally on 2026-11-27: both models' smoke tests passed in the image. Its parity tool
against a real sidecar on the 3060 scored 10 requests within 0.013 of the stored Q4 scores, with
no flips.

**The torch CPU workers come from GHCR too, kept for a rollback.** `.github/workflows/ai-worker-images.yml`
builds `worker-llamacpp`, `kev-worker-cpu` and `pplx-worker-cpu` on every push to `main` that
touches `ml/` (and on pull requests, without pushing); the steps are in
`ai-worker-image-build.yml`. Each torch worker is one chain, from
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

## Running on the home server

The home server runs both workers as one compose stack, `ml/deploy/home-server/`: a folder with
`compose.yml`, a `.env` (from `.env.example`), the two worker TOMLs and their token files, and the
llama.cpp router's `models.ini` and `llamacpp-guard.sh`. Everything runs in containers: no host
timers, scripts or firewall rules (owner's rule). The host's one setting is the udev rule
`99-amdgpu-clock-limit.rules`, kernel settings for the AMD card only the host can make. Its README
says how to set it up.

**Since the owner's production switch (2026-11-27)** both judges run on the server's AMD card
through one llama.cpp router (service `llamacpp`; "The llama.cpp router" below), which serves both
models and holds one at a time, because the 4 GB card fits one:

| Time (Africa/Cairo) | Worker | The router |
|---|---|---|
| 01:00–05:00 | home-h2o scores | loads `h2o` when home-h2o's session asks (unloading `pplx`) |
| 05:05–07:00 | home-pplx scores | loads `pplx` when home-pplx's session asks (unloading `h2o`) |
| otherwise | waiting | the last model sleeps after 10 idle minutes; the card is free |

The router's entrypoint refuses to start unless the card is in `manual` performance mode, which
the udev rule sets together with its clock-state limit (states 0–2). Without that limit a job on
this card resets the whole server (`kev-llamacpp.md`). The CPU caps and the torch notes below
describe the rollback configurations (`torch-kev.toml`, `torch-pplx.toml`).

```bash
docker compose up -d                            # start, and after any change
docker compose pull && docker compose up -d     # update to the latest tested images
docker compose logs -f h2o                      # sleeping until 01:00, window open, ...
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
It is our own code, `python -m makhzan_ml.worker.proxy --listen 10.231.89.2:8100 --to <ip>:8100`
(it listens on its fixed address on `broker-only` only, never on the bridge; the workers'
addresses come from `ip_range` 10.231.89.128/25, so a worker attaching first cannot take it)
(standard library asyncio), run from the Kev worker image with no model loaded, read-only,
no capabilities, non-root, 128 MB. It reads no request, so nothing a worker sends can name
another destination (a `CONNECT` or an absolute URL is only bytes delivered to the broker,
which refuses them), and its target must be an IP, never a name. The host's Tailscale client
carries its traffic to the broker, encrypted. The workers' `broker_url` is
`http://broker-proxy:8100/ai/v1` with `broker_via_proxy = true`.

`internal: true` alone leaves the host an address on the network's bridge, and a container
could reach host services listening on all interfaces through it (the end-to-end run below
reached sshd that way). The network therefore sets `com.docker.network.bridge.inhibit_ipv4`,
which leaves the host without one; it needs Docker Engine 26 or newer, and the stack's
README has the check to run after `up -d` (the engine's version, the connections, and an
external DNS lookup that must fail). The workers also have `pids_limit: 256`, and the README
runs each worker's `--check` before the first `up -d`, so a configuration error does not
become a restart loop.

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

**Re-run after the review fixes (2026-11-19).** The same harness, rebuilt at the fixes' commit,
with `no_new_lease_s = 30` (a test window of 3 minutes cannot hold the default 300) and pplx's
fake judge taking 600 s a request:

- `docker compose run --rm --no-deps <worker> --config ... --check` printed `configuration
  ok` with the image's commit for both, as the README now has it before `up -d`.
- The proxy logged `forwarding 10.231.89.2:8100`; from the egress bridge its address there
  refused the connection. From the workers' network only the proxy connected, an external
  `getaddrinfo` failed, the network had no gateway, and `pids_limit` was 256.
- Kev stopped leasing at 04:07:40, its window's last 30 s (`no new lease in the window's last
  30 s`), unloaded, and slept until the next day: memory 1.53 GiB to 15 MiB at once.
- pplx's request outlasted its window (04:08–04:10): the window's end asked it to stop, the
  request could not be interrupted, and at 04:14:30.001, 270 s after the end, the
  supervisor logged `KILLING the session (pid 8)` and SIGKILLed it; memory went from
  1.53 GiB to 15 MiB in the next sample, and the supervisor slept until the next day. Its two
  leased jobs stayed leased at the broker until their lease would expire.

## Running on the desktop (GPU) for a backlog

The owner decides when a backlog runs (P10). A desktop GPU worker connects to the broker and
drains the queue.

**Since the production switch (2026-11-27) the desktop must run the llama.cpp backend too**:
the broker refuses the torch versions at hello. Start the sidecar first, from the same image
digest as the home server's (the digest is part of the version), as under "Example
configurations" (`desk-kev.toml`, `desk-pplx.toml`), then the worker with `--network host` and
the GGUFs at `/models`. Any worker image runs the llama.cpp backend (it needs no torch); the
steps below are the torch ones, kept for a rollback. Only one 4B model fits on the 12 GB card,
so run Kev first, then pplx:

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

## The llama.cpp router (home server, since 2026-11-27)

The home server's 4 GB AMD card holds one model, and both judges run on it. One llama.cpp server
in router mode (compose service `llamacpp`) serves both, from the preset
`ml/deploy/home-server/models.ini` (one section per model, named as the workers ask for it):

- **`--models-max 1`:** at most one model loaded; loading the other unloads it first.
- **On demand:** each worker's session loads its own model on its window's first lease with jobs,
  before scoring it (`POST /models/load`, then waits on `GET /models`), so no request pays the
  load. While the other model is busy the router refuses with HTTP 500 "model limit reached"; the
  worker retries until its 180 s budget. A load whose child exits is an error at once.
- **Never point anything else at the router during a window.** A parity run or any request for
  the other model evicts the window's model and the two then swap back and forth, each swap
  re-reading about 3 GB from the server's disk under the container's memory limit. Run parity on
  the desktop.
- **The clock limit at every load:** besides the router's entrypoint guard, each worker re-reads
  the card's mode at every load (`require_clock_limit`, on by default for a GPU), since the router
  may run for weeks after its own check.
- **`--sleep-idle-seconds 600`:** idle for 10 minutes, the model sleeps (its memory released,
  ~190 MB kept); the next request wakes it in about 6 s. The card is free for Plex, Jellyfin and
  Pitlane by day.
- **The guard:** the router's entrypoint (`llamacpp-guard.sh`) refuses to start unless every AMD
  card reads `manual` performance mode (the udev clock limit), read from the host's `/sys`, which
  containers see read-only. A refusal repeats under `restart: unless-stopped`: a restart loop with
  the reason in its log, never an unlimited card.
- **`-dev Vulkan0`:** a missing card is a startup error, never a silent CPU run.
- On `broker-only` only, no published port, the stack's hardening (non-root with the render and
  video groups, read-only, no capabilities). Both workers use `llamacpp_url =
  "http://llamacpp:8080"`. The worker also supports a single-model server (the desktop's), which
  it recognises by a `/models` without per-model status.

Tested on the desktop's 3060 under the production compose file with a test-only override (the
NVIDIA card and a fake sysfs reading `manual`): Kev parity within 0.016 (40 requests; the one flip
is E0251, the near-threshold pair below), pplx bit-identical (40 requests), the worker's own load
swapping models in 5.7 s (pplx to Kev) and 8.5 s (Kev to pplx). With the desktop's real sysfs
(`auto`) the guard refused, as intended.

## Swapping a llama.cpp judge (data, not code)

Since D25 a llama.cpp judge is described entirely by data. Replacing the first judge again, with
a GGUF that carries `qwen35.decision.*` metadata and is served by the pinned image, needs these
edits, and no code:

1. **The worker's pin** (`ml/makhzan_ml/worker/pins.py`): one `ALTERNATIVES[(key, "llamacpp")]`
   entry with the GGUF's repo, revision, file, sha256, its stored decision temperature, its
   `qwen35.decision.type`, the router name, the dtype, and the request timeouts; its key in
   `ACTIVE_BACKEND`. The loader, the configuration check (`LLAMACPP_DTYPES`), the timeouts
   (`judges.LLAMACPP_REQUEST_S`), the request's model name (`judges.LLAMACPP_MODELS`), the smoke,
   parity and the fake broker all read them.
2. **The policy registry** (`makhzan_schemas/ai/policy.py`): the `MODELS` entry (its version
   equal to the pin's; the worker's tests hold them equal), a new policy made `ACTIVE`, and the
   model's group-check floor in `JUDGE_FLOORS`. The audit's bands in `ai status` follow from them.
3. **The pipelines registry** (`makhzan_schemas/ai/pipelines.py`): the `match` and `audit` first
   stage's name, model and threshold key. The old stage leaving is handled (the sweep re-offers
   its queued jobs; decisions carrying its score are re-scored).
4. **The deployment**: a `models.ini` section named as the pin's router name, the worker TOML
   (`model`, `expect_version`, `dtype`, `gguf_path`), the compose service and the router's
   mount, and the CI smoke's model list (`.github/workflows/ai-worker-image-build.yml`).

**Still model-specific in code, and why:**

- **The torch loaders** (`judges._LOADERS`: `_load_kev`, `_load_pplx`) run each model's own
  Python code, which differs per model. They are the rollback of the 2026-11-27 switch; a new
  judge comes in through llama.cpp, which needs no loader of its own.
- **The prompt layouts** (`prompt.VARIANTS`: `kev_payload` for K2-150, `pplx_payload` for
  K1-full). A function's source is part of its prompt version, so renaming `kev_payload` would
  change `K2-150`'s version and re-queue every decision for re-scoring. A judge on a new prompt
  is a prompt change, reviewed by the owner, not a swap.
- **The smoke's torch checks** (Kev's code commit in the torch image): torch images only.
- **The GGUF metadata keys** (`qwen35.decision.type`, `qwen35.decision.temperature.noul`): the
  decision-model format of the llama.cpp build in the pin. A model of another architecture
  family would need the loader to read its keys.

## Kev on a llama.cpp sidecar (production since 2026-11-27)

Kev-4B Q4_K_M served by llama.cpp, accepted by the owner on 2026-11-26 (D20 amended;
measurements in `docs/ai/kev-llamacpp.md`) and made production on 2026-11-27
(`decision-review.md`, "Production switch"). It runs on the home server's 4 GB AMD card, held to
clock states 0–2: 4.4 s a request, about 20–27x the CPU worker.

- **The pin** is `pins.ALTERNATIVES[("kev", "llamacpp")]`, which `pins.production_pin("kev")`
  returns since `pins.ACTIVE_BACKEND` names llama.cpp:
  - the GGUF `ggml-org/Kev-4B-GGUF@f4624b6…`, file `Kev-4B-Q4_K_M.gguf`, sha256 `33ae6b18…`;
  - llama.cpp's `server-vulkan` image, build b12767, by digest (`pins.LLAMACPP_IMAGE`);
  - model version `kev-4b-Q4_K_M@33ae6b189265+llama.cpp-b12767-87d189d403fd+T1.0`.

  The policy's `MODELS["kev"]` names this version; the torch pin (`PINS["kev"]`,
  `policy.TORCH_MODELS`) is the rollback, refused at hello while the policy names this one. The
  switch made every standing decision's judge stale, so they are re-scored at the low
  priorities of P8 as amended 2026-11-26 (35 for a "same", 30 for a "not same"), after new
  pairs and the backlog; the owner drains that catch-up (wider windows, the desktop).
- **Scoring.** The worker posts the approved payload to the sidecar's `POST /v1/systemone`,
  one request per call. The GGUF carries Kev's fitted temperature (2.406) and llama.cpp
  always applies it, so the worker undoes it (`judges.uncalibrate`). The score is then raw
  P(yes), the scale every validated Kev score and the policy's 0.8 are on.
- **Text is sent in Unicode NFC** (`judges.nfc`). Kev's own Qwen tokenizer normalises to NFC
  and llama.cpp's does not, so without it text such as the ohm sign (U+2126) tokenises
  differently: 10 of the 1,800 Phase E requests did, measured on pplx's identical tokenizer.
  Only what is sent changes; the broker's request hashes are of the payload as rendered.
- **The answer is checked too.** A missing or malformed `answers.same.noul`, or a value
  that is not a real number in [0, 1] (NaN, infinite, out of range, a bool or a string), is
  an error on that job, never a score. Only exactly 0 and 1 are nudged inward so their
  logit is finite.
- **Timeouts:** 60 s for one request on a GPU sidecar and 120 s on a CPU one, both inside the
  stop bound (above). The load's hash of the GGUF and its wait for the model (up to 180 s:
  `/health`, then, on a router, the model loaded) both check the stop, so a stop never waits on
  them, and no request pays a load.
- **Checks before anything is scored** (a mismatch is a load error, exit 2):
  - the worker's own read-only copy of the GGUF: its name, its sha256, and its metadata
    (`qwen35.decision.type = kev`, the temperature), read with the standard library;
  - the sidecar's `/health`;
  - on a router (the home server's): its `GET /models` lists `kev` with the pinned file in its
    preset args, and the worker loads it (`POST /models/load`, retried while the router answers
    "model limit reached") and waits until it is loaded or asleep (all within 180 s; a load whose
    child exits fails at once); then `/props?model=kev` for the build. On a single-model server:
    `/props`, the file it serves and the build;
  - llama.cpp build b12767.

  The worker cannot see the server's file directly. Compose mounts the same host file into
  both (`WEIGHTS_DIR/Kev-4B-Q4_K_M.gguf`), and the name and build are what the server reports.
- **No torch on this path.** The load imports nothing beyond the standard library; production
  runs it in the slim `worker-llamacpp` image (no torch, about 120 MB).
- **The compose stack** (`ml/deploy/home-server/compose.yml`, service `llamacpp`, "The llama.cpp
  router" below): one router serving Kev and pplx, `models.ini`'s `[kev]` section with the 4 GB
  settings (`n-gpu-layers = 99`, one slot, `c = 4096`, `b = ub = 512`; batch 2048 is 2.7x faster but
  needs about 5.3 GB). `home-kev.toml` beside it is the worker configuration (the torch one it
  replaced is `torch-kev.toml`, the rollback).
- **Parity:** `python -m makhzan_ml.worker.parity --backend llamacpp --llamacpp-url ...
  --gguf-path ... --stored <llama.cpp scores> --stored-temperature 2.406`. On 2026-11-26,
  against a live sidecar on the desktop's 3060 (Vulkan, the 4 GB settings), 40 requests
  through the whole protocol matched the stored Q4 scores within 0.016 (mean 0.002).
  - One request changed side of 0.8: E0251 ab, 0.806 stored against 0.790.
  - The stored scores were read from a server with 4 slots and an 8k context, which is
    enough to move a score by that much.
  - Report: `ml/out/gguf-kev/parity-llamacpp-3060.json`.

**Not done** for this backend:

- **The card's power feed is a workaround.** The original 320 W supply has no PCIe cable and
  feeds the card through a SATA adapter; the udev clock-state limit keeps the card's load step
  small enough (`kev-llamacpp.md`). A proper supply is the fix.
- **The router has not run on the card in production yet.** It ran under the stack's full
  hardening (non-root, read-only, no capabilities) on the desktop's 3060 (2026-11-27: parity
  within 0.016 for Kev and bit-identical for pplx, swaps in 6–9 s), and the card soaks ran the
  same image and settings with `docker run`. The first night's logs are the check, and the card's
  memory during Kev's window (on the 3060 Kev grew to about 4.1 GB while scoring).

## pplx on a llama.cpp sidecar (production since 2026-11-27)

pplx-decider-flash-v1.3 **Q4_K_S**, accepted by the owner under D20's label test
(`decision-review.md`, "pplx quantisation"; measurements in `docs/ai/pplx-llamacpp.md`), served
the same way as Kev above, with these differences.

- **What is pinned** (`pins.ALTERNATIVES[("pplx", "llamacpp")]`):
  - **The GGUF:** our own conversion of the pinned checkpoint (`ml/models/convert_pplx_v13.py`),
    `pplx-flash-v1.3-Q4_K_S.gguf`, sha256 `819a9ad0f8f4…`, decision type `pplx-decider`,
    temperature 1.3302961587905884.
  - **The image:** the same llama.cpp image digest as Kev's.
  - **The model version:** `pplx-decider-flash-v1.3-Q4_K_S@819a9ad0f8f4+llama.cpp-b12767-87d189d403fd+T1.3303`.
    The broker refuses it until the policy names it.
- **No uncalibration.** llama.cpp applies pplx's own temperature, the scale of every validated
  pplx score and of the policy's 0.95, so the answer is taken as served (`judges.rescale`
  returns it unchanged when the two temperatures agree), after the same strict validation.
- **Text is sent in NFC**, as for Kev: pplx's tokenizer is the same family.
- **On the card**, the router's `[pplx]` section (`n-gpu-layers = 99`, `flash-attn = on`), loaded
  when home-pplx's session asks at 05:05, which unloads Kev's model. Soaked on the card at clock
  states 0–2: 1,800 requests, 4.6 s each, about 33x the torch CPU worker, within 0.038 of the
  3060's scores (`kev-llamacpp.md`).
  - pplx is non-causal, so a whole request must fit one batch: `-b`/`-ub`/`-c` 4096. The
    longest Phase E request is 3,574 tokens; about 1 pair in 3,000 of the real backlog exceeds
    4,096 (`pplx-llamacpp.md`). Those have their descriptions cut to fit ("Requests too long
    for the context" below).
  - The worker configuration is `home-pplx.toml` (device `gpu`; the torch one is
    `torch-pplx.toml`, the rollback), window 05:05–07:00.
  - **No CPU fallback is set up.** The same GGUF on the CPU would be the same model version (P8),
    but the router runs only on the card (`-dev Vulkan0`, and its guard needs the clock limit): a
    CPU run needs its own llama.cpp server (no `-dev`, `n-gpu-layers = 0`) and `device = "cpu"`
    in `home-pplx.toml`. Not built.
- **Its request timeout is 60 s on the card, 225 s on a CPU (the fallback).** The longest Phase E request took 48.9 s on the
  desktop's CPU (4 threads) and is estimated at about 193 s on the i7-3770 (not measured there).
  With 3 × 10 s of last posts and the 10 s join, the stop bound is 265 s: under the supervisor's
  270 s window-end kill, and covered by the pplx worker's `stop_grace_period` of 300 s.
- **Parity tool:** `python -m makhzan_ml.worker.parity --model pplx --backend llamacpp --device
  cpu --llamacpp-url … --gguf-path /models/pplx-flash-v1.3-Q4_K_S.gguf --requests
  /req/pplx-K1-full.jsonl --stored ml/out/gguf-pplx/Q4_K_S.jsonl --stored-temperature 1`. The
  stored llama.cpp pplx scores are already on the right scale, hence temperature 1.
  - **Run 2026-11-26:** a CPU sidecar on the desktop (4 threads), 6 requests (3 pairs) through
    the whole fake-broker protocol, against the 3060's Q4_K_S scores. Max |Δp| 0.019, mean
    0.007, no flips at 0.95, exit 0, about 15 s a request.
  - Report: `ml/out/gguf-pplx/parity-llamacpp-cpu.json`.

**Not done:**
- a run of the CPU fallback on the i7-3770 itself (its 225 s timeout rests on an estimate).

## Requests too long for the context (owner, 2026-11-27)

A request longer than the llama.cpp server's batch or context (pplx: 4,096 tokens) is **cut to
fit, not failed**. The owner judges the tail of a very long description irrelevant. This is the
worker's llama.cpp path (`judges._load_llamacpp`), the same for every llama.cpp judge; the broker's
renderer is untouched, so request hashes and prompt versions do not change.

- **Detected** from llama.cpp b12767's refusal (`judges.too_long`):
  - HTTP 500 "input (N tokens) is too large to process. increase the physical batch size
    (current batch size: 4096)";
  - HTTP 400 "request (N tokens) exceeds the available context size (L tokens) …", read with
    or without its counts.
  - Any other error fails the job as before.
- **What is cut:** only each listing's own description, words from the end, the longest
  description first.
  - It is found from the renderer's structure (`makhzan_schemas.ai.prompt.block`), not by
    searching for "Description:". A title or spec value may hold a newline, since only
    descriptions have their whitespace collapsed, so a free search would cut title text. Each
    block's description is its fixed last line: listing B's is the state's last line, listing
    A's the line before the one `[LISTING B]` separator.
  - A state not in that shape (no single separator, or a block not ending in `Description:`) is
    not cut, and the job fails as before.
  - The descriptions are levelled down: the longest is cut to the next one's length, then both
    alike.
  - Each cut description ends in the renderer's marker `[…]` (one marker, even where the renderer
    had already capped it).
  - Titles, category, brand, part number, pack size, specifications, the rules and the question
    are never touched.
  - Text is NFC first, as always.
- **How much** (`judges.words_to_cut`): the excess plus a 64-token margin, turned into words.
  - The first cut uses the refused state's own tokens per word.
  - A later cut uses what the last cut actually saved: Δtokens / Δwords between the last two
    refusals.
  - Only a refusal without counts (a bare HTTP 400) cuts by a fixed step, 15% of the longest
    description.
  - It retries up to 8 times. If even empty descriptions do not fit, the job fails: "too long
    even with its descriptions cut".
  - A stop between retries gives the job back unscored (`judges.ScoreInterrupted`), as a stop
    between orders does.
- **Deterministic:** the cut depends only on the request and the server's answers, so the same
  request on the same server is cut the same way.
- **Recorded** in the score's `extra`:
  `{"truncated": {"words_cut": {"LISTING A": n, …}, "tokens_before": N, "tokens": M, "attempts": k}}`.
  - `tokens` is the cut request's `usage.input_tokens`.
  - A score with no `truncated` key was scored on the whole request.
- **The score is of the cut request** under the same model version and request hash. A
  re-score on a server with a larger context would see more text. That is accepted: the cut
  text is the part the owner judges irrelevant.
- **Real check (2026-11-27):**
  - Setup: pplx Q4_K_S with the real pins, on the pinned llama.cpp image (b12767),
    `-c 4096 -b 4096 -ub 4096 -fa on`. It ran on the desktop's **CPU** (`-ngl 0 -t 8`), because the
    3060 was busy with another experiment.
  - The request: the first K1-full request, listing A's description replaced by filler text.
  - 6,000 words: refused at 8,026 tokens. The first cut fell short: the rules cost more tokens
    a word than the filler. The second, sized from what the first saved, landed at 4,030 tokens
    (3,445 words cut, 2 retries).
  - 3,000 words: refused at 4,546 tokens; one cut of 408 words landed at 4,074.
  - Not checked: the card's own behaviour, which is the same server code.

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
- **One model at a time, enforced**, on a fake clock: no session, lease or load inside
  `no_new_lease_s` (a lease taken just before it goes back uncharged with nothing loaded); a
  real child that ignores SIGTERM killed at the window's end plus 4.5 minutes (05:04:30,
  before pplx's 05:05); the deadline the supervisor sets; a stop seen before the fork forks
  nothing, one recorded during it reaches the child; the signal handler only records. The
  compose file: the proxy listens on its internal address only, workers have `pids_limit`.
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
- **The compose stack's checks on the home server are one window old.** It ran end to end
  on the desktop with fake components ("Running on the home server"), then went live there
  on 2026-11-19 with the real broker and weights; one Kev window has run (above). A pplx
  window that scores, and a window end that interrupts a real request, have not yet been
  seen there. The old timers and the `DOCKER-USER` rules, if they were ever installed, are
  removed by hand; this document does not record that they were.
- **The 5-minute gap after Kev's window is an estimate from the measured worst cases** (a
  request of about 104 s or a load of about 150 s, then up to 3 × 10 s of last posts and a
  10 s join: about 4 minutes). It is now enforced from the stopping side: no lease or load in
  a window's last 5 minutes, and a kill 4.5 minutes after its end. Nothing checks from the
  starting side that the other worker has unloaded (the two containers share no state).
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
- **Pushing a locally reviewed backlog to production** (P4) is separate tooling, not part of
  the worker: `./makhzan ai import DIR` (`worker/ai_import.py`, `docs/ai/broker-api.md`
  §6.1), which imported the backlog on 2026-11-19.
