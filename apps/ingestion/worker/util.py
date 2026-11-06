"""Small parsing helpers shared by adapters."""

from __future__ import annotations

from selectolax.parser import HTMLParser


def strip_html(html: str | None) -> str | None:
    """Flatten an HTML fragment to plain text (product descriptions arrive as HTML)."""
    if not html:
        return None
    text = HTMLParser(html).text(separator=" ").strip()
    return text or None
