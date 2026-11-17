# Deploying the AI broker

The broker is the one service AI workers talk to (`docs/ai/broker-api.md`).
It is built from the API image and run with its own app object,
`app.broker.main:app`, on its own port, behind its own reverse-proxy
hostname (owner decision P2). It runs no model. It renders requests from the
database, leases jobs to authenticated workers, stores their scores and
writes decisions.

## What `docker-compose.prod.yml` gives you

- A `broker` service from the `api` image, started by `./makhzan deploy` like
  every other service (`up -d`), after `migrate` (it needs the `ai_sessions`
  table).
- It listens on **the host's loopback only**: `127.0.0.1:${BROKER_PORT:-8100}`.
  Nothing outside the machine reaches it until your reverse proxy does.
- It is **not** behind the web app's `/api/:path*` rewrite. The public site
  never forwards to it, so `https://<site>/api/ai/...` does not exist.
- `./makhzan status` reports whether `/ai/v1/health` answers.

## The reverse proxy (yours to add)

Give the broker a hostname of its own, for example `broker.<your-domain>`,
with TLS, and forward it to `127.0.0.1:<BROKER_PORT>`. It needs nothing
special:

- plain HTTP/1.1 to the upstream, no websockets, no long polls;
- bodies are small (the broker refuses a POST over 256 KiB by itself;
  `AI_BROKER_MAX_BODY` changes that); a proxy limit of 1 MiB is plenty;
- requests are short, but a lease renders up to `max_jobs` pairs from the
  database, so allow a read timeout of 60 s or more;
- forward only `/ai/v1/`; nothing else is served;
- **TLS only**: catalogue text reaches workers through it, and every request
  carries a bearer token.

An example for Caddy:

```caddyfile
broker.example.com {
    request_body {
        max_size 1MB
    }
    reverse_proxy /ai/v1/* 127.0.0.1:8100
}
```

And for nginx (inside your existing TLS server setup):

```nginx
server {
    listen 443 ssl;
    server_name broker.example.com;
    # ssl_certificate ... as for the site
    client_max_body_size 1m;
    location /ai/v1/ {
        proxy_pass http://127.0.0.1:8100;
        proxy_read_timeout 120s;
    }
    location / { return 404; }
}
```

Optionally, allow only the addresses your workers come from at the proxy (P3
calls an allowlist optional). It is not a substitute for the tokens, and it
does not fit a worker on a changing address.

## Configuration

All from `.env.prod`, which the service reads like the others:

| Variable | What |
|---|---|
| `DATABASE_URL` | The same database as the API. |
| `REDIS_URL` | To queue `rebuild_and_reindex` after a worker's window, when the mode is live (P16). |
| `BROKER_PORT` | The loopback port the proxy forwards to (default 8100). |
| `AI_BROKER_ADMIN_TOKEN_SHA256` | The sha256 of the admin token for `GET /ai/v1/status`. Written by `./makhzan ai admin-token`. Empty: `/status` refuses everyone. |
| `AI_BROKER_MAX_BODY` | Optional; bytes, default 262144. |
| `GIT_SHA` | Baked into the image at build; what `/health` reports. |

## Tokens

- **A worker:** `./makhzan ai worker add <name> --models kev` (or `pplx`, or
  `kev,pplx`) prints its token **once**; only the sha256 is stored. Put the
  token in the worker's `token_file`. `./makhzan ai worker list` shows them,
  `./makhzan ai worker revoke <name>` refuses its token at once (its leases
  expire and go back to the queue).
- **The admin token:** `./makhzan ai admin-token` makes a fresh one, writes
  its sha256 into `.env.prod`, recreates the broker and prints the token
  once. The previous one stops working. A worker token is never an admin
  token, nor the reverse.

## First run, in order

1. Deploy. `./makhzan status` should show the broker's health answering.
2. Add the proxy hostname, then check `https://broker.<your-domain>/ai/v1/health`
   from a worker machine.
3. `./makhzan ai worker add ...` for each worker; install the tokens.
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
