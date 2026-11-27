# The home server's AI workers, as one compose stack

Everything the home server needs to run makhzan's AI-matching workers is one folder:
`compose.yml`, a `.env`, the two worker TOMLs and their token files, the llama.cpp router's
preset (`models.ini`) and guard (`llamacpp-guard.sh`), and the two GGUF files. Everything runs in
containers: no host timers, scripts or firewall rules (owner's rule). The host's one setting is
the udev rule `99-amdgpu-clock-limit.rules`, which holds the AMD card to its safe clock states:
kernel settings only the host can make. The reference is `docs/ai/worker.md`.

| Service | What it is |
|---|---|
| `kev` | `home-kev`: Kev-4B Q4_K_M, window 01:00–05:00 (Africa/Cairo), judge: the router's `kev` |
| `pplx` | `home-pplx`: pplx-decider Q4_K_S, window 05:05–07:00 (Africa/Cairo), judge: the router's `pplx` |
| `llamacpp` | llama.cpp's router on the AMD card: both GGUFs, one loaded at a time, asleep when idle |
| `broker-proxy` | our own TCP forwarder (`makhzan_ml.worker.proxy`), the workers' only way out |

The 4 GB card holds one model. The router (`--models-max 1`) loads whichever a worker asks for,
swapping the other out: Kev's worker loads `kev` when its window opens at 01:00, pplx's loads
`pplx` at 05:05. Idle for 10 minutes, the model sleeps and the card is free for Plex, Jellyfin and
Pitlane. Plain `docker compose up -d` starts all four services. The torch configurations
production ran until 2026-11-27 are kept as `torch-kev.toml` and `torch-pplx.toml` (the rollback,
below).

## Set up

1. Make the folder and copy in `compose.yml`, `home-kev.toml`, `home-pplx.toml`, `models.ini`,
   `llamacpp-guard.sh`, and `.env.example` as `.env`. Fill in `.env`: the folder itself
   (`WORKER_DIR`), the weights (`WEIGHTS_DIR`, holding the two GGUFs below), the user to run as
   (`UID`, `GID`: `id -u`, `id -g`), the card's groups (`RENDER_GID`, `VIDEO_GID`: `getent group
   render video`), and the broker's Tailscale address and port (`BROKER_TARGET`, an IP, never a
   name). Install the udev rule first (below).
2. Put each worker's broker token in `home-kev.token` and `home-pplx.token` (`chmod 600`,
   owned by that user). The broker issues them: `./makhzan ai worker add home-kev --models kev`.
3. Check each worker's configuration first. A configuration error makes the worker exit 2,
   and `restart: unless-stopped` would restart it in a loop:

   ```bash
   docker compose run --rm --no-deps kev --config /etc/makhzan-ai/worker.toml --check
   docker compose run --rm --no-deps pplx --config /etc/makhzan-ai/worker.toml --check
   ```

   Each prints `configuration ok: ...` (with the image's commit) and exits 0.
4. `docker compose up -d`, then the network check below.

Docker Engine 26 or newer is needed (the internal network's `inhibit_ipv4` option, below);
the check prints the engine's version.

Update to the latest tested images with `docker compose pull && docker compose up -d`. To
roll back, set `KEV_IMAGE` / `PPLX_IMAGE` in `.env` to an older `sha-<commit>` tag. A build
whose pins changed is refused by the TOMLs' `expect_version` until they follow.

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
| `Kev-4B-Q4_K_M.gguf` (`ggml-org/Kev-4B-GGUF@f4624b6…`) | `33ae6b18926502b2209a1bf7d3b61a350d65938441515c686bb87d226a19eff9` |
| `pplx-flash-v1.3-Q4_K_S.gguf` (our conversion, `ml/models/convert_pplx_v13.py`) | `819a9ad0f8f4aacb055f6d1783a155e3bd0bf33afb9c2f33749ef25350c61ab3` |

**`models.ini`** is the router's preset: one section per model, named as the workers ask for it
(`kev`, `pplx`), with the settings soaked on the card (Kev: 512-token batches; pplx: one 4,096
batch, flash attention, as its non-causal attention needs). The router runs with
`--models-max 1 --sleep-idle-seconds 600 -dev Vulkan0`. `-dev Vulkan0` makes a missing card a
startup error ("invalid device: Vulkan0") instead of a silent CPU fallback; `RENDER_GID` and
`VIDEO_GID` (required in `.env`) let it, running as `UID`, open `/dev/dri`.

**What a worker does at its window.** Its session's load checks its GGUF, waits for the router's
`/health`, finds its model in the router's `GET /models` (whose preset path must be the pinned
file), asks the router to load it (`POST /models/load`; the other model is unloaded first) and
waits until it is loaded (up to 180 s, interruptible by a stop), then checks the build from
`/props?model=<name>`. On the 3060 the swap took 5–9 s; from this server's disk it may take
longer. Only then does it lease, so no request pays the load. A sleeping model wakes on its first
request (~6 s). The windows never overlap, so the router never swaps back and forth inside one.

**Concurrent use.** Plex, Jellyfin and Pitlane can use the card during a window: their video
encode and decode run on separate engines, and a 1080p hardware transcode beside pplx at full
load ran at real time with about 665 MB of the card's memory to spare (2026-11-27). pplx was about
15% slower meanwhile.

**pplx on the CPU instead** (the card unavailable): the same GGUF is the same model version. Give
the router's `[pplx]` section `n-gpu-layers = 0` and `threads = 4` in `models.ini`, and in
`home-pplx.toml` set `device = "cpu"` (its request timeout becomes 225 s, inside the pplx
worker's 300 s `stop_grace_period`). Requests take about a minute.

## Runbook: the production switch (2026-11-27)

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
3. **The first night:** `docker compose logs -f kev` from 01:00 (the router loads `kev`, requests
   at about 4–5 s), and pplx from 05:05 (the swap, then requests); `./makhzan ai status` the next
   morning. Check the card's memory during Kev's window once
   (`cat /sys/class/drm/card1/device/mem_info_vram_used`): on the 3060 Kev grew to about 4.1 GB
   while scoring (NVIDIA's driver); on this card the soak at the same settings stayed inside 4 GB.

**Rollback:** move `policy.MODELS` back to `policy.TORCH_MODELS` and `pins.ACTIVE_BACKEND` to
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
  `sleeping until 01:00 (Africa/Cairo)`, `window open`, `window closed; model unloaded`.
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
docker compose exec -T kev python - <<'EOF'
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
