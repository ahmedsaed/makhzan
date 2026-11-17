# Deploying the AI broker

The broker is the one service AI workers talk to (`docs/ai/broker-api.md`).
It is built from the API image and run with its own app object,
`app.broker.main:app`, on its own port (owner decision P2), and **reached
only over Tailscale**, by the server's Tailscale IP and a port (owner,
2026-11-17). There is no public hostname and no reverse proxy in front of
it. It runs no model: it renders requests from the database, leases jobs to
authenticated workers, stores their scores and writes decisions.

## What `docker-compose.prod.yml` gives you

- A `broker` service from the `api` image, started by `./makhzan deploy` like
  every other service (`up -d`), after `migrate`.
- Its port is published at **`BROKER_BIND`** (default `127.0.0.1:8100`:
  loopback, so nothing off the host reaches it until you set it).
- It is **not** behind the web app's `/api/:path*` rewrite: the public site
  never forwards to it, so `https://<site>/api/ai/...` does not exist.
- `./makhzan status` reports whether `http://$BROKER_BIND/ai/v1/health`
  answers.

## Binding it to Tailscale

Set in `.env.prod`:

```sh
BROKER_BIND=<server tailscale ip>:8100
```

then `./makhzan deploy` (or `docker compose ... up -d broker`). Workers
connect to `http://<server tailscale ip>:8100/ai/v1`.

- **Recommended: bind the Tailscale IP.** Docker publishes the port on that
  address only, so the broker is reachable from the tailnet and nowhere
  else. The catch: the `tailscale0` interface must be up, with its address,
  **before the container starts**, or Docker cannot bind it and the service
  fails to start. On a host where Docker can start first, order the units
  (for example a systemd drop-in giving `docker.service`
  `After=tailscaled.service` and `Wants=tailscaled.service`), or restart the
  broker once Tailscale is up.
- **Alternative: `BROKER_BIND=0.0.0.0:8100` with a host firewall** that
  allows the port only on `tailscale0` and drops it on every other
  interface. Docker's own iptables rules bypass a plain INPUT rule, so the
  rule belongs in the `DOCKER-USER` chain. This survives boot order, but a
  firewall mistake exposes the broker; prefer the Tailscale IP bind.
- **Plain HTTP is acceptable on the tailnet.** Tailscale encrypts the link
  (WireGuard) end to end between the server and each worker machine, and
  every request still carries the worker's bearer token. Do not publish the
  port on a public interface: the broker sends catalogue text to whoever
  holds a token.
- Tailscale ACLs can narrow it further: allow only the worker machines to
  reach the server on that port.

## Configuration

Interpolated from `.env.prod` into the service's `environment:`. Only these
reach the broker, not the whole env file: it holds no crawler signing key,
search key or report salt.

| Variable | What |
|---|---|
| `DATABASE_URL` | The same database as the API. |
| `REDIS_URL` | To queue `rebuild_and_reindex` after a worker's window, when the mode is live (P16). |
| `BROKER_BIND` | Where its port is published: the server's Tailscale IP and port (default `127.0.0.1:8100`). |
| `AI_BROKER_ADMIN_TOKEN_SHA256` | The sha256 of the admin token for `GET /ai/v1/status`. Written by `./makhzan ai admin-token`. Empty: `/status` refuses everyone. |
| `AI_BROKER_MAX_BODY` | Optional; bytes, default 262144. |
| `REBUILD_WINDOW_SECONDS` | Optional; must match the worker's (default 600), so both share one rebuild job id per window. |
| `GIT_SHA` | Baked into the image at build; what `/health` reports. |

## Tokens

- **A worker:** `./makhzan ai worker add <name> --models kev` (or `pplx`)
  prints its token **once**; only the sha256 is stored. Put the token in the
  worker's `token_file`. A worker process serves one model per session; a
  machine serving two models runs two workers. `./makhzan ai worker list`
  shows them, `./makhzan ai worker revoke <name>` refuses its token at once
  (its leases expire and go back to the queue).
- **The admin token:** `./makhzan ai admin-token` makes a fresh one, writes
  its sha256 into `.env.prod`, recreates the broker and prints the token
  once. The previous one stops working. A worker token is never an admin
  token, nor the reverse.

## First run, in order

1. Set `BROKER_BIND` to the server's Tailscale IP and port; make sure
   Tailscale starts before Docker (above). Deploy. `./makhzan status` should
   show the broker's health answering.
2. From a worker machine on the tailnet:
   `curl http://<server tailscale ip>:8100/ai/v1/health`.
3. `./makhzan ai worker add ...` for each worker; install the tokens; point
   each worker's `broker_url` at `http://<server tailscale ip>:8100/ai/v1`.
4. Leave the mode `off` (the default). The broker leases and scores in either
   mode; `off` only keeps the regroup from reading decisions (P4).
5. The first `ai_candidates` run after a rebuild records a baseline and
   queues nothing; the existing catalogue is the backlog
   (`./makhzan ai backlog`), scored on the owner's machines against a local
   copy and reviewed there before anything reaches production (P4).
6. `./makhzan ai status` (or the AI section of `./makhzan status`) shows the
   queue, workers, throughput and decisions.
7. Only after the owner's review: `make regroup-dry-run ARGS=--ai`, then
   `./makhzan ai mode live`.
