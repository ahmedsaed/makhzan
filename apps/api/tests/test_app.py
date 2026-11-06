"""App-level wiring: the health probe and the CORS policy.

The frontend calls this API from the browser, so CORS is not decoration — if the
allow-list stops covering the web origin, every request from the app fails in a
way the API's own logs look healthy through.
"""

from __future__ import annotations


async def test_health_reports_ok(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_the_default_allow_list_covers_the_dev_web_origin(client):
    """WEB_ORIGINS is unset in tests, which is the shape a fresh checkout runs in."""
    response = await client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_an_unknown_origin_is_not_allowed(client):
    response = await client.get("/health", headers={"Origin": "https://evil.test"})

    # The request itself still succeeds; the browser is what enforces the absence
    # of the header, so that is what this asserts.
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_unknown_routes_404(client):
    assert (await client.get("/nope")).status_code == 404
