# The admin dashboard

An internal page for running makhzan: what needs attention, the crawl, the
catalogue, visitors' reports, grouping rulings and AI matching. One person, one
password, **reached only over Tailscale**. It is not part of the public site and
has no public hostname.

It reuses the code behind `make status` and `./makhzan`, so the page and the
terminal agree: every number on the crawl and catalogue views comes from
`worker/status.py`'s `collect_*` functions, the AI view from
`makhzan_schemas.ai.status.collect`, and every action calls the same function
as its CLI command. It deploys, restarts and reconfigures nothing: containers,
deploys, backups and `.env.prod` stay with `./makhzan` on the server.

## Where it runs

- **A compose service, `admin`**, from the **ingestion image** (which holds the
  status report, the CLI modules and the adapters), running
  `uvicorn admin.app:app` on port 8200. Code: `apps/ingestion/admin/`
  (FastAPI + Jinja, server-rendered; one small script, `static/admin.js`, for
  copy buttons, two-click revoke and polling a queued job; no build step).
- It mounts the private configuration read-only (the report loads the adapters
  and crosswalks), and gets only the variables it uses: the database, Redis,
  Meilisearch (for the index check: set `MEILI_STATS_KEY` to a key allowed
  only `stats.get`, made once with `POST /keys` and the master key; until then
  compose hands it the master key under that name), `SITE_URL`, `CRAWL_ENABLED` (shown as
  this service's copy) and its own `ADMIN_*`. It holds **no crawler signing
  key**: the probe and runs happen in the worker.
- **Long or outbound work is queued to the worker** (`worker/admin_jobs.py`):
  "Run now", "Probe" and "Regroup dry run" write an `admin_actions` row and
  queue `admin_job` for it; the page polls the row and shows the result. The
  worker is the process that owns the per-source locks, the pace gate and the
  key, so nothing the page asks for can overlap a run of the same shop or
  bypass the crawler's politeness. A daily run that finds its shop busy with
  one of these comes back 10 minutes later (up to an hour) instead of losing
  its day. A job cut off by the worker's timeout or a restart is marked
  failed; one the queue lost (still queued after 10 minutes with no arq job
  behind it) is marked failed when a page next shows jobs.

## Exposing it over Tailscale

Exactly as the AI broker (`docs/ai/broker-deploy.md`):

```sh
# .env.prod
ADMIN_BIND=<server tailscale ip>:8200
```

then `./makhzan deploy`. Open `http://<server tailscale ip>:8200/` from a
machine on the tailnet.

- `ADMIN_BIND` defaults to `127.0.0.1:8200`: nothing off the host reaches it
  until it is set. **Always include the address**; a bare port publishes on
  every interface, the public one included.
- The Tailscale interface must be up before the container starts, or Docker
  cannot bind the address; `net.ipv4.ip_nonlocal_bind=1` (see the broker doc)
  fixes boot order for both services.
- Plain HTTP is acceptable on the tailnet (WireGuard encrypts the link). The
  session cookie is therefore not `Secure` by default; if you front the page
  with TLS (for example `tailscale serve`), set `ADMIN_COOKIE_SECURE=true`.
- Tailscale ACLs can narrow it to your own devices.
- `./makhzan status` reports whether `http://$ADMIN_BIND/login` answers.

## The password

```sh
./makhzan admin password
```

asks for the password twice, hashes it inside the container (scrypt, from the
standard library; the password is never written anywhere), writes
`ADMIN_PASSWORD_HASH` into `.env.prod` with, the first time, a random
`ADMIN_SECRET` (the key sessions are signed with), and recreates the `admin`
service. Changing the password ends every session; so does changing the
secret. With either unset nobody can sign in. At least 12 characters.

| Variable | What |
|---|---|
| `ADMIN_BIND` | Where the port is published: the server's Tailscale IP and port. |
| `ADMIN_PASSWORD_HASH` | `scrypt:N:r:p:salt:hash`, written by `./makhzan admin password`. |
| `ADMIN_SECRET` | HMAC key for the session cookie, written once by the same command. |
| `ADMIN_NAME` | Who actions are recorded as (default `admin`): overrides' `created_by`, the audit log. |
| `ADMIN_COOKIE_SECURE` | `true` only when served over TLS. |
| `ADMIN_SESSION_HOURS` | Optional; default 12. |
| `ADMIN_ALLOWED_HOSTS` | Optional; the `Host` values answered (`<tailscale ip>:8200`, a MagicDNS name), comma-separated. Empty: any. Others get 400, which shuts out DNS-rebinding pages. |

**Login security.** The session is an HttpOnly, SameSite=Strict cookie signed
with `ADMIN_SECRET`. Every POST carries a CSRF token from the session (the login
form a token of its own) and is refused from another origin. Request bodies
over 64 KB are refused before anything parses them. The password is checked
with scrypt at N=2^17 (about half a second, 128 MiB); a stored hash that is
malformed or asks for more memory than allowed says so on the login page
instead of "wrong password".

Failed logins are limited to 5 per address and **20 in total** per 15 minutes.
The total is a global lockout: anyone who can reach the page can spend it and
keep you out for up to 15 minutes, which is the price of a cap that holds
whatever addresses an attacker uses (and why the page belongs on the tailnet
only). **Check on the server what address the page sees**: behind Docker's
userland proxy every client can appear as the bridge gateway (172.x), which
makes the per-address limit act as the global one and puts that address in
the audit log. `/activity` shows it after a login; if it is the gateway, set
`"userland-proxy": false` in Docker's daemon.json or accept it. Pages send a strict
Content-Security-Policy (scripts from the page's own origin only),
`X-Frame-Options: DENY` and `Cache-Control: no-store`.

**Audit.** Every action, logins (failed ones included) and logouts too, writes
a row to `admin_actions`: who (`ADMIN_NAME`), from which address, what, the
target, the details, when, and for jobs their status and result. A refused
action is recorded too, with the reason under `detail.refused`. Where the
shared function allows it, the row is written in the action's own
transaction (a report's verdict, rulings and audit row commit together).
`/activity` lists them.
Rulings, decisions and flags also keep their own `created_by`, `removed_by`,
`revoked_by` and `resolved_by`.

## The views

**Overview.** "Needs attention" first, most serious first, each linking to the
view that handles it: shops paused or disabled (critical once their listings
were last checked 45 days ago), stalled sweeps, sources that do not load,
partial or failed runs in the last 48 hours, robots.txt unavailable or served
from an old copy, product-detail backlogs ten runs deep, crosswalk drift,
search-index drift, blocked overrides, open AI flags, uncategorised listings
and open reports. Then tiles (crawl, index, worker queue, review queue,
reports, price observations, AI, products) and the API and broker health
checks. There is no container list: reading Docker would need its socket, which
is root on the host.

**Crawl.**
- The **crawl-wide pause** (see below), with an optional note.
- **Sweep progress** per shop, from the cursors, with the resume points. Each
  shop has **Run now (limit N)**: an ephemeral `limit=` run (1-200 items),
  cursors untouched, nothing archived, no price history, refused while a run
  of the shop is going. **Probe** queues `worker.probe` for that one shop,
  paused or disabled included, with the crawler's own client. robots.txt is
  read through the crawler's own cache (`worker.robots.ROBOTS`): a fresh or
  cached read, a stored copy standing in for an unreadable file, or
  `RobotsUnavailable` (then nothing else is asked), and its Crawl-delay paces
  the probe. Then browser, makhzanbot and signed, at least 15 s apart. Each
  request passes the worker's own per-host gate (`worker.http.take_turn`: the
  shop's pace, a pending `Retry-After`, the slowdown after errors), and what
  the shop answers binds the crawl in turn: an error slows the host, and a
  429 or 503 with a `Retry-After` holds it for the next run too. The probe
  stops asking columns only when a `Retry-After` is pending or the host is
  slowed down, not on a bare 429. A shop in either state is not probed at all:
  the job fails and says why. The cells show under the shop.
  The probe's requests belong to no run, so no run's `stats.pacing` (and so
  not /how-we-crawl) shows them; the job logs them at the same gate and keeps
  their count and gaps on its row (`admin_actions.result.pacing`), shown with
  the result. The command-line probe (`./makhzan probe`) records them nowhere. **Pause / Resume** the shop. Run now and Probe work on a
  paused shop: they are how a blocked shop is looked at.
- Recent runs (errors expandable), cycle history with the most frequent
  errors, cycle targets, T1 short-page shadow tallies, T4/T12 confirmation,
  crawler identity, robots.txt, product-details coverage and queue, and the
  dashboard's own jobs.
- **Crosswalk drift.** "Add to ignore" and "Copy for crosswalk" only copy a
  TOML snippet (the file name is shown) to paste into the private
  configuration. Nothing is written to any repository from the page. Over plain
  HTTP the browser has no clipboard API, so the snippet opens in a prompt to
  copy by hand.

**Catalog.** The status report's CATALOG table, filterable and sortable; the
uncategorised browser (active listings with no category, searchable by title or
the shop's category where the adapter stores one, first 100 shown); the
product lookup (a product id, a listing id, a makhzan URL holding either, or a
shop URL; merged ids are followed), with offers, how each was matched and the
product's identity events. **Regroup dry run** is queued to the worker and
shows the counts `make regroup-dry-run` prints. There is no real regroup
button: the dry run rolls its transaction back and keeps no per-product list,
and the real regroup stays in the CLI.

**Reports.** Open reports, oldest first, as the page showed them (the
snapshot), with what Accept will do. Accept and Reject call
`worker.reports.review_reports`, the code behind `./makhzan reports
accept|reject`: accepting "these offers aren't the same" records never_merge
rulings, "same as another" one must_merge, a report no ruling could act on is
refused; rejecting withdraws a report's rulings. Recently closed reports can
be reviewed again.

Accepting a **wrong price or stock** report (here or with `./makhzan reports
accept`) marks the offers the visitor ticked to be **re-checked first**
(`listings.recheck_requested_at`, owner decision 2026-11-17,
`worker/recheck.py`). The next full run of each one's shop reads it before its
turn, within its pace, robots.txt and page ceiling, in the one way the shop
allows: by id at the start of the run where the adapter can (WooCommerce's
Store API `include`, counted as `stats.requests.recheck` and reported as
`stats.recheck`); else it waits for its partition in the cycle. A shop's
details stage is no answer (owner, 2026-11-17): a product page read never
writes price or stock, so it neither puts a marked listing first nor clears
it. On a WooCommerce shop that hides out-of-stock products from its Store
API, a listing `include` does not return may be out of stock, the very
report: its marker stays (`stats.recheck.hidden_kept`, against
`stats.recheck.absent` elsewhere) for the shop's unlisted out-of-stock pass,
which reads stock by id and clears it, or the sweep. Only a read that writes
price or stock clears the marker, and a re-read that finds it gone from the shop clears it too (the
cycle's archiving decides the rest). A paused shop and a `limit=` run ask
nothing. The Reports view lists the re-checks pending per shop and how each
will be honoured; so does `make status` (RE-CHECKS).

**Overrides.** Every ruling, removed ones too, with what the last regroup found
(in effect, BLOCKED and why, inactive, not yet checked). **Add** requires a
note (`worker.overrides.add_override`: both listings must exist; a must_merge
between one shop's listings is refused, since the same shop never merges).
**Remove** is soft and requires a note, kept as `remove_note`
(`./makhzan overrides remove ID --note ...` takes one too).

**AI matching.** Live in production since 2026-11-19
(`docs/ai/decision-review.md`, "Go-live").
- The **mode** switch opens an in-page confirm saying what the change does
  (turning it off: the next regroup undoes every AI merge, decisions and
  scores kept).
- Throughput (24 hours per model, scores per day over 7 days), decisions,
  with the **effect** of the standing "same" decisions at the last live
  regroup (`ai_decisions.effect`: in effect, blocked with a count per reason,
  inactive, overridden, and unchecked), pipelines, the audit counts, the queue
  with nights to drain, and open **flags**, each dismissed with a required
  note. `./makhzan ai status` and `make status` print the same breakdown.
- **Workers**: issue a token (shown once, on the response page only, never in
  a URL or the audit log; only its sha256 is stored), and revoke one with a
  second click.
- **Review AI merges**: standing "same" decisions, those merged now first
  (`listings.matched_via = 'ai'`; with the mode off none are, and the list is
  what going live would merge). Importing a locally scored backlog stays in
  the CLI (`./makhzan ai import DIR`). **Revoke decision** needs no confirm but a
  note, as `./makhzan ai revoke --note` does (owner, 2026-11-17).
  **Redecide (dry run)** re-applies the active policy to stored
  scores and writes nothing.

## Pausing the crawl

Two pauses, both in the database, so neither needs `.env.prod` edited or a
container recreated, and both survive deploys (`worker/pause.py`):

- **The crawl-wide pause**: `worker_state["crawl_pause"]`, set by the
  dashboard and by `./makhzan crawl off`, cleared by "Resume crawl" and
  `./makhzan crawl on`.
- **One shop's pause**: `sources.paused_at` / `paused_by` / `pause_note`, set
  by the dashboard and `./makhzan shop pause ID [--note ...]`. It sits over
  `enabled`, which is sources.toml's and rewritten by every sync; the sync
  never writes the pause columns.

Paused, `refresh_all` queues nothing for it, a daily job already queued skips
it, and a full run already going stops before its next page, cursors kept,
with `stats.stopped` saying who paused it. A run that is past its sweep
re-reads the pause before asking about the cycle's archive candidates, before
each request it sends for them and before each product page, and stops there.
`limit=` runs and the probe still work. `make status`, `./makhzan status` and
/how-we-crawl show both.

**A pause never archives anything.** A cycle waiting to confirm its archive
candidates stays held while its shop is paused, and a run held by a pause
counts as no attempt. Resuming stamps `resumed_at` (`sources.resumed_at`, or
`resumed_at` in `crawl_pause`), and the hold's one-cycle window is measured
from the later of that and the sweep's end, so the first run after a long
pause is not "overdue" (owner, 2026-11-17). Failed attempts are still bounded
by `CONFIRM_MAX_FAILED_RUNS`. `cycle_seconds` leaves out time a pause held
the cycle **after its sweep had finished** (it is measured to the sweep's
end); a pause **during** the sweep is still counted, since the cycle's pages
were not yet all read and the clock runs from its first page to its last.

`CRAWL_ENABLED` in `.env.prod` remains as the older, harder switch, read when
the worker's container is created; the crawl runs only when it is on *and*
nothing is paused. The page cannot change it, and says so; `./makhzan crawl
on` clears it as well as the pause.

## Running it locally

```sh
cd apps/ingestion && poetry run python -m admin.password --secret   # prints the two lines
export ADMIN_PASSWORD_HASH=... ADMIN_SECRET=...
make admin            # http://localhost:8200, against the dev database
make worker           # in another terminal, for Run now, Probe and the dry run
```

Run now and Probe send real requests to the shop: use them deliberately.

## Owner decisions (2026-11-17)

- Accept on a wrong price or stock report marks the listing to be re-checked
  first (above).
- Health checks in place of a containers panel, as built.
- Revoking an AI decision on the page needs a note.
- The regroup dry run shows counts only, as built.
- Resuming restarts the archive check's window (`resumed_at`).
