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
