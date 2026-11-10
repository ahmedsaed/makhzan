"""/.well-known/http-message-signatures-directory — makhzanbot's public keys.

What a verifier relies on: the media type, a plain 200, a JWKS holding the
current key (and the next one during a rotation), and the response signed by
each key over the site's own authority, checked here with `cryptography` alone.
"""

from __future__ import annotations

import base64
import json
import re

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from makhzan_schemas import botauth

PATH = "/.well-known/http-message-signatures-directory"
# RFC 9421 test-key-ed25519 (Appendix B.1.4), as `d` and `x`.
KEY = "n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU"
KEY_X = "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://makhzan.test")
    monkeypatch.setenv(botauth.KEY_ENV, KEY)
    monkeypatch.delenv(botauth.NEXT_KEY_ENV, raising=False)


def _b64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _verify_all(response, authority: str) -> list[str]:
    inputs = response.headers["signature-input"].split(", ")
    signatures = response.headers["signature"].split(", ")
    keys = {botauth.jwk_thumbprint(k): k for k in response.json()["keys"]}
    verified = []
    for raw_input, raw_sig in zip(inputs, signatures, strict=True):
        label, _, params = raw_input.partition("=")
        assert raw_sig.startswith(f"{label}=:")
        keyid = re.search(r';keyid="([^"]+)"', params)[1]
        assert 'tag="http-message-signatures-directory"' in params
        base = f'"@authority";req: {authority}\n"@signature-params": {params}'.encode()
        signature = base64.b64decode(raw_sig.split("=:", 1)[1].rstrip(":"))
        Ed25519PublicKey.from_public_bytes(_b64url(keys[keyid]["x"])).verify(signature, base)
        verified.append(keyid)
    return verified


async def test_serves_the_jwks_with_its_media_type(client, keyed):
    response = await client.get(PATH, follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/http-message-signatures-directory+json"
    assert response.json() == {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": KEY_X}]}
    # Nothing private in it.
    assert KEY not in response.text and '"d"' not in response.text


async def test_the_response_is_signed_over_the_sites_authority_not_the_host_header(client, keyed):
    # The test client's Host is "testserver"; the signature must still name
    # the public site, which is what a verifier fetched.
    response = await client.get(PATH)
    assert _verify_all(response, "makhzan.test") == [
        botauth.jwk_thumbprint({"kty": "OKP", "crv": "Ed25519", "x": KEY_X})
    ]


async def test_a_rotation_publishes_both_keys_and_signs_with_both(client, keyed, monkeypatch):
    following = botauth.generate_private_key()
    monkeypatch.setenv(botauth.NEXT_KEY_ENV, botauth.private_key_to_text(following))
    response = await client.get(PATH)
    xs = [k["x"] for k in response.json()["keys"]]
    assert xs == [KEY_X, botauth.public_jwk(following)["x"]]
    assert len(_verify_all(response, "makhzan.test")) == 2


async def test_no_key_means_no_directory(client, monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://makhzan.test")
    monkeypatch.delenv(botauth.KEY_ENV, raising=False)
    monkeypatch.delenv(f"{botauth.KEY_ENV}_FILE", raising=False)
    monkeypatch.delenv(botauth.NEXT_KEY_ENV, raising=False)
    response = await client.get(PATH)
    assert response.status_code == 404
    assert json.loads(response.text)["detail"]
