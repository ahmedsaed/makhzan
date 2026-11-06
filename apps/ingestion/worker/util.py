"""Small parsing helpers shared by adapters."""

from __future__ import annotations

from selectolax.parser import HTMLParser


def strip_html(html: str | None) -> str | None:
    """Flatten an HTML fragment to one line of plain text.

    One line on purpose: the newlines in an HTML fragment are source formatting,
    not the shop's line breaks, and descriptions now keep line breaks. For text
    that keeps the fragment's structure, use `worker.richtext.html_to_text`.
    """
    if not html:
        return None
    text = " ".join(HTMLParser(html).text(separator=" ").split())
    return text or None
