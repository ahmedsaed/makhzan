"""The admin dashboard (apps/ingestion/admin): login, CSRF, and every action.

Driven in-process over an ASGI transport against the test session's real
Postgres, as the API suite is. Only the worker's queue is replaced: an action
that queues a job records the action id instead. The shops and listings are
fictional.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid
from decimal import Decimal

import httpx
import pytest
from admin import app as admin_app
from admin import auth
from makhzan_schemas import crawl
from makhzan_schemas.ai.mode import ai_mode
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import (
    AdminAction,
    AiDecision,
    AiFlag,
    AiWorker,
    GroupingOverride,
    IngestionRun,
    Listing,
    Report,
    Source,
    Supplier,
)
from sqlalchemy import select

PASSWORD = "correct horse battery staple"
#: A cheap scrypt for tests; production uses auth.SCRYPT_N.
HASH = auth.hash_password(PASSWORD, n=2**10)


@pytest.fixture
def queued(monkeypatch) -> list[int]:
    """The dashboard's environment, a fresh login limiter, and the queue replaced."""
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", HASH)
    monkeypatch.setenv("ADMIN_SECRET", "test-secret-" + "x" * 20)
    monkeypatch.setenv("ADMIN_NAME", "owner")
    # Health checks must fail fast, not wait on DNS for the compose names.
    monkeypatch.setenv("ADMIN_API_HEALTH_URL", "http://127.0.0.1:9/health")
    monkeypatch.setenv("ADMIN_BROKER_HEALTH_URL", "http://127.0.0.1:9/ai/v1/health")
    monkeypatch.setattr(admin_app, "limiter", auth.LoginLimiter())
    monkeypatch.setattr(admin_app, "VERIFY_SLOTS", asyncio.Semaphore(2))
    jobs: list[int] = []

    async def enqueue(action_id: int) -> None:
        jobs.append(action_id)

    monkeypatch.setattr(admin_app, "enqueue_admin_job", enqueue)
    return jobs


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=admin_app.app), base_url="http://admin.test"
    )


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


async def _login(client: httpx.AsyncClient, password: str = PASSWORD) -> httpx.Response:
    form = await client.get("/login")
    return await client.post("/login", data={"csrf": _csrf(form.text), "password": password})


async def _session(client: httpx.AsyncClient) -> str:
    """Log in; the CSRF token every POST needs."""
    assert (await _login(client)).status_code == 303
    page = await client.get("/activity")
    assert page.status_code == 200
    return _csrf(page.text)


async def _actions(action: str | None = None) -> list[AdminAction]:
    async with SessionLocal() as session:
        query = select(AdminAction).order_by(AdminAction.id)
        if action:
            query = query.where(AdminAction.action == action)
        return list(await session.scalars(query))


async def _accepted(action: str) -> list[AdminAction]:
    return [a for a in await _actions(action) if "refused" not in a.detail]


async def _refused(action: str) -> list[AdminAction]:
    return [a for a in await _actions(action) if "refused" in a.detail]


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


async def test_every_view_needs_a_session(queued):
    async with _client() as client:
        for path in ("/", "/crawl", "/catalog", "/reports", "/overrides", "/ai", "/activity"):
            response = await client.get(path)
            assert (response.status_code, response.headers["location"]) == (303, "/login")
        assert (await client.get("/jobs/1.json")).status_code == 401


async def test_the_right_password_signs_in_and_logout_signs_out(queued):
    async with _client() as client:
        response = await _login(client)
        assert response.status_code == 303
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert (await client.get("/")).status_code == 200
        csrf = _csrf((await client.get("/activity")).text)
        assert (await client.post("/logout", data={"csrf": csrf})).status_code == 303
        assert (await client.get("/")).status_code == 303
    assert [a.action for a in await _actions()] == ["login", "logout"]


async def test_a_wrong_password_is_refused_and_audited(queued):
    async with _client() as client:
        response = await _login(client, "not it")
        assert response.status_code == 401
        assert "Wrong password" in response.text
        assert (await client.get("/")).status_code == 303
    (failed,) = await _actions()
    assert (failed.action, failed.actor) == ("login.failed", "owner")


async def test_concurrent_bad_logins_are_all_counted_and_verified_two_at_a_time(
    queued, monkeypatch
):
    """Each check holds 128 MiB of scrypt: requests arriving together must neither
    slip past the limiter while the first are checked nor all run at once."""
    lock = threading.Lock()
    state = {"running": 0, "peak": 0, "calls": 0}

    def slow_verify(password, stored):
        with lock:
            state["running"] += 1
            state["calls"] += 1
            state["peak"] = max(state["peak"], state["running"])
        time.sleep(0.05)
        with lock:
            state["running"] -= 1
        return False

    monkeypatch.setattr(auth, "verify_password", slow_verify)
    async with _client() as client:
        token = _csrf((await client.get("/login")).text)
        responses = await asyncio.gather(
            *(client.post("/login", data={"csrf": token, "password": "guess"}) for _ in range(40))
        )
    codes = [r.status_code for r in responses]
    limit = auth.LoginLimiter.PER_CLIENT
    assert codes.count(401) == limit and codes.count(429) == 40 - limit
    assert state["calls"] == limit  # every attempt let through was counted first
    assert state["peak"] <= 2
    assert len(admin_app.limiter._by_client["127.0.0.1"]) == limit
    assert len(await _actions("login.failed")) == limit


async def test_a_successful_login_is_refunded(queued):
    async with _client() as client:
        assert (await _login(client, "guess")).status_code == 401
        assert (await _login(client)).status_code == 303
    assert admin_app.limiter.retry_after("127.0.0.1") == 0
    assert len(admin_app.limiter._all) == 1  # the failure; the success was taken back


async def test_logins_are_rate_limited_per_address(queued):
    async with _client() as client:
        for _ in range(auth.LoginLimiter.PER_CLIENT):
            assert (await _login(client, "guess")).status_code == 401
        # Refused even with the right password, until the window passes.
        limited = await _login(client)
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) > 0


def test_the_limiter_forgets_after_the_window_and_on_success():
    now = [0.0]
    limiter = auth.LoginLimiter(clock=lambda: now[0])
    for _ in range(limiter.PER_CLIENT):
        limiter.failed("a")
    assert limiter.retry_after("a") > 0
    assert limiter.retry_after("b") == 0
    now[0] += limiter.WINDOW + 1
    assert limiter.retry_after("a") == 0
    limiter.failed("a")
    limiter.succeeded("a")
    assert limiter.retry_after("a") == 0


async def test_a_login_without_its_form_token_is_refused(queued):
    async with _client() as client:
        response = await client.post("/login", data={"csrf": "made-up", "password": PASSWORD})
        assert response.status_code == 403
        assert (await client.get("/")).status_code == 303


async def test_unconfigured_nobody_signs_in(queued, monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD_HASH")
    async with _client() as client:
        assert (await _login(client)).status_code == 503


async def test_changing_the_password_ends_every_session(queued, monkeypatch):
    async with _client() as client:
        await _session(client)
        monkeypatch.setenv("ADMIN_PASSWORD_HASH", auth.hash_password("another one", n=2**10))
        assert (await client.get("/")).status_code == 303


def test_password_hashes_verify_and_tampered_sessions_do_not():
    assert auth.verify_password(PASSWORD, HASH)
    assert not auth.verify_password("nope", HASH)
    with pytest.raises(auth.HashUnusable):
        auth.verify_password(PASSWORD, "scrypt:broken")
    with pytest.raises(auth.HashUnusable):  # asks for more memory than allowed
        auth.verify_password(PASSWORD, "scrypt:1073741824:8:1:00:00")
    assert ":" in HASH and "$" not in HASH  # safe in .env and compose interpolation
    value, session = auth.new_session(HASH, "s", 1)
    assert auth.read_session(value, HASH, "s").csrf == session.csrf
    assert auth.read_session(value, HASH, "other secret") is None
    body, mac = value.rsplit(".", 1)
    assert auth.read_session(body + "." + "0" * len(mac), HASH, "s") is None


# --------------------------------------------------------------------------- #
# CSRF
# --------------------------------------------------------------------------- #


async def test_a_post_without_the_session_token_is_refused(queued):
    async with _client() as client:
        await _session(client)
        assert (await client.post("/crawl/pause", data={})).status_code == 403
        assert (await client.post("/crawl/pause", data={"csrf": "wrong"})).status_code == 403
    async with SessionLocal() as session:
        assert await crawl.crawl_pause(session) is None
    assert not await _actions("crawl.pause")


async def test_a_cross_origin_post_is_refused_even_with_the_token(queued):
    async with _client() as client:
        csrf = await _session(client)
        response = await client.post(
            "/crawl/pause", data={"csrf": csrf}, headers={"origin": "http://evil.test"}
        )
        assert response.status_code == 403


async def test_an_unusable_hash_says_so_instead_of_wrong_password(queued, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "scrypt:1073741824:8:1:00:00")
    async with _client() as client:
        response = await _login(client)
        assert response.status_code == 503
        assert "cannot be checked" in response.text and "Wrong password" not in response.text


async def test_large_bodies_are_refused_before_parsing(queued):
    big = "x" * (admin_app.MAX_BODY + 1)
    async with _client() as client:
        declared = await client.post("/login", content=f"password={big}")
        assert declared.status_code == 413

        async def chunks():
            for _ in range(3):
                yield b"x" * (admin_app.MAX_BODY // 2)

        # No Content-Length: the streamed read stops at the cap.
        streamed = await client.post("/login", content=chunks())
        assert streamed.status_code == 413
    assert not await _actions("login.failed")


async def test_the_host_allowlist(queued, monkeypatch):
    monkeypatch.setenv("ADMIN_ALLOWED_HOSTS", "100.64.0.1:8200, admin.tailnet")
    async with _client() as client:
        assert (await client.get("/login")).status_code == 400  # admin.test
        ok = await client.get("/login", headers={"host": "100.64.0.1:8200"})
        assert ok.status_code == 200
        named = await client.get("/login", headers={"host": "admin.tailnet:8200"})
        assert named.status_code == 200


async def test_a_post_without_a_session_is_refused(queued):
    async with _client() as client:
        assert (await client.post("/crawl/pause", data={"csrf": "x"})).status_code == 401


# --------------------------------------------------------------------------- #
# Fixtures for the actions
# --------------------------------------------------------------------------- #


async def _source(source_id: str = "shop-a", **kw) -> None:
    async with SessionLocal() as session:
        session.add(
            Source(
                source_id=source_id,
                adapter="fixture",
                supplier={"slug": source_id, "name": source_id},
                config={},
                **kw,
            )
        )
        await session.commit()


async def _listings(n: int, *, same_shop: bool = False) -> list[uuid.UUID]:
    ids = []
    async with SessionLocal() as session:
        shop = None
        for i in range(n):
            if shop is None or not same_shop:
                slug = f"shop-{uuid.uuid4().hex[:6]}"
                shop = Supplier(
                    id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED
                )
                session.add(shop)
            listing = Listing(
                id=uuid.uuid4(),
                supplier_id=shop.id,
                source=shop.slug,
                source_type=SourceType.SCRAPED,
                external_id=str(i),
                domain="electronics",
                title_en=f"example relay module {i}",
                price=Decimal("20"),
                images=[],
                attributes={},
            )
            session.add(listing)
            ids.append(listing.id)
        await session.commit()
    return ids


async def _report(reason: str, listings: list[tuple[uuid.UUID, bool]]) -> int:
    snapshot = {
        "product": {
            "title": "Example relay module",
            "listings": [
                {"id": str(i), "title": "relay", "shop": {"name": "a shop"}, "ticked": t}
                for i, t in listings
            ],
        }
    }
    row = Report(
        product_id=uuid.uuid4(),
        reason=reason,
        offer_ids=[str(i) for i, t in listings if t],
        snapshot=snapshot,
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
    return row.id


# --------------------------------------------------------------------------- #
# Crawl
# --------------------------------------------------------------------------- #


async def test_pausing_and_resuming_the_crawl(queued):
    async with _client() as client:
        csrf = await _session(client)
        r = await client.post("/crawl/pause", data={"csrf": csrf, "note": "host move"})
        assert r.status_code == 303
        async with SessionLocal() as session:
            pause = await crawl.crawl_pause(session)
            assert (pause["by"], pause["note"]) == ("owner", "host move")
            assert await crawl.crawl_enabled_in(session) is False
        page = await client.get("/crawl")
        assert "crawl paused by owner" in page.text
        assert (await client.post("/crawl/resume", data={"csrf": csrf})).status_code == 303
        async with SessionLocal() as session:
            assert await crawl.crawl_pause(session) is None
            assert await crawl.crawl_resumed_at(session) is not None
    actions = await _actions()
    assert [(a.action, a.actor, a.client) for a in actions[1:]] == [
        ("crawl.pause", "owner", "127.0.0.1"),
        ("crawl.resume", "owner", "127.0.0.1"),
    ]
    assert actions[1].detail == {"note": "host move"}


async def test_pausing_and_resuming_a_shop(queued):
    await _source("shop-a")
    async with _client() as client:
        csrf = await _session(client)
        await client.post("/shops/shop-a/pause", data={"csrf": csrf, "note": "403s"})
        async with SessionLocal() as session:
            row = await session.scalar(select(Source).where(Source.source_id == "shop-a"))
            assert (row.paused_by, row.pause_note) == ("owner", "403s")
        assert "paused by owner" in (await client.get("/crawl")).text
        await client.post("/shops/shop-a/resume", data={"csrf": csrf})
        async with SessionLocal() as session:
            row = await session.scalar(select(Source).where(Source.source_id == "shop-a"))
            assert row.paused_at is None
            assert row.resumed_at is not None  # the archive check's window restarts here
        assert (await client.post("/shops/nope/pause", data={"csrf": csrf})).status_code == 404
    assert [(a.action, a.target) for a in await _actions()][1:] == [
        ("shop.pause", "shop-a"),
        ("shop.resume", "shop-a"),
    ]


async def test_run_now_queues_an_ephemeral_job_and_checks_the_limit(queued):
    await _source("shop-a")
    async with _client() as client:
        csrf = await _session(client)
        r = await client.post("/shops/shop-a/run", data={"csrf": csrf, "limit": "10"})
        assert r.status_code == 303
        await client.post("/shops/shop-a/run", data={"csrf": csrf, "limit": "5000"})
        await client.post("/shops/shop-a/run", data={"csrf": csrf, "limit": "ten"})
    (job,) = await _accepted("job.run_limit")
    assert (job.target, job.detail, job.status) == ("shop-a", {"limit": 10}, "queued")
    assert [r.status for r in await _refused("job.run_limit")] == [None, None]
    assert queued == [job.id]


async def test_probe_queues_the_probe_for_one_shop(queued):
    await _source("shop-a", enabled=False)
    async with _client() as client:
        csrf = await _session(client)
        await client.post("/shops/shop-a/probe", data={"csrf": csrf})
        (job,) = await _actions("job.probe")
        assert (job.target, job.status) == ("shop-a", "queued")
        assert queued == [job.id]
        state = await client.get(f"/jobs/{job.id}.json")
        assert state.json() == {"id": job.id, "status": "queued", "error": None}


async def test_a_job_the_queue_refused_is_marked_failed(queued, monkeypatch):
    async def down(action_id):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(admin_app, "enqueue_admin_job", down)
    async with _client() as client:
        csrf = await _session(client)
        r = await client.post("/catalog/regroup-dry-run", data={"csrf": csrf})
        assert r.status_code == 503
    (job,) = await _actions("job.regroup_dry_run")
    assert job.status == "failed" and "redis is down" in job.error


async def test_regroup_dry_run_is_queued_never_run_here(queued):
    async with _client() as client:
        csrf = await _session(client)
        await client.post("/catalog/regroup-dry-run", data={"csrf": csrf})
        (job,) = await _actions("job.regroup_dry_run")
        assert queued == [job.id]
        assert "Regroup dry run" in (await client.get("/catalog")).text


# --------------------------------------------------------------------------- #
# Reports and overrides
# --------------------------------------------------------------------------- #


async def test_accepting_a_wrong_match_records_never_merge_rulings_then_reject_withdraws(queued):
    ticked, other1, other2 = await _listings(3)
    report_id = await _report("offers_not_same", [(ticked, True), (other1, False), (other2, False)])
    async with _client() as client:
        csrf = await _session(client)
        await client.post(f"/reports/{report_id}/accept", data={"csrf": csrf})
        async with SessionLocal() as session:
            rows = list(await session.scalars(select(GroupingOverride)))
            report = await session.get(Report, report_id)
        assert report.status == "accepted"
        assert (
            sorted((r.kind, r.created_by, r.report_id) for r in rows)
            == [("never_merge", "owner", report_id)] * 2
        )
        await client.post(f"/reports/{report_id}/reject", data={"csrf": csrf})
        async with SessionLocal() as session:
            rows = list(await session.scalars(select(GroupingOverride)))
        assert all(r.removed_by == "owner (report rejected)" for r in rows)
    accept, reject = await _actions("report.accept") + await _actions("report.reject")
    assert len(accept.detail["overrides"]) == 2 and reject.detail["withdrawn"] == 2


async def test_accepting_a_wrong_price_report_marks_the_listing_to_be_read_first(queued):
    (listing, other) = await _listings(2)
    report_id = await _report("wrong_price_stock", [(listing, True), (other, False)])
    async with _client() as client:
        csrf = await _session(client)
        assert "re-read first by their shop" in (await client.get("/reports")).text
        response = await client.post(f"/reports/{report_id}/accept", data={"csrf": csrf})
        assert response.status_code == 303
        page = await client.get("/reports")
        assert "Re-checks pending" in page.text and "source not loaded" in page.text
    async with SessionLocal() as session:
        assert (await session.get(Report, report_id)).status == "accepted"
        assert not list(await session.scalars(select(GroupingOverride)))
        assert (await session.get(Listing, listing)).recheck_requested_at is not None
        assert (await session.get(Listing, other)).recheck_requested_at is None  # not ticked
    (accepted,) = await _actions("report.accept")
    assert accepted.detail["rechecks"] == 1

    # Rejected after all: the re-check its accept asked for is withdrawn.
    async with _client() as client:
        csrf = await _session(client)
        await client.post(f"/reports/{report_id}/reject", data={"csrf": csrf})
    async with SessionLocal() as session:
        assert (await session.get(Listing, listing)).recheck_requested_at is None
    (rejected,) = await _actions("report.reject")
    assert rejected.detail["rechecks_cleared"] == 1


async def test_rejecting_a_new_price_report_clears_no_one_elses_re_check(queued):
    """Only the reject of an accepted report withdraws markers: a new one never set any."""
    (listing,) = await _listings(1)
    accepted = await _report("wrong_price_stock", [(listing, True)])
    fresh = await _report("wrong_price_stock", [(listing, True)])
    async with _client() as client:
        csrf = await _session(client)
        await client.post(f"/reports/{accepted}/accept", data={"csrf": csrf})
        await client.post(f"/reports/{fresh}/reject", data={"csrf": csrf})
    async with SessionLocal() as session:
        assert (await session.get(Listing, listing)).recheck_requested_at is not None


async def test_adding_an_override_needs_a_note_and_two_shops_for_must(queued):
    a, b = await _listings(2)
    c, d = await _listings(2, same_shop=True)
    async with _client() as client:
        csrf = await _session(client)
        base = {"csrf": csrf, "a": str(a), "b": str(b), "kind": "must_merge"}
        await client.post("/overrides/add", data={**base, "note": "  "})
        await client.post(
            "/overrides/add", data={**base, "a": str(c), "b": str(d), "note": "same shop"}
        )
        await client.post("/overrides/add", data={**base, "note": "same part", "forced": "on"})
        page = await client.get("/overrides")
        assert "same part" in page.text
    async with SessionLocal() as session:
        (row,) = list(await session.scalars(select(GroupingOverride)))
    assert (row.kind, row.forced, row.source, row.created_by) == (
        "must_merge",
        True,
        "manual",
        "owner",
    )
    (added,) = await _accepted("override.add")
    assert added.target == str(row.id)
    assert len(await _refused("override.add")) == 2


async def test_removing_an_override_is_soft_and_needs_a_note(queued):
    a, b = await _listings(2)
    async with _client() as client:
        csrf = await _session(client)
        await client.post(
            "/overrides/add",
            data={"csrf": csrf, "a": str(a), "b": str(b), "kind": "never_merge", "note": "why"},
        )
        async with SessionLocal() as session:
            (row,) = list(await session.scalars(select(GroupingOverride)))
        refused = await client.post(f"/overrides/{row.id}/remove", data={"csrf": csrf})
        assert refused.status_code == 303 and "remove=" in refused.headers["location"]
        await client.post(
            f"/overrides/{row.id}/remove", data={"csrf": csrf, "note": "different revisions"}
        )
    async with SessionLocal() as session:
        row = await session.get(GroupingOverride, row.id)
    assert (row.removed_by, row.remove_note) == ("owner", "different revisions")
    assert len(await _accepted("override.remove")) == 1
    assert len(await _refused("override.remove")) == 1


# --------------------------------------------------------------------------- #
# AI
# --------------------------------------------------------------------------- #


async def test_the_ai_mode_changes_only_when_confirmed(queued):
    async with _client() as client:
        csrf = await _session(client)
        await client.post("/ai/mode", data={"csrf": csrf, "mode": "live"})
        async with SessionLocal() as session:
            assert await ai_mode(session) == "off"
        await client.post("/ai/mode", data={"csrf": csrf, "mode": "live", "confirm": "yes"})
        async with SessionLocal() as session:
            assert await ai_mode(session) == "live"
    refused, changed = await _actions("ai.mode")
    assert refused.detail == {"refused": "Confirm the change of mode first."}
    assert changed.detail == {"before": "off"}


async def test_refused_actions_are_audited_as_refused(queued):
    (listing,) = await _listings(1)
    same_shop_report = await _report("same_as_other", [(listing, True)])
    async with _client() as client:
        csrf = await _session(client)
        await client.post(
            "/overrides/add",
            data={"csrf": csrf, "a": "x", "b": "y", "kind": "never_merge", "note": ""},
        )
        await client.post(f"/reports/{same_shop_report}/accept", data={"csrf": csrf})
        await client.post("/ai/workers/nobody/revoke", data={"csrf": csrf, "confirmed": "yes"})
    add, report, revoke = (
        await _actions("override.add")
        + await _actions("report.accept")
        + await _actions("ai.worker.revoke")
    )
    assert "Both listings must be full listing ids" in add.detail["refused"]
    assert "no listing" in report.detail["refused"]
    assert revoke.detail["refused"] == "No worker named 'nobody'."
    async with SessionLocal() as session:
        assert (await session.get(Report, same_shop_report)).status == "new"


async def test_a_worker_token_is_shown_once_and_revoking_takes_two_clicks(queued):
    async with _client() as client:
        csrf = await _session(client)
        page = await client.post(
            "/ai/workers/add", data={"csrf": csrf, "name": "cpu-box", "model_kev": "on"}
        )
        assert page.status_code == 200
        token = re.search(r"<code>([^<]+)</code>", page.text).group(1)
        assert token not in (await client.get("/ai")).text
        async with SessionLocal() as session:
            worker = await session.scalar(select(AiWorker))
        assert worker.models == ["kev"] and token.encode() not in worker.token_sha256
        await client.post("/ai/workers/cpu-box/revoke", data={"csrf": csrf, "confirmed": ""})
        async with SessionLocal() as session:
            assert (await session.scalar(select(AiWorker))).revoked_at is None
        await client.post("/ai/workers/cpu-box/revoke", data={"csrf": csrf, "confirmed": "yes"})
        async with SessionLocal() as session:
            assert (await session.scalar(select(AiWorker))).revoked_at is not None
    assert [a.action for a in await _actions()][1:] == [
        "ai.worker.add",
        "ai.worker.revoke",  # the first click: refused, audited
        "ai.worker.revoke",
    ]
    assert len(await _refused("ai.worker.revoke")) == 1
    assert all(token not in str(a.detail) for a in await _actions())


async def test_dismissing_a_flag_needs_a_note(queued):
    async with SessionLocal() as session:
        flag = AiFlag(kind="version_drift", subject="cpu-box/kev", status="open", detail={})
        session.add(flag)
        await session.commit()
    async with _client() as client:
        csrf = await _session(client)
        await client.post(f"/ai/flags/{flag.id}/dismiss", data={"csrf": csrf, "note": ""})
        async with SessionLocal() as session:
            assert (await session.get(AiFlag, flag.id)).status == "open"
        await client.post(f"/ai/flags/{flag.id}/dismiss", data={"csrf": csrf, "note": "updated"})
    async with SessionLocal() as session:
        row = await session.get(AiFlag, flag.id)
    assert (row.status, row.resolved_by, row.note) == ("dismissed", "owner", "updated")


async def _decision() -> int:
    a, b = sorted(await _listings(2))
    row = AiDecision(
        pipeline="match",
        listing_a=a,
        listing_b=b,
        outcome="same",
        decided_by="pplx",
        scores={"kev": {"ab": 0.95, "ba": 0.93, "min": 0.93}},
        policy_version="p1",
        content_sha256_a=b"\0" * 32,
        content_sha256_b=b"\0" * 32,
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
    return row.id


async def test_revoking_a_decision_from_the_review_list(queued):
    decision_id = await _decision()
    async with _client() as client:
        csrf = await _session(client)
        page = await client.get("/ai")
        assert f"#{decision_id}" in page.text
        # No note: refused, nothing revoked.
        await client.post(f"/ai/decisions/{decision_id}/revoke", data={"csrf": csrf, "note": " "})
        async with SessionLocal() as session:
            assert (await session.get(AiDecision, decision_id)).state == "standing"
        note = {"csrf": csrf, "note": "a bracket, not the sensor"}
        await client.post(f"/ai/decisions/{decision_id}/revoke", data=note)
        again = await client.post(f"/ai/decisions/{decision_id}/revoke", data=note)
        assert again.status_code == 303
    async with SessionLocal() as session:
        row = await session.get(AiDecision, decision_id)
    assert (row.state, row.revoked_by, row.revoke_note) == (
        "revoked",
        "owner",
        "a bracket, not the sensor",
    )
    assert len(await _accepted("ai.decision.revoke")) == 1
    refused = await _refused("ai.decision.revoke")
    assert [r.detail["refused"] for r in refused][0].startswith("A note is required")
    assert len(refused) == 2  # no note, then a decision already revoked


async def test_redecide_is_a_dry_run(queued):
    decision_id = await _decision()
    async with _client() as client:
        csrf = await _session(client)
        page = await client.post("/ai/redecide", data={"csrf": csrf})
        assert page.status_code == 200 and "nothing written" in page.text
    async with SessionLocal() as session:
        assert (await session.get(AiDecision, decision_id)).state == "standing"


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #


async def test_every_view_renders_with_data(queued):
    await _source("shop-a", enabled=False)
    (listing,) = await _listings(1)
    await _report("same_as_other", [(listing, True)])
    await _decision()
    async with _client() as client:
        await _session(client)
        for path in ("/", "/crawl", "/catalog", "/reports", "/overrides", "/ai", "/activity"):
            response = await client.get(path)
            assert response.status_code == 200, path
            assert "default-src 'self'" in response.headers["content-security-policy"]
        lookup = await client.get("/catalog", params={"lookup": f"/listings/{listing}"})
        assert "No product or listing matches" in lookup.text  # a listing with no product yet


#: What a shop or a visitor could put in a title, a note, a category name.
HOSTILE = "<script>alert(1)</script>\"'><img src=x onerror=alert(2)>"


def _assert_escaped(html: str) -> None:
    assert "<script>alert(1)" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


async def test_hostile_text_from_shops_and_visitors_is_escaped_everywhere(queued):
    from makhzan_schemas.enums import IngestionStatus

    (listing,) = await _listings(1)
    async with SessionLocal() as session:
        row = await session.get(Listing, listing)
        row.title_en = HOSTILE
        row.source_url = "javascript:alert(3)"
        session.add(
            Report(
                product_id=uuid.uuid4(),
                reason="other",
                description=HOSTILE,
                snapshot={"product": {"title": HOSTILE, "listings": []}},
            )
        )
        session.add(AiFlag(kind="version_drift", subject=HOSTILE[:100], status="open", detail={}))
        session.add(
            IngestionRun(
                source="shop-x",
                source_type=SourceType.SCRAPED,
                status=IngestionStatus.SUCCESS,
                stats={"crosswalk": {"unmapped": {HOSTILE + " x' onclick='alert(4)": 3}}},
            )
        )
        await session.commit()
    async with _client() as client:
        await _session(client)
        catalog = await client.get("/catalog")  # the uncategorised browser lists it
        _assert_escaped(catalog.text)
        assert "javascript:alert(3)" not in catalog.text, "a shop's URL is linked only if http(s)"
        _assert_escaped((await client.get("/reports")).text)
        ai = await client.get("/ai")
        assert "<script>alert(1)" not in ai.text and "&lt;script&gt;" in ai.text
        crawl = await client.get("/crawl")
        _assert_escaped(crawl.text)
        # In the copy buttons' single-quoted attribute, a quote is JSON-escaped.
        assert "onclick='alert(4)" not in crawl.text
        assert "\\u0027 onclick=\\u0027alert(4)" in crawl.text


async def test_the_ai_page_shows_what_the_last_live_regroup_found(queued):
    from datetime import UTC, datetime

    decision_id = await _decision()
    async with _client() as client:
        await _session(client)
        assert "at the last live regroup" not in (await client.get("/ai")).text
        async with SessionLocal() as session:
            row = await session.get(AiDecision, decision_id)
            row.effect, row.blocked_reason = "blocked", "values"
            row.checked_at = datetime.now(UTC)
            await session.commit()
        page = (await client.get("/ai")).text
    assert "at the last live regroup" in page
    assert "in effect 0, blocked 1 (values 1), inactive 0, overridden 0" in page
