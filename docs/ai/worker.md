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
6. **Empty queue.** With `on_empty = "exit"`, the worker exits. With `"wait"`, it polls every
   `poll_s` until the window ends.
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

Anything still undelivered is logged before the process exits. Set `--stop-timeout` above
the bound: 240 s on the home server's CPU, 120 s on the GPU.

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
this image can load the model key, and exits.

### `[worker]`

| Key | Default | Meaning |
|---|---|---|
| `name` | required | the worker's name, as registered (`ai_workers.name`) |
| `broker_url` | required | the broker's base URL over Tailscale, `http://<tailscale-ip>:<port>/ai/v1`. Plain `http://` is accepted only to a Tailscale address (100.64.0.0/10, fd7a:115c:a1e0::/48) or a loopback one (127.0.0.0/8, ::1: the tests, the parity check, a broker on the same machine), and only as an address, never a name (not even `localhost`) and with no zone id; a malformed port is refused at load; anything else must be `https://` |
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
| `poll_s` | 600 | with `"wait"`, how often to ask for work again; at least 5 |

### `[leases]`

| Key | Default | Meaning |
|---|---|---|
| `max_jobs` | 2 | jobs per lease (a job is one pair, up to two requests). "Batch" means this, never batched inference |
| `lease_s` | 900 | the lease length the worker reports at hello, an integer from 60 to 7200 (the broker refuses any other) |
| `heartbeat_s` | 60 | at least 5, and at most half of `lease_s`. If the broker's hello answers a shorter interval, that one is used |
| `retry_max_s` | `lease_s` | how long to retry a call through network failures before giving up |

## Example configurations

These four are examples. The windows are the design's proposal, not decided times. Hosts and
tokens are placeholders. The worker's tests parse every block below.

The home server's Kev worker:

```toml
# home-kev.toml
[worker]
name = "home-kev"
broker_url = "http://<tailscale-ip>:<port>/ai/v1"
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
windows = ["00:30-04:30"]
timezone = "Africa/Cairo"
on_empty = "exit"

[leases]
max_jobs = 2   # 4 requests, about 6 minutes on this CPU (about 86 s a request)
lease_s = 900
heartbeat_s = 60
```

The home server's pplx worker. Its window follows Kev's, so the two never share the memory:

```toml
# home-pplx.toml
[worker]
name = "home-pplx"
broker_url = "http://<tailscale-ip>:<port>/ai/v1"
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
windows = ["04:30-06:30"]
timezone = "Africa/Cairo"
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
demand). Each is one chain, from `ml/docker-bake.hcl`: the lean model image
(`ml/kev/Dockerfile.cpu-lean`, `ml/pplx/Dockerfile.cpu-lean`), then the worker layer on exactly
that build, through a named context, so no registry tag or local image comes between them.
Before pushing, CI runs `python -m makhzan_ml.worker.smoke --model <key>` in the image with
`--network none`. It checks that torch sees no CUDA device and `fla` is absent, that the
model's code and (for Kev) its pinned commit are present, that the image holds no weight file,
that the entrypoint's `--check` passes, and that a whole session runs against the fake broker
with a fake judge. Pull requests touching `ml/` build and smoke-test without pushing. Each image
is tagged `sha-<commit>` (long and short), and the run's summary prints its digest:

```bash
docker pull ghcr.io/ahmedsaed/makhzan/kev-worker-cpu@sha256:<digest>
docker pull ghcr.io/ahmedsaed/makhzan/pplx-worker-cpu@sha256:<digest>
```

The home server pulls by digest and runs by digest (below), so the image it runs is the one
CI smoke-tested, whatever a tag points at later. Both are public. The upstream code is
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
  -t makhzan-ml/kev-worker-gpu:1.0 ml
docker build -f ml/worker.Dockerfile --build-arg BASE=makhzan-ml/pplx-decider:1.3 \
  -t makhzan-ml/pplx-worker-gpu:1.0 ml
```

A local base is referenced by tag, so `FROM` cannot pin it by digest. The desktop run command
passes the built image's id as `MAKHZAN_IMAGE`, which the worker reports at hello.

The Kev images record the Kev code commit they were built from as `MAKHZAN_KEV_COMMIT`
(`ml/kev/Dockerfile*`), and the worker refuses to load Kev if it differs from its pin. A Kev
base built before that change records none, and the worker only logs that.

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
NAME=home-kev   # or home-pplx, with pplx-worker-cpu
IMAGE=ghcr.io/ahmedsaed/makhzan/kev-worker-cpu@sha256:<digest>   # from the CI run's summary
docker pull "$IMAGE"
docker run --rm --name "makhzan-ai-$NAME" --init --stop-timeout 240 \
  --cpus=6 --cpu-shares=256 --memory=20g --memory-swap=20g \
  --read-only --tmpfs /tmp:size=256m -e HOME=/tmp \
  --user "$(id -u):$(id -g)" --cap-drop ALL --security-opt no-new-privileges \
  --network makhzan-ai \
  -e MAKHZAN_IMAGE="$IMAGE" \
  -v "<weights dir>:/models:ro" \
  -v "<config dir>/$NAME.toml:/etc/makhzan-ai/worker.toml:ro" \
  -v "<config dir>/$NAME.token:/run/secrets/makhzan-ai-token:ro" \
  "$IMAGE"
```

- `--stop-timeout 240` covers the bound under "A stop sets one deadline": about 144 s for
  the slowest CPU request in flight, about 170 s for a model load in flight (the 60 s of
  retries runs out during the load, leaving one 10 s attempt for the lease's release, plus
  the 10 s heartbeat join).
- The worker stops itself at the window's end in any case; the timer only starts it.
- `--user` must be able to read the weights and the two mounted files.
- `MAKHZAN_IMAGE` is the registry digest the image was pulled by, so the broker's record of
  each session names exactly the image CI built and smoke-tested.
- To move to a new build, take the digest from the newest run of "AI worker images" and change
  `IMAGE`; nothing on the server follows a tag.

**Egress to the broker only.** The broker is reached over Tailscale at
`http://<tailscale-ip>:<port>`; the host's Tailscale client carries the traffic, encrypted.
`makhzan-ai` is a user-defined bridge network whose subnet may reach only that address and
port. The rules go in Docker's `DOCKER-USER` chain. Each `-I` inserts at the top, so add the
DROP first:

```bash
docker network create --driver bridge --subnet <subnet> makhzan-ai
iptables -I DOCKER-USER -s <subnet> -j DROP
iptables -I DOCKER-USER -s <subnet> -d <tailscale-ip> -p tcp --dport <port> -j ACCEPT
iptables -I DOCKER-USER -s <subnet> -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```

The broker URL is an address, so the worker needs no DNS lookup. The rules must be restored
at boot, for example with `iptables-save` and the distribution's restore service. The worker
enforces what it can on its side: plain `http://` only to a Tailscale or loopback address,
offline model loading, proxy settings ignored, and no other peer.

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
- **Freeing Kev's memory on unload** at the end of a session is coded (the atexit hook that
  held it is removed) but has not been measured with real models.
- **No systemd units or network rules are shipped**: only the examples above. Setting them up
  on the home server is a separate, supervised step.
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
