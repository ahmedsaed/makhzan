"""`python -m worker.probe`: the crawler's own client, per identity, at the real first page.

The probe was a curl script, and curl is not our client: its TLS fingerprint,
HTTP version and header order differ, and Cloudflare scores those. These pin
that every probe request is built by `make_client` with the identity under test,
that it asks the URL a run really asks first, obeys robots.txt, and keeps 15 s
between requests to a host.
"""

from __future__ import annotations

import httpx
import pytest
from makhzan_schemas import botauth
from test_botauth import RFC_JWK_D, RFC_JWK_X, verify

from worker import egress as egress_mod
from worker import http as http_mod
from worker import probe as probe_mod
from worker import robots as robots_mod
from worker.sources.base import SupplierInfo
from worker.sources.odoo import OdooAdapter
from worker.sources.shopify import ShopifyAdapter
from worker.sources.woocommerce import WooCommerceAdapter

SUPPLIER = SupplierInfo(slug="t", name="T")


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def wire(monkeypatch):
    """Route every httpx client to a handler; record what was sent, and when."""
    state = {"sent": [], "robots": "User-agent: *\nAllow: /\n"}
    clock = _Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        state["sent"].append((clock.now, request))
        if request.url.path == "/robots.txt":
            if state.get("robots_redirect"):
                return httpx.Response(301, headers={"Location": state["robots_redirect"]})
            if state.get("robots_status"):
                return httpx.Response(state["robots_status"])
            return httpx.Response(200, text=state["robots"])
        return httpx.Response(200, json=[])

    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(**kwargs):
        kwargs.setdefault("transport", transport)
        return real(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    # The crawler's robots.txt cache, fresh for each test (no copies kept).
    monkeypatch.setattr(
        robots_mod, "ROBOTS", robots_mod.RobotsCache(store=robots_mod.RobotsStore())
    )
    monkeypatch.setenv("SITE_URL", "https://makhzan.test")
    monkeypatch.setenv(botauth.KEY_ENV, RFC_JWK_D)
    # No real DNS, and pool connections to the same handler (`ipv6` column).
    state["aaaa"] = []
    state["bound"] = []

    async def aaaa(host):
        return list(state["aaaa"])

    def bound(address):
        state["bound"].append(address)
        return transport

    monkeypatch.setattr(probe_mod, "_ipv6_addresses", aaaa)
    monkeypatch.setattr(egress_mod, "http_transport", bound)
    monkeypatch.delenv(egress_mod.POOL_ENV, raising=False)
    state["clock"] = clock
    return state


async def test_each_column_is_the_crawlers_own_request_for_that_identity(wire):
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    target = probe_mod.Target("shop", "https://shop.test/products.json?limit=250&page=1")
    rows, notes = await probe_mod.probe([target], gate=gate)

    assert notes == []
    sent = [request for _, request in wire["sent"]]
    assert [r.url.path for r in sent] == ["/robots.txt"] + ["/products.json"] * 3
    robots, browser, bot, signed = sent
    assert browser.headers["User-Agent"] == http_mod.BROWSER_HEADERS["User-Agent"]
    assert browser.headers["sec-ch-ua"] == http_mod.BROWSER_HEADERS["sec-ch-ua"]
    assert bot.headers["User-Agent"].startswith("makhzanbot/1.0 (+https://makhzan.test/")
    assert "Signature" not in bot.headers and "sec-ch-ua" not in bot.headers
    verify(signed, RFC_JWK_X)
    assert str(signed.url) == target.url
    # Each cell: the status and the HTTP version the server answered with.
    row = rows[0]
    assert {k: c.text() for k, c in row.cells.items()} == {
        "robots": "fetched",  # the crawler's cache read it
        "browser": "200 h1.1",
        "makhzanbot": "200 h1.1",
        "signed": "200 h1.1",
        "ipv6": "no IPv6 address",  # no AAAA record: nothing sent over IPv6
    }
    # Fifteen seconds between any two requests to the host.
    times = [t for t, _ in wire["sent"]]
    assert all(b - a >= 15.0 for a, b in zip(times, times[1:]))


async def test_a_page_robots_txt_disallows_is_not_asked(wire):
    wire["robots"] = "User-agent: makhzanbot\nDisallow: /\n"
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    rows, _ = await probe_mod.probe([probe_mod.Target("shop", "https://shop.test/a")], gate=gate)
    assert [r.url.path for _, r in wire["sent"]] == ["/robots.txt"]
    assert rows[0].cells["robots"].text() == "fetched; DISALLOWS this page"
    assert rows[0].cells["browser"].text() == "not asked"


async def test_robots_txt_is_read_as_a_run_reads_it_redirects_included(wire):
    """Through the crawler's own cache: a redirecting robots.txt is followed as a
    run follows it (each hop paced), and the rules where it leads are obeyed."""
    wire["robots_redirect"] = "https://shop.test/real-robots.txt"
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    rows, _ = await probe_mod.probe([probe_mod.Target("shop", "https://shop.test/a")], gate=gate)
    paths = [r.url.path for _, r in wire["sent"]]
    assert paths[:2] == ["/robots.txt", "/real-robots.txt"]
    assert rows[0].cells["robots"].text() == "fetched"
    assert rows[0].cells["browser"].status == 200


async def test_an_unreadable_robots_txt_with_no_copy_refuses_the_host(wire):
    """RobotsUnavailable, as a run gets it: the page is not asked."""
    wire["robots_status"] = 503
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    rows, _ = await probe_mod.probe([probe_mod.Target("shop", "https://shop.test/a")], gate=gate)
    assert rows[0].cells["robots"].text().startswith("unavailable")
    assert rows[0].cells["browser"].text() == "not asked"
    assert {r.url.path for _, r in wire["sent"]} == {"/robots.txt"}


async def test_a_cached_robots_txt_sends_nothing_and_its_crawl_delay_paces_the_probe(wire):
    wire["robots"] = "User-agent: *\nCrawl-delay: 30\nAllow: /\n"
    clock = wire["clock"]
    await robots_mod.ROBOTS.allowed("https://shop.test/a")  # a run read it already
    sent_before = len(wire["sent"])
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    await probe_mod.probe([probe_mod.Target("shop", "https://shop.test/a")], gate=gate)
    assert [r.url.path for _, r in wire["sent"][sent_before:]][0] == "/a"  # no robots.txt
    assert http_mod._pace_of("https://shop.test") == 30.0


async def test_without_a_key_the_signed_column_is_skipped_and_said_so(wire, monkeypatch):
    monkeypatch.delenv(botauth.KEY_ENV)
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    rows, notes = await probe_mod.probe([probe_mod.Target("s", "https://shop.test/a")], gate=gate)
    assert rows[0].cells["signed"].text() == "-"
    assert any("MAKHZANBOT_SIGNING_KEY" in n for n in notes)


def test_the_gap_cannot_be_set_below_the_crawlers_pace():
    assert probe_mod.MIN_GAP == 15.0


@pytest.mark.parametrize(
    ("adapter", "partition"),
    [
        (WooCommerceAdapter("t", "https://shop.test", SUPPLIER, variations=False), None),
        (ShopifyAdapter("t", "https://shop.test", SUPPLIER), ""),
        (OdooAdapter("t", "https://shop.test", SUPPLIER), ""),
    ],
)
async def test_the_probe_url_is_the_first_request_a_run_sends(monkeypatch, adapter, partition):
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return (
            httpx.Response(200, json=[], text=None)
            if "json" in request.url.path
            else (httpx.Response(200, text="<html></html>"))
        )

    class _AllowAll:
        async def allowed(self, url, token=None):
            return True

        async def crawl_delay(self, url, token=None):
            return None

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr(robots_mod, "ROBOTS", _AllowAll())

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
    first = adapter.partitions()[0] if partition is None else partition
    try:
        await adapter.fetch_page(first, 1)
    except Exception:  # noqa: BLE001 — an empty page may not parse; the URL is what counts
        pass
    assert sent and sent[0] == adapter.probe_url()


async def test_a_pending_retry_after_keeps_the_probe_off_the_host(wire):
    """The probe goes through the crawl's gate: a host holding us off is not asked."""
    import time

    http_mod._NOT_BEFORE["https://shop.test"] = time.monotonic() + 120
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    target = probe_mod.Target("shop", "https://shop.test/products.json")
    rows, notes = await probe_mod.probe([target], gate=gate)
    assert wire["sent"] == []
    assert all(cell.error == "not asked" for cell in rows[0].cells.values())
    assert any("Retry-After" in note for note in notes)
    assert "Retry-After" in probe_mod.refusal(target.url)


async def test_every_probe_request_takes_the_crawls_turn_and_a_429_binds_it(wire, monkeypatch):
    turns: list[str] = []
    real = http_mod.take_turn

    async def recording(host, **kw):
        turns.append(host)
        await real(host, **kw)

    monkeypatch.setattr(probe_mod, "take_turn", recording)
    monkeypatch.setattr(robots_mod, "take_turn", recording)  # robots.txt, through the cache
    state_handler = wire

    def throttled(request: httpx.Request) -> httpx.Response:
        state_handler["sent"].append((0, request))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(429, headers={"Retry-After": "60"})

    transport = httpx.MockTransport(throttled)
    original = httpx.AsyncClient

    def client(**kwargs):
        kwargs["transport"] = transport
        return original(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    target = probe_mod.Target("shop", "https://shop.test/products.json")
    rows, _ = await probe_mod.probe([target], gate=gate, sign=False)
    assert turns and set(turns) == {"https://shop.test"}
    assert len(turns) == len(wire["sent"])
    # robots.txt, then browser got the 429; makhzanbot was not asked after it.
    assert [r.url.path for _, r in wire["sent"]] == ["/robots.txt", "/products.json"]
    assert rows[0].cells["browser"].status == 429
    assert rows[0].cells["makhzanbot"].error == "not asked"
    # The 429 now holds the host for the crawl as well.
    assert http_mod._NOT_BEFORE["https://shop.test"] > 0
    assert probe_mod.refusal(target.url) is not None


async def test_the_no_db_probe_keeps_no_robots_copy_in_the_database(wire, monkeypatch, tmp_path):
    import argparse

    from makhzan_schemas.db import SessionLocal
    from makhzan_schemas.models import RobotsCopy
    from sqlalchemy import func, select

    # As in a fresh process: the cache stores copies in the database.
    monkeypatch.setattr(
        robots_mod, "ROBOTS", robots_mod.RobotsCache(store=robots_mod.DatabaseRobotsStore())
    )
    clock = wire["clock"]
    real_gate = probe_mod._Gate
    monkeypatch.setattr(
        probe_mod, "_Gate", lambda gap: real_gate(gap, clock=clock, sleep=clock.sleep)
    )
    sites = tmp_path / "probe-sites.txt"
    sites.write_text("shop|https://shop.test/a\n")
    args = argparse.Namespace(
        sites=str(sites), no_db=True, source=None, no_ip=True, delay=15.0, no_sign=True
    )
    assert await probe_mod.main_async(args) == 0
    assert any(r.url.path == "/robots.txt" for _, r in wire["sent"])
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(RobotsCopy)) == 0


def test_the_sites_list_is_read_as_label_and_url(tmp_path):
    path = tmp_path / "probe-sites.txt"
    path.write_text("# comment\nshop-a|https://a.test/x?y=1\n\nshop-b | https://b.test/\n")
    assert probe_mod.read_sites(path) == {
        "shop-a": "https://a.test/x?y=1",
        "shop-b": "https://b.test/",
    }


async def test_ipv6_is_asked_from_one_pool_address_as_the_sources_own_signed_identity(
    wire, monkeypatch
):
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    wire["aaaa"] = ["2606:4700::1"]
    pool = "2607:f8b0:4005:80a::200e"
    monkeypatch.setenv(egress_mod.POOL_ENV, pool)
    target = probe_mod.Target("shop", "https://shop.test/products.json", identity="makhzanbot")
    rows, _ = await probe_mod.probe([target], gate=gate)

    assert rows[0].cells["ipv6"].text() == "200 h1.1"
    assert wire["bound"][-1] == pool  # bound to the pool address, no fallback transport
    last = wire["sent"][-1][1]
    assert last.headers["User-Agent"].startswith("makhzanbot/1.0")
    verify(last, RFC_JWK_X)
    # Still 15 s after the request before it to the same host.
    times = [t for t, _ in wire["sent"]]
    assert times[-1] - times[-2] >= 15.0


async def test_ipv6_without_a_pool_reports_the_dns_answer_and_sends_nothing(wire):
    clock = wire["clock"]
    gate = probe_mod._Gate(15.0, clock=clock, sleep=clock.sleep)
    wire["aaaa"] = ["2606:4700::1"]
    target = probe_mod.Target("shop", "https://shop.test/products.json")
    rows, _ = await probe_mod.probe([target], gate=gate)
    assert rows[0].cells["ipv6"].text() == "has IPv6; no pool here"
    assert len(wire["sent"]) == 4  # robots.txt and the three IPv4 columns only
