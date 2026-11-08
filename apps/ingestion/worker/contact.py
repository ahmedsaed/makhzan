"""A shop's own contact details, read from the structured data on its pages.

Most shop themes publish a `LocalBusiness` (often `ElectronicsStore`) block of
JSON-LD on every page: address, phone, email, opening hours. That is the shop
telling search engines how to reach it, so it is the right thing to show on its
supplier page — and one request per cycle reads it.

Text is kept as the shop wrote it, Arabic included: nothing is translated. What
is corrected is *placement*. Some shops fill the address fields one slot off —
the street number as the street, the street as the locality, the district as
the region and the city as the country — and those are moved back to where they
belong, which is detectable because the "country" is then not a country.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from selectolax.parser import HTMLParser

#: JSON-LD types that describe a place you can contact. A bare `Organization`
#: counts only when it carries an address or a phone: many sites publish one
#: with nothing but a name and a logo.
_BUSINESS_TYPES = {"localbusiness", "store", "electronicsstore", "hardwarestore", "homegoodsstore"}
_ORGANIZATION = "organization"

#: What a shop writes in `addressCountry` when it is filled correctly.
_COUNTRIES = {"eg", "egy", "egypt", "مصر", "arab republic of egypt"}

#: A WhatsApp click-to-chat link with a number in it (`wa.me/<n>` or
#: `api.whatsapp.com/send?phone=<n>`). A share link has no number and is skipped.
_WHATSAPP = re.compile(
    r"https?://(?:wa\.me/|(?:api|web)\.whatsapp\.com/send/?\?(?:[^\"'#]*&)?phone=)\+?(\d{8,15})"
)
_TEL = re.compile(r"""href=["']tel:([+\d][\d\s()+-]{6,20})["']""")

_MAX_TEXT = 200
_MAX_HOURS = 14


def _text(value: object) -> str | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned[:_MAX_TEXT] if cleaned else None


def _types(node: dict) -> set[str]:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return {k.lower() for k in kinds if isinstance(k, str)}


def _nodes(html: str):
    """Every JSON-LD object on the page, @graph members included."""
    for script in HTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text() or "")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop(0)
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                yield node
                if isinstance(node.get("@graph"), list):
                    stack.extend(node["@graph"])


def _digits(phone: str) -> str:
    """A phone number reduced to digits in international form, for comparison only."""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("0") and len(digits) == 11:  # Egyptian local form
        digits = "20" + digits[1:]
    return digits


def _address(node: dict) -> dict:
    address = node.get("address")
    if isinstance(address, list):
        address = address[0] if address else None
    if isinstance(address, str):
        return {"address": _text(address)} if _text(address) else {}
    if not isinstance(address, dict):
        return {}
    street = _text(address.get("streetAddress"))
    locality = _text(address.get("addressLocality"))
    region = _text(address.get("addressRegion"))
    country = _text(address.get("addressCountry"))

    if country and country.lower() not in _COUNTRIES:
        # One slot off: the country holds the city and everything else shifts
        # with it — "31" / "Selim El Awal St." / "Hadayek El Zeitoun" / "Cairo".
        # The street is then split across the first two fields.
        street = " ".join(part for part in (street, locality) if part) or None
        locality, region = region, country
    out = {"address": street, "area": locality, "governorate": region}
    if out["area"] and out["area"] == out["governorate"]:
        # "Alexandria, Alexandria": the city twice says nothing about the area.
        out["area"] = None
    return {k: v for k, v in out.items() if v}


def _opening_hours(node: dict) -> list[str]:
    hours = node.get("openingHours")
    if isinstance(hours, str):
        hours = [hours]
    out = [h for h in (_text(h) for h in hours or [] if isinstance(hours, list)) if h]
    if not out:
        for spec in node.get("openingHoursSpecification") or []:
            if not isinstance(spec, dict):
                continue
            days = spec.get("dayOfWeek")
            days = days if isinstance(days, list) else [days]
            names = ",".join(str(d).rsplit("/", 1)[-1][:2] for d in days if isinstance(d, str))
            opens, closes = _text(spec.get("opens")), _text(spec.get("closes"))
            if names and opens and closes:
                out.append(f"{names} {opens[:5]}-{closes[:5]}")
    return out[:_MAX_HOURS]


def _phone(node: dict) -> str | None:
    phone = _text(node.get("telephone"))
    if phone:
        return phone
    points = node.get("contactPoint")
    for point in points if isinstance(points, list) else [points]:
        if isinstance(point, dict) and _text(point.get("telephone")):
            return _text(point.get("telephone"))
    return None


def contact_from_html(html: str | None, source_url: str) -> dict | None:
    """The shop's contact details from one of its pages, or None if it names none.

    Read from the first business block in the page's JSON-LD. WhatsApp has no
    JSON-LD field, so it comes from the page's own click-to-chat links — but
    only when they all name one number: a page linking two is two branches or
    two departments, and picking one would be a guess. A phone missing from the
    JSON-LD is taken from `tel:` links under the same rule.
    """
    if not html:
        return None
    business = None
    for node in _nodes(html):
        kinds = _types(node)
        if kinds & _BUSINESS_TYPES:
            business = node
            break
        if _ORGANIZATION in kinds and business is None:
            if node.get("address") or _phone(node):
                business = node

    out: dict = {}
    if business is not None:
        out.update(_address(business))
        if phone := _phone(business):
            out["phone"] = phone
        email = _text(business.get("email"))
        if email and "@" in email:
            out["email"] = email.removeprefix("mailto:")
        if hours := _opening_hours(business):
            out["opening_hours"] = hours

    whatsapp = {_digits(n) for n in _WHATSAPP.findall(html)}
    if len(whatsapp) == 1:
        out["whatsapp"] = "+" + whatsapp.pop()
    if "phone" not in out:
        tel = {}
        for raw in _TEL.findall(html):
            tel.setdefault(_digits(raw), raw.strip())
        if len(tel) == 1:
            out["phone"] = next(iter(tel.values()))

    if not out:
        return None
    out["source_url"] = source_url
    out["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return out
