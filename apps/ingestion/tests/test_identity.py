"""Per-source identity: browser by default, makhzanbot when a source asks for it.

Nothing about a source that does not set `identity` may change, and a source
that does must send *every* request as makhzanbot — pages, retries, redirect
hops, robots.txt and the details stage — signed when a key is configured.
"""

from __future__ import annotations

import httpx
import pytest
from makhzan_schemas import botauth
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import Source

from worker import http as http_mod
from worker import robots as robots_mod
from worker.identity import (
    BROWSER,
    BROWSER_HEADERS,
    MAKHZANBOT,
    current_identity,
    identity_for,
    using_identity,
)
from worker.pipeline import run_source
from worker.sources.base import Page, RawItem, SourceAdapter, SupplierInfo
from worker.sources.registry import build_adapter

from test_botauth import RFC_JWK_D, RFC_JWK_X, verify

SITE = "https://makhzan.test"


@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv("SITE_URL", SITE)
    monkeypatch.delenv(botauth.KEY_ENV, raising=False)
    monkeypatch.delenv(f"{botauth.KEY_ENV}_FILE", raising=False)


@pytest.fixture
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", instant)


def _row(**config) -> Source:
    return Source(
        source_id="shop",
        adapter="fixture",
        base_url=None,
        enabled=True,
        supplier={"slug": "shop", "name": "Shop"},
        config=config,
    )


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_a_source_without_the_key_stays_browser():
    assert build_adapter(_row()).identity == BROWSER


def test_a_source_can_ask_for_makhzanbot():
    assert build_adapter(_row(identity="makhzanbot")).identity == MAKHZANBOT


def test_an_unknown_identity_is_refused_not_ignored():
    with pytest.raises(ValueError, match="identity"):
        build_adapter(_row(identity="googlebot"))


def test_outside_a_run_the_identity_is_the_browser_one():
    assert current_identity().name == BROWSER
    assert current_identity().headers == BROWSER_HEADERS


# --------------------------------------------------------------------------- #
# Headers
# --------------------------------------------------------------------------- #


def test_makhzanbot_is_honest_and_names_the_site(site):
    identity = identity_for(MAKHZANBOT)
    headers = identity.headers
    assert headers["User-Agent"] == (
        "makhzanbot/1.0 (+https://makhzan.test/how-we-crawl; crawler@merope.dev)"
    )
    assert headers["From"] == "crawler@merope.dev"
    assert not any(k.lower().startswith(("sec-ch-ua", "sec-fetch")) for k in headers)
    assert "Mozilla" not in headers["User-Agent"]
    assert identity.signed is False  # no key configured


def test_the_site_url_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://makhzan.example.eg/")
    assert (
        "(+https://makhzan.example.eg/how-we-crawl;"
        in identity_for(MAKHZANBOT).headers["User-Agent"]
    )
    monkeypatch.delenv("SITE_URL")
    with pytest.raises(RuntimeError, match="SITE_URL"):
        identity_for(MAKHZANBOT)


def test_the_browser_identity_is_unchanged():
    identity = identity_for(BROWSER)
    assert identity.headers is BROWSER_HEADERS
    assert identity.signed is False
    assert identity.headers["User-Agent"].startswith("Mozilla/5.0")


def test_a_configured_key_signs_makhzanbot_only(site, monkeypatch):
    monkeypatch.setenv(botauth.KEY_ENV, RFC_JWK_D)
    assert identity_for(MAKHZANBOT).signed is True
    assert identity_for(MAKHZANBOT).describe()["keyid"]
    assert identity_for(BROWSER).signed is False


# --------------------------------------------------------------------------- #
# Every request path
# --------------------------------------------------------------------------- #


def _mock_everything(monkeypatch, handler) -> None:
    """Route every httpx client — make_client's and robots.txt's — to `handler`."""
    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(**kwargs):
        kwargs.setdefault("transport", transport)
        return real(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


async def test_every_request_of_a_signed_run_is_signed_afresh(site, monkeypatch, no_sleep):
    """robots.txt, a redirect hop, a retried 503 and the success after it."""
    monkeypatch.setenv(botauth.KEY_ENV, RFC_JWK_D)
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache())
    sent: list[httpx.Request] = []
    answers = iter([503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "https://shop.test/new"})
        return httpx.Response(next(answers), json={})

    _mock_everything(monkeypatch, handler)
    with using_identity(identity_for(MAKHZANBOT)):
        async with http_mod.make_client() as client:
            await http_mod.get_json(client, "https://shop.test/old")

    paths = [r.url.path for r in sent]
    assert paths == ["/robots.txt", "/old", "/new", "/old", "/new"]
    nonces = set()
    for request in sent:
        assert request.headers["User-Agent"].startswith("makhzanbot/1.0")
        assert "sec-ch-ua" not in request.headers
        nonces.add(verify(request, RFC_JWK_X)["nonce"])
    assert len(nonces) == len(sent)


async def test_a_browser_run_sends_no_signature(site, monkeypatch, no_sleep):
    monkeypatch.setenv(botauth.KEY_ENV, RFC_JWK_D)  # configured, but not this source's identity
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache())
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, json={})

    _mock_everything(monkeypatch, handler)
    async with http_mod.make_client() as client:
        await http_mod.get_json(client, "https://shop.test/a")
    assert [r.url.path for r in sent] == ["/robots.txt", "/a"]
    for request in sent:
        assert request.headers["User-Agent"] == BROWSER_HEADERS["User-Agent"]
        assert "Signature" not in request.headers
        assert "Signature-Agent" not in request.headers


class _Shop(SourceAdapter):
    """One page through the adapter's own client, and one cycle-data request."""

    source_id = "identity-shop"
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug="identity-shop", name="Identity Shop")
    polite_delay = 0.0
    base_url = "https://shop.test"

    def partitions(self) -> list[str]:
        return [""]

    def cycle_data_parts(self) -> list[str]:
        return ["tree"]

    async def fetch_cycle_part(self, fetcher, part: str) -> object:
        await fetcher.get(part, f"{self.base_url}/tree")
        return {}

    async def fetch_page(self, partition: str, page: int) -> Page:
        async with http_mod.make_client() as client:
            await http_mod.get_json(client, f"{self.base_url}/page/{page}")
        item = RawItem(
            source=self.source_id,
            external_id="p1",
            title="Part p1",
            price_text="10 EGP",
            availability_text="In stock",
        )
        return Page([item], has_more=False)


@pytest.mark.parametrize(("identity", "signed"), [("browser", False), ("makhzanbot", True)])
async def test_a_run_sends_everything_as_its_sources_identity(
    site, monkeypatch, no_sleep, identity, signed
):
    monkeypatch.setenv(botauth.KEY_ENV, RFC_JWK_D)
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache())
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, json={})

    _mock_everything(monkeypatch, handler)
    adapter = _Shop()
    adapter.identity = identity
    run = await run_source(adapter.source_id, adapter)

    assert {r.url.path for r in sent} == {"/robots.txt", "/tree", "/page/1"}
    for request in sent:
        assert request.headers["User-Agent"].startswith(
            "makhzanbot/" if identity == MAKHZANBOT else "Mozilla/"
        )
        assert ("Signature" in request.headers) is signed
        if signed:
            verify(request, RFC_JWK_X)
    assert run.stats["identity"]["name"] == identity
    assert run.stats["identity"]["signed"] is signed
    # The run's identity ends with the run.
    assert current_identity().name == BROWSER
