"""Production publishes the web app on the Docker bridge only, and the API not at all.

A web port the internet can reach skips the reverse proxy, and Next's rewrite
forwards whatever X-Forwarded-For a visitor sends: the report rate limit
(apps/api/app/client_ip.py) would then count an address the visitor chose.
Read as text, so the check needs no YAML parser.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = (ROOT / "docker-compose.prod.yml").read_text()


def _service(name: str) -> str:
    """The lines of one top-level service, up to the next one."""
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S)", COMPOSE, re.M | re.S)
    assert match, f"no {name} service"
    return match.group(1)


def _published(block: str) -> list[str]:
    ports = re.search(r"^    ports:\n((?:      - .*\n)+)", block, re.M)
    return re.findall(r'- "?([^"\n]+)"?', ports.group(1)) if ports else []


def test_the_web_app_is_published_on_the_bridge_address_only():
    assert _published(_service("web")) == ["${WEB_BIND:-172.17.0.1}:${WEB_PORT:-3000}:3000"]


def test_nothing_else_publishes_a_port():
    for name in ("api", "db", "search", "redis", "ingestion", "migrate"):
        assert _published(_service(name)) == [], name


def test_the_example_env_names_the_bind_address():
    example = (ROOT / ".env.prod.example").read_text()
    assert re.search(r"^WEB_BIND=172\.17\.0\.1$", example, re.M)
