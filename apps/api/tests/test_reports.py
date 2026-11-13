"""POST /reports: "Report a problem", the API's first write from a visitor.

What is stored (the report, resolved to the product as it is now, with a
snapshot of what the page showed), what is refused, what is dropped without a
word (spam), and the per-address limits. The shops are fictional.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_category, make_listing, make_product, make_supplier
from app.routers.reports import issue_token
from httpx import ASGITransport, AsyncClient
from makhzan_schemas.models import ProductRedirect, Report
from sqlalchemy import func, select, update

SALT = "test-salt"


@pytest.fixture(autouse=True)
def _salt(monkeypatch):
    monkeypatch.setenv("REPORT_IP_SALT", SALT)
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_NETWORKS", raising=False)


def _hash(key: str) -> str:
    return hmac.new(SALT.encode(), key.encode(), hashlib.sha256).hexdigest()


async def _two_shop_product(db):
    category = await make_category(db, slug="stepper-drivers", name_en="Stepper drivers")
    delta = await make_supplier(db, slug="delta-components", name="Delta Components")
    giza = await make_supplier(db, slug="giza-robotics", name="Giza Robotics")
    product = await make_product(
        db, title_en="TB6600 Stepper Motor Driver 4A", category=category, offer_count=2
    )
    a = await make_listing(
        db,
        supplier=delta,
        product=product,
        title_en="TB6600 Stepper Motor Driver 4A 9-42V",
        price="425.00",
    )
    b = await make_listing(
        db,
        supplier=giza,
        product=product,
        title_en="TB6600 4A Stepper Driver Module",
        price="504.00",
    )
    return product, a, b


def _body(product, **fields) -> dict:
    return {"product_id": str(product.id), "token": _token(12), **fields}


def _token(seconds_ago: float) -> str:
    """An opened-at token as the API signs it, for a form opened that long ago."""
    return issue_token(SALT.encode(), int((time.time() - seconds_ago) * 1000))


async def _post(client, body, ip="198.51.100.7", **headers):
    return await client.post("/reports", json=body, headers={"x-forwarded-for": ip, **headers})


async def _reports(db) -> list[Report]:
    # Fresh from the database: the request committed through its own session.
    query = select(Report).order_by(Report.id).execution_options(populate_existing=True)
    return list(await db.scalars(query))


async def test_a_report_is_stored_with_a_snapshot_of_every_offer(client, db):
    product, a, b = await _two_shop_product(db)
    response = await _post(
        client,
        _body(
            product,
            reason="offers_not_same",
            offer_ids=[str(b.id)],
            description="  The Giza one is a smaller module.  ",
            email="buyer@example.com",
        ),
    )
    assert response.status_code == 202
    [report] = await _reports(db)
    assert response.json() == {"reference": f"R-{report.id}"}
    assert report.product_id == product.id
    assert report.reported_product_id is None
    assert report.reason == "offers_not_same"
    assert report.offer_ids == [str(b.id)]
    assert report.description == "The Giza one is a smaller module."
    assert report.email == "buyer@example.com"
    assert report.status == "new" and report.reviewed_at is None
    snap = report.snapshot["product"]
    assert snap["title"] == "TB6600 Stepper Motor Driver 4A"
    assert snap["category"] == "electronics:stepper-drivers"
    # Every offer, the ticked one marked: an unticked offer is half of every
    # "different" pair the review can later make.
    assert [(x["title"], x["shop"]["name"], x["price"], x["ticked"]) for x in snap["listings"]] == [
        ("TB6600 Stepper Motor Driver 4A 9-42V", "Delta Components", "425.00", False),
        ("TB6600 4A Stepper Driver Module", "Giza Robotics", "504.00", True),
    ]
    assert report.snapshot["other_product"] is None


async def test_the_snapshot_keeps_what_the_page_showed_after_a_recrawl(client, db):
    product, a, _ = await _two_shop_product(db)
    await _post(
        client,
        _body(
            product,
            reason="wrong_price_stock",
            offer_ids=[str(a.id)],
            field="price",
            correct_value="EGP 460",
        ),
    )
    a.price = 999
    a.title_en = "Something else"
    await db.commit()
    [report] = await _reports(db)
    assert report.snapshot["product"]["listings"][0]["price"] == "425.00"
    assert report.snapshot["product"]["listings"][0]["title"].startswith("TB6600")
    assert (report.field, report.correct_value) == ("price", "EGP 460")


async def test_a_merged_id_is_reported_against_the_product_it_became(client, db):
    product, a, _ = await _two_shop_product(db)
    old = await make_product(db, title_en="TB6600 old")
    await db.execute(update(type(old)).where(type(old).id == old.id).values(merged_into=product.id))
    await db.commit()
    response = await _post(
        client, {**_body(product, reason="wrong_category"), "product_id": str(old.id)}
    )
    assert response.status_code == 202
    [report] = await _reports(db)
    assert report.product_id == product.id
    assert report.reported_product_id == old.id
    assert report.field == "category"


async def test_an_id_from_before_permanent_ids_follows_its_redirect(client, db):
    product, _, _ = await _two_shop_product(db)
    legacy = uuid.uuid4()
    db.add(ProductRedirect(old_id=legacy, new_id=product.id))
    await db.commit()
    response = await _post(
        client, {**_body(product, reason="wrong_category"), "product_id": str(legacy)}
    )
    assert response.status_code == 202
    [report] = await _reports(db)
    assert (report.product_id, report.reported_product_id) == (product.id, legacy)


async def test_an_unknown_product_is_a_404(client, db):
    response = await _post(
        client,
        {
            "product_id": str(uuid.uuid4()),
            "reason": "other",
            "description": "Typo in the title",
            "token": _token(9),
        },
    )
    assert response.status_code == 404
    assert await _reports(db) == []


async def test_same_as_another_product_snapshots_both(client, db):
    product, _, _ = await _two_shop_product(db)
    nile = await make_supplier(db, slug="nile-parts", name="Nile Parts")
    other = await make_product(db, title_en="TB6600 Stepper Driver 4.5A")
    await make_listing(db, supplier=nile, product=other, title_en="TB6600 4.5A", price="480.00")
    response = await _post(
        client,
        _body(product, reason="same_as_other", other_product_id=str(other.id)),
    )
    assert response.status_code == 202
    [report] = await _reports(db)
    assert report.other_product_id == other.id
    assert report.offer_ids == []
    theirs = report.snapshot["other_product"]
    assert theirs["title"] == "TB6600 Stepper Driver 4.5A"
    assert [x["shop"]["name"] for x in theirs["listings"]] == ["Nile Parts"]


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"reason": "offers_not_same"}, "tick at least one offer"),
        ({"reason": "same_as_other"}, "pick the other product"),
        ({"reason": "wrong_price_stock", "field": "price"}, "choose the offer"),
        ({"reason": "wrong_details"}, "say which detail"),
        ({"reason": "wrong_details", "field": "price"}, "say which detail"),
        ({"reason": "other", "description": "bad"}, "in a few words"),
        ({"reason": "other", "description": "Typo here", "email": "nope@"}, "email"),
        ({"reason": "not_a_reason"}, None),
    ],
)
async def test_an_incomplete_report_is_refused(client, db, fields, message):
    product, _, _ = await _two_shop_product(db)
    response = await _post(client, _body(product, **fields))
    assert response.status_code == 422
    if message:
        assert message in response.json()["detail"]
    assert await _reports(db) == []


async def test_offers_must_be_this_products(client, db):
    product, _, _ = await _two_shop_product(db)
    stranger = await make_listing(db, supplier=await make_supplier(db), title_en="Other")
    response = await _post(
        client, _body(product, reason="offers_not_same", offer_ids=[str(stranger.id)])
    )
    assert response.status_code == 422


async def test_offers_not_the_same_needs_two_offers(client, db):
    shop = await make_supplier(db)
    product = await make_product(db)
    only = await make_listing(db, supplier=shop, product=product)
    response = await _post(
        client, _body(product, reason="offers_not_same", offer_ids=[str(only.id)])
    )
    assert response.status_code == 422


async def test_a_stock_report_says_one_of_three_things(client, db):
    product, a, _ = await _two_shop_product(db)
    bad = await _post(
        client,
        _body(
            product,
            reason="wrong_price_stock",
            offer_ids=[str(a.id)],
            field="stock",
            correct_value="maybe",
        ),
    )
    assert bad.status_code == 422
    good = await _post(
        client,
        _body(
            product,
            reason="wrong_price_stock",
            offer_ids=[str(a.id)],
            field="stock",
            correct_value="out_of_stock",
        ),
    )
    assert good.status_code == 202


async def test_answers_a_reason_does_not_take_are_dropped(client, db):
    product, a, _ = await _two_shop_product(db)
    await _post(
        client,
        _body(
            product,
            reason="other",
            description="The title has a typo",
            offer_ids=[str(a.id)],
            field="price",
            correct_value="EGP 1",
        ),
    )
    [report] = await _reports(db)
    assert (report.offer_ids, report.field, report.correct_value) == ([], None, None)


@pytest.mark.parametrize(
    "extra",
    [
        {"website": "https://spam.example"},  # the honeypot
        {"token": None},  # a client that never opened the form
        {"token": "garbage"},
        {"token": f"{int(time.time() * 1000) - 60_000}.{'0' * 32}"},  # forged
        {"token": issue_token(b"another-secret", int(time.time() * 1000) - 60_000)},
        {"token": None, "elapsed_ms": 60_000},  # what the page says is not evidence
        {"description": "x" * 1001},
        {"description": "see http://a.example http://b.example www.c.example"},
    ],
)
async def test_spam_is_answered_as_if_stored_and_dropped(client, db, extra):
    product, _, _ = await _two_shop_product(db)
    body = {**_body(product, reason="other", description="A real problem here"), **extra}
    response = await _post(client, body)
    assert response.status_code == 202
    assert response.json() == {"reference": None}
    assert await _reports(db) == []


async def test_the_limits_themselves_are_kept(client, db):
    product, _, _ = await _two_shop_product(db)
    body = _body(product, reason="other", description="x" * 1000)
    assert (await _post(client, body)).json()["reference"]
    two_links = _body(
        product, reason="wrong_category", description="http://a.example and http://b.example"
    )
    assert (await _post(client, two_links)).json()["reference"]


async def test_the_same_report_from_the_same_address_counts_once_a_day(client, db):
    product, a, b = await _two_shop_product(db)
    body = _body(product, reason="offers_not_same", offer_ids=[str(b.id)])
    first = (await _post(client, body)).json()["reference"]
    again = (await _post(client, {**body, "offer_ids": [str(a.id)]})).json()["reference"]
    assert again == first
    # Another reason, or another address, is another report.
    await _post(client, _body(product, reason="wrong_category"))
    await _post(client, body, ip="203.0.113.50")
    assert len(await _reports(db)) == 3
    # A day later the same one counts again.
    await db.execute(
        update(Report).values(created_at=datetime.now(UTC) - timedelta(days=1, minutes=1))
    )
    await db.commit()
    assert (await _post(client, body)).json()["reference"] != first


async def _distinct_products(db, n):
    shop = await make_supplier(db)
    products = []
    for i in range(n):
        product = await make_product(db, title_en=f"Part {i}")
        await make_listing(db, supplier=shop, product=product, title_en=f"Part {i}")
        products.append(product)
    return products


async def test_five_an_hour_then_too_many(client, db):
    products = await _distinct_products(db, 6)
    for product in products[:5]:
        response = await _post(client, _body(product, reason="wrong_category"))
        assert response.status_code == 202
    over = await _post(client, _body(products[5], reason="wrong_category"))
    assert over.status_code == 429
    detail = over.json()["detail"]
    assert detail["limit"] == "hour" and detail["count"] == 5
    assert 55 <= detail["retry_after_minutes"] <= 60
    assert int(over.headers["retry-after"]) == detail["retry_after_minutes"] * 60
    assert len(await _reports(db)) == 5
    # Somebody else is not held back.
    assert (
        await _post(client, _body(products[5], reason="wrong_category"), ip="203.0.113.50")
    ).status_code == 202


async def test_the_wait_counts_from_the_oldest_report_in_the_hour(client, db):
    products = await _distinct_products(db, 6)
    for product in products[:5]:
        await _post(client, _body(product, reason="wrong_category"))
    await db.execute(
        update(Report)
        .where(Report.id == (await _reports(db))[0].id)
        .values(created_at=datetime.now(UTC) - timedelta(minutes=20))
    )
    await db.commit()
    detail = (await _post(client, _body(products[5], reason="wrong_category"))).json()["detail"]
    assert 39 <= detail["retry_after_minutes"] <= 41


async def test_twenty_a_day(client, db):
    products = await _distinct_products(db, 21)
    now = datetime.now(UTC)
    key = _hash("198.51.100.7")
    for i, product in enumerate(products[:20]):
        db.add(
            Report(
                product_id=product.id,
                reason="wrong_category",
                snapshot={},
                ip_hash=key,
                created_at=now - timedelta(hours=2, minutes=i),
            )
        )
    await db.commit()
    over = await _post(client, _body(products[20], reason="wrong_category"))
    assert over.status_code == 429
    assert over.json()["detail"]["limit"] == "day"
    assert over.json()["detail"]["count"] == 20


async def test_only_a_salted_hash_of_the_address_is_stored(client, db):
    product, _, _ = await _two_shop_product(db)
    await _post(client, _body(product, reason="wrong_category"), ip="198.51.100.7")
    [report] = await _reports(db)
    assert report.ip_hash == _hash("198.51.100.7")
    assert "198.51.100.7" not in str(report.snapshot)


async def test_an_ipv6_sender_is_counted_by_its_64(client, db):
    products = await _distinct_products(db, 6)
    for i, product in enumerate(products[:5]):
        await _post(client, _body(product, reason="wrong_category"), ip=f"2001:db8:1:2::{i + 1}")
    over = await _post(
        client, _body(products[5], reason="wrong_category"), ip="2001:db8:1:2:ffff::9"
    )
    assert over.status_code == 429
    assert (await _reports(db))[0].ip_hash == _hash("2001:db8:1:2::/64")


async def test_without_the_salt_reports_are_refused(client, db, monkeypatch):
    monkeypatch.delenv("REPORT_IP_SALT")
    product, _, _ = await _two_shop_product(db)
    response = await _post(client, _body(product, reason="wrong_category"))
    assert response.status_code == 503
    assert await _reports(db) == []


async def test_a_forwarded_address_is_believed_only_from_our_proxy(db):
    """A request straight from the internet names its own address, whatever it claims."""
    from app.main import app

    product, _, _ = await _two_shop_product(db)
    transport = ASGITransport(app=app, client=("203.0.113.9", 4000))
    async with AsyncClient(transport=transport, base_url="http://testserver") as direct:
        await _post(direct, _body(product, reason="wrong_category"), ip="10.9.9.9")
    [report] = await _reports(db)
    assert report.ip_hash == _hash("203.0.113.9")


async def test_only_the_entry_our_proxy_appended_is_read(client, db):
    """A visitor's own X-Forwarded-For is to the left of what the proxy added."""
    product, _, _ = await _two_shop_product(db)
    await _post(client, _body(product, reason="wrong_category"), ip="1.2.3.4, 198.51.100.7")
    [report] = await _reports(db)
    assert report.ip_hash == _hash("198.51.100.7")


async def test_more_proxies_in_front_read_further_left(client, db, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    product, _, _ = await _two_shop_product(db)
    await _post(
        client, _body(product, reason="wrong_category"), ip="1.2.3.4, 198.51.100.7, 192.0.2.10"
    )
    [report] = await _reports(db)
    assert report.ip_hash == _hash("198.51.100.7")


async def test_reports_count_nothing_into_the_read_api(client, db):
    """The table is new and private: no read endpoint lists it."""
    product, _, _ = await _two_shop_product(db)
    await _post(client, _body(product, reason="wrong_category", email="buyer@example.com"))
    assert (await client.get("/reports")).status_code == 405
    count = await db.scalar(select(func.count()).select_from(Report))
    assert count == 1


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("198.51.100.7:51234", "198.51.100.7"),
        ("[2001:db8::1]:443", "2001:db8::/64"),
        ("::ffff:198.51.100.7", "198.51.100.7"),
        ("not-an-address", "127.0.0.1"),
    ],
)
def test_forwarded_entries_are_read_as_proxies_write_them(raw, expected):
    from app.client_ip import client_address, rate_limit_key
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "client": ("127.0.0.1", 9),
            "headers": [(b"x-forwarded-for", raw.encode())],
        }
    )
    assert rate_limit_key(client_address(request)) == expected


@pytest.mark.parametrize("seconds_ago", [0, 2.5, 6 * 3600 + 60])
async def test_a_form_sent_too_soon_or_too_late_is_dropped(client, db, seconds_ago):
    product, _, _ = await _two_shop_product(db)
    body = {**_body(product, reason="wrong_category"), "token": _token(seconds_ago)}
    assert (await _post(client, body)).json() == {"reference": None}
    assert await _reports(db) == []


async def test_the_opened_at_token_is_signed_stateless_and_uncached(client, db):
    response = await client.get("/reports/token")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    token = response.json()["token"]
    stamp, _ = token.split(".")
    assert abs(int(stamp) - time.time() * 1000) < 5_000
    assert token == issue_token(SALT.encode(), int(stamp))


async def test_without_the_salt_there_is_no_token(client, monkeypatch):
    monkeypatch.delenv("REPORT_IP_SALT")
    assert (await client.get("/reports/token")).status_code == 503


async def test_a_large_body_is_refused_before_it_is_parsed(client, db):
    product, _, _ = await _two_shop_product(db)
    padded = {**_body(product, reason="wrong_category"), "pad": "x" * 17_000}
    response = await _post(client, padded)
    assert response.status_code == 413
    assert await _reports(db) == []


async def test_a_chunked_body_is_cut_off_at_the_limit_too(client, db):
    product, _, _ = await _two_shop_product(db)

    async def chunks():
        yield b'{"product_id": "' + str(product.id).encode() + b'", "pad": "'
        for _ in range(40):
            yield b"x" * 1024
        yield b'"}'

    response = await client.post(
        "/reports",
        content=chunks(),
        headers={"content-type": "application/json", "x-forwarded-for": "198.51.100.7"},
    )
    assert "content-length" not in response.request.headers
    assert response.status_code == 413


async def test_an_ordinary_body_passes_the_limit(client, db):
    product, _, _ = await _two_shop_product(db)
    body = _body(product, reason="other", description="y" * 1000)
    assert (await _post(client, body)).status_code == 202


async def test_control_characters_never_reach_the_table(client, db):
    product, a, _ = await _two_shop_product(db)
    osc52 = "\x1b]52;c;cm0gLXJmIH4=\x07"
    await _post(
        client,
        _body(
            product,
            reason="wrong_category",
            description=f"Line one\r\nline two{osc52}\twith a tab\x9b31m",
            correct_value=f"Motor\x00 drivers{osc52}",
        ),
    )
    [report] = await _reports(db)
    assert report.description == "Line one\nline two]52;c;cm0gLXJmIH4=\twith a tab31m"
    assert report.correct_value == "Motor drivers]52;c;cm0gLXJmIH4="
    assert not any(ord(c) < 32 and c not in "\n\t" for c in report.description)


async def test_an_email_with_control_characters_is_cleaned_before_it_is_checked(client, db):
    product, _, _ = await _two_shop_product(db)
    await _post(client, _body(product, reason="wrong_category", email="buyer\x1b@example.com"))
    [report] = await _reports(db)
    assert report.email == "buyer@example.com"


async def test_a_snapshot_keeps_every_ticked_offer_and_at_most_50(client, db, monkeypatch):
    import makhzan_schemas.reports as rules

    monkeypatch.setattr(rules, "MAX_SNAPSHOT_LISTINGS", 4)
    product, a, b = await _two_shop_product(db)
    shop = await make_supplier(db, slug="cairo-makers", name="Cairo Makers")
    extra = [
        await make_listing(
            db, supplier=shop, product=product, title_en=f"TB6600 #{i}", price=f"{100 + i}.00"
        )
        for i in range(6)
    ]
    ticked = [b, extra[-1]]
    await _post(
        client,
        _body(product, reason="offers_not_same", offer_ids=[str(o.id) for o in ticked]),
    )
    [report] = await _reports(db)
    snap = report.snapshot["product"]
    assert snap["listings_total"] == 8
    assert len(snap["listings"]) == 4
    kept = {x["id"] for x in snap["listings"]}
    assert {str(o.id) for o in ticked} <= kept
    assert sum(x["ticked"] for x in snap["listings"]) == 2


async def test_a_daily_ceiling_holds_for_everyone_together(client, db, monkeypatch):
    monkeypatch.setenv("REPORTS_PER_DAY_ALL", "3")
    products = await _distinct_products(db, 4)
    for i, product in enumerate(products[:3]):
        ok = await _post(client, _body(product, reason="wrong_category"), ip=f"203.0.113.{i + 1}")
        assert ok.status_code == 202
    over = await _post(client, _body(products[3], reason="wrong_category"), ip="203.0.113.99")
    assert over.status_code == 429
    detail = over.json()["detail"]
    assert detail["limit"] == "site" and detail["count"] == 3
    assert 1 <= detail["retry_after_minutes"] <= 24 * 60
    assert len(await _reports(db)) == 3


@pytest.mark.parametrize(
    "token",
    [
        "1700000000000." + "é" * 32,  # non-ASCII: compare_digest on str would raise
        "١٧٠٠٠٠٠٠٠٠٠٠٠." + "0" * 32,  # digits from another script
        "1700000000000." + "A" * 32,  # upper-case hex is not what we sign
        "1700000000000." + "0" * 31,
        "1.2.3",
        "",
    ],
)
async def test_a_malformed_token_is_dropped_not_a_500(client, db, token):
    product, _, _ = await _two_shop_product(db)
    response = await _post(client, {**_body(product, reason="wrong_category"), "token": token})
    assert response.status_code == 202
    assert response.json() == {"reference": None}
    assert await _reports(db) == []
