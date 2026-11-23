"""Sending from the crawl's IPv6 pool (worker/egress.py).

What matters: an IPv6 source's requests leave from the pool's addresses and
are counted per host and per address; a failure to connect over IPv6 falls
back to IPv4 and is counted with why; a response — a 403 or a 429 included —
never changes the address; the pace stays per host whatever the address; and
without a pool nothing changes at all.
"""

from __future__ import annotations

import socket
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus, SourceType
from makhzan_schemas.models import IngestionRun, Source

from worker import egress as egress_mod
from worker import http as http_mod
from worker import robots as robots_mod
from worker import status as status_mod
from worker.egress import IPV4, IPV4_ANY, IPV6, NO_IPV6_ADDRESS, NO_POOL, EgressTransport
from worker.sources.registry import build_adapter

#: Documentation-range addresses are not global, so tests build the transport
#: directly rather than through the environment's validated pool.
A1, A2, A3 = "2001:db8::1", "2001:db8::2", "2001:db8::3"
POOL = (A1, A2, A3)
#: Global addresses, for what reads the environment.
G1, G2 = "2607:f8b0:4005:80a::200e", "2a00:1450:4001:82f::200e"


class _AllowAll:
    async def allowed(self, url, user_agent):
        return True

    async def crawl_delay(self, url, user_agent):
        return None


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(robots_mod, "ROBOTS", _AllowAll())
    monkeypatch.delenv(egress_mod.POOL_ENV, raising=False)
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(http_mod.asyncio, "sleep", fake_sleep)
    return slept


class _Wire:
    """One fake transport per local address; records which address sent what."""

    def __init__(self, *, fail: dict[str, Exception] | None = None, status: int = 200):
        self.fail = fail or {}
        self.status = status
        self.sent: list[tuple[str, str]] = []
        self.bound: list[str] = []

    def transport_for(self, address: str) -> httpx.AsyncBaseTransport:
        self.bound.append(address)

        def handler(request: httpx.Request) -> httpx.Response:
            if address in self.fail:
                raise self.fail[address]
            self.sent.append((address, request.url.path))
            return httpx.Response(self.status, json={"from": address})

        return httpx.MockTransport(handler)


def _transport(wire: _Wire, egress: str = IPV6, pool=POOL, picks=None) -> EgressTransport:
    order = iter(picks or [])

    def choose(addresses):
        return next(order, addresses[0])

    return EgressTransport(egress, pool, choose=choose, transport_for=wire.transport_for)


# --------------------------------------------------------------------------- #
# The pool and the setting
# --------------------------------------------------------------------------- #


def _pool_file(tmp_path, monkeypatch, body: str):
    path = tmp_path / "crawl-pool.yaml"
    path.write_text(body)
    monkeypatch.setenv(egress_mod.POOL_ENV, str(path))
    egress_mod._POOL_CACHE.clear()
    egress_mod._LAST_GOOD.clear()
    return path


def test_the_pool_is_read_from_its_file_validated_deduplicated_and_sorted(tmp_path, monkeypatch):
    _pool_file(tmp_path, monkeypatch, f"# the crawl pool\nipv6:\n  - {G2}\n  - {G1}\n  - {G1}\n")
    assert egress_mod.configured_pool() == (G1, G2)


def test_no_file_named_is_no_pool_and_a_named_file_missing_is_an_error(tmp_path, monkeypatch):
    assert egress_mod.configured_pool() == ()
    monkeypatch.setenv(egress_mod.POOL_ENV, str(tmp_path / "gone.yaml"))
    with pytest.raises(ValueError, match="no such file"):
        egress_mod.configured_pool()


@pytest.mark.parametrize("bad", ["203.0.113.4", "not-an-address", "fd00::1", "::1", "2001:db8::1"])
def test_a_pool_entry_that_is_not_a_global_ipv6_address_is_refused(tmp_path, monkeypatch, bad):
    _pool_file(tmp_path, monkeypatch, f'ipv6:\n  - {G1}\n  - "{bad}"\n')
    with pytest.raises(ValueError, match="crawl-pool.yaml"):
        egress_mod.configured_pool()


@pytest.mark.parametrize("body", ["ipv6: 2607:f8b0:4005:80a::200e\n", "addresses: []\n", "- x\n"])
def test_a_pool_file_of_the_wrong_shape_is_refused(tmp_path, monkeypatch, body):
    _pool_file(tmp_path, monkeypatch, body)
    with pytest.raises(ValueError):
        egress_mod.configured_pool()


def test_a_pool_file_broken_after_a_good_read_keeps_the_last_good_pool(tmp_path, monkeypatch):
    """One bad commit, or a read mid-`git pull`, must not make every client raise."""
    import os

    path = _pool_file(tmp_path, monkeypatch, f"ipv6: [{G1}]\n")
    assert egress_mod.configured_pool() == (G1,)
    path.write_text("ipv6: [not-an-address\n")
    os.utime(path, (1, 2))
    assert egress_mod.configured_pool() == (G1,)
    path.unlink()
    assert egress_mod.configured_pool() == (G1,)


async def test_a_bad_pool_file_at_startup_stops_the_worker(tmp_path, monkeypatch):
    from worker import main as main_mod

    _pool_file(tmp_path, monkeypatch, "ipv6: [nope]\n")
    loaded = []

    async def load_adapters():
        loaded.append(True)

    monkeypatch.setattr(main_mod, "load_adapters", load_adapters)
    with pytest.raises(ValueError, match="crawl-pool.yaml"):
        await main_mod.startup({})
    assert loaded == []


def test_an_edited_pool_file_is_read_again(tmp_path, monkeypatch):
    import os

    path = _pool_file(tmp_path, monkeypatch, f"ipv6: [{G1}]\n")
    assert egress_mod.configured_pool() == (G1,)
    path.write_text(f"ipv6: [{G1}, {G2}]\n")
    os.utime(path, (1, 2))  # a different mtime, whatever the clock's resolution
    assert egress_mod.configured_pool() == (G1, G2)


def _source(**config) -> Source:
    return Source(
        source_id="shop",
        adapter="fixture",
        supplier={"slug": "shop", "name": "Shop"},
        enabled=True,
        config=config,
    )


def test_a_source_is_ipv4_unless_its_config_says_ipv6():
    assert build_adapter(_source()).egress == IPV4
    assert build_adapter(_source(egress="ipv6")).egress == IPV6
    with pytest.raises(ValueError, match="egress"):
        build_adapter(_source(egress="ipv7"))


def test_without_a_pool_an_ipv4_client_is_built_exactly_as_before(monkeypatch):
    assert egress_mod.transport_for_run() is None
    client = http_mod.make_client()
    assert type(client._transport) is httpx.AsyncHTTPTransport


def test_with_a_pool_an_ipv4_source_binds_ipv4_only(tmp_path, monkeypatch):
    """A server that now has IPv6 must not send an IPv4 source's requests over it."""
    _pool_file(tmp_path, monkeypatch, f"ipv6: [{G1}, {G2}]\n")
    bound: list[str] = []
    monkeypatch.setattr(
        egress_mod, "http_transport", lambda a: bound.append(a) or httpx.MockTransport(None)
    )
    transport = egress_mod.transport_for_run()
    assert isinstance(transport, EgressTransport) and transport.egress == IPV4
    assert bound == [IPV4_ANY]


def test_an_ipv6_run_takes_the_pool_from_its_file(tmp_path, monkeypatch):
    _pool_file(tmp_path, monkeypatch, f"ipv6: [{G1}, {G2}]\n")
    bound: list[str] = []
    monkeypatch.setattr(
        egress_mod, "http_transport", lambda a: bound.append(a) or httpx.MockTransport(None)
    )
    with egress_mod.using_egress(IPV6):
        transport = egress_mod.transport_for_run()
    assert transport._addresses == [G1, G2]
    # Only IPv4 up front: a pool address's connections are built when chosen.
    assert bound == [IPV4_ANY]


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #


async def test_requests_leave_from_the_chosen_pool_address_and_are_counted():
    wire = _Wire()
    with http_mod.logging_requests() as log:
        async with httpx.AsyncClient(transport=_transport(wire, picks=[A2, A3, A2])) as client:
            for _ in range(3):
                await client.get("https://shop.test/p")
    assert [a for a, _ in wire.sent] == [A2, A3, A2]
    assert log.egress_stats() == {"https://shop.test": {"ipv6": 3, "addresses": {A2: 2, A3: 1}}}


async def test_a_failed_ipv6_connection_falls_back_to_ipv4_and_names_the_address():
    wire = _Wire(fail={A1: httpx.ConnectError("Connection refused")})
    with http_mod.logging_requests() as log:
        async with httpx.AsyncClient(transport=_transport(wire, picks=[A1, A2])) as client:
            assert (await client.get("https://shop.test/p")).json() == {"from": IPV4_ANY}
            assert (await client.get("https://shop.test/p")).json() == {"from": A2}
    assert log.egress_stats() == {
        "https://shop.test": {
            "ipv6": 1,
            "fallback": 1,
            "fallback_reasons": {"ConnectError": 1},
            "addresses": {A2: 1},
            "address_failures": {A1: 1},
        }
    }


async def test_a_host_without_an_ipv6_address_is_counted_as_such():
    error = httpx.ConnectError("[Errno -5] No address associated with hostname")
    error.__cause__ = socket.gaierror(-5, "No address associated with hostname")
    wire = _Wire(fail={A1: error})
    with http_mod.logging_requests() as log:
        async with httpx.AsyncClient(transport=_transport(wire, picks=[A1])) as client:
            await client.get("https://shop.test/p")
    assert log.egress_stats()["https://shop.test"]["fallback_reasons"] == {NO_IPV6_ADDRESS: 1}


async def test_a_connect_timeout_falls_back_but_a_read_timeout_does_not():
    """A read timeout may mean the shop got the request: sending it again would be twice."""
    wire = _Wire(fail={A1: httpx.ConnectTimeout("slow"), A2: httpx.ReadTimeout("slow")})
    async with httpx.AsyncClient(transport=_transport(wire, picks=[A1, A2])) as client:
        assert (await client.get("https://shop.test/p")).json() == {"from": IPV4_ANY}
        with pytest.raises(httpx.ReadTimeout):
            await client.get("https://shop.test/p")


@pytest.mark.parametrize("status", [403, 429])
async def test_a_refusal_is_an_answer_and_never_changes_the_address(status):
    wire = _Wire(status=status)
    with http_mod.logging_requests() as log:
        async with httpx.AsyncClient(transport=_transport(wire, picks=[A1])) as client:
            assert (await client.get("https://shop.test/p")).status_code == status
    assert wire.sent == [(A1, "/p")]
    assert "fallback" not in log.egress_stats()["https://shop.test"]


async def test_an_ipv6_source_with_no_pool_goes_over_ipv4_and_says_why():
    wire = _Wire()
    with http_mod.logging_requests() as log:
        async with httpx.AsyncClient(transport=_transport(wire, pool=())) as client:
            await client.get("https://shop.test/p")
    assert wire.sent == [(IPV4_ANY, "/p")]
    assert log.egress_stats()["https://shop.test"]["fallback_reasons"] == {NO_POOL: 1}


async def test_the_pace_stays_per_host_whatever_the_address(monkeypatch, _isolated):
    """Two requests from two pool addresses still wait the host's pace between them."""
    wire = _Wire()
    clock = [1000.0]
    monkeypatch.setattr(http_mod, "_now", lambda: clock[0])
    monkeypatch.setattr(http_mod.time, "monotonic", lambda: clock[0])

    async def sleep(seconds):
        _isolated.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(http_mod.asyncio, "sleep", sleep)
    http_mod.set_host_pace("https://shop.test", 15.0)
    with http_mod.logging_requests() as log:
        client = http_mod.make_client(transport=_transport(wire, picks=[A1, A2]))
        async with client:
            await http_mod.get_json(client, "https://shop.test/a")
            await http_mod.get_json(client, "https://shop.test/b")
    assert [a for a, _ in wire.sent] == [A1, A2]
    times = log.times["https://shop.test"]
    assert times[1] - times[0] >= 15.0


# --------------------------------------------------------------------------- #
# What the run records, and what status shows
# --------------------------------------------------------------------------- #


def test_an_ipv4_source_without_a_pool_records_no_egress():
    from worker.pipeline import _egress_stats

    adapter = build_adapter(_source())
    assert _egress_stats(adapter, http_mod.RequestLog()) == {}


def test_an_ipv6_source_records_its_mode_pool_and_hosts(tmp_path, monkeypatch):
    from worker.pipeline import _egress_stats

    _pool_file(tmp_path, monkeypatch, f"ipv6: [{G1}, {G2}]\n")
    adapter = build_adapter(_source(egress="ipv6"))
    log = http_mod.RequestLog()
    log.note_egress("shop.test", address=G1)
    assert _egress_stats(adapter, log) == {
        "mode": "ipv6",
        "pool": 2,
        "hosts": {"shop.test": {"ipv6": 1, "addresses": {G1: 1}}},
    }


async def test_status_shows_a_weeks_fallbacks_and_flags_a_failing_shop():
    now = datetime.now(timezone.utc)

    def run(source, days_ago, hosts):
        return IngestionRun(
            source=source,
            source_type=SourceType.SCRAPED,
            status=IngestionStatus.SUCCESS,
            started_at=now - timedelta(days=days_ago),
            stats={"egress": {"mode": "ipv6", "pool": 3, "hosts": hosts}},
        )

    async with SessionLocal() as session:
        for source_id in ("good", "bad", "plain"):
            session.add(
                Source(
                    source_id=source_id,
                    adapter="fixture",
                    supplier={"slug": source_id, "name": source_id},
                    config={} if source_id == "plain" else {"egress": "ipv6"},
                )
            )
        session.add(run("good", 1, {"good.test": {"ipv6": 50, "addresses": {A1: 30, A2: 20}}}))
        session.add(
            run(
                "bad",
                2,
                {
                    "bad.test": {
                        "ipv6": 8,
                        "fallback": 2,
                        "fallback_reasons": {"ConnectTimeout": 2},
                        "addresses": {A1: 8},
                        "address_failures": {A3: 2},
                    }
                },
            )
        )
        # Older than a week: in the month's totals, not the week's share.
        session.add(run("bad", 20, {"bad.test": {"fallback": 40, "address_failures": {A3: 40}}}))
        session.add(run("good", 2, {"good.test": {"fallback": 1, "address_failures": {A3: 1}}}))
        await session.commit()

        data = await status_mod.collect_egress(session, None)
        rows = {r["source"]: r for r in data["sources"]}
        await status_mod.egress(session, None)  # prints without raising

    bad, good = rows["bad"], rows["good"]
    assert bad["window"] == {"ipv6": 8, "ipv4": 0, "fallback": 42}
    assert (bad["week_fallback"], bad["week_attempts"]) == (2, 10)
    assert bad["flagged"] and not good["flagged"]
    assert good["max_per_address"] == 30 and good["addresses_used"] == 2
    assert rows["plain"]["configured"] == "ipv4" and rows["plain"]["runs"] == 0
    # One address failing for two shops is the address.
    assert data["address_failures"] == {A3: {"bad": 42, "good": 1}}


async def test_no_pool_on_the_worker_is_not_counted_as_the_shop_failing():
    async with SessionLocal() as session:
        session.add(
            Source(
                source_id="early",
                adapter="fixture",
                supplier={"slug": "early", "name": "early"},
                config={"egress": "ipv6"},
            )
        )
        session.add(
            IngestionRun(
                source="early",
                source_type=SourceType.SCRAPED,
                status=IngestionStatus.SUCCESS,
                stats={
                    "egress": {
                        "mode": "ipv6",
                        "pool": 0,
                        "hosts": {"e.test": {"fallback": 9, "fallback_reasons": {NO_POOL: 9}}},
                    }
                },
            )
        )
        await session.commit()
        (row,) = (await status_mod.collect_egress(session, "early"))["sources"]
    assert row["no_pool"] == 9 and row["week_attempts"] == 0 and not row["flagged"]


# --------------------------------------------------------------------------- #
# Checking the pool
# --------------------------------------------------------------------------- #


async def test_the_check_says_which_addresses_work_and_that_they_send_as_themselves(monkeypatch):
    def transport_for(address):
        def handler(request):
            if address == G2:
                raise httpx.ConnectError("Network is unreachable")
            return httpx.Response(200, text=address)

        return httpx.MockTransport(handler)

    monkeypatch.setattr(egress_mod, "http_transport", transport_for)
    results = await egress_mod.check_pool((G1, G2))
    assert results[0] == {"address": G1, "ok": True, "status": 200, "seen": G1}
    assert results[1]["ok"] is False and "ConnectError" in results[1]["error"]


async def test_the_check_fails_an_address_the_server_does_not_send_from(monkeypatch):
    monkeypatch.setattr(
        egress_mod,
        "http_transport",
        lambda a: httpx.MockTransport(lambda r: httpx.Response(200, text=G2)),
    )
    (result,) = await egress_mod.check_pool((G1,))
    assert result["ok"] is False and result["seen"] == G2


# --------------------------------------------------------------------------- #
# The pool file's publishing keys, and a dedicated IPv4 address
# --------------------------------------------------------------------------- #

V4 = "8.8.8.8"


def test_publish_states_the_addresses_with_their_reverse_dns(tmp_path, monkeypatch):
    _pool_file(
        tmp_path,
        monkeypatch,
        f"ipv6: [{G1}, {G2}]\nipv4:\n  - address: {V4}\n    shared: true\n"
        "reverse_dns: Crawler.Example.dev.\npublish: true\n",
    )
    config = egress_mod.configured_pool_config()
    assert config.published() == {
        "reverse_dns": "crawler.example.dev",
        "ipv6": [G1, G2],
        "ipv4": [{"address": V4, "shared": True}],
    }
    # Shared: published, never bound.
    assert config.ipv4_bind == IPV4_ANY


def test_nothing_is_published_until_the_file_says_so(tmp_path, monkeypatch):
    _pool_file(tmp_path, monkeypatch, f"ipv6: [{G1}]\nreverse_dns: crawler.example.dev\n")
    assert egress_mod.configured_pool_config().published() is None


@pytest.mark.parametrize(
    "body",
    [
        "ipv6: []\npublish: true\n",  # publish without a reverse DNS name
        "ipv6: []\npublish: yes please\n",
        "ipv6: []\nreverse_dns: not a host\n",
        "ipv6: []\nipv4: [10.0.0.1]\n",
        "ipv6: []\nipv4:\n  - address: 10.0.0.1\n",  # not global
        "ipv6: []\nipv4:\n  - address: 8.8.8.8\n    shared: maybe\n",
    ],
)
def test_bad_publishing_keys_are_refused(tmp_path, monkeypatch, body):
    _pool_file(tmp_path, monkeypatch, body)
    with pytest.raises(ValueError):
        egress_mod.configured_pool_config()


def test_a_dedicated_ipv4_address_is_bound_for_every_ipv4_connection(tmp_path, monkeypatch):
    _pool_file(tmp_path, monkeypatch, f"ipv6: []\nipv4:\n  - address: {V4}\n    shared: false\n")
    bound: list[str] = []
    monkeypatch.setattr(
        egress_mod, "http_transport", lambda a: bound.append(a) or httpx.MockTransport(None)
    )
    transport = egress_mod.transport_for_run()
    assert isinstance(transport, EgressTransport)
    assert bound == [V4]


async def test_the_worker_publishes_and_unpublishes_the_list(tmp_path, monkeypatch):
    from makhzan_schemas import crawl

    from worker import main as main_mod

    path = _pool_file(
        tmp_path,
        monkeypatch,
        f"ipv6: [{G1}]\nreverse_dns: crawler.example.dev\npublish: true\n",
    )
    async with SessionLocal() as session:
        await main_mod.publish_crawl_addresses(session)
        found = await crawl.crawl_addresses_in(session)
        assert found is not None and found[0]["ipv6"] == [G1]

        import os

        path.write_text(f"ipv6: [{G1}]\nreverse_dns: crawler.example.dev\npublish: false\n")
        os.utime(path, (1, 2))
        await main_mod.publish_crawl_addresses(session)
        assert await crawl.crawl_addresses_in(session) is None


def test_publishing_nothing_is_refused(tmp_path, monkeypatch):
    _pool_file(tmp_path, monkeypatch, "ipv6: []\nreverse_dns: crawler.example.dev\npublish: true\n")
    with pytest.raises(ValueError, match="no addresses"):
        egress_mod.configured_pool_config()
