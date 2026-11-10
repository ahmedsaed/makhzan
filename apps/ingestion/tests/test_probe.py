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
            return httpx.Response(200, text=state["robots"])
        return httpx.Response(200, json=[])

    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(**kwargs):
        kwargs.setdefault("transport", transport)
        return real(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setenv("SITE_URL", "https://makhzan.test")
    monkeypatch.setenv(botauth.KEY_ENV, RFC_JWK_D)
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
        "robots": "200 h1.1",
        "browser": "200 h1.1",
        "makhzanbot": "200 h1.1",
        "signed": "200 h1.1",
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
    assert rows[0].cells["robots"].text() == "200 h1.1 DISALLOWS this page"
    assert rows[0].cells["browser"].text() == "not asked"


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


def test_the_sites_list_is_read_as_label_and_url(tmp_path):
    path = tmp_path / "probe-sites.txt"
    path.write_text("# comment\nshop-a|https://a.test/x?y=1\n\nshop-b | https://b.test/\n")
    assert probe_mod.read_sites(path) == {
        "shop-a": "https://a.test/x?y=1",
        "shop-b": "https://b.test/",
    }
