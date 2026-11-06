# Seed data

`makhzan-seed.dump` is a `pg_dump -Fc` (custom-format, compressed) snapshot of the
catalog used to seed a fresh deployment — so the server starts with real data
instead of running a full scrape.

The dump is **not committed** (it's data and it grows). Transfer it out-of-band.

## Pull production onto your machine

From a developer machine, with `DEPLOY_HOST` set in `.env.local`:

```bash
make db-refresh      # pull a snapshot and load it into the local database
```

That is the usual way in. It handles migrations and the cursor reset described
below; see `docs/DEV.md`. The rest of this file is about the *server* side.

## Produce a dump (from a machine that has the data)

```bash
docker compose exec -T db pg_dump -U makhzan -Fc makhzan > seed/makhzan-seed.dump
```

It contains schema@head + data + `alembic_version`, so restoring leaves the DB at
the current migration head (a later `alembic upgrade head` is a no-op).

## Use it on the server

```bash
scp seed/makhzan-seed.dump user@server:~/Documents/Projects/makhzan/seed/
# on the server:
./scripts/restore-seed.sh        # restores the dump + rebuilds the search index
./scripts/deploy.sh              # starts the app
```

To start empty and scrape instead, skip `restore-seed.sh` and run `./scripts/seed.sh`.
