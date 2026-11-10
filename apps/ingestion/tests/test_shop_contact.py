"""A shop's contact details: listed in sources.toml, written by sync, merged with the crawler's.

What must hold: a number makhzan cannot dial, a link that is not https or a
detail with no record of where it was read fails the deploy instead of reaching
a page; sync writes every listed column on every deploy, so removing a value
from the file clears it; and the merge shows the listed value wherever there is
one, the crawler's only where there is not, and says which came from where.
"""

from __future__ import annotations

import textwrap
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from makhzan_schemas.contact import phone_number, resolve_contact, shop_reach
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import Source, Supplier
from sqlalchemy import select
from worker.pipeline import run_source
from worker.sources.base import SupplierInfo
from worker.sources.fixture import FixtureAdapter
from worker.sources.sync import read_sources, sync_sources

PROVENANCE = {
    "contact_source_url": "https://shop-a.test/contact-us",
    "contact_checked_on": "2026-11-03",
}

# --------------------------------------------------------------------------- #
# Phone numbers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("written", "e164"),
    [
        ("010 0123 4567", "+201001234567"),
        ("0100-123-4567", "+201001234567"),
        ("+20 100 123 4567", "+201001234567"),
        ("+20 (0)100 123 4567", "+201001234567"),
        ("00201001234567", "+201001234567"),
        ("201001234567", "+201001234567"),
        ("٠١٠٠١٢٣٤٥٦٧", "+201001234567"),
        ("tel:01001234567", "+201001234567"),
        ("02 2345 6789", "+20223456789"),
        ("(02) 2345-6789", "+20223456789"),
        ("03 123 4567", "+2031234567"),
        ("040 123 4567", "+20401234567"),
        ("19123", "19123"),
        ("+44 20 7946 0000", "+442079460000"),
    ],
)
def test_numbers_egyptian_shops_write_are_read_as_e164(written, e164):
    assert phone_number(written) == e164


@pytest.mark.parametrize(
    "written",
    [
        "2345 6789",  # no area code: which city?
        "02 2345 6789 / 02 2345 6780",  # two numbers in one
        "02 2345 6789 ext 4",
        "0100 123 456",  # a digit short
        "011 0123 45678",  # a digit long
        "04 123 4567",  # 04 alone is no area
        "call us",
        "",
        None,
        1001234567,
    ],
)
def test_anything_else_is_none_rather_than_a_guess(written):
    assert phone_number(written) is None


# --------------------------------------------------------------------------- #
# The supplier table in sources.toml
# --------------------------------------------------------------------------- #


def test_a_fully_listed_shop_is_normalized():
    info = SupplierInfo(
        slug="shop-a",
        name="Shop A",
        phone=["02 2345 6789", "02 2345 6789", "0100 123 4567"],
        whatsapp="0100 123 4567",
        email="mailto:sales@shop-a.test",
        address="  12 Example Street  ",
        area="Bab El Louk",
        governorate="Cairo",
        maps_url="https://maps.example.test/shop-a",
        opening_hours=["Sat–Thu 10:00–22:00", "Fri closed"],
        branches=[{"name": "Giza", "address": "3 Other Street", "phone": "02 3333 4444"}],
        **PROVENANCE,
    )

    assert info.contact_columns() == {
        "phones": ["+20223456789", "+201001234567"],
        "whatsapp": "+201001234567",
        "email": "sales@shop-a.test",
        "address": "12 Example Street",
        "area": "Bab El Louk",
        "governorate": "Cairo",
        "maps_url": "https://maps.example.test/shop-a",
        "opening_hours": ["Sat–Thu 10:00–22:00", "Fri closed"],
        "branches": [{"name": "Giza", "address": "3 Other Street", "phones": ["+20233334444"]}],
        "contact_source_url": "https://shop-a.test/contact-us",
        "contact_checked_on": date(2026, 11, 3),
    }


def test_area_and_governorate_need_no_source():
    """They predate the rest, and the private file already carries them."""
    info = SupplierInfo(slug="shop-a", name="Shop A", area="Bab El Louk", governorate="Cairo")
    assert info.contact_columns()["area"] == "Bab El Louk"


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"phone": "2345 6789", **PROVENANCE}, "not a phone number"),
        ({"phone": [], **PROVENANCE}, "empty list"),
        ({"whatsapp": "19123", **PROVENANCE}, "one mobile number"),
        ({"whatsapp": ["0100 123 4567"], **PROVENANCE}, "one mobile number"),
        ({"email": "sales at shop-a", **PROVENANCE}, "not an email"),
        ({"maps_url": "http://maps.example.test/a", **PROVENANCE}, "https"),
        ({"opening_hours": "Sat-Thu 10-22", **PROVENANCE}, "list of lines"),
        ({"branches": [{"name": "Giza", "fax": "1"}], **PROVENANCE}, "unknown key"),
        ({"branches": [{"name": "Giza"}], **PROVENANCE}, "address or a phone"),
        ({"address": ""}, "non-empty"),
        ({"phone": "02 2345 6789"}, "contact_source_url and contact_checked_on"),
        (
            {"email": "a@shop-a.test", "contact_source_url": "https://shop-a.test/"},
            "contact_source_url and contact_checked_on",
        ),
        ({"email": "a@shop-a.test", **PROVENANCE, "contact_checked_on": "3 Nov"}, "a date"),
        (
            {
                "email": "a@shop-a.test",
                **PROVENANCE,
                "contact_checked_on": (date.today() + timedelta(days=5)).isoformat(),
            },
            "in the future",
        ),
    ],
)
def test_a_detail_that_cannot_be_shown_honestly_is_refused(fields, message):
    with pytest.raises((TypeError, ValueError), match=message):
        SupplierInfo(slug="shop-a", name="Shop A", **fields)


def test_an_unknown_key_is_still_an_error():
    with pytest.raises(TypeError, match="fax"):
        SupplierInfo(slug="shop-a", name="Shop A", fax="02 2345 6789")


SOURCES = """
[[source]]
id = "shop-a"
adapter = "fixture"
enabled = false

[source.supplier]
slug = "shop-a"
name = "Shop A"
phone = ["02 2345 6789", "02 2345 6780"]
whatsapp = "0100 123 4567"
contact_source_url = "https://shop-a.test/contact-us"
contact_checked_on = 2026-11-03

[[source.supplier.branches]]
name = "Giza"
address = "3 Other Street"
phone = "02 3333 4444"
"""


def _file(tmp_path, text):
    path = tmp_path / "sources.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_the_table_form_reads_and_its_date_is_stored_as_text(tmp_path):
    """A TOML date is not JSON; the sources row keeps the table as JSONB."""
    (row,) = read_sources(_file(tmp_path, SOURCES))
    assert row.supplier["contact_checked_on"] == "2026-11-03"
    assert row.supplier["branches"][0]["phone"] == "02 3333 4444"


def test_a_bad_number_fails_the_whole_file(tmp_path):
    with pytest.raises(ValueError, match="'shop-a' does not build.*not a phone number"):
        read_sources(_file(tmp_path, SOURCES.replace("02 3333 4444", "3333 4444")))


def test_two_sources_for_one_shop_must_agree(tmp_path):
    second = """
    [[source]]
    id = "shop-a-feed"
    adapter = "fixture"
    enabled = false
    [source.supplier]
    slug = "shop-a"
    name = "Shop A"
    email = "other@shop-a.test"
    contact_source_url = "https://shop-a.test/"
    contact_checked_on = 2026-11-01
    """
    with pytest.raises(ValueError, match="different contact details"):
        read_sources(_file(tmp_path, SOURCES + textwrap.dedent(second)))
    # One that lists nothing defers to the one that does.
    quiet = (
        '[[source]]\nid = "b"\nadapter = "fixture"\nsupplier = { slug = "shop-a", name = "A" }\n'
    )
    assert len(read_sources(_file(tmp_path, SOURCES + quiet))) == 2


# --------------------------------------------------------------------------- #
# Sync writes the row
# --------------------------------------------------------------------------- #


def _source(**supplier) -> Source:
    return Source(
        source_id="shop-a",
        adapter="fixture",
        enabled=False,
        supplier={"slug": "shop-a", "name": "Shop A", **supplier},
        config={},
    )


async def _shop() -> Supplier:
    async with SessionLocal() as session:
        return (
            await session.execute(select(Supplier).where(Supplier.slug == "shop-a"))
        ).scalar_one()


async def _make_shop(**columns) -> None:
    async with SessionLocal() as session:
        session.add(
            Supplier(slug="shop-a", name="Shop A", source_type=SourceType.SCRAPED, **columns)
        )
        await session.commit()


async def _sync(rows):
    async with SessionLocal() as session:
        return await sync_sources(session, rows)


async def test_sync_writes_the_listed_details_onto_the_shop():
    await _make_shop(contact={"phone": "01000000000", "source_url": "https://shop-a.test/"})

    report = await _sync(
        [_source(phone="02 2345 6789", email="sales@shop-a.test", area="Bab El Louk", **PROVENANCE)]
    )

    assert report["shop_details"] == ["shop-a"]
    shop = await _shop()
    assert shop.phones == ["+20223456789"]
    assert shop.email == "sales@shop-a.test"
    assert shop.area == "Bab El Louk"
    assert shop.contact_checked_on == date(2026, 11, 3)
    # What the crawler read is its own column, and sync never touches it.
    assert shop.contact == {"phone": "01000000000", "source_url": "https://shop-a.test/"}
    assert (await _sync([_source(phone="02 2345 6789", email="sales@shop-a.test",
                                 area="Bab El Louk", **PROVENANCE)]))["shop_details"] == []  # fmt: skip


async def test_removing_a_value_from_the_file_clears_it():
    await _make_shop()
    await _sync([_source(phone="02 2345 6789", email="sales@shop-a.test", **PROVENANCE)])

    await _sync([_source(phone="02 2345 6789", **PROVENANCE)])
    shop = await _shop()
    assert shop.email is None
    assert shop.phones == ["+20223456789"]

    await _sync([_source()])
    shop = await _shop()
    assert shop.phones is None
    assert shop.contact_source_url is None
    assert shop.contact_checked_on is None


async def test_a_shop_not_crawled_yet_gets_its_details_when_first_created():
    """Sync has no row to write to; the pipeline creates it with the same details."""
    assert (await _sync([_source(phone="02 2345 6789", **PROVENANCE)]))["shop_details"] == []

    adapter = FixtureAdapter()
    adapter.supplier = SupplierInfo(
        slug="shop-a", name="Shop A", phone="02 2345 6789", area="Bab El Louk", **PROVENANCE
    )
    await run_source(adapter.source_id, adapter, limit=1)

    shop = await _shop()
    assert shop.phones == ["+20223456789"]
    assert shop.area == "Bab El Louk"
    assert shop.contact_checked_on == date(2026, 11, 3)


# --------------------------------------------------------------------------- #
# The merge
# --------------------------------------------------------------------------- #

READ = {
    "phone": "01000000000",
    "whatsapp": "+201000000000",
    "address": "31 Crawled Street",
    "opening_hours": ["Mo-Sa 10:00-20:00"],
    "source_url": "https://shop-a.test/",
    "fetched_at": "2026-11-08T20:00:00+00:00",
}


def _supplier(**columns):
    return SimpleNamespace(**columns)


def test_listed_wins_per_field_and_read_fills_the_gaps():
    contact = resolve_contact(
        _supplier(
            phones=["+20223456789"],
            address="12 Listed Street",
            contact_source_url="https://shop-a.test/contact-us",
            contact_checked_on=date(2026, 11, 3),
            contact=READ,
        )
    )

    assert contact.phones == ["+20223456789"]
    assert contact.address == "12 Listed Street"
    assert contact.whatsapp == "+201000000000"
    assert contact.opening_hours == ["Mo-Sa 10:00-20:00"]
    assert [(s.origin, s.url, s.checked_on, s.fields) for s in contact.sources] == [
        ("listed", "https://shop-a.test/contact-us", date(2026, 11, 3), ["phones", "address"]),
        ("read", "https://shop-a.test/", date(2026, 11, 8), ["whatsapp", "opening_hours"]),
    ]


def test_a_source_that_supplied_nothing_shown_is_not_named():
    contact = resolve_contact(
        _supplier(
            phones=["+20223456789"],
            whatsapp="+201001234567",
            address="12 Listed Street",
            opening_hours=["Sat-Thu 10-22"],
            contact_source_url="https://shop-a.test/contact-us",
            contact_checked_on=date(2026, 11, 3),
            contact=READ,
        )
    )
    assert [s.origin for s in contact.sources] == ["listed"]


def test_nothing_known_is_none():
    assert resolve_contact(_supplier()) is None
    assert resolve_contact(_supplier(contact={"source_url": "https://shop-a.test/"})) is None
    assert shop_reach(None) is None


def test_an_offer_carries_the_first_phone_whatsapp_and_email():
    contact = resolve_contact(
        _supplier(phones=["+20223456789", "+20223456780"], email="sales@shop-a.test")
    )
    reach = shop_reach(contact)
    assert reach.model_dump() == {
        "phone": "+20223456789",
        "whatsapp": None,
        "email": "sales@shop-a.test",
    }
    # An address alone is no way to reach a shop from a product page.
    assert shop_reach(resolve_contact(_supplier(address="12 Listed Street"))) is None
