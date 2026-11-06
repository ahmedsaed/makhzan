# makhzan

**One place to find project materials in Egypt.**

makhzan is a bilingual (English / Arabic) directory of Egyptian hardware and
electronics suppliers. Instead of hunting across dozens of shops, it brings their
products and prices into one searchable catalogue, then hands you off to the
supplier to buy. It is a **directory, not a store**: no cart, no payment, no
delivery.

Live at **[makhzan.merope.dev](https://makhzan.merope.dev)**: about 58,000
products from 8 suppliers, across 16 trades (electronics, tools, piping,
welding, seals and bearings, timber, and more).

## How makhzan crawls

makhzan reads what suppliers already publish, and tries to be a good guest about
it:

- **Public pages only.** The catalogue endpoints a shop already serves to any
  visitor. No accounts, no logins, no orders, nothing behind authentication, and
  nothing about a supplier's customers.
- **robots.txt is honoured.** Fetched per host, cached, and obeyed. A path a shop
  asks us not to read is not read.
- **One request at a time per shop, at least 15 seconds apart.** A
  `Crawl-delay` in robots.txt is a floor on that, never a ceiling.
- **A full pass is spread across about a week.** Each daily run takes only a
  slice of a catalogue, so a shop sees a steady trickle, not a spike.
- **The crawler identifies itself** in every request (`From: crawler@makhzan.eg`).
- **No circumvention.** If a site blocks us, we ask its owner; we do not route
  around a control they chose to switch on.
- **Suppliers can ask us to stop, slow down, or change anything**, and we will.
  Being listed is meant to send them buyers, not to cost them anything.

The same policy, for suppliers, is at
[`/how-we-crawl`](https://makhzan.merope.dev/en/how-we-crawl).

## What is, and is not, in this repository

This is the whole platform: crawling, normalisation, product matching, search,
the API and the web app. What it does **not** contain is the configuration that
points it at real shops: the list of suppliers crawled and the hand-written
crosswalks that map each shop's own categories onto ours. Those are kept in a
separate private repository.

A clone therefore runs with no suppliers, only a built-in test source. To crawl
real shops, write your own `sources.toml`; `config/sources.example.toml`
documents the format. WooCommerce, Shopify and Odoo shops need no code, only an
entry. Anything else is an adapter class, which `sources.toml` can name by import
path from your own package.

## Architecture

```
apps/web          Next.js frontend: search, browse, product and supplier pages; RTL, dark mode
apps/api          FastAPI, read-only, over Postgres and Meilisearch
apps/ingestion    Arq worker: source adapters -> normalise -> upsert -> group -> index
packages/schemas  SQLAlchemy models, migrations, taxonomies, grouping, search contract
config/           sources.example.toml (the format of a sources file)
scripts/          deploy, backup, status and data-loading scripts
```

Some of what makes it work:

- **Resumable sweeps.** A shop is split into partitions (stock status, or
  category), and progress is saved after every page. A crawl that dies on page
  40 of 43 resumes at 40, so a host that throttles mid-catalogue cannot make the
  tail unreachable.
- **Nothing is archived on partial evidence.** A listing is retired only after a
  complete sweep of its shop failed to see it, never because one run fell short.
- **Domains, not one taxonomy.** Each trade has its own category tree and rules
  (`packages/schemas/makhzan_schemas/domains/`). A listing's domain comes from
  its category, so one marketplace can span many trades.
- **Mapping beats guessing.** A shop's own categories are mapped through a
  crosswalk where one exists; keyword inference from titles is the fallback, not
  the default.
- **Cautious product matching.** Listings from different shops merge into one
  product only when an extracted part number *and* their titles agree. Price
  alone never merges anything.

## Getting started

Requires Docker, Python 3.12+ with Poetry, and Node with pnpm
(`corepack enable pnpm`).

```bash
make setup      # .env, Postgres/Meilisearch/Redis, dependencies, migrations, sources
make api        # http://localhost:8000
make web        # http://localhost:3000
make test       # Python test suites
make lint       # exactly what CI checks
```

`make help` lists every target. [docs/DEV.md](docs/DEV.md) walks through the
local workflow, and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) covers production.

## Documentation

- [docs/PLAN.md](docs/PLAN.md): what makhzan is for, and the original plan
- [docs/ROADMAP.md](docs/ROADMAP.md): what is done and what is next
- [docs/DESIGN.md](docs/DESIGN.md): the frontend's design language
- [docs/DOMAIN_GENERALIZATION.md](docs/DOMAIN_GENERALIZATION.md): how verticals are modelled
- [docs/decisions/](docs/decisions/): decision records
- [CLAUDE.md](CLAUDE.md): working notes on ingestion, taxonomy and matching,
  including the mistakes they record

## Licence

[Apache-2.0](LICENSE). See [NOTICE](NOTICE).
