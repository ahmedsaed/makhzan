"""Web Bot Auth for the crawler: an httpx `Auth` that signs every request, and a CLI.

The signing itself is `makhzan_schemas.botauth`, shared with the API's key
directory. This module only attaches it to httpx: `auth_flow` runs once per
request *sent*, so a retry (a new `client.request`) and every redirect hop
(`client.send(next_request)` in worker/http.py) are signed afresh, each with its
own `created`, `expires` and `nonce`. A hop built by httpx copies the previous
request's headers, signature included; it is overwritten here, never reused.

    python -m worker.botauth keygen
        A new Ed25519 key: the private half for .env.prod, the public JWK and
        its keyid (the thumbprint) for the registration forms.

    python -m worker.botauth show
        The keyid and public JWK of the key(s) in the environment.

    python -m worker.botauth headers [--sign] URL
        The exact headers the `makhzanbot` identity sends to URL, one
        `Name: value` per line (used by scripts/probe-suppliers.sh). Sends nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Generator

import httpx
from makhzan_schemas import botauth


class WebBotAuth(httpx.Auth):
    """Adds `Signature-Agent`, `Signature-Input` and `Signature` to each request."""

    def __init__(self, signer: botauth.Signer, site_url: str) -> None:
        self.signer = signer
        #: Validated once here: a non-https site cannot be a Signature-Agent.
        self.signature_agent = botauth.signature_agent_header(site_url)

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Signature-Agent"] = self.signature_agent
        request.headers.update(
            self.signer.sign_request(request.method, str(request.url), request.headers)
        )
        yield request


def _keygen(_: argparse.Namespace) -> int:
    key = botauth.generate_private_key()
    jwk = botauth.public_jwk(key)
    print("# Private key: put this line in .env.prod on the server, and nowhere else.")
    print(f"{botauth.KEY_ENV}={botauth.private_key_to_text(key)}")
    print()
    print("# Public JWK (published by the key directory; safe to share):")
    print(json.dumps(jwk))
    print(f"# keyid (JWK SHA-256 thumbprint): {botauth.jwk_thumbprint(jwk)}")
    return 0


def _show(_: argparse.Namespace) -> int:
    keys = botauth.directory_keys()
    if not keys:
        print(f"no key configured ({botauth.KEY_ENV} / {botauth.KEY_ENV}_FILE)", file=sys.stderr)
        return 1
    for name, key in zip(("current", "next"), keys, strict=False):
        jwk = botauth.public_jwk(key)
        print(f"{name}: keyid {botauth.jwk_thumbprint(jwk)}  {json.dumps(jwk)}")
    return 0


def _headers(args: argparse.Namespace) -> int:
    from worker.identity import MAKHZANBOT, identity_for

    identity = identity_for(MAKHZANBOT, sign=args.sign)
    if args.sign and identity.auth is None:
        print(f"no signing key configured ({botauth.KEY_ENV})", file=sys.stderr)
        return 1
    request = httpx.Request("GET", args.url, headers=dict(identity.headers))
    if identity.auth is not None:
        next(identity.auth.auth_flow(request))
    for name in [*identity.headers, "Signature-Agent", "Signature-Input", "Signature"]:
        if name in request.headers:
            print(f"{name}: {request.headers[name]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m worker.botauth", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("keygen", help="generate a new Ed25519 signing key").set_defaults(
        run=_keygen
    )
    commands.add_parser("show", help="show the configured key(s)").set_defaults(run=_show)
    headers = commands.add_parser("headers", help="print makhzanbot's headers for a URL")
    headers.add_argument("url")
    headers.add_argument("--sign", action="store_true", help="add a fresh signature")
    headers.set_defaults(run=_headers)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
