"""Import a locally scored AI backlog: its scores, then the decisions they make.

    python -m worker.ai_import DIR [--dry-run | --verify] [--policy p2]
    python -m worker.ai import DIR ...            # the same, from the AI command
    ./makhzan ai import DIR ...                   # production (scripts/lib/ai_import.sh)

`DIR` holds `scores-*.jsonl`, one line per scored request, as the backlog
driver writes them (`listing_a` < `listing_b`, `order`, `shown_as_a`, `p`,
`model`, `model_version`, `weights_revision`, `prompt_variant`,
`prompt_version`, `request_sha256`, `content_sha256_a`/`_b`, `hash_version`,
device, dtype, `scored_at`, `source`). The same import serves a local preview
copy and, once the owner has reviewed the groupings, production (P4).

What it does, in order:

1. **Checks every line against the code**: a JSON object; its model's version
   and weights revision are `policy.MODELS`'s (a missing weights revision or
   `scored_at` is refused too); its prompt version is `prompt.PROMPT_VERSIONS`'s for a stage
   of `match`; its hash version is `hashing.HASH_VERSION`; ids, hashes, `p`
   and `scored_at` are well formed, and its order agrees with `shown_as_a`.
   Any bad line refuses the whole import, naming its file and line: scores of
   another judge are not this judge's, whatever their numbers.
2. **Creates the judges** (`ai_model_versions`) the way a stage does on first
   use (`triggers.model_version_id`), so the rows match `policy.py`.
3. **Re-renders each request from the listing as it is now**
   (`render.load_shown`, `render.render`) and keeps the line only when its
   `request_sha256` is what the committed renderer produces. A line whose
   listing's text changed since the run (or whose listing is gone) is
   skipped and counted, with the listings involved: its score answers a
   request nobody would send now. Of those listings, the ones whose current
   text the candidates trigger has already recorded are **stranded**: no
   trigger will offer them again until they change once more (with no
   `ai_listing_state` at all, every stale listing is: `ai_candidates`, which
   runs after every rebuild whatever the mode, records its first baseline
   and offers nothing).
4. **Inserts the scores**, idempotently on (judge, `request_sha256`)
   (`uq_ai_score_request`): a re-run, or a request two pairs share
   byte-for-byte, stores one row. A request already scored in the database
   keeps its stored score, and decisions read that one; a stored score whose
   p differs from the file's is counted.
5. **Decides through the pipeline's own code**: every pair whose stages are
   all scored for its current text gets `pipelines.transition` over the
   stored scores (`flow.scores_for`) and then `flow.write_decision`, under the
   active policy: the same two steps `flow.advance` takes for a pair it
   decides, so the evidence with request hashes, the current content hashes
   and a person's revocation holding are exactly what the broker would
   write. Called directly rather than through `advance` so each pair is
   counted by what `write_decision` returned: written (by outcome), blocked
   by a revocation, or its listing gone. A pair a person has ruled on
   (`grouping_overrides`, `load_overrides`) is never decided (CLAUDE.md:
   never re-ask a model about a ruled pair) and is counted; its scores are
   still stored, as evidence. A pair `transition` does not decide is
   counted, not queued: by the stage it owes when it has fresh scores up to
   it (Kev scored, no pplx line), or as having no fresh score at all. Either
   kind, or a stale listing, makes the report recommend `./makhzan ai
   backlog`, which offers those pairs again.

Decisions are committed in chunks (`CHUNK` pairs): each takes a
transaction-scoped advisory lock, and one transaction over the whole backlog
would exhaust the lock table. A run cut off part-way is resumed by running it
again; everything above is idempotent.

`--dry-run` does steps 1 to 4 inside one transaction, computes each pair's
step with `pipelines.transition` over the scores as they would be stored, and
rolls back: it reports what would be inserted and decided without
`write_decision`'s writes, so a pair a person revoked is reported as such
rather than as blocked.

`--verify` changes nothing. Every fresh line's score is stored under its
judge: with the file's p, or, when the stored row was there before the
import (another source, another time), with whatever p it has, counted
apart. Every pair whose stages are scored and which no person has ruled on
has a standing decision under the active policy with the outcome, stage
minimums and request hashes the stored scores give, unless a person's
revocation keeps it from being written (`flow.write_decision`'s guard),
which is expected and counted. Exit 1 on any mismatch.

`--policy` names the policy the run was approved under (`p2`); the import
refuses to run when the code's active policy is another.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from makhzan_schemas.ai import flow, triggers
from makhzan_schemas.ai.decisions import REVOKED, STANDING
from makhzan_schemas.ai.hashing import HASH_VERSION
from makhzan_schemas.ai.pipelines import DECIDE, Stage, pipeline, transition
from makhzan_schemas.ai.policy import ACTIVE, MODELS
from makhzan_schemas.ai.render import Shown, load_shown, render
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import AiDecision, AiListingState, AiScore
from makhzan_schemas.overrides import load_overrides
from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

#: The pipeline backlog pairs belong to.
PIPELINE = "match"
#: Pairs per committed decision chunk (one advisory lock each).
CHUNK = 500
#: Score rows per INSERT: 14 parameters each, inside asyncpg's 32767.
_INSERT_BATCH = 2000
#: Keys per lookup.
_LOOKUP = 5000
ORDERS = ("ab", "ba")
#: How many stale listing ids the report prints in full.
STALE_IDS_SHOWN = 200
RECOMMEND_BACKLOG = (
    "Run `./makhzan ai backlog` after this import: it finds candidates for every listing and "
    "offers the pairs left undecided here ({why})."
)


class ImportRefused(ValueError):
    """The files cannot be imported as they are; the message says why."""


@dataclass(frozen=True)
class Line:
    """One scored request, checked against the code."""

    number: int
    file: str
    stage: Stage
    listing_a: uuid.UUID
    listing_b: uuid.UUID
    order: str
    p: float
    request_sha256: bytes
    content_sha256_a: bytes
    content_sha256_b: bytes
    extra: dict
    seconds: float | None
    device: str | None
    dtype: str | None
    threads: int | None
    scored_at: datetime

    @property
    def pair(self) -> tuple[uuid.UUID, uuid.UUID]:
        return (self.listing_a, self.listing_b)


@dataclass
class Report:
    lines: int = 0
    by_model: Counter = field(default_factory=Counter)
    stale: Counter = field(default_factory=Counter)
    missing_listing: int = 0
    content_hash_differs: int = 0
    stale_pairs: int = 0
    stale_listings: list[str] = field(default_factory=list)
    stranded_listings: int = 0
    inserted: int = 0
    already_stored: int = 0
    already_stored_p_differs: int = 0
    repeated_in_files: int = 0
    pairs: int = 0
    ruled: int = 0
    planned: Counter = field(default_factory=Counter)
    planned_by: Counter = field(default_factory=Counter)
    written: Counter = field(default_factory=Counter)
    written_by: Counter = field(default_factory=Counter)
    listing_gone: int = 0
    unsettled: int = 0
    owes: Counter = field(default_factory=Counter)
    previous: Counter = field(default_factory=Counter)
    revoked_pairs: int = 0
    blocked_by_revocation: int = 0
    held_before_import_p_differs: int = 0
    mismatches: list[str] = field(default_factory=list)
    recommendation: str | None = None

    def as_dict(self) -> dict:
        return {
            "lines": self.lines,
            "lines_by_model": dict(self.by_model),
            "stale_lines_by_model": dict(self.stale),
            "lines_listing_missing": self.missing_listing,
            "lines_fresh_but_content_hash_differs": self.content_hash_differs,
            "stale_pairs": self.stale_pairs,
            "stale_listings": len(self.stale_listings),
            "stale_listings_stranded": self.stranded_listings,
            "stale_listing_ids": self.stale_listings[:STALE_IDS_SHOWN],
            "scores_inserted": self.inserted,
            "scores_already_stored": self.already_stored,
            "scores_already_stored_p_differs": self.already_stored_p_differs,
            "lines_repeating_a_request": self.repeated_in_files,
            "pairs": self.pairs,
            "pairs_ruled_by_a_person": self.ruled,
            "decisions_planned": dict(self.planned),
            "planned_by_stage": dict(self.planned_by),
            "decisions_written": dict(self.written),
            "written_by_stage": dict(self.written_by),
            "blocked_by_revocation": self.blocked_by_revocation,
            "listing_gone_at_write": self.listing_gone,
            "pairs_unsettled_stale_or_unscored": self.unsettled,
            "pairs_owing_a_stage": dict(self.owes),
            "planned_against_standing": dict(self.previous),
            "pairs_with_a_revoked_decision": self.revoked_pairs,
            "scores_held_before_import_p_differs": self.held_before_import_p_differs,
            "mismatches": len(self.mismatches),
            "first_mismatches": self.mismatches[:20],
            "recommendation": self.recommendation,
        }


def _stages() -> dict[tuple[str, str], Stage]:
    """The `match` stages by (model key, prompt variant)."""
    return {(s.model, s.prompt): s for s in pipeline(PIPELINE).stages}


def _bytes(value: object, what: str, where: str) -> bytes:
    try:
        raw = bytes.fromhex(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ImportRefused(f"{where}: {what} is not hex") from None
    if len(raw) != 32:
        raise ImportRefused(f"{where}: {what} is not a sha256")
    return raw


def _uuid(value: object, what: str, where: str) -> uuid.UUID:
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            pass
    raise ImportRefused(f"{where}: {what} {value!r} is not a UUID")


def _time(value: object, where: str) -> datetime:
    if value is None:
        raise ImportRefused(f"{where}: scored_at missing")
    try:
        moment = datetime.fromisoformat(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ImportRefused(f"{where}: scored_at {value!r} is not an ISO time") from None
    if moment.tzinfo is None:
        raise ImportRefused(f"{where}: scored_at {value!r} has no time zone")
    return moment


def parse_line(raw: object, where: str, file: str = "", number: int = 0) -> Line:
    """One line, checked against the registry; raises `ImportRefused`."""
    if not isinstance(raw, dict):
        raise ImportRefused(f"{where}: not a JSON object")
    stages = _stages()
    model = MODELS.get(raw.get("model"))  # type: ignore[arg-type]
    if model is None:
        raise ImportRefused(f"{where}: unknown model {raw.get('model')!r}")
    if raw.get("model_version") != model.model_version:
        raise ImportRefused(
            f"{where}: model version {raw.get('model_version')!r} is not the code's "
            f"{model.model_version!r}"
        )
    if raw.get("weights_revision") != model.weights_revision:
        raise ImportRefused(
            f"{where}: weights revision {raw.get('weights_revision')!r} is not the code's "
            f"{model.weights_revision!r}"
        )
    stage = stages.get((model.key, raw.get("prompt_variant")))
    if stage is None:
        raise ImportRefused(
            f"{where}: no {PIPELINE} stage reads {model.key} through {raw.get('prompt_variant')!r}"
        )
    if raw.get("prompt_version") != stage.prompt_version:
        raise ImportRefused(
            f"{where}: prompt version {raw.get('prompt_version')!r} is not the code's "
            f"{stage.prompt_version!r}"
        )
    if raw.get("hash_version") != HASH_VERSION:
        raise ImportRefused(f"{where}: hash version {raw.get('hash_version')!r} != {HASH_VERSION}")
    a = _uuid(raw.get("listing_a"), "listing_a", where)
    b = _uuid(raw.get("listing_b"), "listing_b", where)
    if not a < b:
        raise ImportRefused(f"{where}: listing_a must sort before listing_b")
    order = raw.get("order")
    if order not in ORDERS:
        raise ImportRefused(f"{where}: order {order!r}")
    if raw.get("shown_as_a") is not None:
        if _uuid(raw["shown_as_a"], "shown_as_a", where) != (a if order == "ab" else b):
            raise ImportRefused(f"{where}: shown_as_a disagrees with order {order}")
    p = raw.get("p")
    if isinstance(p, bool) or not isinstance(p, int | float) or not 0 <= p <= 1:
        raise ImportRefused(f"{where}: p {p!r} is not a probability")
    extra = raw.get("extra") or {}
    if not isinstance(extra, dict):
        raise ImportRefused(f"{where}: extra is not an object")
    extra = dict(extra)
    if raw.get("source"):
        extra["source"] = raw["source"]
    return Line(
        number=number,
        file=file,
        stage=stage,
        listing_a=a,
        listing_b=b,
        order=order,
        p=float(p),
        request_sha256=_bytes(raw.get("request_sha256"), "request_sha256", where),
        content_sha256_a=_bytes(raw.get("content_sha256_a"), "content_sha256_a", where),
        content_sha256_b=_bytes(raw.get("content_sha256_b"), "content_sha256_b", where),
        extra=extra,
        seconds=raw.get("seconds"),
        device=raw.get("device"),
        dtype=raw.get("dtype"),
        threads=raw.get("threads"),
        scored_at=_time(raw.get("scored_at"), where),
    )


def read_lines(directory: Path) -> list[Line]:
    """Every `scores-*.jsonl` line in `directory`, checked; refuses on the first bad one."""
    files = sorted(directory.glob("scores-*.jsonl"))
    if not files:
        raise ImportRefused(f"no scores-*.jsonl in {directory}")
    out = []
    for path in files:
        with path.open(encoding="utf-8") as handle:
            for number, text in enumerate(handle, 1):
                if not text.strip():
                    continue
                where = f"{path.name}:{number}"
                try:
                    raw = json.loads(text)
                except json.JSONDecodeError:
                    raise ImportRefused(f"{where}: not JSON") from None
                out.append(parse_line(raw, where, path.name, number))
    return out


async def judges_for(session: AsyncSession) -> dict[str, int]:
    """Each `match` stage's judge id, created as a stage creates it."""
    return {s.name: await triggers.model_version_id(session, s) for s in pipeline(PIPELINE).stages}


def fresh_lines(lines: Sequence[Line], shown: dict[uuid.UUID, Shown], report: Report) -> list[Line]:
    """The lines whose request is what the renderer produces now; the rest counted,
    with the pairs and listings involved."""
    cache: dict[tuple[str, uuid.UUID, uuid.UUID], dict[str, bytes]] = {}
    keep = []
    stale_pairs: set[tuple] = set()
    involved: set[uuid.UUID] = set()
    for line in lines:
        report.by_model[line.stage.model] += 1
        if line.listing_a not in shown or line.listing_b not in shown:
            report.missing_listing += 1
            report.stale[line.stage.model] += 1
            stale_pairs.add(line.pair)
            involved.update(x for x in line.pair if x not in shown)
            continue
        key = (line.stage.name, line.listing_a, line.listing_b)
        if key not in cache:
            cache[key] = render(line.stage, shown[line.listing_a], shown[line.listing_b]).sha256
        a_moved = shown[line.listing_a].content_sha256 != line.content_sha256_a
        b_moved = shown[line.listing_b].content_sha256 != line.content_sha256_b
        if cache[key][line.order] != line.request_sha256:
            report.stale[line.stage.model] += 1
            stale_pairs.add(line.pair)
            moved = [x for x, m in ((line.listing_a, a_moved), (line.listing_b, b_moved)) if m]
            involved.update(moved or line.pair)
            continue
        if a_moved or b_moved:
            # Same request, so the judge saw exactly this; only a field no
            # prompt shows (the Arabic title under an English one) moved.
            report.content_hash_differs += 1
        keep.append(line)
    report.stale_pairs = len(stale_pairs)
    report.stale_listings = sorted(str(x) for x in involved)
    return keep


async def count_stranded(
    session: AsyncSession, shown: dict[uuid.UUID, Shown], report: Report
) -> None:
    """Of the stale listings still present, those whose current text the candidates
    trigger has already recorded, so it will not offer them; all of them when the
    trigger has recorded nothing yet (its first run records and offers nothing)."""
    ids = [uuid.UUID(x) for x in report.stale_listings if uuid.UUID(x) in shown]
    if not ids:
        return
    if not await session.scalar(select(func.count()).select_from(AiListingState)):
        report.stranded_listings = len(ids)
        return
    states: dict[uuid.UUID, bytes | None] = {}
    for start in range(0, len(ids), _LOOKUP):
        rows = await session.execute(
            select(AiListingState.listing_id, AiListingState.candidates_sha256).where(
                AiListingState.listing_id.in_(ids[start : start + _LOOKUP])
            )
        )
        states.update(dict(rows.all()))
    for x in ids:
        recorded = states.get(x)
        if recorded is not None and recorded == shown[x].content_sha256:
            report.stranded_listings += 1


async def _stored(
    session: AsyncSession, keys: Sequence[tuple[int, bytes]]
) -> dict[tuple[int, bytes], tuple[float, dict | None, datetime | None]]:
    """Stored scores by (judge, request hash): p, extra, scored_at."""
    out = {}
    ordered = sorted(set(keys))
    for start in range(0, len(ordered), _LOOKUP):
        rows = await session.execute(
            select(
                AiScore.model_version_id,
                AiScore.request_sha256,
                AiScore.p,
                AiScore.extra,
                AiScore.scored_at,
            ).where(
                tuple_(AiScore.model_version_id, AiScore.request_sha256).in_(
                    ordered[start : start + _LOOKUP]
                )
            )
        )
        for judge, digest, p, extra, scored_at in rows:
            out[(judge, digest)] = (p, extra, scored_at)
    return out


async def store_scores(
    session: AsyncSession, lines: Sequence[Line], judges: dict[str, int], report: Report
) -> None:
    """Insert the scores, idempotent on (judge, request hash). A request already
    stored keeps its row (and its p, which decisions then read)."""
    existing = await _stored(session, [(judges[x.stage.name], x.request_sha256) for x in lines])
    rows, seen = [], set()
    for line in lines:
        judge = judges[line.stage.name]
        if (judge, line.request_sha256) in seen:
            report.repeated_in_files += 1
            continue
        seen.add((judge, line.request_sha256))
        held = existing.get((judge, line.request_sha256))
        if held is not None:
            report.already_stored += 1
            if held[0] != line.p:
                report.already_stored_p_differs += 1
            continue
        row = {
            "model_version_id": judge,
            "listing_a": line.listing_a,
            "listing_b": line.listing_b,
            "reading_order": line.order,
            "request_sha256": line.request_sha256,
            "content_sha256_a": line.content_sha256_a,
            "content_sha256_b": line.content_sha256_b,
            "p": line.p,
            "extra": line.extra or None,
            "seconds": line.seconds,
            "device": line.device,
            "dtype": line.dtype,
            "threads": line.threads,
        }
        if line.scored_at is not None:
            row["scored_at"] = line.scored_at
        rows.append(row)
    # Rows with and without scored_at cannot share one multi-row VALUES.
    for has_time in (True, False):
        part = [r for r in rows if ("scored_at" in r) == has_time]
        for start in range(0, len(part), _INSERT_BATCH):
            batch = part[start : start + _INSERT_BATCH]
            result = await session.execute(
                insert(AiScore)
                .values(batch)
                .on_conflict_do_nothing(constraint="uq_ai_score_request")
                .returning(AiScore.id)
            )
            inserted = len(result.all())
            report.inserted += inserted
            # Stored meanwhile by someone else (a broker result): theirs stands.
            report.already_stored += len(batch) - inserted
    await session.flush()


async def _standing(
    session: AsyncSession, keys: Sequence[tuple[uuid.UUID, uuid.UUID]]
) -> tuple[dict[tuple, AiDecision], set[tuple]]:
    """Standing decisions, and pairs with a revoked one, among `keys`."""
    standing: dict[tuple, AiDecision] = {}
    revoked: set[tuple] = set()
    for start in range(0, len(keys), _LOOKUP):
        chunk = list(keys[start : start + _LOOKUP])
        rows = await session.scalars(
            select(AiDecision).where(
                AiDecision.pipeline == PIPELINE,
                AiDecision.state.in_((STANDING, REVOKED)),
                tuple_(AiDecision.listing_a, AiDecision.listing_b).in_(chunk),
            )
        )
        for row in rows:
            key = (row.listing_a, row.listing_b)
            if row.state == STANDING:
                standing[key] = row
            else:
                revoked.add(key)
    return standing, revoked


async def _steps(
    session: AsyncSession,
    keys: Sequence[tuple[uuid.UUID, uuid.UUID]],
    shown: dict[uuid.UUID, Shown],
    all_judges: flow.Judges,
) -> dict[tuple, tuple]:
    """Each pair's (step, current scores) from what is stored now."""
    current = await flow.scores_for(session, [(PIPELINE, a, b) for a, b in keys], shown, all_judges)
    return {(a, b): (transition(PIPELINE, s.scores, ACTIVE), s) for (_, a, b), s in current.items()}


def _check_policy(policy: str) -> None:
    if policy != ACTIVE:
        raise ImportRefused(
            f"the run was approved under policy {policy!r} but the code's active policy is "
            f"{ACTIVE!r}: decisions are written under the active one"
        )


def _not_decided(report: Report, step) -> None:
    """Count a pair `transition` does not decide: owing a stage it has fresh
    scores up to, or with no fresh score at all (stale, unscored, listing gone)."""
    if step is not None and step.mins:
        report.owes[step.stage] += 1
    else:
        report.unsettled += 1


def _recommend(report: Report) -> None:
    why = []
    if report.stale_listings:
        why.append(
            f"{len(report.stale_listings)} listing(s) changed since the run, "
            f"{report.stranded_listings} of them stranded"
        )
    if report.unsettled:
        why.append(f"{report.unsettled} pair(s) with no fresh score")
    for stage, n in sorted(report.owes.items()):
        why.append(f"{n} pair(s) owing the {stage} stage")
    if why:
        report.recommendation = RECOMMEND_BACKLOG.format(why="; ".join(why))


async def import_scores(
    directory: Path,
    *,
    dry_run: bool = False,
    policy: str = "p2",
    chunk: int = CHUNK,
    log=print,
) -> Report:
    """Steps 1 to 5 of the module docstring; `dry_run` rolls back and writes no decision."""
    _check_policy(policy)
    lines = read_lines(directory)
    report = Report(lines=len(lines))
    keys = sorted({line.pair for line in lines})
    report.pairs = len(keys)
    log(f"{len(lines)} lines, {len(keys)} pairs: all match the code's judges")
    async with SessionLocal() as session:
        judges = await judges_for(session)
        all_judges = await flow.current_judges(session)
        shown = await load_shown(session, {x for key in keys for x in key})
        fresh = fresh_lines(lines, shown, report)
        await count_stranded(session, shown, report)
        log(
            f"{len(fresh)} lines fresh, {sum(report.stale.values())} stale "
            f"({report.stale_pairs} pairs, {len(report.stale_listings)} listings); storing scores"
        )
        await store_scores(session, fresh, judges, report)
        overrides = await load_overrides(session)
        steps = await _steps(session, keys, shown, all_judges)
        standing, revoked = await _standing(session, keys)
        report.revoked_pairs = len(revoked)
        settled = []
        for key in keys:
            if overrides.kind(*key) is not None:
                report.ruled += 1
                continue
            step = steps.get(key, (None,))[0]
            if step is None or step.action != DECIDE:
                _not_decided(report, step)
                continue
            settled.append(key)
            report.planned[step.outcome] += 1
            report.planned_by[step.decided_by] += 1
            before = standing.get(key)
            if before is None:
                report.previous["new"] += 1
            elif before.outcome == step.outcome:
                report.previous["same_outcome"] += 1
            else:
                report.previous[f"{before.outcome}_to_{step.outcome}"] += 1
        _recommend(report)
        if dry_run:
            await session.rollback()
            log("dry run: rolled back")
            return report
        await session.commit()
        log(f"scores committed; deciding {len(settled)} pairs in chunks of {chunk}")
        for start in range(0, len(settled), chunk):
            batch = settled[start : start + chunk]
            # What `flow.advance` does for a pair it decides, counted per pair.
            batch_shown = await load_shown(session, {x for key in batch for x in key})
            current = await flow.scores_for(
                session, [(PIPELINE, a, b) for a, b in batch], batch_shown, all_judges
            )
            for a, b in batch:
                scores = current.get((PIPELINE, a, b))
                step = transition(PIPELINE, scores.scores, ACTIVE) if scores else None
                if step is None or step.action != DECIDE:
                    _not_decided(report, step)  # changed since it was planned
                    continue
                row = await flow.write_decision(session, PIPELINE, a, b, step, scores)
                if row is flow.BLOCKED:
                    report.blocked_by_revocation += 1
                elif row is None:
                    report.listing_gone += 1
                else:
                    report.written[row.outcome] += 1
                    report.written_by[row.decided_by] += 1
            await session.commit()
            if (start // chunk) % 20 == 0:
                log(f"  {start + len(batch)}/{len(settled)} decided")
    return report


def _from_file(extra: dict | None, scored_at: datetime | None, line: Line) -> bool:
    """Whether a stored score row is the one this import wrote from `line`."""
    if (extra or {}).get("source") != line.extra.get("source"):
        return False
    return line.scored_at is None or scored_at == line.scored_at


async def verify(directory: Path, *, policy: str = "p2") -> Report:
    """What `--verify` checks; changes nothing."""
    _check_policy(policy)
    lines = read_lines(directory)
    report = Report(lines=len(lines))
    keys = sorted({line.pair for line in lines})
    report.pairs = len(keys)
    async with SessionLocal() as session:
        judges = await judges_for(session)
        all_judges = await flow.current_judges(session)
        shown = await load_shown(session, {x for key in keys for x in key})
        fresh = fresh_lines(lines, shown, report)
        stored = await _stored(session, [(judges[x.stage.name], x.request_sha256) for x in fresh])
        for line in fresh:
            held = stored.get((judges[line.stage.name], line.request_sha256))
            if held is None:
                report.mismatches.append(f"{line.file}:{line.number}: score not stored")
                continue
            p, extra, scored_at = held
            if p == line.p:
                continue
            if _from_file(extra, scored_at, line):
                report.mismatches.append(f"{line.file}:{line.number}: stored p {p} != {line.p}")
            else:
                # Stored before the import, from elsewhere: that row is the score.
                report.held_before_import_p_differs += 1
        overrides = await load_overrides(session)
        steps = await _steps(session, keys, shown, all_judges)
        standing, revoked = await _standing(session, keys)
        report.revoked_pairs = len(revoked)
        for key in keys:
            if overrides.kind(*key) is not None:
                report.ruled += 1
                continue
            step, scores = steps.get(key, (None, None))
            if step is None or step.action != DECIDE:
                _not_decided(report, step)
                continue
            report.planned[step.outcome] += 1
            row = standing.get(key)
            if row is None:
                evidence = {n: {**scores.evidence[n], "min": low} for n, low in step.mins}
                if key in revoked and await flow.revocation_stands(
                    session, PIPELINE, key[0], key[1], evidence
                ):
                    report.blocked_by_revocation += 1
                else:
                    report.mismatches.append(f"{key[0]} {key[1]}: no standing decision")
                continue
            problems = []
            if row.outcome != step.outcome or row.decided_by != step.decided_by:
                problems.append(f"outcome {row.outcome}/{row.decided_by}")
            if row.policy_version != ACTIVE:
                problems.append(f"policy {row.policy_version}")
            for name, low in step.mins:
                entry = (row.scores or {}).get(name) or {}
                if entry.get("min") != low:
                    problems.append(f"{name} min {entry.get('min')} != {low}")
                if entry.get("requests") != scores.evidence[name]["requests"]:
                    problems.append(f"{name} request hashes differ")
            if problems:
                report.mismatches.append(f"{key[0]} {key[1]}: " + "; ".join(problems))
            else:
                report.written[row.outcome] += 1
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worker.ai_import", description=__doc__.split("\n")[0])
    add_arguments(parser)
    return parser


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("directory", type=Path, help="the folder holding scores-*.jsonl")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report, then roll back")
    mode.add_argument("--verify", action="store_true", help="check what is stored; change nothing")
    parser.add_argument("--policy", default="p2", help="the policy the run was approved under")


async def main(args: argparse.Namespace) -> int:
    try:
        if args.verify:
            report = await verify(args.directory, policy=args.policy)
        else:
            report = await import_scores(args.directory, dry_run=args.dry_run, policy=args.policy)
    except ImportRefused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    print(json.dumps(report.as_dict(), indent=1, default=str))
    if report.recommendation:
        print(f"recommendation: {report.recommendation}")
    return 1 if report.mismatches else 0


def run(argv: Iterable[str] | None = None) -> int:
    return asyncio.run(main(_parser().parse_args(None if argv is None else list(argv))))


if __name__ == "__main__":
    sys.exit(run())
