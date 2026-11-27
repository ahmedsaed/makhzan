"""AI matching by hand: workers, the admin token, the mode, decisions, the backlog.

    python -m worker.ai status [--json]            # queue, throughput, workers, decisions
    python -m worker.ai worker add NAME --models h2o[,pplx]   # prints the token once
    python -m worker.ai worker list
    python -m worker.ai worker revoke NAME
    python -m worker.ai admin-token                # a fresh admin token and its sha256
    python -m worker.ai mode [off|live]            # no argument: show it
    python -m worker.ai redecide --dry-run [--policy NAME]
    python -m worker.ai revoke DECISION_ID --note "why" [--by NAME]
    python -m worker.ai backlog [--mutual]         # the whole catalogue's candidates
    python -m worker.ai candidates [--mutual]      # the daily producers, now
    python -m worker.ai jobs list [--dead] [--limit N]
    python -m worker.ai jobs retry ID [ID ...]
    python -m worker.ai flags list [--all]
    python -m worker.ai flags dismiss ID [ID ...] --note "why" [--by NAME]
    python -m worker.ai import DIR [--dry-run | --verify]   # a locally scored backlog

`./makhzan ai ...` runs this in the production worker (for `admin-token` it
also writes the hash into .env.prod and recreates the broker), and `make ai
ARGS="..."` against the local database. The contract is docs/ai/broker-api.md;
the owner's decisions are docs/ai/decision-review.md §6.

A worker token is printed once and stored only as its sha256 (P3); revoking
a worker refuses its token at once. The mode governs only whether the regroup
reads decisions: run `make regroup-dry-run ARGS=--ai` before `mode live`, and
before going back to `off`, which undoes every AI merge at the next regroup.
`redecide` recomputes standing decisions from their stored scores under a
policy (P7) and changes nothing: only `--dry-run` exists. `revoke` withdraws
one decision and cancels the pair's queued jobs; the next regroup undoes what
it joined. The pair is offered again only when the text the models see
changes, and no decision is written for it from scores the revocation already
saw (to rule on it for good, use `./makhzan overrides`).
`import` stores a locally scored backlog's scores and writes the decisions
they make through the pipeline's own code (`worker.ai_import`).
`flags dismiss` sets `resolved_at` (a hand-closed flag must too). Given
several ids it dismisses the open ones and exits 1 if any was not open.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import Sequence

from makhzan_schemas.ai import broker as core
from makhzan_schemas.ai import candidates as producers
from makhzan_schemas.ai import flow
from makhzan_schemas.ai.decisions import STANDING
from makhzan_schemas.ai.mode import LIVE, MODES, ai_mode, set_ai_mode
from makhzan_schemas.ai.pipelines import DECIDE, PIPELINES, decide
from makhzan_schemas.ai.policy import ACTIVE, MODELS, POLICIES
from makhzan_schemas.ai.status import collect, format_text
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import AiDecision, AiFlag, AiJob, AiWorker
from sqlalchemy import func, select

from worker import ai_import
from worker.reports import printable, who


async def _status(as_json: bool) -> int:
    async with SessionLocal() as session:
        data = await collect(session)
    print(json.dumps(data, indent=1, default=str) if as_json else format_text(data))
    return 0


class Refused(ValueError):
    """An AI action that cannot be done as asked; the message says why."""


async def add_worker(session, name: str, models: list[str]) -> str:
    """Register a worker (flushed, not committed) and return its token, shown once.

    Only the token's sha256 is stored (P3). Raises `Refused` for an unknown
    model key or a name already taken.
    """
    unknown = [m for m in models if m not in MODELS]
    if unknown:
        raise Refused(f"Unknown model key {', '.join(unknown)} (known: {sorted(MODELS)}).")
    if not models:
        raise Refused("Name at least one model key.")
    if await session.scalar(select(AiWorker.id).where(AiWorker.name == name)) is not None:
        raise Refused(f"A worker named {name!r} exists; revoke it or pick another name.")
    token = core.new_token()
    session.add(AiWorker(name=name, token_sha256=core.token_sha256(token), models=models))
    await session.flush()
    return token


async def _worker_add(name: str, models: list[str]) -> int:
    async with SessionLocal() as session:
        try:
            token = await add_worker(session, name, models)
        except Refused as refused:
            print(str(refused), file=sys.stderr)
            return 1
        await session.commit()
    print(f"Worker {name} may lease jobs for: {', '.join(models)}.")
    print("Its token, shown only now (store it in the worker's token_file):")
    print(token)
    return 0


async def _worker_list() -> int:
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(AiWorker).order_by(AiWorker.name)))
    if not rows:
        print("No AI workers.")
        return 0
    for w in rows:
        state = f"revoked {w.revoked_at:%Y-%m-%d}" if w.revoked_at else "active"
        seen = f"{w.last_seen_at:%Y-%m-%d %H:%M}" if w.last_seen_at else "never"
        print(f"{w.name:<20} {','.join(w.models):<12} {state:<20} last seen {seen}")
    return 0


async def revoke_worker(session, name: str) -> AiWorker:
    """Refuse a worker's token from now on (flushed, not committed). Its leases
    expire and requeue. Raises `Refused` if there is no such worker."""
    worker = await session.scalar(select(AiWorker).where(AiWorker.name == name))
    if worker is None:
        raise Refused(f"No worker named {name!r}.")
    if worker.revoked_at is None:
        worker.revoked_at = await session.scalar(select(func.now()))
        await session.flush()
    return worker


async def _worker_revoke(name: str) -> int:
    async with SessionLocal() as session:
        try:
            await revoke_worker(session, name)
        except Refused as refused:
            print(str(refused), file=sys.stderr)
            return 1
        await session.commit()
    print(f"Revoked {name}: its token is refused from now on. Its leases expire and requeue.")
    return 0


def _admin_token() -> int:
    """Machine-readable, for ./makhzan: the token and the hash the broker keeps."""
    token = core.new_token()
    print(f"token={token}")
    print(f"sha256={core.token_sha256(token).hex()}")
    return 0


async def _mode(value: str | None) -> int:
    async with SessionLocal() as session:
        if value is None:
            print(f"AI matching mode: {await ai_mode(session)}")
            return 0
        before = await ai_mode(session)
        await set_ai_mode(session, value)
        await session.commit()
    print(f"AI matching mode: {before} -> {value}. It takes effect at the next regroup.")
    if value == LIVE and before != LIVE:
        print("The regroup now reads standing 'same' decisions; the broker queues a rebuild")
        print("after a worker's window. Check `make regroup-dry-run ARGS=--ai` first.")
    elif value != LIVE and before == LIVE:
        print("The next regroup undoes every AI merge; decisions and scores are kept.")
    return 0


async def redecide(session, policy: str) -> dict:
    """What `policy` would decide from each standing decision's stored scores. Writes nothing.

    `{"policy", "thresholds", "active", "total", "counts": {key: n}, "examples": {key: [ids]}}`,
    where a key is `unchanged <outcome>`, `<before> -> <after>`, `needs <stage>
    scores first`, `policy lacks <stage>` (no threshold for a stage of the pipeline) or
    `unregistered pipeline`. Raises `Refused` for an unknown policy.
    """
    if policy not in POLICIES:
        raise Refused(f"No policy {policy!r} (known: {sorted(POLICIES)}).")
    rows = list(await session.scalars(select(AiDecision).where(AiDecision.state == STANDING)))
    counts: Counter = Counter()
    examples: dict[str, list[int]] = {}
    for d in rows:
        if d.pipeline not in PIPELINES:
            counts["unregistered pipeline"] += 1
            continue
        scores = {
            name: {"ab": entry.get("ab"), "ba": entry.get("ba")}
            for name, entry in (d.scores or {}).items()
        }
        lacking = [
            s.name
            for s in PIPELINES[d.pipeline].stages
            if s.threshold is not None and s.threshold not in POLICIES[policy]
        ]
        if lacking:
            # A policy of another judge (p1 has no threshold for H2O's stage, D25): nothing
            # to recompute, rather than a traceback.
            key = f"policy lacks {lacking[0]}"
            counts[key] += 1
            examples.setdefault(key, []).append(d.id)
            continue
        step = decide(d.pipeline, scores, policy)
        if step.action != DECIDE:
            key = f"needs {step.stage} scores first"
        elif step.outcome == d.outcome:
            key = f"unchanged {d.outcome}"
        else:
            key = f"{d.outcome} -> {step.outcome}"
        counts[key] += 1
        examples.setdefault(key, []).append(d.id)
    return {
        "policy": policy,
        "thresholds": POLICIES[policy],
        "active": ACTIVE,
        "total": len(rows),
        "counts": dict(sorted(counts.items())),
        "examples": {k: v[:5] for k, v in examples.items()},
    }


async def _redecide(policy: str) -> int:
    async with SessionLocal() as session:
        try:
            result = await redecide(session, policy)
        except Refused as refused:
            print(str(refused), file=sys.stderr)
            return 1
    print(f"Standing decisions under policy {policy} {POLICIES[policy]} (active: {ACTIVE}):")
    if not result["total"]:
        print("  none")
    for key, n in result["counts"].items():
        ids = result["examples"].get(key, [])
        sample = f"  e.g. #{', #'.join(map(str, ids))}" if ids and "unchanged" not in key else ""
        print(f"  {key:<32} {n}{sample}")
    print("Dry run: nothing written. Applying a new policy is a change of policy.ACTIVE.")
    return 0


async def _revoke(decision_id: int, note: str, by: str) -> int:
    async with SessionLocal() as session:
        # Locks the pair as `write_decision` does, so no decision being written
        # meanwhile can slip past the revocation.
        decision, cancelled, refusal = await flow.revoke_decision(
            session, decision_id, by=by, note=note
        )
        if refusal:
            print(refusal, file=sys.stderr)
            return 1
        await session.commit()
    print(
        printable(
            f"Revoked #{decision_id} ({decision.pipeline} {decision.outcome}, "
            f"{decision.listing_a} / {decision.listing_b}) by {by}; {cancelled} queued "
            "job(s) cancelled. The next regroup undoes what it joined."
        )
    )
    return 0


async def _backlog(mutual: bool) -> int:
    async with SessionLocal() as session:
        result = await producers.backlog(session, mutual=mutual)
        await session.commit()
    print(json.dumps(result, indent=1, default=str))
    return 0


async def _candidates(mutual: bool) -> int:
    async with SessionLocal() as session:
        result = await producers.daily(session, mutual=mutual)
        await session.commit()
    print(json.dumps(result, indent=1, default=str))
    return 0


async def _jobs_list(dead: bool, limit: int) -> int:
    async with SessionLocal() as session:
        query = select(AiJob).order_by(AiJob.id.desc()).limit(limit)
        query = (
            query.where(AiJob.status == "dead")
            if dead
            else query.where(AiJob.status.in_(core.OPEN))
        )
        rows = list(await session.scalars(query))
    if not rows:
        print("No jobs.")
    for j in rows:
        print(
            f"#{j.id} {j.pipeline}.{j.stage} {j.status} p{j.priority} {j.reason} "
            f"attempts {j.attempts}/{j.max_attempts} {j.listing_a} / {j.listing_b}"
            + (f"\n    last error: {j.last_error}" if j.last_error else "")
        )
    return 0


async def _jobs_retry(ids: Sequence[int]) -> int:
    failed = 0
    async with SessionLocal() as session:
        for job_id in ids:
            job = await core.retry_job(session, job_id)
            if job is None:
                print(f"#{job_id}: not dead or cancelled, or an open twin exists.", file=sys.stderr)
                failed += 1
            else:
                print(f"#{job_id}: queued again.")
        await session.commit()
    return 1 if failed else 0


async def _flags_list(everything: bool) -> int:
    async with SessionLocal() as session:
        query = select(AiFlag).order_by(AiFlag.id.desc()).limit(200)
        if not everything:
            query = query.where(AiFlag.status == "open")
        rows = list(await session.scalars(query))
    if not rows:
        print("No flags.")
    for f in rows:
        about = f.subject or (f"{f.listing_a} / {f.listing_b}" if f.listing_a else "")
        line = f"#{f.id} {f.kind} {f.status} {about} {json.dumps(f.detail, default=str)}"
        if f.note:
            line += f"\n    note: {f.note}"
        print(printable(line))
    return 0


async def dismiss_flags(session, ids: Sequence[int], *, note: str, by: str) -> list[int]:
    """Dismiss open flags with a note (flushed, not committed). Returns the ids
    that were not open flags, which are left alone."""
    if not note.strip():
        raise Refused("A note must say why.")
    missing = []
    now = await session.scalar(select(func.now()))
    for flag_id in ids:
        flag = await session.get(AiFlag, flag_id, with_for_update=True)
        if flag is None or flag.status != "open":
            missing.append(flag_id)
            continue
        flag.status, flag.resolved_at, flag.resolved_by, flag.note = "dismissed", now, by, note
    await session.flush()
    return missing


async def _flags_dismiss(ids: Sequence[int], note: str, by: str) -> int:
    async with SessionLocal() as session:
        try:
            missing = await dismiss_flags(session, ids, note=note, by=by)
        except Refused as refused:
            print(str(refused), file=sys.stderr)
            return 1
        await session.commit()
    for flag_id in ids:
        if flag_id in missing:
            print(f"#{flag_id}: no open flag.", file=sys.stderr)
        else:
            print(f"#{flag_id}: dismissed by {by}.")
    return 1 if missing else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="queue, throughput, workers, decisions")
    status.add_argument("--json", action="store_true")
    worker = sub.add_parser("worker", help="workers allowed to lease jobs")
    wsub = worker.add_subparsers(dest="action", required=True)
    add = wsub.add_parser("add", help="register a worker and print its token once")
    add.add_argument("name")
    add.add_argument("--models", required=True, help=f"comma-separated: {sorted(MODELS)}")
    wsub.add_parser("list")
    revoke_w = wsub.add_parser("revoke", help="refuse a worker's token from now on")
    revoke_w.add_argument("name")
    sub.add_parser("admin-token", help="a fresh admin token for GET /status, and its sha256")
    mode = sub.add_parser("mode", help="off or live; no argument shows it")
    mode.add_argument("value", nargs="?", choices=MODES)
    redecide = sub.add_parser("redecide", help="recompute decisions from stored scores (P7)")
    redecide.add_argument("--dry-run", action="store_true", required=True)
    redecide.add_argument("--policy", default=ACTIVE)
    revoke = sub.add_parser("revoke", help="withdraw one standing decision")
    revoke.add_argument("decision", type=lambda v: int(v.strip().removeprefix("#")))
    revoke.add_argument("--note", required=True, help="why: kept with the decision")
    revoke.add_argument("--by", help="who is revoking (default: login)")
    backlog = sub.add_parser("backlog", help="queue the whole catalogue's candidates")
    backlog.add_argument("--mutual", action="store_true", help="both directions (always so here)")
    cands = sub.add_parser("candidates", help="run the daily producers now")
    cands.add_argument("--mutual", action="store_true", help="also listings whose top K changed")
    flags = sub.add_parser("flags", help="flags for a person: list, dismiss")
    fsub = flags.add_subparsers(dest="action", required=True)
    flist = fsub.add_parser("list")
    flist.add_argument("--all", action="store_true", help="closed flags too")
    dismiss = fsub.add_parser("dismiss", help="close flags with a note")
    dismiss.add_argument("ids", type=lambda v: int(v.strip().removeprefix("#")), nargs="+")
    dismiss.add_argument("--note", required=True, help="why: kept with the flag")
    dismiss.add_argument("--by", help="who is dismissing (default: login)")
    imported = sub.add_parser("import", help="store a locally scored backlog and decide its pairs")
    ai_import.add_arguments(imported)
    jobs = sub.add_parser("jobs", help="the job queue")
    jsub = jobs.add_subparsers(dest="action", required=True)
    jlist = jsub.add_parser("list")
    jlist.add_argument("--dead", action="store_true")
    jlist.add_argument("--limit", type=int, default=50)
    retry = jsub.add_parser("retry", help="queue dead or cancelled jobs again")
    retry.add_argument("ids", type=int, nargs="+")
    return parser


async def run(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    match args.command:
        case "status":
            return await _status(args.json)
        case "worker" if args.action == "add":
            models = [m.strip() for m in args.models.split(",") if m.strip()]
            if not models:
                parser.error("--models names at least one model key")
            return await _worker_add(args.name, models)
        case "worker" if args.action == "list":
            return await _worker_list()
        case "worker":
            return await _worker_revoke(args.name)
        case "admin-token":
            return _admin_token()
        case "mode":
            return await _mode(args.value)
        case "redecide":
            return await _redecide(args.policy)
        case "revoke":
            if not args.note.strip():
                parser.error("--note must say why")
            return await _revoke(args.decision, args.note, who(args.by))
        case "backlog":
            return await _backlog(True)
        case "candidates":
            return await _candidates(args.mutual)
        case "flags" if args.action == "list":
            return await _flags_list(args.all)
        case "flags":
            if not args.note.strip():
                parser.error("--note must say why")
            return await _flags_dismiss(args.ids, args.note, who(args.by))
        case "import":
            return await ai_import.main(args)
        case "jobs" if args.action == "list":
            return await _jobs_list(args.dead, args.limit)
        case "jobs":
            return await _jobs_retry(args.ids)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
