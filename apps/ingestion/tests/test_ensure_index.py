"""`python -m worker.ensure_index`: the deploy's migrate step applies the
search index settings before the API starts, waiting for Meilisearch."""

from __future__ import annotations

import meilisearch
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
