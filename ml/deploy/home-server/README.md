# The home server's AI workers, as one compose stack

Everything the home server needs to run makhzan's CPU AI-matching workers is one folder:
`compose.yml`, a `.env`, the two worker TOMLs and their token files. There are no systemd
timers and no host firewall rules. The reference is `docs/ai/worker.md`.

| Service | What it is |
|---|---|
| `kev` | `home-kev`: Kev on CPU, window 01:00–05:00 (Africa/Cairo) |
| `pplx` | `home-pplx`: pplx on CPU, window 05:05–07:00 (Africa/Cairo) |
| `broker-proxy` | our own TCP forwarder (`makhzan_ml.worker.proxy`), the workers' only way out |

## Set up

1. Make the folder and copy in `compose.yml`, `home-kev.toml`, `home-pplx.toml`, and
   `.env.example` as `.env`. Fill in `.env`: the folder itself (`WORKER_DIR`), the weights
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

`kev-llamacpp` (profile `llamacpp`) is Kev-4B Q4_K_M on the AMD card through llama.cpp, with
`llamacpp-kev.toml` as its worker configuration. It is built but **not in use**, and plain
`docker compose up -d` does not start it. The card is serviced and passed a 1,800-request soak
**at a 65 W cap** (docs/ai/kev-llamacpp.md). Install the udev rule `99-amdgpu-power-cap.rules`
first (its header has the commands): at the stock 85 W the card's SATA-adapter power feed reset
the server. Nothing stops the sidecar if the cap is missing, so check
`cat /sys/class/drm/card*/device/hwmon/hwmon*/power1_cap` reads 65000000 after any reboot before
enabling it.
Enabling the sidecar then waits only on the owner's policy switch: docs/ai/worker.md, "Kev on a
llama.cpp sidecar".

`pplx-llamacpp` (profile `llamacpp-pplx`) is pplx-decider-flash-v1.3 Q4_K_S on the CPU through
llama.cpp, with `llamacpp-pplx.toml` as its worker configuration and the GGUF
`pplx-flash-v1.3-Q4_K_S.gguf` in `WEIGHTS_DIR`. Also built and **not in use**: it waits on the
owner's policy switch, and its speed on this CPU is estimated, not measured
(docs/ai/worker.md, "pplx on a llama.cpp sidecar"). The pplx worker's `stop_grace_period` is
300 s, for this backend's longer requests.

## How it behaves

- **Each worker waits for its own window** (`outside_window = "wait"`). Outside it, the
  container holds only a small supervisor process, no model: `docker stats` shows a few tens
  of MB. When the window opens, the supervisor forks a session that says hello, leases,
  loads the model on the first lease with jobs, scores, and stops gracefully at the window's
  end (finishes the request in flight, submits, releases the rest, ends the session, unloads).
  The child then exits, so all of the model's memory goes back to the system. The log says
  `sleeping until 01:00 (Africa/Cairo)`, `window open`, `window closed; model unloaded`.
- **An empty queue** (`on_empty = "exit"`) ends that window's session early and frees the
  model until the next window. Set `on_empty = "wait"` to keep polling every `poll_s` until
  the window's end instead, with the model held once loaded.
- **One model at a time on this machine** (the owner's rule: 31 GB in all, other services
  running, about 18 GB per model). The windows never overlap, and pplx starts 5 minutes after
  Kev's ends: Kev's graceful stop can run about 4 minutes past 05:00 (a request in flight, up
  to about 104 s on this CPU, or a model load, about 150 s, then its last posts), and pplx
  loads on its first lease after its window opens. Keep at least that gap when changing
  either window; a test (`ml/tests/test_worker_deploy.py`) fails without it. It is also
  enforced: a worker takes no new lease and starts no model load in its window's last
  5 minutes (`no_new_lease_s = 300`, the CPU default), and if a session is still running
  4.5 minutes after its window's end the supervisor kills it (logged as `KILLING the
  session`), so its memory is free before the other worker's window opens. A killed session's
  lease expires at the broker and charges the job in hand one attempt.
- **`docker compose stop`** while a worker sleeps exits at once; during a window it is the
  graceful stop, within `stop_grace_period` (240 s).
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
