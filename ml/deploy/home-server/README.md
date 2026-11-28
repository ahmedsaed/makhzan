# The home server's AI workers, as one compose stack

Everything the home server needs to run makhzan's AI-matching workers is one folder:
`compose.yml`, a `.env`, the two worker TOMLs and their token files, the llama.cpp router's
preset (`models.ini`) and guard (`llamacpp-guard.sh`), and the two GGUF files. Everything runs in
containers: no host timers, scripts or firewall rules (owner's rule). The host's one setting is
the udev rule `99-amdgpu-clock-limit.rules`, which holds the AMD card to its safe clock states:
kernel settings only the host can make. The reference is `docs/ai/worker.md`.

| Service | What it is |
|---|---|
| `h2o` | `home-h2o`: H2O-Lightning-4B Q4_K_M, the first judge since D25 (2026-11-27; Kev before), window 06:00–10:00 (Africa/Cairo), judge: the router's `h2o` |
| `pplx` | `home-pplx`: pplx-decider Q4_K_S, window 10:05–12:00 (Africa/Cairo), judge: the router's `pplx` |
| `llamacpp` | llama.cpp's router on the AMD card: the judges' GGUFs (and Kev's, for the rollback), one loaded at a time, asleep when idle |
| `broker-proxy` | our own TCP forwarder (`makhzan_ml.worker.proxy`), the workers' only way out |

The 4 GB card holds one model. The router (`--models-max 1`) loads whichever a worker asks for,
swapping the other out: H2O's worker loads `h2o` on its window's first lease with jobs (from
06:00), pplx's loads `pplx` the same way (from 10:05). Idle for 10 minutes, the model sleeps and the card is free for Plex, Jellyfin and
Pitlane. Plain `docker compose up -d` starts all four services. The torch configurations
production ran until 2026-11-27 are kept as `torch-kev.toml` and `torch-pplx.toml`, and Kev's
llama.cpp worker, first judge until D25, is the rollback of D25 (below).

## Set up

1. Make the folder and copy in `compose.yml`, `home-h2o.toml`, `home-pplx.toml`, `models.ini`,
   `llamacpp-guard.sh`, and `.env.example` as `.env`. Fill in `.env`: the folder itself
   (`WORKER_DIR`), the weights (`WEIGHTS_DIR`, holding the GGUFs below), the user to run as
   (`UID`, `GID`: `id -u`, `id -g`), the card's groups (`RENDER_GID`, `VIDEO_GID`: `getent group
   render video`), and the broker's Tailscale address and port (`BROKER_TARGET`, an IP, never a
   name). Install the udev rule first (below).
2. Put each worker's broker token in `home-h2o.token` and `home-pplx.token` (`chmod 600`,
   owned by that user). The broker issues them: `./makhzan ai worker add home-h2o --models h2o`.
3. Check each worker's configuration first. A configuration error makes the worker exit 2,
   and `restart: unless-stopped` would restart it in a loop:

   ```bash
   docker compose run --rm --no-deps h2o --config /etc/makhzan-ai/worker.toml --check
   docker compose run --rm --no-deps pplx --config /etc/makhzan-ai/worker.toml --check
   ```

   Each prints `configuration ok: ...` (with the image's commit) and exits 0.
4. `docker compose up -d`, then the network check below.

Docker Engine 26 or newer is needed (the internal network's `inhibit_ipv4` option, below);
the check prints the engine's version.

Update to the latest tested images with `docker compose pull && docker compose up -d`. To
roll back, set `H2O_IMAGE` / `PPLX_IMAGE` in `.env` to an older `sha-<commit>` tag. A build
whose pins changed is refused by the TOMLs' `expect_version` until they follow.

**Pull before copying configs that use a new key.** A worker refuses a configuration key its
image does not know, so a TOML carrying a new key (such as `llamacpp_image`, D26, which records
the router's image with every score) deploys only after the image that accepts it: `docker
compose pull` first, then copy the TOMLs, then `docker compose up -d`.

## The llama.cpp router on the AMD card

**The clock limit comes first.** The card is held to clock states 0–2 (max 753 MHz) by the udev
rule `99-amdgpu-clock-limit.rules` (its header has the install commands). At higher states the
card's SATA-adapter power feed resets the whole server (docs/ai/kev-llamacpp.md). The router's
entrypoint, `llamacpp-guard.sh`, refuses to start unless every AMD card's
`/sys/class/drm/card*/device/power_dpm_force_performance_level` reads `manual` (containers see
the host's `/sys` read-only). A refusal is an exit, which `restart: unless-stopped` repeats: a
restart loop with the reason in `docker compose logs llamacpp`, never an unlimited card. sysfs
cannot show the clock-state mask itself, so `manual` is a necessary check, not a sufficient one:
it relies on the rule setting both together. Only a load shows the mask (the clock never above
753 MHz).

**The GGUFs** go in `WEIGHTS_DIR` (both the router and the workers mount them, read-only; each
worker hashes its own against the pin before scoring):

| File | sha256 |
|---|---|
| `h2o-lightning-4b-Q4_K_M.gguf` (`h2oai/h2o-lightning-4b-gguf@61f8d8b…`) | `5ec969c6edbad5f1750141742f635cc7f01576bf9432151f730f0a6c30042768` |
| `Kev-4B-Q4_K_M.gguf` (`ggml-org/Kev-4B-GGUF@f4624b6…`; the rollback of D25 only) | `33ae6b18926502b2209a1bf7d3b61a350d65938441515c686bb87d226a19eff9` |
| `pplx-flash-v1.3-Q4_K_S.gguf` (our conversion, `ml/models/convert_pplx_v13.py`) | `819a9ad0f8f4aacb055f6d1783a155e3bd0bf33afb9c2f33749ef25350c61ab3` |

**`models.ini`** is the router's preset: one section per model, named as the workers ask for it
(`h2o`, `pplx`, and `kev` for the rollback), with the settings soaked on the card (Kev: 512-token
batches; pplx: one 4,096 batch, flash attention, as its non-causal attention needs). `h2o` takes
Kev's settings (the same architecture and size, causal, so the batch changes speed, not
scores). A 2,048-token batch was about 3x faster on the 3060 (Q8: 1.06 to 3.05 requests/s; Q4 at
2,048: 3.12), using about 3.8 GB there, but is untested on this card (the optional test in the
runbook below). The router runs with
`--models-max 1 --sleep-idle-seconds 600 -dev Vulkan0`. `-dev Vulkan0` makes a missing card a
startup error ("invalid device: Vulkan0") instead of a silent CPU fallback; `RENDER_GID` and
`VIDEO_GID` (required in `.env`) let it, running as `UID`, open `/dev/dri`.

**What a worker does at its window.** Its session's load checks its GGUF, waits for the router's
`/health`, finds its model in the router's `GET /models` (whose preset path must be the pinned
file), asks the router to load it (`POST /models/load`; the other model is unloaded first) and
waits until it is loaded (up to 180 s, interruptible by a stop), then checks the build from
`/props?model=<name>`. On the 3060 the swap took 5–9 s; from this server's disk it may take
longer. Only then does it lease, so no request pays the load. A sleeping model wakes on its first
request (~6 s). The workers' windows never overlap. **Never send the router anything else during
a window** (a parity run, a `--check` that loads, a request for the other model): it evicts the
window's model and the two swap back and forth, each swap re-reading about 3 GB from this server's
disk under the container's memory limit. Run parity on the desktop. While the other model is busy
the router answers a load with HTTP 500 "model limit reached"; the worker retries within its
180 s budget.

**The clock limit at every load.** Each worker also re-reads the card's mode before every load
(`require_clock_limit = true` in `home-*.toml`) and refuses unless it reads `manual`: the router
checks only at its own start and may run for weeks.

**Concurrent use, and the card's voltage.** Plex, Jellyfin and Pitlane can share the card's
memory with a judge (a 1080p hardware transcode beside pplx left about 665 MB to spare,
2026-11-27), but not its power: their video engine lifts the card's voltage to the top state's
1,150 mV whatever the clock limit, and full compute load at that voltage resets the server (it did
at 05:05 on 2026-11-28, Jellyfin's trickplay task beside pplx). So each worker reads the card's
voltage (`max_vddgfx_mv`, 1,000 mV by default with `require_clock_limit`) before every lease and
every request: above it, it gives back what it holds unscored and waits, reading every 5 s, until
the card has read low for a minute on end (`vddgfx_clear_s`), so a gap between a trickplay job's
items does not end the wait (`docs/ai/worker.md`, "The card's voltage").

Its limits:
- It leaves the request in flight exposed when another app starts on the card.
- It reads the highest voltage of every amdgpu card on the host: on this server, the one card.
  A host with an AMD APU beside the card would wait whenever the APU reads high too.
- A failed read is retried twice; only when no amdgpu card can be read does the session end.

Keep the media servers' scheduled jobs (Jellyfin's trickplay and Plex's maintenance) out of the
windows. The real fix is a power supply that feeds the card properly.

**No CPU fallback is set up.** The router runs only on the card (`-dev Vulkan0`, and its guard
needs the clock limit). Scoring pplx on the CPU with the same GGUF (the same model version) would
need its own llama.cpp server without `-dev`, `n-gpu-layers = 0`, and `device = "cpu"` in
`home-pplx.toml`, which also turns off its clock-limit check; it is not built.

## Runbook: H2O as the first judge (D25, 2026-11-27)

The order matters: once production runs policy p2, the broker refuses `home-kev` at hello (its
model is no longer in `policy.MODELS`), so the H2O worker should be ready to start right after
the deploy. Nothing breaks in between; that night's first window is simply lost.

1. **Before the merge, on the home server** (nothing changes for the running stack):
   1. Fetch the GGUF into `WEIGHTS_DIR` as a real file (from the desktop's
      `ml/out/models-compare/h2o-q4/`, or from the Hub at the pinned revision), then check it:

      ```bash
      scp <desktop>:<repo>/ml/out/models-compare/h2o-q4/h2o-lightning-4b-Q4_K_M.gguf "$WEIGHTS_DIR/"
      # or: curl -L -o "$WEIGHTS_DIR/h2o-lightning-4b-Q4_K_M.gguf"       #   https://huggingface.co/h2oai/h2o-lightning-4b-gguf/resolve/61f8d8b7a8c2d84426d0d143ca187f65d235934b/h2o-lightning-4b-Q4_K_M.gguf
      sha256sum "$WEIGHTS_DIR/h2o-lightning-4b-Q4_K_M.gguf"
      # must print 5ec969c6edbad5f1750141742f635cc7f01576bf9432151f730f0a6c30042768
      ```

      Readable by the stack's `UID`. Keep `Kev-4B-Q4_K_M.gguf` there: it is the rollback, and
      the router mounts it.
2. **Merge** the PR. CI republishes `worker-llamacpp` from `main`; the smoke builds an `h2o`
   worker too.
3. **Deploy production** (`./makhzan deploy`, the owner's step). No migration. At the first
   hello and at the next daily producers run, the queued Kev jobs are moved to the `h2o`
   stage at their own reason and priority, and every standing decision carrying a Kev score is
   queued for re-scoring at 35 ("same") / 30 ("not same"), behind new pairs and the backlog.
4. **The worker record**, in production:

   ```bash
   ./makhzan ai worker add home-h2o --models h2o   # prints the token once
   ```

   Put the token in `home-h2o.token` in the stack folder (`chmod 600`, owned by `UID`).
5. **The home server**, in its stack folder (`/mnt/disk3/makhzan-ml/worker`):
   1. Copy the new `compose.yml`, `home-h2o.toml` and `models.ini` from the repository
      (`ml/deploy/home-server/`), keeping `.env` and the tokens. If `.env` sets `KEV_IMAGE`,
      rename it `H2O_IMAGE`.
   2. `docker compose pull`, then the new worker's check:
      `docker compose run --rm --no-deps h2o --config /etc/makhzan-ai/worker.toml --check`
      prints `configuration ok: ...` with `gpu q4_k_m`.
   3. `docker compose up -d --remove-orphans`: starts `h2o`, recreates the router with the
      `[h2o]` preset, and removes the old `kev` container (its service is gone).
      `home-kev.toml` and `home-kev.token` can then be deleted from the folder.
   4. A dry check outside the windows: `docker compose logs llamacpp` shows the router
      listening (and no guard refusal); `docker compose exec -T h2o python -c "import
      urllib.request as u; print(u.urlopen('http://llamacpp:8080/models').read()[:400])"` lists
      `h2o`, `kev` and `pplx`.
6. **Revoke the old worker**, in production: `./makhzan ai worker revoke home-kev`.
7. **The first windows** (06:00–12:00, Cairo time): `docker compose logs -f h2o` from 06:00 (the router loads `h2o`; requests
   at about Kev's 4–5 s on this card), then pplx from 10:05; `./makhzan ai status` after
   noon (the queue at `match.h2o`, and the audit per model). Check the card's memory during
   H2O's window once (`cat /sys/class/drm/card1/device/mem_info_vram_used`): on the 3060 H2O Q4
   used about 3.8–3.9 GB.
8. **The catch-up** is the owner's, as at the production switch: the re-scores of every standing
   decision, through H2O and then pplx where H2O passes (`desk-h2o` / `desk-pplx` on the desktop,
   `docs/ai/worker.md`).

**Optional: batch 2048 on the card.** H2O was about 3x faster at a 2,048-token batch on the 3060
(the scores do not depend on it: causal). Outside the windows, set `b = 2048` and `ub = 2048` in
`models.ini`'s `[h2o]`, `docker compose up -d llamacpp`, then score a few requests through the
router (the worker's `parity` tool, run with `--network container:` the router's, or one night's
window) while watching `mem_info_vram_used` and the clock. Keep it only if memory stays inside the
card with Plex's headroom and nothing resets; otherwise put 512 back.

**Rollback of D25** (to Kev on llama.cpp, one commit and the old stack files):

1. One forward commit: in `policy.py`, `ACTIVE = "p1"` and `MODELS["kev"] = LLAMACPP_KEV` in
   place of `MODELS["h2o"]`; in `pipelines.py`, the `match` and `audit` stages back to `kev`; in
   the worker, `pins.ACTIVE_BACKEND` names `kev` again. Not a `git revert` of D25: that would also
   take out the sweep's re-offer, and the queued `h2o` jobs would be cancelled. Deploy: the sweep
   moves queued `h2o` jobs back to `kev`, and decisions carrying H2O scores are re-scored (the
   group check still reads them at H2O's floor meanwhile).
   The same commit sets `ai_import`'s default `--policy` back to `p1`
   (`apps/ingestion/worker/ai_import.py`: `import_scores`, `verify` and the CLI default), or pass
   `--policy p1` to every `./makhzan ai import` after the rollback.
2. `./makhzan ai worker add home-kev --models kev` (a new token; the old record was revoked).
3. On the server: the previous `compose.yml`, `home-kev.toml` and `models.ini` from git,
   the new token in `home-kev.token`, `docker compose up -d --remove-orphans`. Kev's GGUF is still
   in `WEIGHTS_DIR`.

## Runbook: the production switch (2026-11-27, done)

Production already runs the new policy (deployed 2026-11-27 with #95), so the home server's old
workers would be refused at hello; they are stopped. **Already done on the server:** the udev rule
installed and checked (`manual`; under load the clock peaked at 753 MHz); both GGUFs in
`WEIGHTS_DIR` (`/mnt/disk3/makhzan-ml/cache/huggingface/`) with the hashes above verified; the
torch weights deleted; `RENDER_GID`/`VIDEO_GID` in `.env`; the `worker-llamacpp` image pulled.
No host timers were installed.

1. **Merge** this PR. CI republishes `worker-llamacpp` from `main` (public on GHCR).
2. **The home server**, in its stack folder (`/mnt/disk3/makhzan-ml/worker`):
   1. Delete the two scripts #95's runbook copied in, which are not used any more:
      `rm sidecar-window.sh install-sidecar-timers.sh`.
   2. Copy the new `compose.yml`, `home-kev.toml`, `home-pplx.toml`, `models.ini` and
      `llamacpp-guard.sh` from the repository (`ml/deploy/home-server/`), keeping `.env` and the
      tokens.
   3. `docker compose pull`, then each worker's `--check` (Set up, step 3): it must print its
      llama.cpp configuration (`gpu q4_k_m` / `gpu q4_k_s`). The old torch images can then be
      removed (`docker image rm` of the `kev-` and `pplx-worker-cpu` tags).
   4. `docker compose up -d`: the workers, the proxy and the router.
   5. A dry check outside the windows: `docker compose logs llamacpp` shows the router listening
      (and no guard refusal); `docker compose exec -T kev python -c "import urllib.request as u;
      print(u.urlopen('http://llamacpp:8080/models').read()[:300])"` lists `kev` and `pplx`.
3. **The first windows** (Cairo time): `docker compose logs -f kev` from 06:00 (the router loads `kev`, requests
   at about 4–5 s), and pplx from 10:05 (the swap, then requests); `./makhzan ai status` after
   noon. Check the card's memory during Kev's window once
   (`cat /sys/class/drm/card1/device/mem_info_vram_used`): on the 3060 Kev grew to about 4.1 GB
   while scoring (NVIDIA's driver); on this card the soak at the same settings stayed inside 4 GB.

**Rollback to torch** (before D25; after it, roll D25 back first, above): move `policy.MODELS` back to `policy.TORCH_MODELS` and `pins.ACTIVE_BACKEND` to
`torch` (one commit) and deploy. On the home server, **the torch weights were deleted** on
2026-11-27, so first re-download them into `WEIGHTS_DIR` as real files (`rsync -L`; Kev-4B with its
Qwen3.5-4B-Base, and pplx-decider-flash-v1.3, at the revisions in `worker/pins.py`; about 20 GB).
Then copy `torch-kev.toml` / `torch-pplx.toml` over `home-*.toml`, set `KEV_IMAGE` / `PPLX_IMAGE`
to the torch worker images (`kev-worker-cpu`, `pplx-worker-cpu`: CI still builds and publishes
them), `docker compose stop llamacpp`, and `docker compose up -d kev pplx broker-proxy`.

## How it behaves

- **Each worker waits for its own window** (`outside_window = "wait"`). Outside it, the
  container holds only a small supervisor process, no model (the model is in the router, on the card): `docker stats` shows a few tens
  of MB. When the window opens, the supervisor forks a session that says hello, leases,
  loads the model on the first lease with jobs, scores, and stops gracefully at the window's
  end (finishes the request in flight, submits, releases the rest, ends the session, unloads).
  The child then exits, so all of the model's memory goes back to the system. The log says
  `sleeping until 06:00 (Africa/Cairo)`, `window open`, `window closed; model unloaded`.
- **An empty queue** (`on_empty = "exit"`) ends that window's session early and frees the
  model until the next window. Set `on_empty = "wait"` to keep polling every `poll_s` until
  the window's end instead, with the model held once loaded.
- **One model at a time on the card.** The windows never overlap, and the router
  (`--models-max 1`) unloads one model before it loads the other. A worker whose model cannot be
  loaded (the router down, refusing on the guard, or slower than 180 s) fails its load, logged,
  and the next window tries again. If a session is still running 4.5 minutes after its window's
  end the supervisor kills it (logged as `KILLING the session`); a killed session's lease expires
  at the broker and charges the job in hand one attempt.
- **`docker compose stop`** while a worker sleeps exits at once; during a window it is the
  graceful stop, within `stop_grace_period` (240 s; 300 s for pplx, for its CPU fallback).
- **The image names itself at hello** as `ghcr.io/ahmedsaed/makhzan/<image>:sha-<commit>`,
  the commit CI built and tested, so the broker's record says which build scored.

## The network

The workers are on `broker-only`, a Docker network with `internal: true`: no route out, no
DNS beyond the stack's own service names. `broker-proxy` is on that network, at a fixed
address (`PROXY_ADDRESS`, 10.231.89.2 by default) that the workers' own addresses can never
take (they are drawn from `BROKER_NET_DYNAMIC`, 10.231.89.128/25), and on an ordinary bridge (`egress`). It
listens on its `broker-only` address only, never on the bridge, and forwards one TCP port to
`BROKER_TARGET`, byte for byte, and to nothing else: it reads no request, so nothing a worker
sends can name another destination. The host's Tailscale client carries the proxy's traffic to the broker, as it did
for the workers before. The worker TOMLs say `broker_url = "http://broker-proxy:8100/ai/v1"`
with `broker_via_proxy = true`, the only case where the worker accepts plain http to a name,
and only to that exact name (`broker_proxy_hosts`, default `["broker-proxy"]`). That is safe
only inside this stack, where the name can resolve to nothing but the proxy on an internal
network; never set it for a worker on an ordinary network.

`internal: true` alone still gives the host an address on that network's bridge, so a worker
could reach a host service listening on all interfaces. `com.docker.network.bridge.inhibit_ipv4`
removes that address; it needs Docker Engine 26 or newer. Check it after `docker compose up -d`:
only the proxy should connect.

```bash
docker version --format '{{.Server.Version}}'   # 26 or newer
docker compose exec -T h2o python - <<'EOF'
import socket
for host, port in [("broker-proxy", 8100), ("1.1.1.1", 443), ("172.17.0.1", 22)]:
    try:
        socket.create_connection((host, port), timeout=5).close(); print(host, port, "CONNECTED")
    except OSError as e:
        print(host, port, "blocked:", e)
try:  # no DNS for anything outside the stack
    socket.getaddrinfo("example.com", 443); print("DNS example.com RESOLVED: not isolated")
except OSError as e:
    print("DNS example.com blocked:", e)
EOF
docker network inspect makhzan-ai_broker-only -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

Only `broker-proxy 8100` should connect, and the DNS lookup must fail. The last line should print nothing (or `invalid IP`): no host address on the bridge. If it
prints an address, the engine ignored the option; try connecting to that address from the
container as above, and if it answers, update Docker before relying on the isolation.
