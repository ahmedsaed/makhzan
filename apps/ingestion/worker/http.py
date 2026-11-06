"""Shared HTTP client for adapters.

Two lessons baked in from real supplier sites:
  - WAFs reject bare/unusual requests, so we send browser-like headers.
  - Sites rate-limit, so `get_json` backs off and retries on 429/503 (honoring
    Retry-After), and adapters pace themselves between pages.

Being deliberate about pacing keeps the pragmatic scraping stance (docs/PLAN.md)
from getting sources blocked.
"""

from __future__ import annotations

import asyncio
import random

import httpx

# A contact address lives in the header set so we're identifiable without tripping
# WAFs. Everything else here exists to look like a current browser. This set is
# shared by every adapter via make_client(), so a fix here covers all sources.
#
# The User-Agent version is load-bearing, not decoration: Cloudflare scores a
# stale browser version as a bot. One supplier's shop returned 429 with a
# zero-length body to Chrome/124 while serving Chrome/139 normally from the same
# IP — which looked exactly like rate limiting and cost a long investigation.
# Bump this when it ages; treat a sudden 429 on a Cloudflare-fronted site as a
# suspect here before assuming a rate limit.
#
# Checking what "current" is does not need a guess: Playwright ships a real
# Chromium, and `apps/web` pins it. `browser.version()` reported 153.0.8010.12,
# so 139 was fourteen releases — well over a year — behind.
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
    "From": "crawler@merope.dev",
}

#: Default seconds to wait between paginated requests to the same host.
#: Sized for a weekly refresh cycle rather than a daily one: each run now sweeps
#: a slice of the catalogue, so even the busiest source makes a few hundred
#: requests a day and can afford a long pause between them.
#: This is a per-HOST pace, not a global one: sources hit different origins with
#: independent rate limits, so the worker scrapes them concurrently (see
#: refresh_all) while each host still sees only one request per this interval.
#: Touchier sources (e.g. behind Cloudflare) can raise it via SourceAdapter.polite_delay.
POLITE_DELAY = 15.0

_RETRYABLE = {429, 503}


def make_client(**kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=BROWSER_HEADERS,
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
        **kwargs,
    )


async def _request(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None,
    retries: int,
    base_delay: float,
    method: str = "GET",
    **kwargs,
) -> httpx.Response:
    """Request with backoff on rate-limit/unavailable responses.

    Not every source answers on GET: one marketplace returns its product listings only
    to a POST against the same URL. The retry and pacing behaviour is identical
    either way, so the method is a parameter rather than a second code path.
    """
    # Imported here rather than at module scope: robots.py needs this module's
    # headers, so a top-level import would be circular.
    from worker.robots import ROBOTS, DisallowedByRobots

    if not await ROBOTS.allowed(url, BROWSER_HEADERS["User-Agent"]):
        raise DisallowedByRobots(url)

    resp = None
    for attempt in range(retries + 1):
        resp = await client.request(method, url, params=params, **kwargs)
        if resp.status_code in _RETRYABLE and attempt < retries:
            retry_after = resp.headers.get("Retry-After", "")
            delay = (
                float(retry_after)
                if retry_after.isdigit()
                else base_delay * (2**attempt) + random.uniform(0, 0.5)
            )
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()  # exhausted retries — surface the last error
    return resp  # unreachable


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    *,
    retries: int = 5,
    base_delay: float = 2.0,
    method: str = "GET",
    **kwargs,
):
    """Fetch parsed JSON (GET by default; pass method="POST" where a source needs it)."""
    return (await _request(client, url, params, retries, base_delay, method, **kwargs)).json()


async def get_text(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    *,
    retries: int = 5,
    base_delay: float = 2.0,
) -> str:
    """GET returning response text (for HTML-scraped sources)."""
    return (await _request(client, url, params, retries, base_delay)).text
