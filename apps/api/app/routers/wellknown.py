"""The crawler's key directory: `/.well-known/http-message-signatures-directory`.

A shop's edge that receives a request signed by makhzanbot (Web Bot Auth) reads
its `Signature-Agent` header — our site's origin — and fetches this path to find
the public key whose thumbprint is the signature's `keyid`. Cloudflare and the
IETF draft ask for:

  - a JWKS body with `Content-Type: application/http-message-signatures-directory+json`;
  - a plain 200, never a redirect (the web app proxies the path here with a
    rewrite, not a redirect: apps/web/next.config.ts);
  - the response itself signed by every key it lists, with
    `tag="http-message-signatures-directory"`, covering the request's
    `@authority` — taken from SITE_URL, not from the Host header, which behind
    the web app's proxy is the API's internal name.

Two keys at once for rotation: `MAKHZANBOT_SIGNING_KEY` (current, signs the
crawler's requests) and `MAKHZANBOT_SIGNING_KEY_NEXT` (published ahead of the
switch). The private keys are needed here only to sign this response. No key
configured means no directory: 404.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Response
from makhzan_schemas import botauth

router = APIRouter(tags=["crawler"])


@router.get(botauth.DIRECTORY_PATH, include_in_schema=False)
async def key_directory() -> Response:
    keys = botauth.directory_keys()
    site = os.environ.get("SITE_URL", "").strip().rstrip("/")
    if not keys or not site:
        raise HTTPException(status_code=404, detail="no crawler signing key is configured")
    headers = botauth.sign_directory_response(keys, site)
    # Short: a verifier re-fetches during a rotation, and the response
    # signature (valid DIRECTORY_LIFETIME seconds) must outlive any cached copy.
    headers["Cache-Control"] = "public, max-age=60"
    return Response(
        content=botauth.directory_body(keys),
        media_type=botauth.DIRECTORY_MEDIA_TYPE,
        headers=headers,
    )
