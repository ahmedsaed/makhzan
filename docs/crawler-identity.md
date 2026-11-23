# Crawler identity: makhzanbot and Web Bot Auth

How the crawler says who it is, how a shop can verify it, and how to move a shop
from the browser identity to the honest one. The research behind it is
`docs/crawling-practices.md` in the private configuration (November 2026).

## The two identities

Each source has `identity` in its config (`sources.toml` in the private
configuration). The worker reads it per run (`worker/identity.py`).

| | `browser` (default) | `makhzanbot` |
|---|---|---|
| User-Agent | `Mozilla/5.0 … Chrome/153.0.0.0 Safari/537.36` | `makhzanbot/1.0 (+<SITE_URL>/how-we-crawl; crawler@makhzan.merope.dev)` |
| Client hints, `Sec-Fetch-*` | sent | not sent |
| `From` | `crawler@makhzan.merope.dev` | `crawler@makhzan.merope.dev` |
| Web Bot Auth signature | never | on every request, when `MAKHZANBOT_SIGNING_KEY` is set |
| robots.txt group | `makhzanbot`, else `*` | `makhzanbot`, else `*` |

Every request a run sends goes out as its source's identity: pages, retries,
each redirect hop, robots.txt, cycle data and the product-page details stage.
The pace (15 s per host, Crawl-delay as a floor, Retry-After, slowing down on
errors) is the same in both.

robots.txt is matched on `makhzanbot` in **both** identities, so a shop that
writes this is obeyed whichever headers we send:

```
User-agent: makhzanbot
Disallow: /
```

### robots.txt when it cannot be read

RFC 9309 says an unreadable robots.txt (a 5xx, a 429, a timeout) means "assume
complete disallow". The crawler handles it in this order (`worker/robots.py`):

1. It retries once, after the host's pace.
2. If the file is still unreadable, it uses the host's last good copy, up to
   30 days old. Copies are kept in the `robots_copies` table, so a restart
   does not lose them.
3. With no copy, the host is refused for 10 minutes. A run whose own host is
   refused stops at once, with one error and every cursor kept, and resumes
   at the next run.

A copy older than 30 days is not used. The research note would then treat the
file as absent and allow everything. This code refuses the host instead, on
purpose: a file nobody could read for a month is no evidence that its rules
went away. Each run records what robots.txt said in `stats.robots`.
`make status` shows it under ROBOTS.TXT and flags any host served from a copy
more than 7 days old.

The browser identity exists only because every source used it before November
2026. Some shops' edges challenge an unknown bot, so shops move one at a time,
after a probe. The rule from the research note is in force: if a shop refuses
makhzanbot, register the key and write to the shop; never move a switched shop
back to the browser headers, and never bump the Chrome version to get past a
bot score.

## What gets signed

RFC 9421 HTTP Message Signatures, profiled by the IETF webbotauth working group
(`draft-ietf-webbotauth-httpsig-protocol-01`, October 2026). Implementation:
`packages/schemas/makhzan_schemas/botauth.py`.

- Key: Ed25519. `keyid` is its JWK SHA-256 thumbprint (RFC 7638 / RFC 8037).
- Covered components: `@authority` and `signature-agent`. Never `@query-params`,
  which Cloudflare rejects. `@method` and `@path` are left out for now; see
  `REQUEST_COMPONENTS` for why.
- Parameters: `created`, `expires` (created + 60 s), a random `nonce`, `keyid`,
  `alg="ed25519"`, `tag="web-bot-auth"`. Each request is signed afresh,
  including retries and redirect hops.
- `Signature-Agent: "https://<SITE_URL host>"`: Cloudflare's bare quoted-string
  form. Draft -01 asks for the dictionary form (`sig1="https://…"`), which
  Cloudflare fails. The choice lives in `signature_agent_header()` and has a
  test. Re-check it at each draft revision.

The key directory is at `<SITE_URL>/.well-known/http-message-signatures-directory`.
The API serves it (`apps/api/app/routers/wellknown.py`), and the web app proxies
it with a rewrite, not a redirect. It returns a JWKS with
`Content-Type: application/http-message-signatures-directory+json`, signed by each
key it lists with `tag="http-message-signatures-directory"`. With no key
configured it answers 404.

The API container therefore holds the private key or keys, and uses them only
to sign this response. The signature must come from every listed key and
expire within minutes, so it is made per request. A signature made in advance
would need an expiry verifiers distrust, and signing with a separate key would
prove nothing about the listed ones.

Signatures expire 60 seconds after they are made, so the server's clock must be
synced. See `docs/DEPLOYMENT.md`.

## Before registering: generate and publish the key

See `docs/DEPLOYMENT.md`, "Crawler signing key": generate the key on the server,
put it in `.env.prod`, deploy, then check the directory with curl. Registration
forms ask for the directory URL, so it must answer 200 first.

## Registering with Cloudflare

Cloudflare's "signed agents" route. Written from Cloudflare's Web Bot Auth docs
(<https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/>,
read 2026-11-10). **Verify each step against the live form**: it changes, and
nothing here was submitted.

1. Log in to the Cloudflare dashboard. The docs say to "select your account
   and domain", so you need a Cloudflare account. They do not say whether
   makhzan's own domain must be on Cloudflare. Check that on the form.
2. Go to **Manage Account** → **Configurations** → **Bot Submission Form** tab.
3. **Verification Method**: choose **Request Signature**.
4. **Validation Instructions**: enter the key directory URL,
   `<SITE_URL>/.well-known/http-message-signatures-directory`.
5. Fill in whatever else the form asks (bot name, purpose, contact, user agent)
   with the values below. Do not guess fields the form does not show.
6. Submit. Track it under **BotBase** → **Submission history**.

Cloudflare's verified-bot policy requires honest, consistent identification, and
lists a mismatch between declared purpose and traffic as a breach. Before
submitting, check that every source Cloudflare will see is on makhzanbot, or
that you can explain the ones that are not.

## Registering with Shopify

Shopify asks bots to sign with Web Bot Auth. Unsigned traffic "is subject to the
strictest limits" (Shopify changelog, 2026-05-07,
<https://shopify.dev/changelog/bots-and-agents-should-identify-themselves-via-web-bot-auth.md>).
The changelog says enrolling with Cloudflare is not required. It describes no
key registration step for third-party crawlers. It links a form for parties
that need **higher rate limits** than signed traffic gets:
<https://forms.gle/V88RD31uAVirqE4e9>. **Verify against the live changelog and
form before relying on this.**

- Community reports (Shopify dev forum, November 2026) say a valid signature
  still got 429s until Shopify activated the operator's registration, with no
  stated timeline. Expect a wait. Treat a signed 429 from a Shopify shop as
  "not yet activated" before blaming the code. Probe it, and check
  `make status` shows the runs as signed.
- The "Crawler access" signatures in a merchant's Shopify admin are for a
  merchant crawling their **own** store. They are not for us.

## The values to submit

| Field | Value |
|---|---|
| Bot name / product token | `makhzanbot` |
| User-Agent | `makhzanbot/1.0 (+<SITE_URL>/how-we-crawl; crawler@makhzan.merope.dev)` |
| Purpose | A product directory for Egyptian electronics and hardware suppliers. It reads public catalogue pages and product APIs and links buyers to the shop. No purchases, no logins, no AI training. |
| Contact | `crawler@makhzan.merope.dev` |
| Information page | `<SITE_URL>/how-we-crawl` |
| Key directory | `<SITE_URL>/.well-known/http-message-signatures-directory` |
| keyid | the output of `python -m worker.botauth show` on the server |
| Signature-Agent | `"<SITE_URL origin>"` |
| Rate | One request at a time per site, at least 15 s apart (more if Crawl-delay asks), a few hundred requests per site per day |
| Operator | the owner's call (an open question in the research note) |

Every row with `<SITE_URL>` is tied to the domain. Changing the domain later
means a new directory URL and re-registering with both vendors.

## Switching a shop to makhzanbot

One shop at a time, starting with one that does not sit behind a strict WAF.

1. **Probe first**, from the server: `./makhzan probe --source <id>` (from a laptop it runs on the server over SSH).
   On the server this runs `python -m worker.probe` in the ingestion image. The
   `makhzanbot` and `signed` columns must be 200 for that shop, and the
   `robots` column must not say `unreadable` or `DISALLOWS`.
   - Run it while the shop's crawl is idle: the probe keeps its own 15 s gap,
     but it runs in a separate container, so it does not share the worker's.
   - The probe sends each source's real first page, using the crawler's own
     client (`make_client`) for each identity. It never uses curl: curl's TLS
     fingerprint, HTTP/2 and header order differ from the crawler's, and
     Cloudflare scores those. curl with browser headers once got 429 from a
     shop that served the crawler fine.
   - It is read-only: no retries, at least 15 s between requests to a host, and
     it obeys robots.txt.
2. **Switch one shop**: in the private configuration, add
   `identity = "makhzanbot"` to that source's config, commit, and deploy. The
   `migrate` service syncs `sources.toml`, and an unknown identity fails the
   sync instead of being ignored.
3. **Watch `./makhzan status`**. **CRAWLER IDENTITY** should show
   `last run: makhzanbot, signed` after the next daily run. If it shows
   "unverifiable: no key on the worker", the worker has no
   `MAKHZANBOT_SIGNING_KEY`. Also check **RECENT RUNS** for new 403/429 errors,
   and **SWEEP PROGRESS** for the shop still moving.
4. Give it a full cycle (about a week) before switching the next shop.
5. **If the shop starts refusing us**, leave it on makhzanbot, with its cursor
   resuming each day. Write to the shop at the address on /how-we-crawl, and
   check whether the registration has been activated. Do not switch it back to
   `browser`. That is the "fall back to a disguised crawler" pattern the
   research note rules out.

## Where requests leave from: the IPv6 pool

The server's IPv4 address carries other traffic too (it is a Tailscale exit
node), so it is never published. The crawl can instead send from a pool of
IPv6 addresses that carry nothing else (`worker/egress.py`), which can be
published and given reverse DNS.

- **The pool** is `crawl-pool.yaml` in the private configuration, an `ipv6:`
  list of addresses (`docs/server/ipv6.md` there says which are the server's
  own). `MAKHZAN_CRAWL_POOL` names the file. Production sets it for the
  worker, so a laptop or a test run has no pool. At startup, a file that is
  named but missing, or an entry that is not a global IPv6 address, stops the
  worker (later edits: see "Deployment notes"). `./makhzan egress list` prints the pool. `./makhzan egress check`
  sends one request from each address to an IPv6 echo service (never a shop),
  and fails any address that cannot connect or that the service sees as a
  different address.
- **Per source**, `egress = "ipv4"` (the default) or `egress = "ipv6"` in its
  config. Each request of an IPv6 source leaves from a pool address chosen at
  random: pages, retries, redirect hops, robots.txt and the details stage alike.
- **The pace stays per host.** `take_turn` keys on the shop's host, never on
  our address, so a shop gets the same requests at the same gaps from one
  address or twenty. Never pace per address.
- **The set is fixed** (owner, 2026-11-23). It grows only with the crawler,
  never in answer to a block: a shop that refuses us is written to, as in
  step 5 above, and a blocked shop is never moved to fresh addresses.
- **Fallback.** A connection that fails over IPv6 (no IPv6 address for the
  host, refused, a connect timeout) is retried once over IPv4. Only failures
  before anything was sent fall back, so a shop never gets a request twice.
  A 403 or a 429 is the shop's answer: it never changes the address.
- **Recorded** in each run's `stats.egress`: per host, requests over IPv6 and
  over IPv4, fallbacks by why, and requests and failures per pool address. Not
  in `stats.pacing`. `./makhzan status` (**EGRESS**) and the dashboard's Crawl
  page show 30 days per shop, the most any one address sent it, and a week's
  fallback share, flagged over 10%. An address failing for several shops is
  named on its own.
- With a pool configured, an IPv4 source binds 0.0.0.0, so the server's own
  IPv6 address is never used for crawling. Without one, clients are built
  exactly as before.

### Publishing the addresses

/how-we-crawl has an **Addresses** tab, and `/crawler-addresses.json` lists
the same addresses in the shape Google uses for Googlebot (`prefixes`, each an
`ipv6Prefix` or `ipv4Prefix`). Both appear only once `crawl-pool.yaml` says
so:

```yaml
ipv6: [ ... ]                 # the pool
ipv4:                         # optional: where IPv4 requests leave from
  - address: 203.0.113.7   # documentation example
    shared: true              # the server's own: published, no crawler PTR, not bound
reverse_dns: crawler.merope.dev
publish: true                 # only once every address's PTR and AAAA exist
```

The worker states the list in `worker_state` (`crawl_addresses`) at startup
and before each daily sweep, and the API serves it as `GET
/crawler/addresses` (404 until published). Setting `publish: false`, or
removing it, takes the list down at the next daily sweep (the crawl being
off or paused doesn't delay it), plus up to 10 minutes of the page's and the
JSON's caches. Restart the worker to start that at once. An `ipv4` entry with `shared: false` is an address used for
crawling only: the worker then binds it for every IPv4 connection, and the
page says it passes the same reverse DNS check.

Before setting `publish: true`, check both directions for every address:
`dig -x ADDR +short` gives `crawler.merope.dev.`, and `dig AAAA
crawler.merope.dev +short` (or `A` for a dedicated IPv4) lists the address.

### Moving a shop to IPv6

1. `./makhzan probe --source <id>`. The `ipv6` column checks for an AAAA
   record and, with a pool configured, asks the page once from one pool address
   as the shop's own identity, with no fallback. It must say 200.
2. Add `egress = "ipv6"` to the source in `sources.toml`, commit, deploy.
3. Watch **EGRESS** after the next run. If the shop's IPv6 keeps failing, set
   it back to `"ipv4"`: that is a connectivity call, not a block.

Blocked shops stay disabled whatever their egress.

## Deployment notes

- **The worker uses host networking** so it can bind the addresses, which sit
  directly on the server's interface (`docker-compose.prod.yml`). `db`,
  `redis` and `search` publish their usual ports on the stack's own loopback
  address (`MAKHZAN_LOOPBACK`, production's `127.0.0.1`), and the worker's
  hosts file maps their names there, so the URLs in `.env.prod` are
  unchanged. A throwaway stack beside production uses another address
  (`127.0.0.2`), which `scripts/lib/ops.sh` enforces. Redis takes a password
  now that the host can reach it (`REDIS_PASSWORD`, docs/DEPLOYMENT.md).
- **A pool file edited while the worker runs** is read again, without a
  restart. If the new file is invalid or missing (a bad commit, or a read
  mid-`git pull`), the worker keeps the last good pool and logs the error, so
  one bad commit cannot stop every source. The same file at startup stops the
  worker.

## Not done yet

- **Cloudflare registration.** Submitted to Cloudflare's verified bots
  directory on 2026-11-10; on 2026-11-12 Cloudflare requested changes, asking
  for a registered business, which the operator does not have yet. Pending.
  Nothing has been submitted to Shopify (see "Registering with Shopify"). The
  production signing key exists and its directory is published.

The `/how-we-crawl` redesign, listed here until 2026-11-19, shipped on
2026-11-13 (commit c5d6be4): the page explains the token, the block snippet,
Web Bot Auth (with an annotated signed request) and the key directory,
publishes the activity record, and deliberately names no IP address.
