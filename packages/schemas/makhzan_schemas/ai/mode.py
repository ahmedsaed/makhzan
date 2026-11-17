"""Whether the regroup acts on AI decisions: the `ai_matching` key in `worker_state`.

The mode governs one thing only: whether the regroup reads decisions. Scoring
goes on in either mode (the broker leases jobs and accepts results, and
decisions are written), so the backlog can be scored while off and previewed.

- `off` (the default): the regroup does not read decisions.
  `make regroup-dry-run ARGS=--ai` shows what reading them would do, which is
  how the backlog's groupings are reviewed on a local copy before they reach
  production (owner decision P4, 2026-11-17).
- `live`: the regroup reads standing "same" decisions
  (`decisions.load_ai_same`), and the broker's rebuild-after-a-window (P16)
  is armed.

Stored as `{"mode": "<mode>"}`. A missing row, or one that names no known mode,
reads as `off`: nothing merges on an AI decision until someone says `live`.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.models import WorkerState

MODE_KEY = "ai_matching"
OFF, LIVE = "off", "live"
MODES = (OFF, LIVE)
DEFAULT_MODE = OFF


async def ai_mode(session: AsyncSession) -> str:
    """The mode in force; `off` when none was ever set."""
    state = await session.get(WorkerState, MODE_KEY)
    value = state.value if state is not None and isinstance(state.value, dict) else {}
    mode = value.get("mode")
    return mode if mode in MODES else DEFAULT_MODE


async def set_ai_mode(session: AsyncSession, mode: str) -> None:
    """Set the mode (flushed, not committed). Takes effect at the next regroup."""
    if mode not in MODES:
        raise ValueError(f"an AI matching mode is {' or '.join(MODES)}, not {mode!r}")
    value = {"mode": mode}
    await session.execute(
        insert(WorkerState)
        .values(key=MODE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[WorkerState.key], set_={"value": value, "updated_at": func.now()}
        )
    )
    await session.flush()
