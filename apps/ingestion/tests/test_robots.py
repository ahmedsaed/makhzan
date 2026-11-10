"""Honouring robots.txt.

Every path makhzan crawls was already allowed by the suppliers' files — that was
luck, not mechanism. These pin the mechanism, including the failure modes, which
are where a naive implementation either stops crawling on a blip or quietly
ignores a rule.
"""

from __future__ import annotations

import httpx
import pytest

from worker import robots as robots_mod
from worker.robots import DisallowedByRobots, RobotsCache, RobotsUnavailable

#: What every lookup is matched on, whichever identity sends the request.
UA = "makhzanbot"

DISALLOWS_API = """
User-agent: *
Disallow: /wp-admin/
Disallow: /wp-json/
Crawl-delay: 20
"""

ALLOWS_ALL = "User-agent: *\nDisallow:\n"


def _client_returning(status: int, body: str = ""):
    """Stand in for httpx.AsyncClient so nothing leaves the machine."""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            return httpx.Response(status, text=body, request=httpx.Request("GET", url))

    return lambda **_kwargs: _Client()


def _client_raising(exc: Exception):
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            raise exc

    return lambda **_kwargs: _Client()


async def test_a_disallowed_path_is_refused(monkeypatch):
    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_returning(200, DISALLOWS_API))
    cache = RobotsCache()
    assert await cache.allowed("https://shop.test/wp-json/wc/store/v1/products", UA) is False
    assert await cache.allowed("https://shop.test/shop", UA) is True


async def test_crawl_delay_is_read(monkeypatch):
    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_returning(200, DISALLOWS_API))
    cache = RobotsCache()
    assert await cache.crawl_delay("https://shop.test/anything", UA) == 20.0


async def test_no_crawl_delay_is_none_not_zero(monkeypatch):
    """None means "they did not say" — zero would read as "no wait needed"."""
    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_returning(200, ALLOWS_ALL))
    cache = RobotsCache()
    assert await cache.crawl_delay("https://shop.test/anything", UA) is None


async def test_a_missing_robots_file_allows_everything(monkeypatch):
    """404 is the common case and means the host published no rules."""
    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_returning(404))
    cache = RobotsCache()
    assert await cache.allowed("https://shop.test/wp-json/anything", UA) is True
    assert cache.failures == {}


async def test_an_unreachable_robots_file_with_no_copy_disallows_the_host(monkeypatch):
    """RFC 9309 §2.3.1.4: unreachable means "assume complete disallow". It used to
    allow everything; the durable cursor makes refusing cheap (the page resumes
    tomorrow), and it is never mistaken for a path-level disallow."""
    monkeypatch.setattr(
        robots_mod.httpx, "AsyncClient", _client_raising(httpx.ConnectTimeout("slow"))
    )
    cache = RobotsCache()
    with pytest.raises(RobotsUnavailable):
        await cache.allowed("https://shop.test/anything", UA)
    assert "unreachable" in cache.failures["https://shop.test"]
    assert not issubclass(RobotsUnavailable, DisallowedByRobots)


@pytest.mark.parametrize("status", [500, 503, 429])
async def test_a_server_error_with_no_copy_disallows_the_host(monkeypatch, status):
    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_returning(status))
    cache = RobotsCache()
    with pytest.raises(RobotsUnavailable):
        await cache.allowed("https://shop.test/anything", UA)
    assert str(status) in cache.failures["https://shop.test"]
    # Read from the cache for the rest of the TTL: the run does not keep asking.
    assert await cache.crawl_delay("https://shop.test/anything", UA) is None


def _client_sequence(responses: list):
    """Each `AsyncClient()` answers with the next (status, body) or raises the next error."""

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            status, body = item
            return httpx.Response(status, text=body, request=httpx.Request("GET", url))

    return lambda **_kwargs: _Client()


class _Wall:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


async def test_a_server_error_falls_back_to_the_last_good_copy(monkeypatch):
    wall = _Wall()
    monkeypatch.setattr(
        robots_mod.httpx,
        "AsyncClient",
        _client_sequence([(200, DISALLOWS_API), (503, ""), httpx.ConnectError("down")]),
    )
    cache = RobotsCache(ttl=0, wall=wall)
    assert await cache.allowed("https://shop.test/shop", UA) is True
    wall.now += 29 * 86400
    # The copy's rules still apply, disallows included.
    assert await cache.allowed("https://shop.test/wp-json/x", UA) is False
    assert "copy from 29.0 days ago" in cache.failures["https://shop.test"]
    assert await cache.allowed("https://shop.test/shop", UA) is True


async def test_a_good_copy_older_than_thirty_days_is_not_used(monkeypatch):
    wall = _Wall()
    monkeypatch.setattr(
        robots_mod.httpx, "AsyncClient", _client_sequence([(200, ALLOWS_ALL), (503, "")])
    )
    cache = RobotsCache(ttl=0, wall=wall)
    assert await cache.allowed("https://shop.test/a", UA) is True
    wall.now += 31 * 86400
    with pytest.raises(RobotsUnavailable):
        await cache.allowed("https://shop.test/a", UA)


async def test_a_404_is_a_good_copy_too(monkeypatch):
    """ "No rules" was what the host last said; an outage does not change it."""
    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_sequence([(404, ""), (502, "")]))
    cache = RobotsCache(ttl=0)
    assert await cache.allowed("https://shop.test/a", UA) is True
    assert await cache.allowed("https://shop.test/a", UA) is True
    assert "502" in cache.failures["https://shop.test"]


async def test_the_fetch_layer_sends_nothing_when_robots_cannot_be_read(monkeypatch):
    from worker import http as http_mod

    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_returning(503))
    monkeypatch.setattr(robots_mod, "ROBOTS", RobotsCache())
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={})

    with pytest.raises(RobotsUnavailable):
        async with http_mod.make_client(transport=httpx.MockTransport(handler)) as client:
            await http_mod.get_json(client, "https://shop.test/products.json")
    assert sent == []


async def test_robots_txt_is_fetched_as_the_runs_identity(monkeypatch):
    """A makhzanbot run asks for robots.txt as makhzanbot, not as a browser."""
    from worker.identity import MAKHZANBOT, identity_for, using_identity

    monkeypatch.setenv("SITE_URL", "https://makhzan.test")
    seen: list[dict] = []

    class _Client:
        def __init__(self, **kwargs):
            seen.append(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            return httpx.Response(200, text=ALLOWS_ALL, request=httpx.Request("GET", url))

    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _Client)
    with using_identity(identity_for(MAKHZANBOT)):
        await RobotsCache().allowed("https://shop.test/a")
    await RobotsCache().allowed("https://other.test/a")
    assert seen[0]["headers"]["User-Agent"].startswith("makhzanbot/1.0 (+https://makhzan.test/")
    assert seen[1]["headers"]["User-Agent"].startswith("Mozilla/5.0")


async def test_robots_is_fetched_once_per_host(monkeypatch):
    """It sits on the critical path of every request; fetching it each time would
    double the traffic we are trying to be careful about."""
    calls = {"n": 0}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url):
            calls["n"] += 1
            return httpx.Response(200, text=ALLOWS_ALL, request=httpx.Request("GET", url))

    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", lambda **_k: _Client())
    cache = RobotsCache()
    for _ in range(5):
        await cache.allowed("https://shop.test/a", UA)
        await cache.allowed("https://shop.test/b", UA)
    assert calls["n"] == 1


async def test_the_fetch_layer_refuses_a_disallowed_url(monkeypatch):
    """The check lives at the one choke point every adapter goes through."""
    from worker import http as http_mod

    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_returning(200, DISALLOWS_API))
    monkeypatch.setattr(robots_mod, "ROBOTS", RobotsCache())

    with pytest.raises(DisallowedByRobots):
        async with http_mod.make_client() as client:
            await http_mod.get_json(client, "https://shop.test/wp-json/wc/store/v1/products")


async def test_crawl_delay_is_a_floor_not_a_ceiling(monkeypatch):
    """A host asking for 20 gets 20 even though the default is 15. A host asking
    for 1 still gets the full polite delay — being asked to hurry is not a
    reason to."""
    from worker.pipeline import _pace
    from worker.sources.base import SourceAdapter, SupplierInfo

    class _Stub(SourceAdapter):
        source_id = "t"
        supplier = SupplierInfo(slug="t", name="T")
        base_url = "https://shop.test"
        polite_delay = 15.0

        async def fetch_page(self, partition, page):  # pragma: no cover
            raise NotImplementedError

    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", _client_returning(200, DISALLOWS_API))
    monkeypatch.setattr(robots_mod, "ROBOTS", RobotsCache())
    assert await _pace(_Stub()) == 20.0

    monkeypatch.setattr(
        robots_mod.httpx, "AsyncClient", _client_returning(200, "User-agent: *\nCrawl-delay: 1\n")
    )
    monkeypatch.setattr(robots_mod, "ROBOTS", RobotsCache())
    assert await _pace(_Stub()) == 15.0


async def test_a_source_with_no_host_still_paces(monkeypatch):
    """The fixture source has nothing to ask."""
    from worker.pipeline import _pace
    from worker.sources.base import SourceAdapter, SupplierInfo

    class _Stub(SourceAdapter):
        source_id = "t"
        supplier = SupplierInfo(slug="t", name="T")
        polite_delay = 7.0

        async def fetch_page(self, partition, page):  # pragma: no cover
            raise NotImplementedError

    assert await _pace(_Stub()) == 7.0


# --------------------------------------------------------------------------- #
# Matching, as RFC 9309 has it — not as the 3.12 standard library does
# --------------------------------------------------------------------------- #

STOREFRONT = """
User-agent: *
Allow: /
Disallow: /cart
Disallow: /collections/*sort_by*
Disallow: /collections/*+*
Disallow: /*.atom$
Allow: /cart/help
"""


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/products.json?limit=250&page=2", True),
        ("/collections/sensors/products.json?limit=250&page=1", True),
        # Wildcards: the standard library on Python 3.12 reads these literally.
        ("/collections/all?sort_by=price-ascending", False),
        ("/collections/sensors+motors", False),
        ("/collections/sensors%2Bmotors/products.json", False),  # however it is spelled
        # `$` anchors the end: the feed is disallowed, a page named like it is not.
        ("/collections/all.atom", False),
        ("/collections/all.atom/more", True),
        # Longest match wins, not the first line: `Allow: /` comes first.
        ("/cart", False),
        ("/cart/help", True),
        ("/robots.txt", True),
    ],
)
def test_rules_match_the_way_rfc_9309_says(path, allowed):
    rules = robots_mod.Rules(STOREFRONT)
    assert rules.allowed(f"https://shop.test{path}", UA) is allowed


def test_a_group_naming_us_replaces_the_star_group():
    rules = robots_mod.Rules(
        "User-agent: *\nDisallow: /\n\nUser-agent: makhzanbot\nUser-agent: other\nDisallow: /x\n"
    )
    assert rules.allowed("https://shop.test/a", UA) is True
    assert rules.allowed("https://shop.test/x", UA) is False


@pytest.mark.parametrize("agent", ["makhzanbot", "MakhzanBot", "makhzanbot/1.0"])
def test_a_shop_can_block_us_by_name(agent):
    """The snippet /how-we-crawl publishes. It binds every identity: the lookup
    is always on our own token, never on the User-Agent string we sent."""
    rules = robots_mod.Rules(f"User-agent: {agent}\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert rules.allowed("https://shop.test/products.json", UA) is False
    assert rules.allowed("https://shop.test/products.json") is False  # the default token


def test_a_group_for_mozilla_no_longer_applies_to_us():
    """The browser identity's User-Agent starts "Mozilla", which a group for
    browsers used to catch. Our token is makhzanbot; such a group is not ours."""
    rules = robots_mod.Rules("User-agent: mozilla\nDisallow: /\n\nUser-agent: *\nDisallow: /x\n")
    assert rules.allowed("https://shop.test/a", UA) is True
    assert rules.allowed("https://shop.test/x", UA) is False


def test_a_group_matching_part_of_our_token_is_not_ours():
    rules = robots_mod.Rules("User-agent: bot\nDisallow: /\n")
    assert rules.allowed("https://shop.test/a", UA) is True


def test_crawl_delay_is_read_from_the_group_naming_us():
    rules = robots_mod.Rules(
        "User-agent: *\nCrawl-delay: 5\n\nUser-agent: makhzanbot\nCrawl-delay: 30\n"
    )
    assert rules.crawl_delay(UA) == 30.0


async def test_the_fetch_layer_obeys_a_makhzanbot_block_in_browser_mode(monkeypatch):
    """No identity set (browser headers), and still refused by a group naming us."""
    from worker import http as http_mod

    monkeypatch.setattr(
        robots_mod.httpx,
        "AsyncClient",
        _client_returning(200, "User-agent: makhzanbot\nDisallow: /\n"),
    )
    monkeypatch.setattr(robots_mod, "ROBOTS", RobotsCache())
    with pytest.raises(DisallowedByRobots):
        async with http_mod.make_client() as client:
            await http_mod.get_json(client, "https://shop.test/products.json")


def test_rules_before_any_user_agent_bind_nobody():
    rules = robots_mod.Rules("Disallow: /\nUser-agent: *\nDisallow: /private\n")
    assert rules.allowed("https://shop.test/a", UA) is True
    assert rules.allowed("https://shop.test/private/a", UA) is False


def test_a_malformed_crawl_delay_is_not_a_rule():
    rules = robots_mod.Rules("User-agent: *\nCrawl-delay: soon\nDisallow: /x\n")
    assert rules.crawl_delay(UA) is None
    assert rules.allowed("https://shop.test/x", UA) is False


def test_the_details_stage_treats_an_unreadable_robots_txt_as_host_trouble():
    """It stops the stage for the run and blames no listing, like a host backing off."""
    from worker.details import _host_trouble

    assert _host_trouble(RobotsUnavailable("https://shop.test", "robots.txt returned 503"))
    assert not _host_trouble(DisallowedByRobots("https://shop.test/p/1"))
