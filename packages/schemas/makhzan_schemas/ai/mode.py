"""Whether the regroup acts on AI decisions: the `ai_matching` key in `worker_state`.

- `off`: nothing is scored or read (the candidates job and the broker stand still).
- `shadow` (the default, decision P4): scores and decisions are recorded, marked
  `shadow`, and the regroup ignores them. `make regroup-dry-run ARGS=--ai`
  shows what going live would do.
- `live`: the regroup reads standing, non-shadow "same" decisions
  (`decisions.load_ai_same`).

Stored as `{"mode": "<mode>"}`. A missing row, or one that names no known mode,
reads as `shadow`: nothing merges until someone says `live`.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.models import WorkerState

MODE_KEY = "ai_matching"
OFF, SHADOW, LIVE = "off", "shadow", "live"
MODES = (OFF, SHADOW, LIVE)
DEFAULT_MODE = SHADOW


async def ai_mode(session: AsyncSession) -> str:
    """The mode in force; `shadow` when none was ever set."""
    state = await session.get(WorkerState, MODE_KEY)
    value = state.value if state is not None and isinstance(state.value, dict) else {}
    mode = value.get("mode")
    return mode if mode in MODES else DEFAULT_MODE


async def set_ai_mode(session: AsyncSession, mode: str) -> None:
    """Set the mode (flushed, not committed). Takes effect at the next regroup."""
    if mode not in MODES:
        raise ValueError(f"an AI matching mode is {', '.join(MODES)}, not {mode!r}")
    value = {"mode": mode}
    await session.execute(
        insert(WorkerState)
        .values(key=MODE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[WorkerState.key], set_={"value": value, "updated_at": func.now()}
        )
    )
    await session.flush()
