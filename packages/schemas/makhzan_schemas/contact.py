"""How to reach a shop: what a person read off its site, what the crawler read, and the merge.

A shop's contact details reach the database by two routes, and both are the
shop's own words:

  - **listed**: a person read them from the shop's own pages and wrote them into
    the shop's `supplier` table in sources.toml, with where (`contact_source_url`)
    and when (`contact_checked_on`). `worker.sources.sync` writes them onto the
    Supplier's columns on every deploy, so the file is their only writer.
  - **read**: the crawler found them in the shop's own LocalBusiness JSON-LD
    (`Supplier.contact`, refreshed once a cycle, for the adapters that read it).

`resolve_contact` merges the two **per field**: a listed value wins, a read one
fills the gap. The listed details were checked by a person and the crawler's
are whatever one page's markup said, so where both name a phone the person's is
the one shown; where only the crawler found opening hours, those are shown,
said to be read from the site and when.

Phone numbers are stored and served in E.164 (`+20…`), or as the bare digits of
a five-digit hotline (19xxx), which has no international form. Formatting them
for an Egyptian reader is the page's job (apps/web/lib/contact.ts).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

#: The longest free text kept from a contact field.
_MAX_TEXT = 200
#: The most opening-hour lines shown; a week is seven, a split week fourteen.
_MAX_HOURS = 14
#: The most branches or numbers one shop shows.
_MAX_ITEMS = 10

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
#: Separators people write inside a phone number.
_PHONE_PUNCTUATION = re.compile(r"[\s\-./() ‎‏]")
_EMAIL = re.compile(r"^[^@\s<>\"]+@[^@\s<>\"]+\.[^@\s<>\"]+$")


def _text(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, str):
        return None
    text = value.strip()
    return text if text and len(text) <= _MAX_TEXT else None


def https_url(value: object) -> str | None:
    """A web link a page may show: https only, no whitespace, a sane length."""
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url.lower().startswith("https://") or len(url) > 2000 or any(c.isspace() for c in url):
        return None
    return url


def email_address(value: object) -> str | None:
    """An email address, or None. `mailto:` is dropped; nothing else is rewritten."""
    text = _text(value)
    if text is None:
        return None
    text = text.removeprefix("mailto:")
    return text if _EMAIL.match(text) else None


def _egyptian_national(digits: str) -> bool:
    """Whether `digits` (no trunk 0) is a valid Egyptian number's national part.

    Mobiles are 1x + 8 digits; Cairo and Giza landlines 2 + 8; Alexandria 3 + 7;
    every other area a two-digit code from 4 to 9 + 7 digits.
    """
    if len(digits) == 10:
        return digits[0] == "1" and digits[1] in "0125"
    if len(digits) == 9:
        return digits[0] == "2" or digits[0] in "456789"
    if len(digits) == 8:
        return digits[0] == "3"
    return False


def phone_number(value: object) -> str | None:
    """A phone number as E.164 (`+201001234567`), a hotline's five digits, or None.

    Reads what Egyptian shops write: `010 0123 4567`, `02-2345-6789`,
    `+20 (2) 2345 6789`, `00201001234567`, Arabic-Indic digits. A number from
    another country is kept when written with its `+` or `00`. Anything else —
    two numbers in one string, an extension, letters — is None rather than a
    guess: a wrong number is worse than none.
    """
    text = _text(value)
    if text is None:
        return None
    text = _PHONE_PUNCTUATION.sub("", text.translate(_ARABIC_DIGITS)).removeprefix("tel:")
    international = text.startswith("+") or text.startswith("00")
    digits = text.lstrip("+")
    if text.startswith("00"):
        digits = text[2:]
    if not digits.isdigit():
        return None
    if not international:
        if len(digits) == 5 and digits[0] == "1":
            return digits  # a hotline: 19xxx, 16xxx, 15xxx
        if digits.startswith("0"):
            national = digits[1:]
        elif digits.startswith("20") and _egyptian_national(digits[2:]):
            national = digits[2:]
        else:
            return None
        return f"+20{national}" if _egyptian_national(national) else None
    if digits.startswith("20"):
        national = digits[2:].removeprefix("0")  # "+20 (0)10…" is written too
        return f"+20{national}" if _egyptian_national(national) else None
    return f"+{digits}" if 8 <= len(digits) <= 15 else None


def _phones(value: object) -> list[str]:
    """Numbers from a string or a list of them, normalized, deduplicated, in order."""
    raw = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in raw:
        number = phone_number(item)
        if number and number not in out:
            out.append(number)
    return out[:_MAX_ITEMS]


def _hours(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [h for h in (_text(v) for v in value) if h][:_MAX_HOURS]


def _day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# What the crawler read (Supplier.contact)
# --------------------------------------------------------------------------- #


class SupplierContact(BaseModel):
    """What the crawler read from the shop's own structured data, validated.

    Text is the shop's own, in whatever language it wrote it; only its shape is
    checked here. The phone is kept as written: normalizing it is the merge's
    job, which is where a number that does not parse is dropped.
    """

    address: str | None = None
    area: str | None = None
    governorate: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    opening_hours: list[str] = Field(default_factory=list)
    source_url: str | None = None
    fetched_at: datetime | None = None

    @field_validator("address", "area", "governorate", "phone", "whatsapp", "email", mode="before")
    @classmethod
    def _text(cls, value: object) -> str | None:
        return _text(value)

    @field_validator("opening_hours", mode="before")
    @classmethod
    def _hours(cls, value: object) -> list[str]:
        return _hours(value)

    @field_validator("source_url", mode="before")
    @classmethod
    def _url(cls, value: object) -> str | None:
        return https_url(value)

    @field_validator("fetched_at", mode="before")
    @classmethod
    def _when(cls, value: object) -> datetime | None:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            return None


def public_contact(value: object) -> SupplierContact | None:
    """The crawler's stored contact, validated; None when it holds nothing to show."""
    if not isinstance(value, dict):
        return None
    try:
        contact = SupplierContact.model_validate(value)
    except ValueError:
        return None
    shown = contact.model_dump(exclude={"source_url", "fetched_at"})
    return contact if any(shown.values()) else None


# --------------------------------------------------------------------------- #
# The merge
# --------------------------------------------------------------------------- #

#: Where a shown value came from: "listed" by a person from the shop's own
#: pages, or "read" by the crawler from the shop's own structured data.
Origin = Literal["listed", "read"]

#: The single-valued fields, in the order a page lists them.
_SINGLE = ("whatsapp", "email", "address", "area", "governorate", "maps_url")


class ContactBranch(BaseModel):
    """One more place the shop trades from, beyond its main address."""

    name: str | None = None
    address: str | None = None
    area: str | None = None
    governorate: str | None = None
    phones: list[str] = Field(default_factory=list)
    maps_url: str | None = None


class ContactSource(BaseModel):
    """Where some of a contact block came from, and when it was last read there."""

    origin: Origin
    #: The page it was read from. None only for a listed area or governorate
    #: entered before contact details carried their source.
    url: str | None = None
    checked_on: date | None = None
    #: The fields this source supplied, by their names in ResolvedContact.
    fields: list[str] = Field(default_factory=list)


class ResolvedContact(BaseModel):
    """How to reach a shop, one value per field, with where each came from."""

    phones: list[str] = Field(default_factory=list)
    whatsapp: str | None = None
    email: str | None = None
    address: str | None = None
    area: str | None = None
    governorate: str | None = None
    maps_url: str | None = None
    opening_hours: list[str] = Field(default_factory=list)
    branches: list[ContactBranch] = Field(default_factory=list)
    sources: list[ContactSource] = Field(default_factory=list)


class ShopReach(BaseModel):
    """The few ways to reach a shop an offer row needs: its first phone, WhatsApp, email.

    A product page lists offers from several shops; the full block (addresses,
    hours, branches) is the shop page's, fetched once, not repeated per offer.
    """

    phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None


def _branch(value: object) -> ContactBranch | None:
    if not isinstance(value, dict):
        return None
    branch = ContactBranch(
        name=_text(value.get("name")),
        address=_text(value.get("address")),
        area=_text(value.get("area")),
        governorate=_text(value.get("governorate")),
        phones=_phones(value.get("phones")),
        maps_url=https_url(value.get("maps_url")),
    )
    shown = branch.model_dump(exclude={"name"})
    return branch if any(shown.values()) else None


def resolve_contact(supplier: object) -> ResolvedContact | None:
    """A shop's contact details, listed values first and the crawler's filling gaps.

    `supplier` is a Supplier row, or anything with its attributes. None when
    neither route knows anything to show.
    """
    listed: dict = {
        "phones": _phones(getattr(supplier, "phones", None) or []),
        "whatsapp": phone_number(getattr(supplier, "whatsapp", None)),
        "email": email_address(getattr(supplier, "email", None)),
        "address": _text(getattr(supplier, "address", None)),
        "area": _text(getattr(supplier, "area", None)),
        "governorate": _text(getattr(supplier, "governorate", None)),
        "maps_url": https_url(getattr(supplier, "maps_url", None)),
        "opening_hours": _hours(getattr(supplier, "opening_hours", None)),
        "branches": [
            b for b in map(_branch, getattr(supplier, "branches", None) or []) if b is not None
        ][:_MAX_ITEMS],
    }
    crawled = public_contact(getattr(supplier, "contact", None))
    read: dict = {}
    if crawled is not None:
        read = {
            "phones": _phones(crawled.phone),
            "whatsapp": phone_number(crawled.whatsapp),
            "email": email_address(crawled.email),
            "address": crawled.address,
            "area": crawled.area,
            "governorate": crawled.governorate,
            "opening_hours": crawled.opening_hours,
        }

    resolved: dict = {}
    taken: dict[Origin, list[str]] = {"listed": [], "read": []}
    for name in ("phones", *_SINGLE, "opening_hours", "branches"):
        for origin, values in (("listed", listed), ("read", read)):
            value = values.get(name)
            if value:
                resolved[name] = value
                taken[origin].append(name)
                break
    if not resolved:
        return None

    sources: list[ContactSource] = []
    if taken["listed"]:
        sources.append(
            ContactSource(
                origin="listed",
                url=https_url(getattr(supplier, "contact_source_url", None)),
                checked_on=_day(getattr(supplier, "contact_checked_on", None)),
                fields=taken["listed"],
            )
        )
    if taken["read"] and crawled is not None:
        sources.append(
            ContactSource(
                origin="read",
                url=crawled.source_url,
                checked_on=_day(crawled.fetched_at),
                fields=taken["read"],
            )
        )
    return ResolvedContact(**resolved, sources=sources)


def shop_reach(contact: ResolvedContact | None) -> ShopReach | None:
    """The compact form an offer carries; None when there is no way to reach the shop."""
    if contact is None:
        return None
    phone = contact.phones[0] if contact.phones else None
    if phone is None:
        # A shop that lists numbers only per branch is still reachable by phone.
        phone = next((b.phones[0] for b in contact.branches if b.phones), None)
    if not (phone or contact.whatsapp or contact.email):
        return None
    return ShopReach(phone=phone, whatsapp=contact.whatsapp, email=contact.email)
