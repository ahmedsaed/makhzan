# The home server's AI workers, as one compose stack

Everything the home server needs to run makhzan's AI-matching workers is one folder:
`compose.yml`, a `.env`, the two worker TOMLs and their token files, plus (since the production
switch of 2026-11-27) the two GGUF files, the udev rule that limits the AMD card's clocks, and the
systemd timers that start and stop the llama.cpp sidecars. No host firewall rules. The reference
is `docs/ai/worker.md`.

| Service | What it is |
|---|---|
| `kev` | `home-kev`: Kev-4B Q4_K_M, window 01:00–05:00 (Africa/Cairo), judge: `kev-llamacpp` |
| `pplx` | `home-pplx`: pplx-decider Q4_K_S, window 05:05–07:00 (Africa/Cairo), judge: `pplx-llamacpp` |
| `kev-llamacpp` | llama.cpp on the AMD card with Kev's GGUF (profile `llamacpp`), up 00:55–05:03 |
| `pplx-llamacpp` | llama.cpp on the AMD card with pplx's GGUF (profile `llamacpp-pplx`), up 05:03–07:03 |
| `broker-proxy` | our own TCP forwarder (`makhzan_ml.worker.proxy`), the workers' only way out |

The 4 GB card holds one model, so the sidecars take turns, started and stopped by the host's
timers (`install-sidecar-timers.sh`, `sidecar-window.sh`). Plain `docker compose up -d` starts the
workers and the proxy only. The torch configurations production ran until 2026-11-27 are kept as
`torch-kev.toml` and `torch-pplx.toml` (the rollback, below).

## Set up

1. Make the folder and copy in `compose.yml`, `home-kev.toml`, `home-pplx.toml`,
   `sidecar-window.sh`, `install-sidecar-timers.sh`, and `.env.example` as `.env`. Fill in `.env`: the folder itself (`WORKER_DIR`), the weights
   (`WEIGHTS_DIR`, a Hugging Face home whose `hub/` holds the pinned snapshots as real files,
   copied with `rsync -L`), the user to run as (`UID`, `GID`: `id -u`, `id -g`), and the
   broker's Tailscale address and port (`BROKER_TARGET`, an IP, never a name).
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

## The llama.cpp sidecars on the AMD card

**The clock limit comes first.** The card is held to clock states 0–2 (max 753 MHz) by the udev
rule `99-amdgpu-clock-limit.rules` (its header has the install commands). At higher states the
card's SATA-adapter power feed resets the whole server (docs/ai/kev-llamacpp.md).
`sidecar-window.sh` refuses to start a sidecar unless the card reads `manual`:
`cat /sys/class/drm/card*/device/power_dpm_force_performance_level`. sysfs cannot show the
clock-state mask itself, so `manual` is a necessary check, not a sufficient one: it relies on the
rule setting both together. Only a load shows the mask (the clock never above 753 MHz).

**The GGUFs** go in `WEIGHTS_DIR` (both the sidecar and the worker mount them, read-only; the worker
hashes its copy against the pin before scoring):

| File | sha256 |
|---|---|
| `Kev-4B-Q4_K_M.gguf` (`ggml-org/Kev-4B-GGUF@f4624b6…`) | `33ae6b18926502b2209a1bf7d3b61a350d65938441515c686bb87d226a19eff9` |
| `pplx-flash-v1.3-Q4_K_S.gguf` (our conversion, `ml/models/convert_pplx_v13.py`) | `819a9ad0f8f4aacb055f6d1783a155e3bd0bf33afb9c2f33749ef25350c61ab3` |

**`.env`** also needs `RENDER_GID` and `VIDEO_GID` (`getent group render video`), so the sidecars,
running as `UID`, can open `/dev/dri`. `sidecar-window.sh` refuses to start a sidecar without
both. Without access to the card llama.cpp would otherwise fall back to the CPU, silently, with
the worker still recording `gpu`; each sidecar therefore runs with `-dev Vulkan0`, which makes no
card a startup error ("invalid device: Vulkan0") rather than a slow CPU run. The worker cannot
check the device itself (llama.cpp's `/props` does not report it): a sidecar that exits leaves the
worker waiting 120 s for `/health`, then failing its load, logged.

**The timers** (`sudo sh install-sidecar-timers.sh`, from this folder): four systemd timers with
the time zone in their `OnCalendar`, so the server's UTC clock does not matter, each running
`sidecar-window.sh` as the invoking user (in the `docker` group):

| Africa/Cairo | Runs | Why then |
|---|---|---|
| 00:55 | `start kev` (stops pplx's first) | Kev's window opens at 01:00 |
| 05:03 | `stop kev` | Kev's last request ends by about 05:01:40 (60 s GPU timeout + posts) |
| 05:03:30 | `start pplx` (stops Kev's first) | pplx's window opens at 05:05; its worker waits up to 120 s for the sidecar |
| 07:03 | `stop pplx` | the card is free for Plex and Jellyfin until 00:55 |

Kev's sidecar also starts at **01:00:20** (idempotent): on the night Egypt's clocks spring
forward (00:00 to 01:00, the last Friday of April), 00:55 does not exist; the worker waits up to
120 s for its sidecar, which covers that.

**Reboots and crashes.** The sidecars have `restart: "no"`: Docker never restarts one on its own,
since that would skip the script's checks. Instead `makhzan-sidecar-boot.service` runs after
Docker at every boot: `sidecar-window.sh boot` starts the sidecar whose window it is (Kev's
00:55–05:03, pplx's 05:03:30–07:03), waiting up to 60 s for the udev rule, through the same checks.
A sidecar that crashes mid-window stays down until the next timer or boot; its worker's jobs fail
and are retried by the broker.

`systemctl list-timers 'makhzan-sidecar-*'` shows the next runs, `journalctl -u
'makhzan-sidecar*'` what each did. By hand: `./sidecar-window.sh start kev`, `stop kev`, `boot`,
and so on.

**pplx on the CPU instead** (the card unavailable): the same GGUF is the same model version. In
`compose.yml` give `pplx-llamacpp` `-ngl 0 -t 4` instead of `-ngl 99 -dev Vulkan0` and drop its
`devices` and `group_add`; in `home-pplx.toml` set `device = "cpu"` (its request timeout becomes 225 s, inside
the pplx worker's 300 s `stop_grace_period`). Requests take about a minute.

## Runbook: the production switch (2026-11-27)

In this order. Until the home server is updated (step 3), its old workers are refused at hello by
the new policy (exit 4, a `version_drift` flag): harmless, nothing is scored.

**Already done on the server (2026-11-27, owner-approved):** the udev rule installed and checked
(`manual`; under load the clock peaked at 753 MHz); both GGUFs in `WEIGHTS_DIR`
(`/mnt/disk3/makhzan-ml/cache/huggingface/`) with the hashes above verified; the torch weights
deleted and the old test containers removed. The AI workers are stopped.

1. **Merge** PR #94 (the udev rule), then this PR. CI then publishes the llama.cpp worker image
   from `main` (`worker-llamacpp`, below); the server can only pull it after that.
2. **Production:** `./makhzan deploy`. The broker and API take the new policy (`MODELS` names the
   llama.cpp versions). Queued jobs move to the new judge at the next hello; standing decisions
   are re-queued by the next re-score run at the low P8 priorities (after new pairs and the
   backlog), the catch-up the owner drains (wider windows, the desktop).
3. **The home server**, in its stack folder (`/mnt/disk3/makhzan-ml/worker`):
   1. Copy the new `compose.yml`, `home-kev.toml`, `home-pplx.toml`, `sidecar-window.sh`,
      `install-sidecar-timers.sh` from the repository (`ml/deploy/home-server/`), keeping `.env`
      and the tokens. Add `RENDER_GID` and `VIDEO_GID` to `.env` (`getent group render video`).
   2. `docker compose pull`, then each worker's `--check` (Set up, step 3): it must print the
      llama.cpp version, `kev-4b-Q4_K_M@33ae6b189265+…` / `pplx-…-Q4_K_S@819a9ad0f8f4+…`.
   3. `sudo sh install-sidecar-timers.sh`, then `systemctl list-timers 'makhzan-sidecar-*'`.
   4. `docker compose up -d` (the workers and the proxy; they wait for their windows).
   5. A dry check outside the windows: `./sidecar-window.sh start kev`, wait for
      `docker compose --profile llamacpp logs kev-llamacpp` to say the model is loaded (and that it
      offloaded to `Vulkan0`), then `./sidecar-window.sh stop kev`; the same for pplx.
4. **The first night:** `docker compose logs -f kev` from 01:00 (the sidecar checked, requests at
   about 4–5 s), and pplx from 05:05; `./makhzan ai status` the next morning.

**Rollback:** move `policy.MODELS` back to `policy.TORCH_MODELS` and `pins.ACTIVE_BACKEND` to
`torch` (one commit) and deploy. On the home server, **the torch weights were deleted** on
2026-11-27, so first re-download them into `WEIGHTS_DIR` as real files (`rsync -L`; Kev-4B with its
Qwen3.5-4B-Base, and pplx-decider-flash-v1.3, at the revisions in `worker/pins.py`; about 20 GB).
Then copy `torch-kev.toml` / `torch-pplx.toml` over `home-*.toml`, set `KEV_IMAGE` / `PPLX_IMAGE`
to the torch worker images, `sudo sh install-sidecar-timers.sh remove`, stop the sidecars, and
`docker compose up -d`.

## How it behaves

- **Each worker waits for its own window** (`outside_window = "wait"`). Outside it, the
  container holds only a small supervisor process, no model (the model is in the window's sidecar, on the card): `docker stats` shows a few tens
  of MB. When the window opens, the supervisor forks a session that says hello, leases,
  loads the model on the first lease with jobs, scores, and stops gracefully at the window's
  end (finishes the request in flight, submits, releases the rest, ends the session, unloads).
  The child then exits, so all of the model's memory goes back to the system. The log says
  `sleeping until 01:00 (Africa/Cairo)`, `window open`, `window closed; model unloaded`.
- **An empty queue** (`on_empty = "exit"`) ends that window's session early and frees the
  model until the next window. Set `on_empty = "wait"` to keep polling every `poll_s` until
  the window's end instead, with the model held once loaded.
- **One model at a time on the card.** The windows never overlap, and the timers keep exactly one
  sidecar up: Kev's stops at 05:03, two minutes after Kev's last possible request on the card
  (60 s timeout, then its posts), before pplx's starts at 05:03:30. A test
  (`ml/tests/test_worker_sidecar_window.py`) holds the timers against the windows and the stop
  bound. A worker whose sidecar is down when its window opens waits up to 120 s for it, then
  fails the load (logged), and the next window tries again. If a session is still running
  4.5 minutes after its window's end the supervisor kills it (logged as `KILLING the session`);
  a killed session's lease expires at the broker and charges the job in hand one attempt.
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
