"""Reading a shop's own product prose: structured text, spec tables, datasheets.

Shops publish descriptions as HTML, and the structure carries meaning: a list of
features, a "Parameter | Specification" table, a link to the datasheet. Flattening
it to one line (`util.strip_html`) keeps the words and loses all of that — the
product page then shows a wall of text where the shop showed a table.

Everything here works on HTML an adapter already has. Nothing fetches.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

#: Elements that start a new line. Anything else (b, span, a, em…) is inline.
_BLOCK = {
    "address", "article", "blockquote", "dd", "div", "dl", "dt", "figcaption",
    "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
    "ol", "p", "pre", "section", "table", "tbody", "thead", "tfoot", "ul",
}  # fmt: skip
#: Never text: scripts, embedded players, form controls.
_SKIP = {"script", "style", "iframe", "noscript", "object", "embed", "svg", "button", "form"}

_SPACES = re.compile(r"[ \t\r\f\v\xa0​]+")


def _cell_text(node: Node) -> str:
    return _SPACES.sub(" ", node.text(separator=" ")).strip()


def _row_text(row: Node) -> str:
    cells = [c for c in (_cell_text(cell) for cell in row.css("td, th")) if c]
    if len(cells) == 2:
        # A two-column row is a name and a value — read it as one.
        return f"{_strip_label(cells[0])}: {cells[1]}"
    return " | ".join(cells)


def html_to_text(html: str | None) -> str | None:
    """Plain text that keeps the HTML's line structure.

    Blocks and `<br>` become line breaks, list items get a bullet, a table row
    becomes one line; blank lines are dropped. Inline markup joins its
    neighbours without a break, so "<b>5</b>V" stays "5V".
    """
    if not html:
        return None
    tree = HTMLParser(html)
    root = tree.body or tree.root
    if root is None:
        return None

    out: list[str] = []

    def walk(node: Node) -> None:
        for child in node.iter(include_text=True):
            tag = child.tag
            if tag == "-text":
                out.append(child.text_content or "")
            elif tag in _SKIP or tag in ("-comment", "img"):
                continue
            elif tag == "br":
                out.append("\n")
            elif tag == "tr":
                out.append(f"\n{_row_text(child)}\n")
            else:
                block = tag in _BLOCK
                if block:
                    out.append("\n")
                if tag == "li":
                    out.append("• ")
                walk(child)
                if block:
                    out.append("\n")

    walk(root)
    lines = (_SPACES.sub(" ", line).strip() for line in "".join(out).split("\n"))
    text = "\n".join(line for line in lines if line and line != "•")
    return text or None


# --------------------------------------------------------------------------- #
# Specs
# --------------------------------------------------------------------------- #

#: Words a spec table's header row uses for its two columns.
_HEADER_WORDS = {
    "parameter", "parameters", "specification", "specifications", "spec", "specs",
    "details", "detail", "value", "values", "item", "items", "property",
    "properties", "feature", "features", "attribute", "description", "data",
}  # fmt: skip
#: A table whose first column is one of these is a pinout or a part list, not specs.
_NOT_SPEC_TABLE = {"pin", "pins", "pin name", "pin no", "pin no.", "pin number", "no", "no.", "#"}
#: …and one whose second column is one of these is wiring: "Wire Color | Function".
_WIRING_COLUMN = {"function", "functions", "purpose", "connection", "connect to", "usage"}

#: "Operating Voltage: 5V" on a line of its own. Bounded on purpose: a feature bullet
#: ("Excellent IR Rejection: provides >99% typical infrared rejection across…")
#: has the same shape, and only its length tells it apart.
_KV_LINE = re.compile(r"^(?P<k>[^\W\d_][\w /().,+°%-]{0,39}?)\s*[:：]\s*(?P<v>\S.*)$")
_MAX_KEY_WORDS = 5
_MAX_VALUE = 60
_MAX_SPECS = 40


def _strip_label(text: str) -> str:
    return text.strip().rstrip(":：").strip()


def _add(specs: dict[str, str], key: str, value: str) -> None:
    key, value = _strip_label(key), value.strip()
    if not key or not value or len(key) > 40 or len(key.split()) > _MAX_KEY_WORDS:
        return
    if len(value) > _MAX_VALUE or len(specs) >= _MAX_SPECS:
        return
    # First statement wins: a later "Voltage" in the prose does not overwrite the table.
    if key.lower() not in {k.lower() for k in specs}:
        specs[key] = value


def specs_from_html(html: str | None) -> dict[str, str]:
    """Name → value pairs a shop published in its description.

    Two shapes are read, both common in shop descriptions:
      - a two-column table (optionally under a "Parameter | Specification"
        header), but not a pinout — "Pin | Function" is wiring, not specs;
      - lines and list items written "Name: value".

    Conservative by construction: short keys, short values, first one wins. A
    spec missed is a line still in the description; a feature bullet published
    as a spec is a wrong fact on the product page.
    """
    if not html:
        return {}
    tree = HTMLParser(html)
    specs: dict[str, str] = {}

    for table in tree.css("table"):
        rows = [[_cell_text(c) for c in tr.css("td, th")] for tr in table.css("tr")]
        rows = [r for r in rows if len(r) == 2 and all(r)]
        if not rows:
            continue
        head = [_strip_label(c).lower() for c in rows[0]]
        if head[0] in _NOT_SPEC_TABLE or head[1] in _WIRING_COLUMN:
            continue
        if head[0] in _HEADER_WORDS and head[1] in _HEADER_WORDS:
            rows = rows[1:]
        for key, value in rows:
            _add(specs, key, value)

    # Then the prose, with the tables taken out: a pinout's rows read exactly
    # like "Name: value" lines once flattened, and were rejected above on purpose.
    for table in tree.css("table"):
        table.decompose()
    body = tree.body or tree.root
    for line in ((html_to_text(body.html) if body else None) or "").split("\n"):
        match = _KV_LINE.match(line.removeprefix("• "))
        if match:
            _add(specs, match.group("k"), match.group("v"))

    return specs


def merge_specs(first: dict[str, str], more: dict[str, str]) -> dict[str, str]:
    """`first` as it is, then whatever of `more` it does not already state.

    For a shop with structured attributes as well as a description: the
    attributes win, and the description's "Name: value" lines only add names
    they lack, under the same caps as `specs_from_html`.
    """
    merged = dict(first)
    for key, value in more.items():
        _add(merged, key, value)
    return merged


def documents_from_html(html: str | None, base_url: str) -> list[dict[str, str]]:
    """Links to PDFs (datasheets, manuals) in a description, as {label, url}."""
    if not html:
        return []
    docs: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in HTMLParser(html).css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href.lower().split("?")[0].endswith(".pdf"):
            continue
        url = urljoin(base_url + "/", href)
        # A "mailto:…?subject=x.pdf" or a script link is not a document.
        if url in seen or not url.startswith(("http://", "https://")):
            continue
        seen.add(url)
        label = _cell_text(a) or url.rsplit("/", 1)[-1].split("?")[0]
        docs.append({"label": label, "url": url})
    return docs
