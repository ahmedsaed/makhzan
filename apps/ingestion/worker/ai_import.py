"""Import a locally scored AI backlog: its scores, then the decisions they make.

    python -m worker.ai_import DIR [--dry-run | --verify] [--policy p1]
    python -m worker.ai import DIR ...            # the same, from the AI command

`DIR` holds `scores-*.jsonl`, one line per scored request, as the backlog
driver writes them (`listing_a` < `listing_b`, `order`, `shown_as_a`, `p`,
`model`, `model_version`, `weights_revision`, `prompt_variant`,
`prompt_version`, `request_sha256`, `content_sha256_a`/`_b`, `hash_version`,
device, dtype, `scored_at`, `source`). The same import serves a local preview
copy and, once the owner has reviewed the groupings, production (P4).

What it does, in order:

1. **Checks every line against the code**: its model's version and weights
   revision are `policy.MODELS`'s, its prompt version is
   `prompt.PROMPT_VERSIONS`'s for a stage of `match`, its hash version is
   `hashing.HASH_VERSION`, and its order agrees with `shown_as_a`. Any
   mismatch refuses the whole import: scores of another judge are not this
   judge's, whatever their numbers.
2. **Creates the judges** (`ai_model_versions`) the way a stage does on first
   use (`triggers.model_version_id`), so the rows match `policy.py`.
3. **Re-renders each request from the listing as it is now**
   (`render.load_shown`, `render.render`) and keeps the line only when its
   `request_sha256` is what the committed renderer produces. A line whose
   listing's text changed since the run (or whose listing is gone) is
   skipped and counted: its score answers a request nobody would send now.
4. **Inserts the scores**, idempotently on (judge, `request_sha256`)
   (`uq_ai_score_request`): a re-run, or a request two pairs share
   byte-for-byte, stores one row.
5. **Decides through the pipeline's own code**: every pair whose stages are
   all scored for its current text goes through `flow.advance` and so
   `flow.write_decision`, under the active policy, exactly as the broker's
   result handling would (evidence with request hashes, current content
   hashes, a person's revocation holding). Pairs left owing a stage (their
   text changed) are counted and not queued: in production, their listings'
   changed text is the candidates trigger's to pick up.

Decisions are committed in chunks (`CHUNK` pairs): each takes a
transaction-scoped advisory lock, and one transaction over the whole backlog
would exhaust the lock table. A run cut off part-way is resumed by running it
again; everything above is idempotent.

`--dry-run` does steps 1 to 4 inside one transaction, computes each pair's
step with `pipelines.transition` over the scores as they would be stored, and
rolls back: it reports what would be inserted and decided (and how that
differs from standing decisions) without `write_decision`'s writes, so a
pair a person revoked is reported as such rather than as blocked.

`--verify` changes nothing: every fresh line's score is stored under its
judge with the same p, and every pair whose stages are scored has a standing
decision under the active policy with the outcome, stage minimums and
request hashes the stored scores give. Exit 1 on any mismatch.

`--policy` names the policy the run was approved under (`p1`); the import
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
from makhzan_schemas.models import AiDecision, AiScore
from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

#: The pipeline backlog pairs belong to.
PIPELINE = "match"
#: Pairs per committed decision chunk (one advisory lock each).
CHUNK = 500
#: Score rows per INSERT: 14 parameters each, inside asyncpg's 32767.
_INSERT_BATCH = 2000
ORDERS = ("ab", "ba")


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
    scored_at: datetime | None

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
    inserted: int = 0
    already_stored: int = 0
    repeated_in_files: int = 0
    pairs: int = 0
    decided: Counter = field(default_factory=Counter)
    decided_by: Counter = field(default_factory=Counter)
    unsettled: int = 0
    previous: Counter = field(default_factory=Counter)
    revoked_pairs: int = 0
    blocked_by_revocation: int = 0
    mismatches: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "lines": self.lines,
            "lines_by_model": dict(self.by_model),
            "stale_lines_by_model": dict(self.stale),
            "lines_listing_missing": self.missing_listing,
            "lines_fresh_but_content_hash_differs": self.content_hash_differs,
            "scores_inserted": self.inserted,
            "scores_already_stored": self.already_stored,
            "lines_repeating_a_request": self.repeated_in_files,
            "pairs": self.pairs,
            "decisions": dict(self.decided),
            "decided_by_stage": dict(self.decided_by),
            "pairs_unsettled_stale": self.unsettled,
            "against_standing": dict(self.previous),
            "pairs_with_a_revoked_decision": self.revoked_pairs,
            "blocked_by_revocation": self.blocked_by_revocation,
            "mismatches": len(self.mismatches),
            "first_mismatches": self.mismatches[:20],
        }


def _stages() -> dict[tuple[str, str], Stage]:
    """The `match` stages by (model key, prompt variant)."""
    return {(s.model, s.prompt): s for s in pipeline(PIPELINE).stages}


def _bytes(value: str, what: str, where: str) -> bytes:
    try:
        raw = bytes.fromhex(value)
    except (TypeError, ValueError):
        raise ImportRefused(f"{where}: {what} is not hex") from None
    if len(raw) != 32:
        raise ImportRefused(f"{where}: {what} is not a sha256")
    return raw


def parse_line(raw: dict, where: str, file: str = "", number: int = 0) -> Line:
    """One line, checked against the registry; raises `ImportRefused`."""
    stages = _stages()
    model = MODELS.get(raw.get("model"))
    if model is None:
        raise ImportRefused(f"{where}: unknown model {raw.get('model')!r}")
    if raw.get("model_version") != model.model_version:
        raise ImportRefused(
            f"{where}: model version {raw.get('model_version')!r} is not the code's "
            f"{model.model_version!r}"
        )
    if raw.get("weights_revision", model.weights_revision) != model.weights_revision:
        raise ImportRefused(f"{where}: weights revision is not the code's")
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
    try:
        a, b = uuid.UUID(raw["listing_a"]), uuid.UUID(raw["listing_b"])
    except (KeyError, TypeError, ValueError):
        raise ImportRefused(f"{where}: listing ids missing or malformed") from None
    if not a < b:
        raise ImportRefused(f"{where}: listing_a must sort before listing_b")
    order = raw.get("order")
    if order not in ORDERS:
        raise ImportRefused(f"{where}: order {order!r}")
    shown_a = raw.get("shown_as_a")
    if shown_a is not None and uuid.UUID(shown_a) != (a if order == "ab" else b):
        raise ImportRefused(f"{where}: shown_as_a disagrees with order {order}")
    p = raw.get("p")
    if not isinstance(p, int | float) or not 0 <= p <= 1:
        raise ImportRefused(f"{where}: p {p!r} is not a probability")
    extra = dict(raw.get("extra") or {})
    if raw.get("source"):
        extra["source"] = raw["source"]
    scored_at = raw.get("scored_at")
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
        scored_at=datetime.fromisoformat(scored_at) if scored_at else None,
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
    """The lines whose request is what the renderer produces now; the rest counted."""
    cache: dict[tuple[str, uuid.UUID, uuid.UUID], dict[str, bytes]] = {}
    keep = []
    for line in lines:
        report.by_model[line.stage.model] += 1
        if line.listing_a not in shown or line.listing_b not in shown:
            report.missing_listing += 1
            report.stale[line.stage.model] += 1
            continue
        key = (line.stage.name, line.listing_a, line.listing_b)
        if key not in cache:
            cache[key] = render(line.stage, shown[line.listing_a], shown[line.listing_b]).sha256
        if cache[key][line.order] != line.request_sha256:
            report.stale[line.stage.model] += 1
            continue
        if (
            shown[line.listing_a].content_sha256 != line.content_sha256_a
            or shown[line.listing_b].content_sha256 != line.content_sha256_b
        ):
            # Same request, so the judge saw exactly this; only a field no
            # prompt shows (the Arabic title under an English one) moved.
            report.content_hash_differs += 1
        keep.append(line)
    return keep


async def store_scores(
    session: AsyncSession, lines: Sequence[Line], judges: dict[str, int], report: Report
) -> None:
    """Insert the scores, idempotent on (judge, request hash)."""
    rows, seen = [], set()
    for line in lines:
        judge = judges[line.stage.name]
        if (judge, line.request_sha256) in seen:
            report.repeated_in_files += 1
            continue
        seen.add((judge, line.request_sha256))
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
            report.already_stored += len(batch) - inserted
    await session.flush()


async def _standing(
    session: AsyncSession, keys: Sequence[tuple[uuid.UUID, uuid.UUID]]
) -> tuple[dict[tuple, AiDecision], set[tuple]]:
    """Standing decisions, and pairs with a revoked one, among `keys`."""
    standing: dict[tuple, AiDecision] = {}
    revoked: set[tuple] = set()
    for start in range(0, len(keys), 5000):
        chunk = list(keys[start : start + 5000])
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


async def import_scores(
    directory: Path, *, dry_run: bool = False, policy: str = "p1", chunk: int = CHUNK, log=print
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
        log(f"{len(fresh)} lines fresh, {sum(report.stale.values())} stale; storing scores")
        await store_scores(session, fresh, judges, report)
        steps = await _steps(session, keys, shown, all_judges)
        standing, revoked = await _standing(session, keys)
        report.revoked_pairs = len(revoked & set(keys))
        settled = []
        for key in keys:
            step = steps.get(key, (None,))[0]
            if step is None or step.action != DECIDE:
                report.unsettled += 1
                continue
            settled.append(key)
            report.decided[step.outcome] += 1
            report.decided_by[step.decided_by] += 1
            before = standing.get(key)
            if before is None:
                report.previous["new"] += 1
            elif before.outcome == step.outcome:
                report.previous["same_outcome"] += 1
            else:
                report.previous[f"{before.outcome}_to_{step.outcome}"] += 1
        if dry_run:
            await session.rollback()
            log("dry run: rolled back")
            return report
        await session.commit()
        log(f"scores committed; deciding {len(settled)} pairs in chunks of {chunk}")
        for start in range(0, len(settled), chunk):
            batch = [
                triggers.PairRequest(a, b, PIPELINE, triggers.BACKLOG, "backlog")
                for a, b in settled[start : start + chunk]
            ]
            counts = await flow.advance(session, batch, judges=all_judges)
            if counts["queued"] or counts["missing"]:
                raise RuntimeError(f"a settled pair was not decided: {counts}")
            report.blocked_by_revocation += counts["revoked_blocked"]
            await session.commit()
            if (start // chunk) % 20 == 0:
                log(f"  {start + len(batch)}/{len(settled)} decided")
    return report


async def verify(directory: Path, *, policy: str = "p1") -> Report:
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
        stored: dict[tuple[int, bytes], float] = {}
        wanted = sorted({(judges[x.stage.name], x.request_sha256) for x in fresh})
        for start in range(0, len(wanted), 5000):
            part = wanted[start : start + 5000]
            rows = await session.execute(
                select(AiScore.model_version_id, AiScore.request_sha256, AiScore.p).where(
                    tuple_(AiScore.model_version_id, AiScore.request_sha256).in_(part)
                )
            )
            stored.update({(j, d): p for j, d, p in rows})
        for line in fresh:
            got = stored.get((judges[line.stage.name], line.request_sha256))
            if got is None:
                report.mismatches.append(f"{line.file}:{line.number}: score not stored")
            elif got != line.p:
                report.mismatches.append(f"{line.file}:{line.number}: stored p {got} != {line.p}")
        steps = await _steps(session, keys, shown, all_judges)
        standing, _ = await _standing(session, keys)
        for key in keys:
            step, scores = steps.get(key, (None, None))
            if step is None or step.action != DECIDE:
                report.unsettled += 1
                continue
            report.decided[step.outcome] += 1
            row = standing.get(key)
            if row is None:
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
    parser.add_argument("--policy", default="p1", help="the policy the run was approved under")


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
    return 1 if report.mismatches else 0


def run(argv: Iterable[str] | None = None) -> int:
    return asyncio.run(main(_parser().parse_args(None if argv is None else list(argv))))


if __name__ == "__main__":
    sys.exit(run())
