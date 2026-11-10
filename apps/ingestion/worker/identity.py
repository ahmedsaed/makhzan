"""Who the crawler says it is, per source.

Two identities, chosen per source by `identity = "browser" | "makhzanbot"` in its
config (default "browser", so nothing changes until a shop is switched by hand):

  - **browser**: what the crawler has always sent — a current Chrome
    User-Agent, Chrome's client hints and fetch metadata, plus `From`.
  - **makhzanbot**: an honest crawler. `makhzanbot/1.0 (+<SITE_URL>/how-we-crawl;
    <contact>)`, no client hints, no `Sec-Fetch-*`, `From` kept, and — when a key
    is configured — every request signed with Web Bot Auth (worker/botauth.py),
    so a shop's edge can verify it is really us.

Why both: the browser identity is the pattern Cloudflare publicly calls stealth
crawling, and it leaves a shop no way to address us in robots.txt. The honest
one is the goal, but some WAFs will challenge an unknown bot, so shops are
switched one at a time after a probe (docs/crawler-identity.md), never all at
once, and a shop that refuses makhzanbot is written to, not given the browser
headers back.

robots.txt is matched on our own token, `makhzanbot`, whichever identity sends
the request (worker/robots.py): a shop that names us must reach us either way.

The identity in force is a context variable set by the pipeline for a run
(`using_identity`), the same way the request log is: every client the run makes
(`worker.http.make_client`, a robots.txt fetch, the details stage, a bespoke
adapter kept in the private configuration) reads it, so no adapter has to
thread it through. The pace gate stays process-wide and per host, whatever the
identity.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field

import httpx
from makhzan_schemas import botauth

BROWSER = "browser"
MAKHZANBOT = "makhzanbot"
IDENTITIES = (BROWSER, MAKHZANBOT)

#: Our product token in robots.txt (RFC 9309 §2.2.1), in every identity.
ROBOTS_TOKEN = "makhzanbot"

#: Where a shop can reach the operator. In every request, as `From`.
CONTACT = "crawler@makhzan.merope.dev"

#: The browser identity's Chrome version. Kept as it is while sources still use
#: that identity; it is not to be bumped to get past a bot check. That is the
#: history: Cloudflare scored Chrome/124 as a bot and answered 429 with an
#: empty body, which was misread as rate limiting more than once — and the
#: score was right, the crawler *is* a bot. A WAF objecting is now a reason to
#: switch the shop to makhzanbot and register the key (docs/crawler-identity.md),
#: or to write to the shop; never to look more like a browser.
CHROME_VERSION = "153"

BROWSER_HEADERS = {
    "User-Agent": (
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
    # Deliberately omits "br": httpx only decodes brotli when the optional
    # dependency is installed, and advertising it without that yields raw bytes.
    "Accept-Encoding": "gzip, deflate",
    "sec-ch-ua": f'"Chromium";v="{CHROME_VERSION}", "Not;A=Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "From": CONTACT,
}


def site_url() -> str:
    """The public site's origin (`SITE_URL`), which the User-Agent and Signature-Agent name.

    Read from the environment, never hard-coded: the domain may change, and a
    User-Agent pointing at a dead page is worse than none.
    """
    value = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if not value:
        raise RuntimeError("the makhzanbot identity needs SITE_URL (the public site's origin)")
    return value


def makhzanbot_headers(site: str) -> dict[str, str]:
    return {
        "User-Agent": f"makhzanbot/1.0 (+{site}/how-we-crawl; {CONTACT})",
        # What the adapters actually read: JSON APIs and HTML pages.
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "From": CONTACT,
    }


@dataclass(frozen=True)
class Identity:
    name: str
    headers: Mapping[str, str]
    #: Signs each request (makhzanbot with a configured key), else None.
    auth: httpx.Auth | None = field(default=None, compare=False)
    #: The signing key's thumbprint, for the run's stats and `make status`.
    keyid: str | None = None

    @property
    def signed(self) -> bool:
        return self.auth is not None

    def describe(self) -> dict:
        """What goes on the run's row as `stats.identity` (never published)."""
        out: dict = {"name": self.name, "signed": self.signed}
        if self.keyid:
            out["keyid"] = self.keyid
        return out


BROWSER_IDENTITY = Identity(BROWSER, BROWSER_HEADERS)


def identity_for(name: str, *, sign: bool = True) -> Identity:
    """The identity a source's config names, built from the environment now.

    makhzanbot signs only when a key is configured (`MAKHZANBOT_SIGNING_KEY`);
    without one it is still honest, just unverifiable.
    """
    if name == BROWSER:
        return BROWSER_IDENTITY
    if name != MAKHZANBOT:
        raise ValueError(f"unknown identity {name!r}: expected one of {IDENTITIES}")
    from worker.botauth import WebBotAuth

    site = site_url()
    key = botauth.configured_key() if sign else None
    if key is None:
        return Identity(MAKHZANBOT, makhzanbot_headers(site))
    signer = botauth.Signer(key)
    return Identity(
        MAKHZANBOT, makhzanbot_headers(site), auth=WebBotAuth(signer, site), keyid=signer.keyid
    )


_IDENTITY: ContextVar[Identity | None] = ContextVar("crawler_identity", default=None)


def current_identity() -> Identity:
    """The identity of the run in progress in this task; browser outside any run."""
    return _IDENTITY.get() or BROWSER_IDENTITY


@contextlib.contextmanager
def using_identity(identity: Identity) -> Iterator[Identity]:
    """Send every request made inside the block (and tasks it starts) as `identity`."""
    token = _IDENTITY.set(identity)
    try:
        yield identity
    finally:
        _IDENTITY.reset(token)
