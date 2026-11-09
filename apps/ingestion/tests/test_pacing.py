"""`stats.pacing`: the requests a run sent and the gaps between them, as measured.

/how-we-crawl publishes these numbers to the shops themselves, as proof of the
"at least 15 seconds" it promises. So they must be what the shop's server saw:
taken at the moment each request is sent, retries included, across every
partition and the once-a-cycle reference data — never the pause the code meant
to leave.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from makhzan_schemas import crawl
from makhzan_schemas.enums import IngestionStatus, SourceType
from makhzan_schemas.models import IngestionRun
from sqlalchemy import select

from worker import http as http_mod
from worker import pipeline
from worker import robots as robots_mod
from worker.pipeline import run_source
from worker.sources.base import Page, RawItem, SourceAdapter, SupplierInfo


class _AllowAll:
    async def allowed(self, url, user_agent):
        return True

    async def crawl_delay(self, url, user_agent):
        return None


class _Clock:
    """Monotonic time that moves only when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(robots_mod, "ROBOTS", _AllowAll())
    monkeypatch.setattr(http_mod, "_NOT_BEFORE", {})
    # One asyncio module: this patches every sleep, the pipeline's and the client's.
    monkeypatch.setattr(http_mod.asyncio, "sleep", clock.sleep)
    # The log's clock only: patching time.monotonic itself would move the event loop's.
    monkeypatch.setattr(http_mod, "_now", clock)
    return clock


# --------------------------------------------------------------------------- #
# The summary
# --------------------------------------------------------------------------- #


def test_one_request_has_no_gap():
    assert crawl.pacing_stats({"https://shop.test": [5.0]}) == {
        "requests": 1,
        "min_gap_s": None,
        "median_gap_s": None,
        "max_gap_s": None,
        "by_host": {
            "https://shop.test": {
                "requests": 1,
                "min_gap_s": None,
                "median_gap_s": None,
                "max_gap_s": None,
            }
        },
    }


def test_no_requests_is_zero_not_missing():
    assert crawl.pacing_stats({})["requests"] == 0


def test_gaps_are_measured_within_a_host_never_across_two():
    pacing = crawl.pacing_stats(
        {"https://a.test": [0.0, 15.0, 31.5], "https://b.test": [1.0, 21.0]}
    )
    assert pacing["requests"] == 5
    # a: 15, 16.5; b: 20. The 1 s between a's first and b's first is not a gap.
    assert (pacing["min_gap_s"], pacing["median_gap_s"], pacing["max_gap_s"]) == (15, 16.5, 20)
    assert pacing["gaps"] == {"15": 1, "16": 1, "20": 1}
    assert pacing["by_host"]["https://a.test"]["requests"] == 3
    assert pacing["by_host"]["https://b.test"]["min_gap_s"] == 20


def test_a_week_of_runs_merges_by_histogram_and_skips_runs_without_pacing():
    runs = [
        crawl.pacing_stats({"h": [0, 15, 30, 45]}),  # three gaps of 15
        crawl.pacing_stats({"h": [0, 20, 40]}),  # two of 20
        {"requests": 1, "min_gap_s": None},  # one request: nothing to add
    ]
    assert crawl.merge_gaps(runs) == (15, 15)
    assert crawl.merge_gaps([]) == (None, None)


def test_the_merged_median_is_floored_never_rounded_up():
    # 14.9 s is "14", not "15": the published figure must not flatter.
    assert crawl.merge_gaps([crawl.pacing_stats({"h": [0, 14.9]})]) == (14.9, 14)


def test_the_next_run_is_today_until_it_starts_then_tomorrow():
    morning = datetime(2026, 11, 9, 1, 30, tzinfo=UTC)
    assert crawl.next_refresh(morning, 3) == datetime(2026, 11, 9, 3, tzinfo=UTC)
    at_three = datetime(2026, 11, 9, 3, tzinfo=UTC)
    assert crawl.next_refresh(at_three, 3) == datetime(2026, 11, 10, 3, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #


def _client(statuses: list[int], sent: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(statuses.pop(0) if len(statuses) > 1 else statuses[0], json={})

    return http_mod.make_client(transport=httpx.MockTransport(handler))


async def test_a_retry_is_a_request_and_its_wait_is_a_gap(clock):
    """The shop sees the retry, so it keeps the published pace: a 2 s backoff
    still waits the host's 15 s."""
    http_mod.set_host_pace("https://shop.test", 15.0)
    sent: list[str] = []
    with http_mod.logging_requests(http_mod.RequestLog()) as log:
        async with _client([429, 200], sent) as client:
            await http_mod.get_json(client, "https://shop.test/a", retries=1, base_delay=2.0)

    pacing = log.pacing()
    assert pacing["requests"] == len(sent) == 2
    assert pacing["min_gap_s"] >= 15.0


async def test_the_backoff_still_grows_above_the_pace(clock):
    http_mod.set_host_pace("https://shop.test", 15.0)
    sent: list[str] = []
    with http_mod.logging_requests(http_mod.RequestLog()) as log:
        async with _client([503, 503, 503, 200], sent) as client:
            await http_mod.get_json(client, "https://shop.test/a", retries=3, base_delay=10.0)

    times = log.times["https://shop.test"]
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    assert len(sent) == 4
    # max(pace, 10·2^n + jitter): 15, then 20+, then 40+.
    assert 15.0 <= gaps[0] < 16.0
    assert 20.0 <= gaps[1] <= 20.5
    assert 40.0 <= gaps[2] <= 40.5


async def test_crawl_delay_raises_the_retry_floor(clock, monkeypatch):
    class _Slow(_AllowAll):
        def cached_crawl_delay(self, host, user_agent):
            return 30.0

    monkeypatch.setattr(robots_mod, "ROBOTS", _Slow())
    http_mod.set_host_pace("https://shop.test", 15.0)
    with http_mod.logging_requests() as log:
        async with _client([429, 200], []) as client:
            await http_mod.get_json(client, "https://shop.test/a", retries=1, base_delay=2.0)
    assert log.pacing()["min_gap_s"] >= 30.0


async def test_no_two_requests_to_a_host_go_out_closer_than_its_pace(clock):
    """Whatever code path sends them: here, two calls with no pause between."""
    http_mod.set_host_pace("https://shop.test", 15.0)
    with http_mod.logging_requests() as log:
        async with _client([200], []) as client:
            await http_mod.get_json(client, "https://shop.test/a")
            await http_mod.get_json(client, "https://shop.test/b")
            await http_mod.get_json(client, "https://other.test/c")  # another host: no wait
    pacing = log.pacing()
    assert pacing["by_host"]["https://shop.test"]["min_gap_s"] == 15.0


def _shop_with_robots(monkeypatch, sent: list[str], robots_txt: str = "User-agent: *\n"):
    """Pages and robots.txt from one fake host, through the real RobotsCache."""
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_txt)
        return httpx.Response(200, json={})

    def client(**kwargs):
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", client)
    return client


async def test_robots_txt_is_a_paced_and_counted_request(clock, monkeypatch):
    """Fetched before the first page, it is logged, and the page waits the
    full pace after it rather than going out on its heels."""
    sent: list[str] = []
    client = _shop_with_robots(monkeypatch, sent)
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache())
    http_mod.set_host_pace("https://shop.test", 15.0)

    with http_mod.logging_requests() as log:
        async with client() as c:
            await http_mod.get_json(c, "https://shop.test/a")

    assert sent == ["/robots.txt", "/a"]
    pacing = log.pacing()
    assert (pacing["requests"], pacing["robots"]) == (2, 1)
    assert pacing["min_gap_s"] == 15.0


async def test_a_robots_txt_refetch_mid_run_keeps_the_pace_both_sides(clock, monkeypatch):
    sent: list[str] = []
    client = _shop_with_robots(monkeypatch, sent)
    # Expired at once: every request re-reads it, the worst case of the hourly TTL.
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache(ttl=0))
    http_mod.set_host_pace("https://shop.test", 15.0)

    with http_mod.logging_requests() as log:
        async with client() as c:
            await http_mod.get_json(c, "https://shop.test/a")
            await clock.sleep(15.0)  # the pipeline's own pause between pages
            await http_mod.get_json(c, "https://shop.test/b")

    assert sent == ["/robots.txt", "/a", "/robots.txt", "/b"]
    pacing = log.pacing()
    assert pacing["robots"] == 2
    assert pacing["gaps"] == {"15": 3}


async def test_a_crawl_delay_read_from_robots_txt_paces_the_next_page(clock, monkeypatch):
    sent: list[str] = []
    client = _shop_with_robots(monkeypatch, sent, "User-agent: *\nCrawl-delay: 20\n")
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache())
    http_mod.set_host_pace("https://shop.test", 15.0)

    with http_mod.logging_requests() as log:
        async with client() as c:
            await http_mod.get_json(c, "https://shop.test/a")
    assert log.pacing()["min_gap_s"] == 20.0


def _redirecting_shop(routes: dict[str, httpx.Response], sent: list[str]) -> httpx.AsyncClient:
    """A client whose host answers each path from `routes` (200 for the rest)."""

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(f"{request.method} {request.url.path}")
        return routes.get(request.url.path, httpx.Response(200, json={}))

    return http_mod.make_client(transport=httpx.MockTransport(handler))


def _moved(status: int, to: str) -> httpx.Response:
    return httpx.Response(status, headers={"Location": to})


async def test_a_redirect_hop_waits_the_pace_and_is_counted(clock):
    """httpx following it sent the hop at once: two requests ms apart in the
    shop's logs, one of them missing from what /how-we-crawl publishes."""
    http_mod.set_host_pace("https://shop.test", 15.0)
    sent: list[str] = []
    routes = {"/a": _moved(301, "https://shop.test/a/"), "/a/": _moved(302, "/b")}
    with http_mod.logging_requests() as log:
        async with _redirecting_shop(routes, sent) as client:
            assert await http_mod.get_json(client, "https://shop.test/a") == {}

    assert sent == ["GET /a", "GET /a/", "GET /b"]
    pacing = log.pacing()
    assert pacing["requests"] == 3
    assert pacing["min_gap_s"] == 15.0


async def test_a_redirect_is_followed_the_way_httpx_would_have(clock):
    """Only when a hop goes out changes, never what it is: 307/308 keep the
    method and body, 303 turns into a GET."""
    sent: list[str] = []
    routes = {"/a": _moved(307, "/b"), "/b": _moved(303, "/c")}
    async with _redirecting_shop(routes, sent) as client:
        await http_mod.get_json(client, "https://shop.test/a", method="POST", json={"q": 1})
    assert sent == ["POST /a", "POST /b", "GET /c"]


async def test_a_redirect_robots_txt_disallows_is_not_followed(clock, monkeypatch):
    class _DenyB(_AllowAll):
        async def allowed(self, url, user_agent):
            return not url.endswith("/b")

    monkeypatch.setattr(robots_mod, "ROBOTS", _DenyB())
    sent: list[str] = []
    async with _redirecting_shop({"/a": _moved(301, "/b")}, sent) as client:
        with pytest.raises(robots_mod.DisallowedByRobots):
            await http_mod.get_json(client, "https://shop.test/a")
    assert sent == ["GET /a"]


async def test_a_redirect_loop_gives_up(clock):
    sent: list[str] = []
    async with _redirecting_shop({"/a": _moved(302, "/a")}, sent) as client:
        with pytest.raises(httpx.TooManyRedirects):
            await http_mod.get_json(client, "https://shop.test/a")
    assert len(sent) == 1 + http_mod.MAX_REDIRECTS


async def test_a_robots_txt_redirect_is_paced_and_counted_too(clock, monkeypatch):
    sent: list[str] = []
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        if request.url.path == "/robots.txt":
            return _moved(301, "/robots-live.txt")
        if request.url.path == "/robots-live.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, json={})

    def client(**kwargs):
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(robots_mod.httpx, "AsyncClient", client)
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache())
    http_mod.set_host_pace("https://shop.test", 15.0)

    with http_mod.logging_requests() as log:
        async with client() as c:
            await http_mod.get_json(c, "https://shop.test/a")
            with pytest.raises(robots_mod.DisallowedByRobots):
                await http_mod.get_json(c, "https://shop.test/private")

    assert sent == ["/robots.txt", "/robots-live.txt", "/a"]
    pacing = log.pacing()
    assert (pacing["requests"], pacing["robots"]) == (3, 2)
    assert pacing["min_gap_s"] == 15.0


@pytest.mark.parametrize(
    "spelled",
    ["HTTPS://Shop.TEST:443/x", "https://shop.test:443/x", "https://SHOP.test/x"],
)
def test_one_host_has_one_key_however_its_url_is_spelled(spelled):
    assert http_mod.host_of(spelled) == http_mod.host_of("https://shop.test/x")
    assert http_mod.host_of(spelled) == "https://shop.test"


def test_a_non_default_port_is_a_different_host():
    assert http_mod.host_of("https://shop.test:8443/x") == "https://shop.test:8443"
    assert http_mod.host_of("http://shop.test:443/x") == "http://shop.test:443"


async def test_robots_txt_and_pages_queue_at_one_gate_however_the_base_url_is_spelled(
    clock, monkeypatch
):
    """A source whose `base_url` is `HTTPS://Shop.TEST:443` reads robots.txt
    through that spelling and its pages through the shop's own links. Keyed
    apart, the page went out on robots.txt's heels and never saw its
    Crawl-delay."""
    sent: list[str] = []
    client = _shop_with_robots(monkeypatch, sent, "User-agent: *\nCrawl-delay: 20\n")
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache())
    http_mod.set_host_pace("HTTPS://Shop.TEST:443", 15.0)

    with http_mod.logging_requests() as log:
        # What the pipeline's pause does with the source's base_url.
        await robots_mod.polite_pause("HTTPS://Shop.TEST:443/x", 15.0)
        async with client() as c:
            await http_mod.get_json(c, "https://shop.test/x")

    assert sent == ["/robots.txt", "/x"]
    pacing = log.pacing()
    assert list(pacing["by_host"]) == ["https://shop.test"]
    assert (pacing["requests"], pacing["robots"]) == (2, 1)
    assert pacing["min_gap_s"] == 20.0


async def test_nothing_is_logged_outside_a_run(clock):
    sent: list[str] = []
    async with _client([200], sent) as client:
        await http_mod.get_json(client, "https://shop.test/a")
    assert sent and http_mod._REQUEST_LOG.get() is None


async def test_a_request_robots_refuses_is_not_logged(clock, monkeypatch):
    class _Deny(_AllowAll):
        async def allowed(self, url, user_agent):
            return False

    monkeypatch.setattr(robots_mod, "ROBOTS", _Deny())
    with http_mod.logging_requests() as log:
        async with _client([200], []) as client:
            with pytest.raises(robots_mod.DisallowedByRobots):
                await http_mod.get_json(client, "https://shop.test/private")
    assert log.pacing()["requests"] == 0


# --------------------------------------------------------------------------- #
# A run
# --------------------------------------------------------------------------- #


class _Shop(SourceAdapter):
    """Two partitions of two pages each, one HTTP request per page, plus a
    once-a-cycle part of two requests through the CycleFetcher."""

    source_id = "pacing-shop"
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug="pacing-shop", name="Pacing Shop")
    polite_delay = 15.0
    base_url = "https://shop.test"

    def __init__(self) -> None:
        self.sent: list[str] = []

    def partitions(self) -> list[str]:
        return ["a", "b"]

    def cycle_data_parts(self) -> list[str]:
        return ["tree"]

    def _transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.sent.append(request.url.path)
            return httpx.Response(200, json={})

        return httpx.MockTransport(handler)

    async def fetch_cycle_part(self, fetcher, part: str) -> object:
        await fetcher.get(part, f"{self.base_url}/tree/1")
        await fetcher.get(part, f"{self.base_url}/tree/2")
        return {}

    async def fetch_page(self, partition: str, page: int) -> Page:
        async with httpx.AsyncClient(transport=self._transport()) as client:
            await http_mod.get_json(client, f"{self.base_url}/{partition}/{page}")
        item = RawItem(
            source=self.source_id,
            external_id=f"{partition}{page}",
            title=f"Part {partition}{page}",
            price_text="10 EGP",
            availability_text="In stock",
        )
        return Page([item], has_more=page < 2)


async def test_a_run_records_every_request_and_every_gap(clock, monkeypatch):
    adapter = _Shop()

    def fetcher_client(**kwargs):
        return httpx.AsyncClient(transport=adapter._transport(), **kwargs)

    monkeypatch.setattr(http_mod, "make_client", fetcher_client)
    run = await run_source(adapter.source_id, adapter)

    pacing = run.stats["pacing"]
    # Two cycle-data requests and four pages: one count, the same both ways.
    assert pacing["requests"] == len(adapter.sent) == 6
    assert pacing["requests"] == sum(run.stats["requests"].values())
    # Five gaps, every one of them the 15 s pace: after the cycle data, between
    # pages, and between the two partitions.
    assert pacing["gaps"] == {"15": 5}
    assert (pacing["min_gap_s"], pacing["median_gap_s"], pacing["max_gap_s"]) == (15, 15, 15)
    assert list(pacing["by_host"]) == ["https://shop.test"]

    # Stored on the run's row, where the API reads it.
    async with pipeline.SessionLocal() as session:
        stored = (await session.execute(select(IngestionRun))).scalar_one()
    assert stored.stats["pacing"] == pacing


class _CutOffShop(_Shop):
    """The worker is stopped (a deploy) while partition b's first page is in flight."""

    async def fetch_page(self, partition: str, page: int) -> Page:
        if partition == "b":
            raise asyncio.CancelledError
        return await super().fetch_page(partition, page)


async def test_a_run_cut_off_mid_sweep_keeps_what_it_sent(clock, monkeypatch):
    """Stats used to be written only when a run ended, so a run a deploy cut
    short published no requests and no pacing: /how-we-crawl said "at least
    N" for its week. They are on the row from the first committed page, and
    closing the interrupted run keeps them."""
    from worker.main import close_interrupted_runs

    adapter = _CutOffShop()

    def fetcher_client(**kwargs):
        return httpx.AsyncClient(transport=adapter._transport(), **kwargs)

    monkeypatch.setattr(http_mod, "make_client", fetcher_client)
    with pytest.raises(asyncio.CancelledError):
        await run_source(adapter.source_id, adapter)

    async with pipeline.SessionLocal() as session:
        assert await close_interrupted_runs(session) == 1
        stored = (await session.execute(select(IngestionRun))).scalar_one()

    assert stored.status == IngestionStatus.FAILED
    # The cycle data's two requests and partition a's two pages: everything
    # sent before the cut, counted both ways.
    assert len(adapter.sent) == 4
    assert stored.stats["requests"] == {"tree": 2, "pages": 2}
    assert stored.stats["pacing"]["requests"] == 4
    assert stored.stats["pacing"]["gaps"] == {"15": 3}
