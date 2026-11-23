"""GET /crawler/addresses: the crawler's addresses, once the owner publishes them.

The worker states them from the private pool file (worker/egress.py); until
the file says `publish: true` there is nothing, and the endpoint answers 404 so
the page shows no list. Each address in the answer is one a shop can allow.
"""

from __future__ import annotations

from makhzan_schemas import crawl

V6 = ["2607:f8b0:4005:80a::200e", "2a00:1450:4001:82f::200e"]


async def test_nothing_is_published_until_the_worker_states_it(client, db):
    response = await client.get("/crawler/addresses")
    assert response.status_code == 404


async def test_the_published_addresses_and_their_reverse_dns(client, db):
    await crawl.record_crawl_addresses(
        db,
        {
            "reverse_dns": "crawler.example.dev",
            "ipv6": V6,
            "ipv4": [{"address": "8.8.8.8", "shared": True}],
        },
    )
    response = await client.get("/crawler/addresses")
    assert response.status_code == 200
    body = response.json()
    assert body["reverse_dns"] == "crawler.example.dev"
    assert body["ipv6"] == V6
    assert body["ipv4"] == [{"address": "8.8.8.8", "shared": True}]
    assert body["updated_at"]


async def test_unpublishing_removes_the_list(client, db):
    await crawl.record_crawl_addresses(db, {"reverse_dns": "crawler.example.dev", "ipv6": V6})
    await crawl.record_crawl_addresses(db, None)
    assert (await client.get("/crawler/addresses")).status_code == 404
