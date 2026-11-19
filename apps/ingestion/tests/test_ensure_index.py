"""`python -m worker.ensure_index`: the deploy's migrate step applies the
search index settings before the API starts, waiting for Meilisearch."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import arq
import meilisearch
from makhzan_schemas import rebuild as _rebuild
from worker import ensure_index as mod


def test_it_waits_for_meilisearch_then_applies_the_settings(monkeypatch):
    calls = []

    def flaky(client):
        calls.append(client)
        if len(calls) < 3:
            raise meilisearch.errors.MeilisearchCommunicationError("not up yet")

    monkeypatch.setattr(mod, "ensure_index", flaky)
    monkeypatch.setattr(mod, "get_client", lambda: "client")
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    assert mod.main() == 0
    assert len(calls) == 3


def test_it_fails_the_deploy_if_meilisearch_never_answers(monkeypatch):
    def down(client):
        raise meilisearch.errors.MeilisearchCommunicationError("down")

    monkeypatch.setattr(mod, "ensure_index", down)
    monkeypatch.setattr(mod, "get_client", lambda: "client")
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    assert mod.main() == 1


def _applied(monkeypatch, changed: bool) -> list[str]:
    monkeypatch.setattr(mod, "ensure_index", lambda client: changed)
    monkeypatch.setattr(mod, "get_client", lambda: "client")
    queued: list[str] = []

    async def enqueue():
        queued.append("rebuild")
        return "rebuild:1"

    monkeypatch.setattr(mod, "enqueue_rebuild", enqueue)
    return queued


def test_changed_searchable_attributes_queue_a_reindex(monkeypatch, capsys):
    """The indexed documents lack what the new attributes search until a
    reindex fills them; the deploy queues one rather than waiting for a crawl."""
    queued = _applied(monkeypatch, changed=True)
    assert mod.main() == 0
    assert queued == ["rebuild"]
    assert "queued rebuild:1" in capsys.readouterr().out


def test_unchanged_settings_queue_nothing(monkeypatch):
    queued = _applied(monkeypatch, changed=False)
    assert mod.main() == 0
    assert queued == []


def test_a_rebuild_already_queued_is_not_an_error(monkeypatch, capsys):
    _applied(monkeypatch, changed=True)

    async def deduplicated():
        return None

    monkeypatch.setattr(mod, "enqueue_rebuild", deduplicated)
    assert mod.main() == 0
    assert "already queued" in capsys.readouterr().out


def test_redis_down_leaves_a_note_and_the_deploy_goes_on(monkeypatch, capsys):
    """Search works with the new settings; only the fill waits. Failing the
    deploy over it would cost more than it saves."""
    _applied(monkeypatch, changed=True)

    async def down():
        raise ConnectionError("redis down")

    monkeypatch.setattr(mod, "enqueue_rebuild", down)
    assert mod.main() == 0
    err = capsys.readouterr().err
    assert "make reindex" in err and "redis down" in err


def test_a_settings_task_that_outlasts_the_wait_fails_the_deploy(monkeypatch, capsys):
    """The new API's queries name the new attributes and would be rejected until
    the settings land; the running one keeps working. So stop here, clearly."""

    def slow(client):
        raise meilisearch.errors.MeilisearchTimeoutError("task 42 still processing")

    monkeypatch.setattr(mod, "ensure_index", slow)
    monkeypatch.setattr(mod, "get_client", lambda: "client")
    monkeypatch.setattr(mod.time, "sleep", lambda seconds: None)
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "not applied within 300 s" in err and "task 42" in err


class FakePool:
    def __init__(self, queued: bool = True) -> None:
        self.calls: list[tuple] = []
        self.closed = False
        self.queued = queued

    async def enqueue_job(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return object() if self.queued else None

    async def aclose(self) -> None:
        self.closed = True


def _pool(monkeypatch, pool: FakePool) -> FakePool:
    async def create_pool(settings):
        return pool

    monkeypatch.setattr(arq, "create_pool", create_pool)
    return pool


def _window_start(offset_seconds: int) -> datetime:
    window = _rebuild.REBUILD_WINDOW
    start = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
    start -= timedelta(seconds=int(start.timestamp()) % window)
    return start + timedelta(seconds=offset_seconds)


def test_enqueue_rebuild_queues_this_windows_rebuild(monkeypatch):
    """The window's own id and end, so it is the rebuild every source finishing
    in the window shares."""
    pool = _pool(monkeypatch, FakePool())
    now = _window_start(10)

    assert asyncio.run(mod.enqueue_rebuild(now)) == _rebuild.rebuild_job_id(now)[0]

    job_id, runs_at = _rebuild.rebuild_job_id(now)
    assert pool.calls == [
        (_rebuild.REBUILD_FUNCTION, (), {"_job_id": job_id, "_defer_until": runs_at})
    ]
    assert pool.closed


def test_near_a_windows_end_it_queues_the_next_one(monkeypatch):
    """Due within MIN_LEAD, the rebuild could run on the old worker before the
    deploy recreates it, and its reindex would put back the old settings."""
    pool = _pool(monkeypatch, FakePool())
    window = _rebuild.REBUILD_WINDOW
    now = _window_start(window - 30)
    this_id, this_end = _rebuild.rebuild_job_id(now)
    next_id, next_end = _rebuild.rebuild_job_id(now + timedelta(seconds=window))

    assert asyncio.run(mod.enqueue_rebuild(now)) == next_id

    assert next_id != this_id
    assert next_end - this_end == timedelta(seconds=window)
    assert pool.calls == [
        (_rebuild.REBUILD_FUNCTION, (), {"_job_id": next_id, "_defer_until": next_end})
    ]
    assert next_end - now >= mod.MIN_LEAD


def test_enqueue_rebuild_says_when_the_window_already_has_one(monkeypatch):
    _pool(monkeypatch, FakePool(queued=False))
    assert asyncio.run(mod.enqueue_rebuild(_window_start(10))) is None
