"""Reading a shop's own product prose: structured text, spec tables, datasheets.

Shops publish descriptions as HTML, and the structure carries meaning: a list of
features, a "Parameter | Specification" table, a link to the datasheet. Flattening
it to one line (`util.strip_html`) keeps the words and loses all of that — the
product page then shows a wall of text where the shop showed a table.

Everything here works on HTML an adapter already has. Nothing fetches.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urljoin, urlsplit

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


_HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}


def _heading_key(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def without_sections(html: str | None, headings: list[str] | tuple[str, ...]) -> str | None:
    """`html` without the sections under the named headings.

    For a shop that appends the same boilerplate ("Why buy from us?", "Ordering
    and delivery") to every description: identical on most of the catalogue, it
    would otherwise dominate every text index and bury the product's own words.

    A section is its heading and everything after it up to the next heading of
    the same or a higher level, so a sub-heading inside it goes with it. Headings
    match by their words, ignoring case and punctuation. Only top-level siblings
    are removed: a template's sections are flat, and reaching into nested markup
    risks taking the product's own text with it.
    """
    if not html or not headings:
        return html
    wanted = {_heading_key(h) for h in headings if h.strip()}
    tree = HTMLParser(html)
    root = tree.body or tree.root
    if root is None:
        return html
    doomed: list[Node] = []
    level = None  # the level of the section being removed, while inside one
    for node in root.iter():
        rank = _HEADING.get(node.tag)
        if rank is not None and level is not None and rank <= level:
            level = None
        if level is None and rank is not None and _heading_key(node.text()) in wanted:
            level = rank
        if level is not None:
            doomed.append(node)
    if not doomed:
        return html
    for node in doomed:
        node.decompose()
    return "".join(child.html or "" for child in root.iter(include_text=True))


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
#: "Note: check the pinout", "Slogan: Power your ideas": shaped like a spec line,
#: but advice or marketing. Checked in the prose only; a spec table's rows are
#: specs by construction.
_NOT_A_SPEC = {
    "note", "notes", "slogan", "warning", "caution", "attention", "important", "tip",
    "tips", "hint", "reminder", "remark", "remarks", "disclaimer", "shipping",
    "delivery", "contact", "contact us", "ps", "p.s", "nb", "n.b",
}  # fmt: skip
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
        if match and _strip_label(match.group("k")).lower().rstrip(".") not in _NOT_A_SPEC:
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


#: Datasheet archives whose pages are datasheets without ending in ".pdf"
#: ("…/datasheet-pdf/pdf/23210/…/74HC07.html"). Kept to hosts that serve nothing
#: else: a link to a maker's product page or a wiki is a page, not a document.
_DATASHEET_HOSTS = ("alldatasheet.com",)


def _is_document(href: str) -> bool:
    url = urlsplit(href.lower())
    if url.path.endswith(".pdf"):
        return True
    host = url.hostname or ""
    return "datasheet" in url.path and any(
        host == h or host.endswith("." + h) for h in _DATASHEET_HOSTS
    )


def documents_from_html(html: str | None, base_url: str) -> list[dict[str, str]]:
    """Links to datasheets and manuals in a description, as {label, url}.

    A document is a link to a PDF, or to a page of a datasheet archive.
    """
    if not html:
        return []
    docs: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in HTMLParser(html).css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not _is_document(href):
            continue
        url = urljoin(base_url + "/", href)
        # A "mailto:…?subject=x.pdf" or a script link is not a document.
        if url in seen or not url.startswith(("http://", "https://")):
            continue
        seen.add(url)
        label = _cell_text(a) or re.split(r"[?#]", url.rsplit("/", 1)[-1], maxsplit=1)[0]
        docs.append({"label": label, "url": url})
    return docs


# --------------------------------------------------------------------------- #
# Videos
# --------------------------------------------------------------------------- #

_YOUTUBE_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_YOUTUBE_HOSTS = ("youtube.com", "youtube-nocookie.com")
#: Labels that name the player, not the video: a shop pasting YouTube's embed
#: code gets `title="YouTube video player"` on every one of them.
_GENERIC_VIDEO_LABELS = {
    "youtube video player", "youtube video", "youtube", "vimeo video player", "vimeo",
    "video player", "video", "click here", "here", "watch", "watch video", "link",
}  # fmt: skip
_MAX_VIDEOS = 10


def _on(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def video_url(href: str | None) -> str | None:
    """The canonical https address of a YouTube or Vimeo video, or None.

    Embeds and links to one video come in many spellings ("//www.youtube.com/
    embed/ID?si=…", "youtu.be/ID", "watch?v=ID&t=30", "player.vimeo.com/video/N");
    they are reduced to one per video so the same video is not listed twice.
    Anything else — a channel, a playlist, a shop's own mp4 — is not one.
    """
    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    try:
        url = urlsplit(href)
        host = (url.hostname or "").lower()
    except ValueError:
        return None
    if url.scheme not in ("http", "https"):
        return None
    segments = [s for s in url.path.split("/") if s]
    video_id = None
    if _on(host, _YOUTUBE_HOSTS):
        if url.path == "/watch":
            video_id = (parse_qs(url.query).get("v") or [None])[0]
        elif len(segments) >= 2 and segments[0] in ("embed", "shorts", "live", "v"):
            video_id = segments[1]
        if video_id and _YOUTUBE_ID.fullmatch(video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
    elif host == "youtu.be":
        if segments and _YOUTUBE_ID.fullmatch(segments[0]):
            return f"https://www.youtube.com/watch?v={segments[0]}"
    elif _on(host, ("vimeo.com",)):
        if host == "player.vimeo.com" and len(segments) >= 2 and segments[0] == "video":
            video_id = segments[1]
        elif host in ("vimeo.com", "www.vimeo.com") and len(segments) == 1:
            video_id = segments[0]
        if video_id and video_id.isascii() and video_id.isdigit():
            return f"https://vimeo.com/{video_id}"
    return None


def videos_from_html(html: str | None) -> list[dict[str, str]]:
    """YouTube and Vimeo videos a description embeds or links to, as {label, url}.

    The label is the embed's title or the link's text, unless that only names
    the player ("YouTube video player"), in which case it is "Video". URLs are
    canonical https watch addresses, so an embed and a link to the same video
    count once.
    """
    if not html:
        return []
    videos: list[dict[str, str]] = []
    seen: set[str] = set()
    for node in HTMLParser(html).css("iframe, a[href]"):
        attrs = node.attributes
        if node.tag == "iframe":
            url = video_url(attrs.get("src") or attrs.get("data-src"))
            label = (attrs.get("title") or "").strip()
        else:
            url = video_url(attrs.get("href"))
            label = _cell_text(node)
        if not url or url in seen:
            continue
        seen.add(url)
        if not label or label.lower() in _GENERIC_VIDEO_LABELS or video_url(label):
            label = "Video"
        videos.append({"label": label[:120], "url": url})
        if len(videos) >= _MAX_VIDEOS:
            break
    return videos


# --------------------------------------------------------------------------- #
# Product pages
# --------------------------------------------------------------------------- #

#: A heading that introduces a shop's links to datasheets, manuals and wikis.
_DOCUMENTS_HEADING = re.compile(
    r"^(?:documents?|documentation|downloads?|datasheets?|data sheets?|manuals?|resources?"
    r"|files?|useful links?)\b",
    re.I,
)
_MAX_LINK_LABEL = 120


def _is_heading(node: Node) -> bool:
    """A heading element, or a short bold or paragraph line standing as one."""
    if node.tag in _HEADING:
        return True
    if node.tag not in ("p", "strong", "b") or node.css_first("a") is not None:
        return False
    text = _cell_text(node)
    return 0 < len(text) <= 40 and not _KV_LINE.match(text)


def section_links(html: str | None, base_url: str) -> list[dict[str, str]]:
    """Every link under a "Documents" / "Downloads" / "Datasheet" heading, as {label, url}.

    Shops that write their own descriptions link a datasheet as often to the
    maker's product page or wiki as to a PDF, and `documents_from_html` takes
    PDFs only. Under a heading that says "these are the documents", a link is a
    document whatever it ends in. The section runs to the next heading.
    """
    if not html:
        return []
    tree = HTMLParser(html)
    root = tree.body or tree.root
    if root is None:
        return []
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    inside = False
    for node in root.traverse():
        if _is_heading(node):
            inside = bool(_DOCUMENTS_HEADING.match(_cell_text(node).rstrip(":：")))
            continue
        if not inside or node.tag != "a":
            continue
        url = urljoin(base_url + "/", (node.attributes.get("href") or "").strip())
        if url in seen or not url.startswith(("http://", "https://")) or video_url(url):
            continue
        seen.add(url)
        label = _cell_text(node) or url.rsplit("/", 1)[-1]
        links.append({"label": label[:_MAX_LINK_LABEL], "url": url})
    return links


#: Spec names that state the maker, and its own part number, in so many words.
#: Compared with everything but letters and "#" removed. A bare "Part Number" or
#: "Model" is not here: on a shop's own page it is as likely its catalogue code.
_MAKER_KEYS = {"brand", "manufacturer", "manufacturerbrand", "mfr", "mfg", "maker"}
_MAKER_PART_KEYS = {
    "mfrpart#", "mfrpartno", "mfrpartnumber", "manufacturerpart#", "manufacturerpartno",
    "manufacturerpartnumber", "mpn",
}  # fmt: skip
_NOT_A_MAKER = {"generic", "no brand", "unbranded", "oem", "other", "others", "none", "n/a"}


def maker_from_specs(specs: dict[str, str]) -> tuple[str | None, str | None]:
    """(brand, manufacturer part number) a spec sheet states explicitly, if any."""
    brand = part = None
    for name, value in specs.items():
        key = re.sub(r"[^a-z#]", "", name.lower())
        value = value.strip()
        if key in _MAKER_PART_KEYS and part is None and 0 < len(value) <= 60:
            part = value
        elif key in _MAKER_KEYS and brand is None and value.lower() not in _NOT_A_MAKER:
            brand = value[:120] or None
    return brand, part
