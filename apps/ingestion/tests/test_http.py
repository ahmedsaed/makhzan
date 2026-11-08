"""`Retry-After` is a floor, and it binds every request to that host.

A survey of one shop, after a 429 carrying `Retry-After: 60`, sent six more
requests at 12-second spacing. The crawler must never do that: a retry waits at
least what the host asked, a wait longer than the cap is not retried in this run,
and a host that asked us to hold back is not sent anything — from any partition —
until the time has passed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from worker import http as http_mod
from worker import robots as robots_mod


class _AllowAll:
    async def allowed(self, url, user_agent):
        return True

    async def crawl_delay(self, url, user_agent):
        return None


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """No robots.txt fetch, no real sleeping, no state carried between tests."""
    monkeypatch.setattr(robots_mod, "ROBOTS", _AllowAll())
    monkeypatch.setattr(http_mod, "_NOT_BEFORE", {})
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(http_mod.asyncio, "sleep", fake_sleep)
    return slept


def _client(responses: list[httpx.Response], sent: list[str]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return responses.pop(0) if len(responses) > 1 else responses[0]

    return http_mod.make_client(transport=httpx.MockTransport(handler))


async def test_a_retry_waits_at_least_what_the_host_asked(_isolated):
    sent: list[str] = []
    client = _client(
        [httpx.Response(429, headers={"Retry-After": "60"}), httpx.Response(200, json={"ok": 1})],
        sent,
    )
    async with client:
        assert await http_mod.get_json(client, "https://shop.test/products.json") == {"ok": 1}
    assert len(sent) == 2
    assert sum(_isolated) >= 60, "the retry went out before the host's Retry-After"


async def test_a_503_with_an_http_date_is_honoured_too(_isolated):
    later = datetime.now(UTC) + timedelta(seconds=120)
    sent: list[str] = []
    client = _client(
        [
            httpx.Response(503, headers={"Retry-After": format_datetime(later, usegmt=True)}),
            httpx.Response(200, json={}),
        ],
        sent,
    )
    async with client:
        await http_mod.get_json(client, "https://shop.test/a")
    assert sum(_isolated) >= 110


async def test_a_wait_beyond_the_cap_is_not_retried_and_holds_the_host(_isolated):
    """Asked for an hour: give up for this run, and send that host nothing more —
    not even another URL, the way the next partition would."""
    sent: list[str] = []
    client = _client([httpx.Response(429, headers={"Retry-After": "3600"})], sent)
    async with client:
        with pytest.raises(httpx.HTTPStatusError):
            await http_mod.get_json(client, "https://shop.test/a")
        assert len(sent) == 1, "a request was retried long before the host allowed it"
        assert not _isolated or max(_isolated) < 3600

        with pytest.raises(http_mod.HostBackingOff):
            await http_mod.get_json(client, "https://shop.test/collections/b/products.json")
    assert len(sent) == 1

    # Another host is not held back by this one.
    other: list[str] = []
    async with _client([httpx.Response(200, json={})], other) as client:
        await http_mod.get_json(client, "https://other.test/a")
    assert len(other) == 1


async def test_the_next_request_to_a_host_waits_out_its_retry_after(_isolated):
    """Retries exhausted on a 429 asking for 60 s: the next call — a new
    partition, say — must still wait for it, not go out at once."""
    sent: list[str] = []
    client = _client([httpx.Response(429, headers={"Retry-After": "60"})], sent)
    async with client:
        with pytest.raises(httpx.HTTPStatusError):
            await http_mod.get_json(client, "https://shop.test/a", retries=0)
        _isolated.clear()
        with pytest.raises(httpx.HTTPStatusError):
            await http_mod.get_json(client, "https://shop.test/b", retries=0)
    assert _isolated and _isolated[0] > 55, "the second request ignored the first Retry-After"


async def test_without_retry_after_it_still_backs_off(_isolated):
    sent: list[str] = []
    client = _client([httpx.Response(503), httpx.Response(200, json={})], sent)
    async with client:
        await http_mod.get_json(client, "https://shop.test/a", base_delay=2.0)
    assert len(sent) == 2 and _isolated[0] >= 2.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [("60", 60.0), ("0", 0.0), (None, None), ("", None), ("soon", None), ("-5", None)],
)
def test_retry_after_is_read_as_seconds(value, expected):
    assert http_mod.retry_after_seconds(value) == expected


def test_retry_after_dates_in_the_past_mean_now():
    past = format_datetime(datetime.now(UTC) - timedelta(minutes=5), usegmt=True)
    assert http_mod.retry_after_seconds(past) == 0.0


async def test_robots_is_checked_against_the_query_string_too(monkeypatch):
    """`Disallow: /collections/*sort_by*` is about the query, which `params` adds."""
    rules = robots_mod.Rules("User-agent: *\nDisallow: /collections/*sort_by*\n")

    class _Cache:
        async def allowed(self, url, user_agent):
            return rules.allowed(url, user_agent)

    monkeypatch.setattr(robots_mod, "ROBOTS", _Cache())
    sent: list[str] = []
    async with _client([httpx.Response(200, json={})], sent) as client:
        with pytest.raises(robots_mod.DisallowedByRobots):
            await http_mod.get_json(client, "https://shop.test/collections/x", {"sort_by": "p"})
        await http_mod.get_json(client, "https://shop.test/collections/x", {"page": 2})
    assert sent == ["https://shop.test/collections/x?page=2"]
