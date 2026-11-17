# AI matching: the worker

Status: **built and tested against a fake broker; not yet run against the real broker**
(phase 2, built in parallel against `docs/ai/broker-api.md`). What is not here yet is listed
at the end.

A worker is one process that serves the model key(s) its configuration names. It talks only
to the broker, over HTTPS with its own bearer token. It loads its model once, scores the
requests the broker renders, one request per forward call, and posts the scores back. The
broker treats every worker the same. Each worker's TOML file decides what it runs, on what
hardware, and when, so two workers on one machine overlap only if their windows say so (owner
decision, 2026-11-17).

The code is `ml/makhzan_ml/worker/`, and its tests are `ml/tests/` (`make test-worker`).

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
2. **Pre-flight.** If the container's memory limit (cgroup `memory.max`) is below
   `memory_gib`, the worker refuses to start, because it would be killed mid-job and the
   broker would count an attempt. It then lowers its own priority by `nice`.
3. **`POST /hello`** sends the worker's name, its model keys with each model version and
   weights revision, the image, device, dtype, threads and its configuration. The broker
   answers `ok` per model key. A key answered `ok: false` (version drift) is never leased. If
   no key is `ok`, the worker exits 3.
4. **Lease, load, score, submit.** The worker drains each model key in the configured order:
   - `POST /lease` carries the seconds left in the window and the measured seconds per
     request.
   - The model is **loaded on the first lease that brings jobs**, never on an empty night.
     Once loaded, it is checked against its pins: the snapshot revision, the temperature it
     scores at, the Kev code commit and the prefix cache off. Then every weight file is
     checked to be unmapped (CPU).
   - Each job's requests are scored **in the order the broker sent them, one per call: no
     batching, no reordering** (owner decision, 2026-11-17). Before scoring a request, the
     worker recomputes `request_sha256` over its payload. A mismatch is never scored; the job
     goes back as an error.
   - The worker sends `POST /results` once per job.
   - While a lease is held, a background thread sends `POST /heartbeat` every `heartbeat_s`
     with the lease ids, the resident memory and the request in progress.
   - When the worker moves on to another model key, the first model is unloaded before the
     next one loads. Two 4B models do not fit side by side in 20 GB, or on a 12 GB card.
5. **Graceful stop** happens at the window's end, on SIGTERM or on SIGINT:
   - no new request is started, and the one in flight finishes (a forward pass cannot be
     interrupted);
   - finished orders are submitted, so half a job is kept;
   - the rest of the lease goes back with `POST /release`, reason `graceful`, which counts no
     attempt.

   The worker also never starts a request it does not expect to finish before the window
   ends, using its measured seconds per request.
6. **Empty queue.** With `on_empty = "exit"`, the worker exits. With `"wait"`, it polls every
   `poll_s` until the window ends.
7. **Session end.** Every session ends with a graceful `POST /release`, so the broker sees the
   session end and can queue the rebuild (P16). That last release names no jobs.

**Retries.** A network failure, a 5xx or a 429 is retried with exponential backoff: 1 s, 2 s,
4 s and so on, capped at 60 s, and never shorter than a `Retry-After`. Retries continue for
up to `retry_max_s` in all. A 4xx is the broker's answer and is not retried.

**Never drop a result silently.** A score that cannot be delivered within `retry_max_s`, or
that the broker refuses (422), is logged at ERROR as `UNDELIVERED`, with its job, order,
request hash and score, never the payload. The exit code then says so (4 or 6). A score for a
lease the broker reports lost is logged at WARNING: the job's new holder scores it again.

Payloads are never logged or written to disk. The token is sent only in the Authorization
header.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | the window ended, the queue was empty (`on_empty = "exit"`), or the worker started outside its window |
| 1 | the model failed 3 requests in a row, or an unexpected error |
| 2 | configuration error, memory limit below `memory_gib`, or a model that will not load as pinned (its lease goes back as an error) |
| 3 | version drift: the broker's registry runs another model version (at hello, or 409 at lease) |
| 4 | the broker could not be reached for `retry_max_s`; undelivered scores are logged |
| 5 | 401 or 403: the token is wrong or revoked, or the worker is not registered for a model key |
| 6 | the session ended, but the broker refused some scores; they are logged |

## Configuration reference

The configuration is one TOML file, by default `/etc/makhzan-ai/worker.toml` inside the
container. Unknown sections and keys are errors. Relative paths resolve against the file's
directory. `python -m makhzan_ml.worker --config FILE --check` validates a file and exits.

### `[worker]`

| Key | Default | Meaning |
|---|---|---|
| `name` | required | the worker's name, as registered (`ai_workers.name`) |
| `broker_url` | required | the broker's base URL, `https://<broker host>/ai/v1`. Plain `http://` is refused except to a loopback address (the tests, the parity check, or a local broker on the same machine) |
| `token_file` / `token` | exactly one | the bearer token, preferably as a file (a Docker secret or a read-only mount) |
| `ca_file` | system CAs | a CA bundle to trust instead, for a privately signed broker certificate |
| `models` | required | the model keys served, from `policy.MODELS`: `["kev"]`, `["pplx"]` or both (drained in this order) |

### `[model.<key>]` (optional)

| Key | Meaning |
|---|---|
| `expect_version` | the model version this configuration was written for. The file is refused if the image serves another version: the image or the configuration is stale |

### `[compute]`

| Key | Default | Meaning |
|---|---|---|
| `device` | `"cpu"` | `"cpu"` or `"gpu"` |
| `dtype` | `fp32` on CPU, `bf16` on GPU | only the validated pairing is accepted. GPU bf16 and CPU fp32 are one model version (P8), and each score records its device and dtype |
| `threads` | all the container may use | the CPU cap: `torch.set_num_threads`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` |
| `nice` | 10 on CPU, 0 on GPU | how much the worker lowers its own priority (0 to 19) |
| `memory_gib` | unset | the expected peak resident memory. The worker refuses to start under a smaller container limit and warns if a load peaks above it. Measured on CPU fp32: Kev 17.5 GiB, pplx 18.4 GiB |
| `mmap` | `false` on CPU, `true` on GPU | `false` reads every weight file with pread(2) and fails the load if any weight file is still mapped afterwards |
| `weights_cache` | the image's `HF_HOME` | the Hugging Face home holding `hub/`, mounted read-only. The worker always runs offline |

### `[schedule]`

| Key | Default | Meaning |
|---|---|---|
| `windows` | `"always"` | `"always"`, or one or more `"HH:MM-HH:MM"` in local time. A window may cross midnight (`"22:00-02:00"`). Windows that touch or overlap run on as one |
| `timezone` | the machine's | an IANA zone such as `"Africa/Cairo"`. Set it: a container's local time is UTC unless told otherwise |
| `on_empty` | `"exit"` | `"exit"` or `"wait"` |
| `poll_s` | 600 | with `"wait"`, how often to ask for work again |

### `[leases]`

| Key | Default | Meaning |
|---|---|---|
| `max_jobs` | 2 | jobs per lease (a job is one pair, up to two requests). "Batch" means this, never batched inference |
| `lease_s` | 900 | the lease length the worker reports at hello |
| `heartbeat_s` | 60 | at most half of `lease_s`. If the broker's hello answers a shorter interval, that one is used |
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
(`ml/kev`, `ml/pplx`; see `ml/README.md`), then build from the `ml/` directory. Its
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

- `--stop-timeout 240` lets the request in flight finish on `docker stop`. One CPU request
  takes 86 to 104 s.
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
   docker run --rm --name "makhzan-ai-$NAME" --init --stop-timeout 60 --gpus all \
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

- Kev: snapshot `6cfce5c…`, code `6b719c3`, temperature 1.0, fused kernels on, prefix cache
  off.
- pplx: snapshot `d06fb3f…`, temperature 1.3303.

Both loaded offline from the read-only cache. Each session ended with its graceful release
and exit 0. The GPU time was under a minute in all.

This proves the GPU path. The CPU path (fp32, no mmap) uses the same calls. The CPU
benchmark has already measured those against these GPU scores (`ml/README.md` on the
ml-improve branch, PR #57). It has not
yet been run through the worker itself (see "Not done yet").

## Tests

`make test-worker` runs `ml/tests/` with the ingestion environment. It needs no database and
no model. CI runs it with the ingestion suite.

- **Configuration**: defaults, every refusal, windows (crossing midnight, touching windows,
  boundaries), and every example in this document.
- **Lifecycle**, against the fake broker with a fake judge and clock:
  - a full session, and the payloads scored exactly as sent, in order;
  - an empty queue with `exit` and with `wait`, and starting outside the window;
  - a window closing across midnight, a half-scored job, SIGTERM, and a request that would
    overrun;
  - retries with backoff and `Retry-After`, a broker that stays down, and a refused result;
  - heartbeats during a long job, and a lease lost at heartbeat or at results;
  - version drift at hello, on one key only, and at lease;
  - a tampered payload, a failing request, a model that keeps failing, and a model that
    will not load;
  - a wrong token, a key not granted, a memory limit too small, and two models in turn.
- **Pins**: `pins.PINS` equals `policy.MODELS`, the worker's request hash equals
  `prompt.request_sha256` on rendered requests, the mapped-weights check can fire, and scores
  outside [0, 1] are refused.

## Not done yet

- **Not run against the real broker.** Phase 2 is being built in parallel. The open
  questions on the contract are listed in the phase 3 report and repeated here until the
  contract settles them:
  - Is a session-ending `/release` that names no lease and no jobs valid? The worker sends
    one and tolerates a 4xx.
  - Should hello carry prompt versions? The broker renders, so the worker has none of its
    own. It logs each job's `prompt_version`.
  - Does a heartbeat that answers `lease_lost` for some jobs still extend the others?
- **No systemd units or network rules are shipped**: only the examples above. Setting them up
  on the home server is a separate, supervised step.
- **No registry or image digests.** The images are local builds.
- **The CPU path has not been run through the worker itself.** It uses the same calls,
  settings and no-mmap loader as the CPU benchmark, and the parity check above covers the GPU
  path. A CPU parity run on the home server is the next check.
- **Pushing a locally reviewed backlog to production** (P4) is separate tooling, not part of
  the worker.
