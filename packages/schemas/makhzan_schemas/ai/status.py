"""AI matching's numbers: what `GET /ai/v1/status`, `./makhzan ai status` and
`make status` show. Read-only.

- the mode and policy, and each stage's current judge;
- the queue by pipeline and stage: queued, leased and dead jobs, the oldest
  queued, and requests owed (two a job, an upper bound);
- throughput over the last 24 hours, per model: scores and the median
  seconds a request;
- workers: models, last seen, the last hello's device and window, revoked;
- projected nights to drain each model's queue, at the median seconds a
  request and the windows its workers reported (none reported: unknown);
- open flags by kind;
- decisions: standing by pipeline and outcome, written in the last 7 days,
  stale and revoked; re-scores due (P6: a standing decision whose text or
  judge changed), with how many have an open job, a dead one, or none;
- the audit (P12): rules-merged pairs scored, and how many fell below 0.8 and
  below 0.05. No threshold is chosen; these are counts only.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from makhzan_schemas.ai.decisions import REVOKED, STALE, STANDING
from makhzan_schemas.ai.mode import ai_mode
from makhzan_schemas.ai.pipelines import PIPELINES
from makhzan_schemas.ai.policy import ACTIVE, MODELS, thresholds
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import (
    AiDecision,
    AiFlag,
    AiJob,
    AiListingState,
    AiModelVersion,
    AiScore,
    AiWorker,
    Listing,
)

#: P12's two counts.
AUDIT_BELOW = (0.8, 0.05)


def _window_seconds(window: str | None) -> int | None:
    """ "00:30-04:30" -> 14400; a window across midnight wraps."""
    if not window or "-" not in window:
        return None
    try:
        start, end = window.split("-", 1)
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except ValueError:
        return None
    seconds = ((eh * 60 + em) - (sh * 60 + sm)) * 60
    return seconds if seconds > 0 else seconds + 86400


async def collect(session: AsyncSession) -> dict:
    now: datetime = await session.scalar(select(func.now()))
    versions = {row.id: row for row in await session.scalars(select(AiModelVersion))}
    current_judge: dict[tuple[str, str], int | None] = {}
    for p in PIPELINES.values():
        for s in p.stages:
            match = next(
                (
                    v.id
                    for v in versions.values()
                    if v.model == s.model
                    and v.model_version == s.model_version
                    and v.prompt_version == s.prompt_version
                ),
                None,
            )
            current_judge[(p.name, s.name)] = match

    queue_rows = await session.execute(
        select(
            AiJob.pipeline,
            AiJob.stage,
            AiJob.status,
            func.count(),
            func.min(AiJob.created_at),
        )
        .where(AiJob.status.in_(("queued", "leased", "dead")))
        .group_by(AiJob.pipeline, AiJob.stage, AiJob.status)
    )
    queue: dict[str, dict] = {}
    for pipeline_name, stage, status, count, oldest in queue_rows:
        entry = queue.setdefault(
            f"{pipeline_name}.{stage}",
            {"queued": 0, "leased": 0, "dead": 0, "oldest_queued": None, "requests": 0},
        )
        entry[status] = count
        if status == "queued":
            entry["oldest_queued"] = oldest.isoformat() if oldest else None
            entry["requests"] = 2 * count

    since = now - timedelta(hours=24)
    scored = await session.execute(
        select(AiModelVersion.model, AiScore.seconds)
        .join(AiModelVersion, AiModelVersion.id == AiScore.model_version_id)
        .where(AiScore.scored_at >= since)
    )
    per_model: dict[str, list[float]] = {}
    counts_24h: dict[str, int] = {}
    for model, seconds in scored:
        counts_24h[model] = counts_24h.get(model, 0) + 1
        if seconds is not None:
            per_model.setdefault(model, []).append(seconds)
    median: dict[str, float | None] = {}
    for model in MODELS:
        recent = per_model.get(model)
        if not recent:
            # Fall back to the last 1,000 scores of any age.
            recent = list(
                await session.scalars(
                    select(AiScore.seconds)
                    .join(AiModelVersion, AiModelVersion.id == AiScore.model_version_id)
                    .where(AiModelVersion.model == model, AiScore.seconds.is_not(None))
                    .order_by(AiScore.scored_at.desc())
                    .limit(1000)
                )
            )
        median[model] = round(statistics.median(recent), 1) if recent else None
    throughput = {
        model: {"scores_24h": counts_24h.get(model, 0), "median_seconds": median[model]}
        for model in MODELS
    }

    workers = []
    window_by_model: dict[str, int] = {}
    for w in await session.scalars(select(AiWorker).order_by(AiWorker.name)):
        hello = w.last_hello or {}
        config = hello.get("config") or {}
        window = config.get("window")
        workers.append(
            {
                "name": w.name,
                "models": list(w.models),
                "last_seen_at": w.last_seen_at.isoformat() if w.last_seen_at else None,
                "revoked": w.revoked_at is not None,
                "device": hello.get("device"),
                "dtype": hello.get("dtype"),
                "threads": hello.get("threads"),
                "window": window,
            }
        )
        seconds = _window_seconds(window)
        recent = w.last_seen_at is not None and w.last_seen_at >= now - timedelta(days=7)
        if w.revoked_at is None and seconds and recent:
            for model in w.models:
                window_by_model[model] = window_by_model.get(model, 0) + seconds

    owed_by_model: dict[str, int] = {}
    for key, entry in queue.items():
        pipeline_name, stage = key.split(".", 1)
        p = PIPELINES.get(pipeline_name)
        if p is None:
            continue
        try:
            model = p.stage(stage).model
        except ValueError:
            continue
        owed_by_model[model] = owed_by_model.get(model, 0) + entry["requests"]
    nights = {}
    for model in MODELS:
        owed = owed_by_model.get(model, 0)
        per_night = window_by_model.get(model)
        if not owed:
            nights[model] = 0.0
        elif median[model] and per_night:
            nights[model] = round(owed * median[model] / per_night, 1)
        else:
            nights[model] = None

    flags = dict(
        (
            await session.execute(
                select(AiFlag.kind, func.count())
                .where(AiFlag.status == "open")
                .group_by(AiFlag.kind)
            )
        ).all()
    )

    decision_rows = await session.execute(
        select(AiDecision.pipeline, AiDecision.state, AiDecision.outcome, func.count()).group_by(
            AiDecision.pipeline, AiDecision.state, AiDecision.outcome
        )
    )
    decisions: dict[str, dict] = {}
    for pipeline_name, state, outcome, count in decision_rows:
        entry = decisions.setdefault(
            pipeline_name, {"same": 0, "not_same": 0, STALE: 0, REVOKED: 0, "new_7d": {}}
        )
        if state == STANDING:
            entry[outcome] = count
        else:
            entry[state] += count
    recent_rows = await session.execute(
        select(AiDecision.pipeline, AiDecision.outcome, func.count())
        .where(AiDecision.state == STANDING, AiDecision.created_at >= now - timedelta(days=7))
        .group_by(AiDecision.pipeline, AiDecision.outcome)
    )
    for pipeline_name, outcome, count in recent_rows:
        decisions.setdefault(
            pipeline_name, {"same": 0, "not_same": 0, STALE: 0, REVOKED: 0, "new_7d": {}}
        )["new_7d"][outcome] = count

    rescore = await _rescore_due(session, current_judge)
    audit = await _audit(session, current_judge)
    return {
        "at": now.isoformat(),
        "mode": await ai_mode(session),
        "policy": {"name": ACTIVE, "thresholds": thresholds(ACTIVE)},
        "judges": {
            f"{p}.{s}": (
                {
                    "id": jid,
                    "model_version": versions[jid].model_version,
                    "prompt_version": versions[jid].prompt_version,
                }
                if jid is not None
                else None
            )
            for (p, s), jid in current_judge.items()
        },
        "queue": queue,
        "throughput": throughput,
        "workers": workers,
        "nights": nights,
        "flags": flags,
        "decisions": decisions,
        "rescore_due": rescore,
        "audit": audit,
    }


async def _rescore_due(session: AsyncSession, judges: dict) -> dict:
    """Standing decisions whose text (by `ai_listing_state`) or a stage's
    judge changed, and what is being done about them (P6: no timeout)."""
    sa, sb = aliased(AiListingState), aliased(AiListingState)
    la, lb = aliased(Listing), aliased(Listing)
    changed = or_(
        AiDecision.content_sha256_a.is_distinct_from(sa.content_sha256),
        AiDecision.content_sha256_b.is_distinct_from(sb.content_sha256),
    )
    rows = (
        await session.execute(
            select(
                AiDecision.pipeline,
                AiDecision.listing_a,
                AiDecision.listing_b,
                AiDecision.scores,
                changed,
            )
            .join(sa, sa.listing_id == AiDecision.listing_a)
            .join(sb, sb.listing_id == AiDecision.listing_b)
            .join(la, and_(la.id == AiDecision.listing_a, la.status == ListingStatus.ACTIVE))
            .join(lb, and_(lb.id == AiDecision.listing_b, lb.status == ListingStatus.ACTIVE))
            .where(AiDecision.state == STANDING)
        )
    ).all()
    due = []
    for pipeline_name, a, b, scores, changed in rows:
        judged = any(
            judges.get((pipeline_name, name)) != (entry or {}).get("model_version_id")
            for name, entry in (scores or {}).items()
        )
        if changed or judged:
            due.append((pipeline_name, a, b))
    if not due:
        return {"due": 0, "open_job": 0, "dead_job": 0, "no_job": 0}
    jobs = await session.execute(
        select(AiJob.pipeline, AiJob.listing_a, AiJob.listing_b, AiJob.status).where(
            AiJob.status.in_(("queued", "leased", "dead"))
        )
    )
    status_of: dict[tuple, set[str]] = {}
    for pipeline_name, a, b, status in jobs:
        status_of.setdefault((pipeline_name, a, b), set()).add(status)
    out = {"due": len(due), "open_job": 0, "dead_job": 0, "no_job": 0}
    for key in due:
        seen = status_of.get(key, set())
        if seen & {"queued", "leased"}:
            out["open_job"] += 1
        elif "dead" in seen:
            out["dead_job"] += 1
        else:
            out["no_job"] += 1
    return out


async def _audit(session: AsyncSession, judges: dict) -> dict:
    """Rules-merged pairs the audit scored in both orders (at the judge each
    job was queued at), and how many fell below each of P12's counts."""
    rows = (
        await session.execute(
            text(
                """
            SELECT LEAST(sab.p, sba.p) AS low
              FROM ai_jobs j
              JOIN ai_scores sab ON sab.model_version_id = j.model_version_id
                                AND sab.request_sha256 = decode(j.request_sha256->>'ab', 'hex')
              JOIN ai_scores sba ON sba.model_version_id = j.model_version_id
                                AND sba.request_sha256 = decode(j.request_sha256->>'ba', 'hex')
             WHERE j.pipeline = 'audit' AND j.status = 'done'
            """
            )
        )
    ).all()
    lows = [row.low for row in rows]
    return {
        "scored": len(lows),
        **{f"below_{limit}": sum(1 for x in lows if x < limit) for limit in AUDIT_BELOW},
    }


def _age(iso: str | None, now: datetime) -> str:
    if not iso:
        return "-"
    delta = now - datetime.fromisoformat(iso)
    hours = int(delta.total_seconds() // 3600)
    return f"{hours // 24}d {hours % 24}h" if hours >= 24 else f"{hours}h"


def format_text(data: dict) -> str:
    """The section as `make status` prints it."""
    now = datetime.fromisoformat(data["at"])
    limits = ", ".join(f"{k} >= {v}" for k, v in data["policy"]["thresholds"].items())
    lines = [f"  mode: {data['mode']}   policy {data['policy']['name']}: {limits}"]
    for key, judge in data["judges"].items():
        shown = (
            f"{judge['model_version']} / {judge['prompt_version']}" if judge else "(not yet used)"
        )
        lines.append(f"  judge {key:<12} {shown}")
    if data["queue"]:
        for key, q in sorted(data["queue"].items()):
            lines.append(
                f"  queue {key:<12} {q['queued']} queued ({q['requests']} requests, oldest "
                f"{_age(q['oldest_queued'], now)}), {q['leased']} leased, {q['dead']} dead"
            )
    else:
        lines.append("  queue        empty")
    for model, t in data["throughput"].items():
        med = f"{t['median_seconds']} s/request median" if t["median_seconds"] else "no timing yet"
        nights = data["nights"].get(model)
        backlog = (
            "nothing queued"
            if nights == 0
            else f"about {nights} nights to drain"
            if nights is not None
            else "nights to drain unknown (no timing or no reported window)"
        )
        lines.append(f"  model {model:<12} {t['scores_24h']} scores in 24 h, {med}; {backlog}")
    if data["workers"]:
        for w in data["workers"]:
            state = "REVOKED" if w["revoked"] else f"last seen {_age(w['last_seen_at'], now)} ago"
            where = " ".join(
                str(x)
                for x in (w["device"], w["dtype"], w["threads"] and f"x{w['threads']}", w["window"])
                if x
            )
            lines.append(f"  worker {w['name']:<11} {','.join(w['models'])}  {state}  {where}")
    else:
        lines.append("  workers      none registered (./makhzan ai worker add)")
    flags = data["flags"]
    lines.append(
        "  flags        "
        + (", ".join(f"{k} {v}" for k, v in sorted(flags.items())) if flags else "none open")
    )
    for pipeline_name, d in sorted(data["decisions"].items()):
        new = ", ".join(f"{k} {v}" for k, v in sorted(d["new_7d"].items())) or "none"
        lines.append(
            f"  decisions {pipeline_name:<8} standing: same {d['same']}, not same {d['not_same']}"
            f"; stale {d[STALE]}, revoked {d[REVOKED]}; new in 7 d: {new}"
        )
    r = data["rescore_due"]
    if r["due"]:
        flag = "  <- re-scores due with no open job" if r["no_job"] or r["dead_job"] else ""
        lines.append(
            f"  re-score due {r['due']}: {r['open_job']} queued, {r['dead_job']} dead job, "
            f"{r['no_job']} no job{flag}"
        )
    else:
        lines.append("  re-score due none")
    a = data["audit"]
    lines.append(
        f"  audit        {a['scored']} rules-merged pairs scored; "
        + ", ".join(f"below {limit}: {a[f'below_{limit}']}" for limit in AUDIT_BELOW)
    )
    return "\n".join(lines)
