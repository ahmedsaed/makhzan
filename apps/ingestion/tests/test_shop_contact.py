"""A shop's contact details: listed in sources.toml, written by sync, merged with the crawler's.

What must hold: a number makhzan cannot dial, a link that is not https, a map
link that is not a map, or a detail with no record of where it was read fails
the deploy instead of reaching a page; every listed field names exactly one
source, so a Google Maps listing the shop never claimed is never passed off as
the shop's own; sync writes every listed column on every deploy, so removing a
value from the file clears it; and the merge shows the listed value wherever
there is one, the crawler's only where there is not (the address as one), and
says which came from where.
"""

from __future__ import annotations

import textwrap
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from makhzan_schemas.contact import map_url, phone_number, resolve_contact, shop_reach
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType
from makhzan_schemas.models import Source, Supplier
from sqlalchemy import select
from worker.pipeline import run_source
from worker.sources.base import SupplierInfo
from worker.sources.fixture import FixtureAdapter
from worker.sources.sync import read_sources, sync_sources

#: The shorthand: one page gave everything listed.
PROVENANCE = {
    "contact_source_url": "https://shop-a.test/contact-us",
    "contact_checked_on": "2026-11-03",
}
MAP = "https://maps.app.goo.gl/shopA"
#: A Google Maps listing the shop has not claimed.
PLACE = "https://www.google.com/maps/place/Shop+A/@31.2,29.9,17z"

# --------------------------------------------------------------------------- #
# Phone numbers and map links
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
        ("015 5000 0000", "+201550000000"),  # a ten-digit 015 is a mobile
        ("02 2345 6789", "+20223456789"),
        ("(02) 2345-6789", "+20223456789"),
        ("03 123 4567", "+2031234567"),
        ("040 123 4567", "+20401234567"),
        ("013 322 1234", "+20133221234"),  # Banha
        ("015 436 1234", "+20154361234"),  # 10th of Ramadan, a landline
        ("+20 15 436 1234", "+20154361234"),
        ("19123", "19123"),
        ("16789", "16789"),
        ("15999", "15999"),
        ("17000", "17000"),
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
        "014 123 4567",  # no such area
        "12345",  # not a short code a company rents
        "18000",
        "call us",
        "",
        None,
        1001234567,
    ],
)
def test_anything_else_is_none_rather_than_a_guess(written):
    assert phone_number(written) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://maps.app.goo.gl/AbCdEf123",
        "https://goo.gl/maps/abc",
        "https://g.page/example-shop?share",
        "https://www.google.com/maps/place/x",
        "https://www.google.com.eg/maps/place/x",
        "https://maps.google.com/?q=x",
        "https://maps.apple.com/?q=x",
    ],
)
def test_map_links_on_a_map_service_are_kept(url):
    assert map_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://maps.app.goo.gl/x",
        "https://shop-a.test/maps",
        "https://www.google.com/search?q=shop",
        "https://evil.test/www.google.com/maps",
    ],
)
def test_anything_else_is_not_a_map_link(url):
    assert map_url(url) is None


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
        maps_url=MAP,
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
        "maps_url": MAP,
        "opening_hours": ["Sat–Thu 10:00–22:00", "Fri closed"],
        "branches": [{"name": "Giza", "address": "3 Other Street", "phones": ["+20233334444"]}],
        # The shorthand is one source naming everything, by column name.
        "contact_sources": [
            {
                "url": "https://shop-a.test/contact-us",
                "checked_on": "2026-11-03",
                "fields": [
                    "phones",
                    "whatsapp",
                    "email",
                    "address",
                    "area",
                    "governorate",
                    "maps_url",
                    "opening_hours",
                    "branches",
                ],
            }  # fmt: skip
        ],
    }


def test_each_field_names_the_page_it_was_read_from():
    """Phone and email from the shop's own site; the address from a Google Maps
    listing the shop has not claimed, so the page can say so."""
    info = SupplierInfo(
        slug="shop-a",
        name="Shop A",
        phone="02 4000 0000",
        email="info@shop-a.test",
        address="158 Example Road",
        area="Ibrahimiya",
        governorate="Alexandria",
        contact_sources=[
            {
                "url": "https://shop-a.test/contact-us/",
                "checked_on": date(2026, 11, 10),
                "fields": ["phone", "email"],
            },
            {
                "url": PLACE,
                "checked_on": date(2026, 11, 10),
                "fields": ["address", "area", "governorate"],
            },
        ],  # fmt: skip
    )
    assert info.contact_columns()["contact_sources"] == [
        {"url": "https://shop-a.test/contact-us/", "checked_on": "2026-11-10",
         "fields": ["phones", "email"]},
        {"url": PLACE, "checked_on": "2026-11-10", "fields": ["address", "area", "governorate"]},
    ]  # fmt: skip


def test_area_and_governorate_need_no_source():
    """They predate the rest, and the private file already carries them."""
    info = SupplierInfo(slug="shop-a", name="Shop A", area="Bab El Louk", governorate="Cairo")
    assert info.contact_columns()["area"] == "Bab El Louk"
    assert info.contact_columns()["contact_sources"] is None


def _sources(*entries):
    return {
        "contact_sources": [
            {"url": "https://shop-a.test/", "checked_on": "2026-11-03", **entry}
            for entry in entries
        ]
    }


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"phone": "2345 6789", **PROVENANCE}, "not a phone number"),
        ({"phone": [], **PROVENANCE}, "empty list"),
        ({"whatsapp": "19123", **PROVENANCE}, "takes WhatsApp"),
        ({"whatsapp": ["0100 123 4567"], **PROVENANCE}, "takes WhatsApp"),
        ({"email": "sales at shop-a", **PROVENANCE}, "not an email"),
        ({"maps_url": "http://maps.app.goo.gl/a", **PROVENANCE}, "Google Maps or Apple Maps"),
        ({"maps_url": "https://shop-a.test/where", **PROVENANCE}, "Google Maps or Apple Maps"),
        ({"opening_hours": "Sat-Thu 10-22", **PROVENANCE}, "list of lines"),
        ({"branches": [{"name": "Giza", "fax": "1"}], **PROVENANCE}, "unknown key"),
        ({"branches": [{"name": "Giza"}], **PROVENANCE}, "address or a phone"),
        (
            {"branches": [{"phone": "02 3333 4444", "maps_url": "https://x.test/"}], **PROVENANCE},
            "Google Maps",
        ),
        ({"address": ""}, "non-empty"),
        ({"phone": "02 2345 6789"}, "without where and when"),
        (
            {"email": "a@shop-a.test", "contact_source_url": "https://shop-a.test/"},
            "go together",
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
        ({**PROVENANCE}, "for no details"),
        # The list form.
        ({"email": "a@shop-a.test", **PROVENANCE, **_sources({"fields": ["email"]})}, "not both"),
        ({"email": "a@shop-a.test", "contact_sources": []}, "contact_sources must be"),
        ({"email": "a@shop-a.test", **_sources({"fields": ["e-mail"]})}, "not a contact field"),
        ({"email": "a@shop-a.test", **_sources({"fields": ["email", "phone"]})}, "does not list"),
        ({"email": "a@shop-a.test", **_sources({"fields": []})}, "list of field names"),
        ({"email": "a@shop-a.test", **_sources({"fields": ["email"], "by": "x"})}, "unknown key"),
        ({"email": "a@shop-a.test", **_sources({"fields": ["email"], "url": None})}, "https"),
        (
            {"email": "a@shop-a.test", "phone": "02 2345 6789", **_sources({"fields": ["email"]})},
            "lists phone without where and when",
        ),
        (
            {"email": "a@shop-a.test", **_sources({"fields": ["email"]}, {"fields": ["email"]})},
            "more than one",
        ),
        # Once a shop has sources, its area needs one too.
        ({"email": "a@shop-a.test", "area": "Dokki", **_sources({"fields": ["email"]})}, "area"),
    ],
)
def test_a_detail_that_cannot_be_shown_honestly_is_refused(fields, message):
    with pytest.raises((TypeError, ValueError), match=message):
        SupplierInfo(slug="shop-a", name="Shop A", **fields)


def test_a_landline_on_whatsapp_business_is_accepted():
    info = SupplierInfo(slug="shop-a", name="Shop A", whatsapp="02 2345 6789", **PROVENANCE)
    assert info.whatsapp == "+20223456789"


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
address = "158 Example Road"

[[source.supplier.contact_sources]]
url = "https://shop-a.test/contact-us"
checked_on = 2026-11-03
fields = ["phone", "whatsapp", "branches"]

[[source.supplier.contact_sources]]
url = "https://maps.app.goo.gl/shopA"
checked_on = 2026-11-04
fields = ["address"]

[[source.supplier.branches]]
name = "Giza"
address = "3 Other Street"
phone = "02 3333 4444"
"""


def _file(tmp_path, text):
    path = tmp_path / "sources.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_the_table_form_reads_and_its_dates_are_stored_as_text(tmp_path):
    """A TOML date is not JSON; the sources row keeps the table as JSONB."""
    (row,) = read_sources(_file(tmp_path, SOURCES))
    assert row.supplier["contact_sources"][1]["checked_on"] == "2026-11-04"
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
    listed = {"phone": "02 2345 6789", "email": "sales@shop-a.test", "area": "Bab El Louk"}

    report = await _sync([_source(**listed, **PROVENANCE)])

    assert report["shop_details"] == ["shop-a"]
    shop = await _shop()
    assert shop.phones == ["+20223456789"]
    assert shop.email == "sales@shop-a.test"
    assert shop.area == "Bab El Louk"
    assert shop.contact_sources == [
        {
            "url": "https://shop-a.test/contact-us",
            "checked_on": "2026-11-03",
            "fields": ["phones", "email", "area"],
        }
    ]
    # What the crawler read is its own column, and sync never touches it.
    assert shop.contact == {"phone": "01000000000", "source_url": "https://shop-a.test/"}
    assert (await _sync([_source(**listed, **PROVENANCE)]))["shop_details"] == []


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
    assert shop.contact_sources is None


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
    assert shop.contact_sources[0]["checked_on"] == "2026-11-03"


# --------------------------------------------------------------------------- #
# The merge
# --------------------------------------------------------------------------- #

READ = {
    "phone": "01000000000",
    "whatsapp": "+201000000000",
    "address": "31 Crawled Street",
    "area": "Crawled Area",
    "opening_hours": ["Mo-Sa 10:00-20:00"],
    "source_url": "https://shop-a.test/",
    "fetched_at": "2026-11-08T20:00:00+00:00",
}


def _supplier(**columns):
    return SimpleNamespace(**columns)


def _listed(url, *fields, day="2026-11-03"):
    return {"url": url, "checked_on": day, "fields": list(fields)}


def test_listed_wins_per_field_and_read_fills_the_gaps():
    contact = resolve_contact(
        _supplier(
            phones=["+20223456789"],
            address="12 Listed Street",
            contact_sources=[_listed("https://shop-a.test/contact-us", "phones", "address")],
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


def test_the_address_comes_whole_from_one_origin():
    """A listed street must not sit under the district the crawler read."""
    contact = resolve_contact(
        _supplier(
            address="12 Listed Street",
            contact_sources=[_listed("https://shop-a.test/contact-us", "address")],
            contact=READ,
        )
    )
    assert (contact.address, contact.area) == ("12 Listed Street", None)
    # And a listed area alone still takes the whole address group.
    contact = resolve_contact(_supplier(governorate="Cairo", contact=READ))
    assert (contact.address, contact.area, contact.governorate) == (None, None, "Cairo")


def test_each_listed_source_is_named_for_the_fields_it_gave():
    contact = resolve_contact(
        _supplier(
            phones=["+20240000000"],
            address="158 Example Road",
            area="Ibrahimiya",
            contact_sources=[
                _listed("https://shop-a.test/contact-us/", "phones", day="2026-11-10"),
                _listed(PLACE, "address", "area", day="2026-11-10"),
            ],
        )
    )
    assert [(s.url, s.fields) for s in contact.sources] == [
        ("https://shop-a.test/contact-us/", ["phones"]),
        (PLACE, ["address", "area"]),
    ]


def test_a_source_that_supplied_nothing_shown_is_not_named():
    contact = resolve_contact(
        _supplier(
            phones=["+20223456789"],
            whatsapp="+201001234567",
            address="12 Listed Street",
            opening_hours=["Sat-Thu 10-22"],
            contact_sources=[
                _listed(
                    "https://shop-a.test/contact-us",
                    "phones",
                    "whatsapp",
                    "address",
                    "opening_hours",
                ),
                _listed("https://shop-a.test/old", "email"),  # a field since removed
            ],  # fmt: skip
            contact=READ,
        )
    )
    assert [(s.origin, s.url) for s in contact.sources] == [
        ("listed", "https://shop-a.test/contact-us")
    ]


def test_a_map_link_that_is_not_a_map_is_not_shown():
    contact = resolve_contact(_supplier(address="12 Listed Street", maps_url="https://x.test/"))
    assert contact.maps_url is None


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
