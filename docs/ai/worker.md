# AI matching: the worker

Status: **built, tested against a contract-following fake broker, and checked against the
phase 2 broker app on its final contract** (five end-to-end sessions, below). Nothing has
run on the home server yet. What is not here yet is listed at the end.

A worker is one process that serves the model key(s) its configuration names. It talks only
to the broker, over HTTPS with its own bearer token. It loads its model once, scores the
requests the broker renders, one request per forward call, and posts the scores back. The
broker treats every worker the same. Each worker's TOML file decides what it runs, on what
hardware, and when, so two workers on one machine overlap only if their windows say so (owner
decision, 2026-11-17).

The code is `ml/makhzan_ml/worker/`, and its tests are `ml/tests/` (`make test-worker`).

**Merge order: `feat/ml-improve` (PR #57) first.** The worker images build on the lean CPU
images and the pplx shim that PR adds (`ml/kev/Dockerfile.cpu-lean`, `ml/pplx/`). This
branch carries none of them.

| Module | What it does |
|---|---|
| `config.py` | the TOML file: parsing, validation, windows |
| `broker.py` | the HTTPS client: bearer token, typed errors, retry with backoff |
| `judges.py` | loads a model in-process on the validated scoring path; no mmap; pin checks |
| `pins.py` | what each model key is pinned to (a copy of `makhzan_schemas.ai.policy.MODELS`, held equal by a test) |
| `run.py` | one session, from hello to the last release |
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

1. **Window.** Outside every window, the worker exits 0 and sends nothing. Start it at the
   window's start, with a systemd timer or cron.
2. **Pre-flight.** Every model key must be loadable in this image. Each model image holds
   one model's code, so naming a key the image lacks is refused before anything is sent. If
   the container's memory limit (cgroup v2 `memory.max`) is below `memory_gib`, the worker
   refuses to start, because it would be killed mid-job and the broker would count an
   attempt. When no limit is visible (no `--memory`, or cgroup v1), the check is skipped and
   the log says so. The worker then lowers its own priority by `nice`.
3. **`POST /hello`** sends the worker's name, its model keys with each model version and
   weights revision, the image, device, dtype, threads and its configuration. The broker
   answers `ok` per model key, and the `stages` that use it: each (pipeline, stage) and the
   prompt version its leases will carry, which the worker logs. A key answered `ok: false`
   (version drift) is never leased. If no key is `ok`, the worker exits 3.
4. **Lease, load, score, submit.** The worker drains each model key in the configured order:
   - `POST /lease` carries a fresh `lease_request_id` per lease. The client's retries of
     that call send the same id, so a lease whose answer was lost on the way comes back as
     the same lease instead of being orphaned until it expires. The body is rebuilt for
     each retry, so after a backoff it says how much time is left now; the broker replays
     by id, so a fresh time value is harmless.
   - It also carries honest time: the seconds left in the window, less an estimate of a
     model load still to come (`LOAD_ESTIMATE_S`: 150 s on CPU, 30 s on GPU), and the
     measured seconds per request (the configured estimate until the first is measured).
     The broker returns only jobs that fit, keeping a 60 s margin, and stops at the first
     that does not. A job the worker cannot start after all goes back gracefully. A worker
     that runs "always" sends no time, and only `max_jobs` limits its leases.
   - An empty lease that says `"reason": "none_fit"` means jobs are queued but none fits
     the time left. The worker logs "no job fits the time left" and stops for this window,
     whatever `on_empty` says: polling would only find the same. The broker ends the session
     on this answer (`end_reason` "none_fit", with no P16 rebuild), so no session release
     follows it. An empty lease without the field is an empty queue.
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
   - When the worker moves on to another model key, the first model is unloaded before the
     next one loads. Two 4B models do not fit side by side in 20 GB, or on a 12 GB card.
5. **Graceful stop** happens at the window's end, on SIGTERM or on SIGINT. A timer enforces
   the window's end, and it is also checked between retries, with no backoff sleeping past
   it. So a call retrying through a broker outage cannot keep the model loaded past the
   window while the next worker on the machine loads its own:
   - no new request is started, and the one in flight finishes (a forward pass cannot be
     interrupted);
   - finished orders are submitted, so half a job is kept;
   - the rest of the lease goes back with `POST /release`, reason `graceful`, which counts no
     attempt;
   - the model is unloaded.

   The worker also never starts a request it does not expect to finish before the window
   ends, using its measured seconds per request.
6. **Empty queue.** With `on_empty = "exit"`, the worker exits. With `"wait"`, it polls every
   `poll_s` until the window ends.
7. **Session end, exactly once.** The broker records a session's end at an empty lease
   ("empty"), at a lease answering `none_fit` ("none_fit", no P16 rebuild), or at a graceful
   release, with jobs or without ("released"). The worker ends every session it opened
   exactly once:
   - when one of those already ended it, nothing more is sent (a session release would
     overwrite "empty" or "none_fit" with "released");
   - otherwise (stopped between leases with nothing held: the window's end, a signal, an
     error, a 403 for a model key) it sends `POST /release {"session"}`, a
     graceful release naming no jobs (broker-api.md §3.5);
   - nothing is sent to a broker that is unreachable or refused the token (401);
   - a stop that comes before hello opens no session at all.

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
| the request in flight | 86 to 104 s on the home server's CPU, under 1 s on the GPU |
| retries, all calls together (`STOP_GRACE_S`) | 60 s |
| one last attempt each for the results, the lease release and the session release (`STOP_TIMEOUT_S`) | 3 × 10 s |
| joining the heartbeat thread | 10 s |

That is the request plus about 100 s. Anything still undelivered is logged before the process
exits. Set `--stop-timeout` above it: 240 s on the home server's CPU, 120 s on the GPU.

**Never drop a result silently.** A score is logged at ERROR as `UNDELIVERED`, with its job,
order, request hash and score (never the payload), the moment it is known not to have
arrived: the broker unreachable past the retry budget or the stop deadline, the broker
refusing it (422 or any other 4xx), or an unexpected error while posting. A summary is
logged at exit on every path. When the session would otherwise have exited 0, the exit code
says so (6); otherwise the code names what ended the session (for example 4). A score for a
lease the broker reports lost is logged at WARNING: the job's new holder scores it again.

**Unexpected errors** end the session with exit 1. These are a broker answer with no
handling (400, 404, 413), a malformed reply, or a bug. The jobs still held go back
gracefully first, unless the broker is unreachable; in that case they return when their
leases expire.

Payloads are never logged or written to disk. The token is sent only in the Authorization
header.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | the window ended, the queue was empty (`on_empty = "exit"`), or the worker started outside its window |
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
this image can load each model key, and exits.

### `[worker]`

| Key | Default | Meaning |
|---|---|---|
| `name` | required | the worker's name, as registered (`ai_workers.name`) |
| `broker_url` | required | the broker's base URL, `https://<broker host>/ai/v1`. Plain `http://` is refused except to a loopback address (the tests, the parity check, or a local broker on the same machine) |
| `token_file` / `token` | exactly one | the bearer token, preferably as a file (a Docker secret or a read-only mount) |
| `ca_file` | system CAs | a CA bundle to trust instead, for a privately signed broker certificate |
| `models` | required | the model keys served, from `policy.MODELS`: `["kev"]` or `["pplx"]`. Each image holds one model's code, so today a worker serves one key; a key the image cannot load is refused at start and by `--check`. A list exists for an image that holds several (drained in order) |

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
| `poll_s` | 600 | with `"wait"`, how often to ask for work again; at least 5 |

### `[leases]`

| Key | Default | Meaning |
|---|---|---|
| `max_jobs` | 2 | jobs per lease (a job is one pair, up to two requests). "Batch" means this, never batched inference |
| `lease_s` | 900 | the lease length the worker reports at hello, an integer from 60 to 7200 (the broker refuses any other) |
| `heartbeat_s` | 60 | at least 5, and at most half of `lease_s`. If the broker's hello answers a shorter interval, that one is used |
| `seconds_per_request` | 90 | the first estimate, replaced by the measured time after the first request. It sizes leases and decides whether a request still fits in the window |
| `retry_max_s` | `lease_s` | how long to retry a call through network failures before giving up |

## Example configurations

These four are examples. The windows are the design's proposal, not decided times. Hosts and
tokens are placeholders. The worker's tests parse every block below.

The home server's Kev worker:

```toml
# home-kev.toml
[worker]
name = "home-kev"
broker_url = "https://<broker host>/ai/v1"
token_file = "/run/secrets/makhzan-ai-token"
models = ["kev"]

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
windows = ["00:30-04:30"]
timezone = "Africa/Cairo"
on_empty = "exit"

[leases]
max_jobs = 2              # 4 requests, about 6 minutes on this CPU
lease_s = 900
heartbeat_s = 60
seconds_per_request = 90  # measured: about 86 s a request
```

The home server's pplx worker. Its window follows Kev's, so the two never share the memory:

```toml
# home-pplx.toml
[worker]
name = "home-pplx"
broker_url = "https://<broker host>/ai/v1"
token_file = "/run/secrets/makhzan-ai-token"
models = ["pplx"]

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
windows = ["04:30-06:30"]
timezone = "Africa/Cairo"
on_empty = "exit"

[leases]
max_jobs = 2
lease_s = 900
heartbeat_s = 60
seconds_per_request = 105  # measured: about 104 s a request
```

The desktop's GPU workers, for a backlog. They run until the queue is empty. Run one at a
time: each 4B model needs most of the 12 GB card.

```toml
# desk-kev.toml
[worker]
name = "desk-kev"
broker_url = "https://<broker host>/ai/v1"
token_file = "/run/secrets/makhzan-ai-token"
models = ["kev"]

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
seconds_per_request = 1   # measured: about 3 requests a second
```

```toml
# desk-pplx.toml
[worker]
name = "desk-pplx"
broker_url = "https://<broker host>/ai/v1"
token_file = "/run/secrets/makhzan-ai-token"
models = ["pplx"]

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
seconds_per_request = 1   # measured: about 2 requests a second
```

## Images

`ml/worker.Dockerfile` adds the worker to a model image. Build the base images first
(`ml/kev`, `ml/pplx`; see `ml/README.md`; the lean CPU images and `ml/pplx` come with
PR #57), then build from the `ml/` directory. Its
`.dockerignore` sends only the worker's code, never the weights cache or `ml/out/`.

```bash
# CPU (home server): on the lean images
docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/kev-cpu-lean:1.0 \
  -t makhzan-ml/kev-worker-cpu:1.0 ml
docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/pplx-decider-cpu-lean:1.3 \
  -t makhzan-ml/pplx-worker-cpu:1.0 ml
# GPU (desktop): on the GPU images
docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/kev:1.0 \
  -t makhzan-ml/kev-worker-gpu:1.0 ml
docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/pplx-decider:1.3 \
  -t makhzan-ml/pplx-worker-gpu:1.0 ml
```

The base images are local builds referenced by tag. They are not in a registry, so `FROM`
cannot pin them by digest. Each run command below passes the built image's id as
`MAKHZAN_IMAGE`, which the worker reports at hello.

## Running on the home server (CPU, capped)

The caps:

- **CPU**: 6 threads (`threads = 6` and `--cpus=6`), a lowered priority (`nice = 10`,
  applied by the worker itself), and `--cpu-shares=256`, so anything else on the machine
  wins contention.
- **Memory**: `--memory=20g --memory-swap=20g`, so there is no swap.
- **Weights**: no mmap (`mmap = false`), read-only from the HDD cache.
- **Network**: egress to the broker only.
- **`--rm`**.

The weights directory is a Hugging Face home whose `hub/` holds the pinned snapshots as
real files (copied with `rsync -L`, as for the CPU benchmark), plus `trees/` and `refs/`.

```bash
NAME=home-kev IMAGE=makhzan-ml/kev-worker-cpu:1.0   # or home-pplx, makhzan-ml/pplx-worker-cpu:1.0
docker run --rm --name "makhzan-ai-$NAME" --init --stop-timeout 240 \
  --cpus=6 --cpu-shares=256 --memory=20g --memory-swap=20g \
  --read-only --tmpfs /tmp:size=256m -e HOME=/tmp \
  --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges \
  --network makhzan-ai --add-host "<broker host>:<broker address>" \
  -e MAKHZAN_IMAGE="$(docker image inspect -f '{{.Id}}' "$IMAGE")" \
  -v "<weights dir>:/models:ro" \
  -v "<config dir>/$NAME.toml:/etc/makhzan-ai/worker.toml:ro" \
  -v "<config dir>/$NAME.token:/run/secrets/makhzan-ai-token:ro" \
  "$IMAGE"
```

- `--stop-timeout 240` covers the bound under "A stop sets one deadline": one CPU request
  (86 to 104 s) plus about 100 s for delivering, releasing and ending the session.
- The worker stops itself at the window's end in any case; the timer only starts it.
- `--user` must be able to read the weights and the two mounted files.

**Egress to the broker only.** `makhzan-ai` is a user-defined bridge network whose subnet may
reach only the broker, on port 443. The rules go in Docker's `DOCKER-USER` chain. Each `-I`
inserts at the top, so add the DROP first:

```bash
docker network create --driver bridge --subnet <subnet> makhzan-ai
iptables -I DOCKER-USER -s <subnet> -j DROP
iptables -I DOCKER-USER -s <subnet> -d <broker address> -p tcp --dport 443 -j ACCEPT
iptables -I DOCKER-USER -s <subnet> -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

`--add-host` pins the broker's name, so the worker needs no DNS lookup. The rules must be
restored at boot, for example with `iptables-save` and the distribution's restore service. The
worker enforces what it can on its side: `https://` only, offline model loading, and no other
peer.

**Starting at the window.** One timer per worker, at its window's start:

```ini
# /etc/systemd/system/makhzan-ai-home-kev.timer
[Timer]
OnCalendar=*-*-* 00:30:00
Persistent=false
[Install]
WantedBy=timers.target
```

The timer's service runs the `docker run` above (`Type=oneshot`). Do the same for `home-pplx`
at 04:30. If a run is late, it ends at its window's end all the same.

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
   `--stop-timeout 120` covers the stop bound: a GPU request (under 1 s) plus about 100 s.
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
`feat/ai-broker`), on a test database seeded with fictional listings. The broker was served
by uvicorn on the test's event loop, and the real worker ran with a fake judge in a thread,
over HTTP. Run last against the final contract (`feat/ai-broker`, commit `fcbc5a2`); five
sessions:

- **Kev, then pplx, then a decision.** Two match pairs were leased, scored and posted for
  Kev. The broker queued their pplx stage, the worker unloaded Kev, loaded pplx and drained
  it. The result was two standing "same" decisions and 8 score rows carrying the device,
  dtype and threads. Hello announced the stages (`match/kev`, `audit/kev`, `match/pplx`),
  the broker recorded the lease request id, and the empty lease ended the session
  ("empty"), with no session release after it.
- **A graceful stop.** A heartbeat with `job_ids` was sent mid-job. SIGTERM on the third
  request kept the finished order, and the two jobs not finished went back with no attempt
  counted. The session ended "released".
- **Session end between leases.** SIGTERM right after a job's results, with nothing held:
  the session release ended the session.
- **A lease whose answer is lost.** The broker leased two jobs and the answer was dropped.
  The client's retry, with the same `lease_request_id`, got the same lease back. Both jobs
  were scored once, none charged an attempt.
- **Time fit.** With 30 minutes left, 300 s a request and Kev not yet loaded, the worker
  sent `seconds_left` 1650. The broker leased the two jobs that fit (1590 s after its
  margin) and stopped at the third. Twenty minutes later, with 600 s left, nothing fit. Two
  jobs stayed queued, none charged.

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
  - version drift at hello, on one key only, and at lease;
  - a tampered payload, a failing request, a model that keeps failing, and a model that
    will not load;
  - a wrong token, a key not granted, a memory limit too small, and two models in turn;
  - every session ending exactly once (window end, SIGTERM, empty queue, a fatal error,
    SIGTERM mid-lease, a 403 at lease), none sent to a broker that is down or refused the
    token, and none opened by a stop before hello; a lost lease answer retried into the
    same lease, and a lease retry carrying the time left now under the same id; `none_fit`
    ending the window whatever `on_empty`, and the session with no release after it; no
    lost warning for a job being settled; leases carrying honest time and holding only jobs
    that fit; a heartbeat naming each job as it starts, before its results, with an integer
    job id; a crash charged to the job in hand alone; an unannounced prompt version logged.
- **Pins**: `pins.PINS` equals `policy.MODELS`, the worker's request hash equals
  `prompt.request_sha256` on rendered requests, the mapped-weights check can fire, and scores
  outside [0, 1] are refused.

## Not done yet

- **The model load estimate is a constant** (`LOAD_ESTIMATE_S`), taken from the measured
  loads, not measured per run. A first lease whose load took longer than the estimate can
  hold a job the worker cannot finish. That job goes back gracefully, with no attempt.
- **The Kev code commit is not verified.** The base images keep `KEV_COMMIT` as a build ARG
  only, so the worker cannot read which Kev code it runs. The tarball checksum in the base
  Dockerfile pins it at build time. The full fix is an `ENV` or `LABEL` in
  `ml/kev/Dockerfile*`, passed on as `MAKHZAN_KEV_COMMIT`.
- **One model per worker.** Each image holds one model's code, so a worker names one key;
  the start-up check refuses any other. The code still unloads one model before loading
  another, for an image that someday holds both. Freeing Kev's memory on unload is coded (the
  atexit hook that held it is removed) but has not been measured with real models.
- **No systemd units or network rules are shipped**: only the examples above. Setting them up
  on the home server is a separate, supervised step.
- **No registry or image digests.** The images are local builds.
- **Nothing has run on the home server through the worker.** Both models were checked on
  CPU on the desktop, under the same caps (above). The next check is one supervised run of
  each worker on the home server, against the real broker.
- **Pushing a locally reviewed backlog to production** (P4) is separate tooling, not part of
  the worker.
