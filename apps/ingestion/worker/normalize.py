"""Shared normalization: RawItem -> NormalizedListing.

Centralised so every source gets consistent price parsing, Arabic handling,
stock interpretation, and confidence scoring. This is intentionally rule-based
and conservative for V1; an LLM extraction pass can slot in here later for the
messy long tail without changing the adapter contract.
"""

from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation

from makhzan_schemas.contracts import NormalizedListing, RawItem
from makhzan_schemas.enums import DEFAULT_CURRENCY, ReviewReason, StockSignal
from makhzan_schemas.domains import get_profile
from makhzan_schemas.domains.crosswalks import normalize_category_name

# Arabic-Indic digits -> ASCII, so "٣٥٠" parses like "350".
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Confidence below this routes the item to the review queue instead of going live.
REVIEW_THRESHOLD = 0.6

_ARABIC_RE = re.compile(r"[؀-ۿ]")
_PRICE_RE = re.compile(r"\d[\d,]*\.?\d*")

_OUT_OF_STOCK_HINTS = ("out of stock", "sold out", "غير متوفر", "نفذ", "unavailable")
_IN_STOCK_HINTS = ("in stock", "متوفر", "available")
_ORDER_HINTS = ("made to order", "arriving soon", "بالطلب", "pre-order", "preorder")


def _has_arabic(text: str) -> bool:
    return bool(_ARABIC_RE.search(text))


def clean_text(text: str | None) -> str | None:
    """Decode HTML entities (titles arrive as e.g. 'A &#038; B') and collapse whitespace."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return cleaned or None


def parse_price(price_text: str | None) -> Decimal | None:
    if not price_text:
        return None
    normalized = price_text.translate(_ARABIC_DIGITS)
    match = _PRICE_RE.search(normalized)
    if not match:
        return None
    try:
        value = Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    # A price of 0 (or less) means "unpriced", not free.
    return value if value > 0 else None


def parse_stock(availability_text: str | None) -> StockSignal:
    if not availability_text:
        return StockSignal.UNKNOWN
    text = availability_text.strip().lower()
    if any(h in text for h in _OUT_OF_STOCK_HINTS):
        return StockSignal.OUT_OF_STOCK
    if any(h in text for h in _ORDER_HINTS):
        return StockSignal.MADE_TO_ORDER
    if any(h in text for h in _IN_STOCK_HINTS):
        return StockSignal.IN_STOCK
    return StockSignal.UNKNOWN


# Shop catalogues carry entries that are not stock: a placeholder a theme or an
# app created ("Item", "point1"), a delivery fee a checkout app sells as a product,
# a service. Published as products, they are the first thing a shop notices.
_PLACEHOLDER_TITLE = re.compile(r"(?:items?|points?|products?|test|untitled|sample)\s*-?\s*\d*")
_FEE_TITLE = re.compile(
    r"(?:local |express |home |free |standard )?(?:delivery|shipping)"
    r"(?: (?:fees?|charges?|costs?|services?))?"
)
#: A shop filing a listing under one of these says itself that it is not stock.
_SERVICE_CATEGORIES = {"service", "services"}


def not_a_product(title: str | None, categories: list[str] | None = None) -> str | None:
    """Why a catalogue entry is not a product, or None if it is one.

    Deliberately narrow — the whole title has to be the placeholder or the fee,
    and the category has to be exactly "Services" — because a false positive is
    a real product silently dropped. "Disc Brake Pad & Caliper Service Tool Kit"
    and "Automatic Delivery System for Greases" are products; "Local Delivery"
    and "3D Printing Service" filed under Services are not.
    """
    text = normalize_category_name(title)
    if _PLACEHOLDER_TITLE.fullmatch(text):
        return "placeholder title"
    if _FEE_TITLE.fullmatch(text):
        return "delivery fee"
    if any(normalize_category_name(c) in _SERVICE_CATEGORIES for c in categories or []):
        return "filed as a service"
    return None


def normalize_item(raw: RawItem, domain: str | None = None) -> NormalizedListing:
    reasons: list[str] = []

    # Title: decode entities/whitespace, then route to EN or AR by script.
    title = clean_text(raw.title)
    title_en = title_ar = None
    if title:
        if _has_arabic(title):
            title_ar = title
        else:
            title_en = title

    # A missing/zero price is common on real sites (unpriced / "price on request")
    # — it's shown as unavailable, NOT treated as an extraction error.
    price = parse_price(raw.price_text)

    stock = parse_stock(raw.availability_text)

    # Confidence gates the review queue. A confident title is what matters; a
    # missing price does not lower confidence.
    confidence = 1.0
    if not (title_en or title_ar):
        confidence -= 0.6
        reasons.append(ReviewReason.AMBIGUOUS_PARSE)
    if raw.category_hint is None:
        confidence -= 0.1
    confidence = max(0.0, round(confidence, 2))

    if confidence < REVIEW_THRESHOLD and ReviewReason.LOW_CONFIDENCE not in reasons:
        reasons.append(ReviewReason.LOW_CONFIDENCE)

    description = clean_text(raw.description)
    desc_is_ar = bool(description and _has_arabic(description))

    return NormalizedListing(
        source=raw.source,
        external_id=raw.external_id,
        source_url=raw.source_url,
        title_en=title_en,
        title_ar=title_ar,
        description_en=None if desc_is_ar else description,
        description_ar=description if desc_is_ar else None,
        # Prefer an adapter-provided MPN; otherwise extract from the title.
        part_number=raw.part_number or get_profile(domain).extract_identifier(title),
        brand=raw.brand,
        price=price,
        currency=(raw.currency or DEFAULT_CURRENCY).upper()[:3],
        unit=raw.unit_text,
        stock_signal=stock,
        category_slug=None,  # category mapping is a later step
        images=raw.images,
        attributes=raw.raw,
        confidence=confidence,
        review_reasons=reasons,
    )
