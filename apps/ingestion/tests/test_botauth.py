"""Web Bot Auth signing (makhzan_schemas.botauth, worker/botauth.py).

Pinned three ways, so a mistake cannot hide behind its own implementation:
the RFC 9421 Ed25519 test vector (Appendix B.2.6) for the signature base and
the signature bytes; RFC 8037's thumbprint vector for the `keyid`; and an
independent verifier below that re-derives each signed request's base from
what httpx actually put on the wire and checks it with `cryptography` alone.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from makhzan_schemas import botauth

from worker.botauth import WebBotAuth
from worker.botauth import main as botauth_cli

# RFC 9421 Appendix B.1.4, test-key-ed25519.
RFC_PRIVATE_PEM = """-----BEGIN PRIVATE KEY-----
MC4CAQAwBQYDK2VwBCIEIJ+DYvh6SEqVTm50DFtMDoQikTmiCqirVv9mWG9qfSnF
-----END PRIVATE KEY-----"""
RFC_PUBLIC_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAJrQLj5P/89iXES9+vFgrIy29clF9CC/oPPsw3c5D0bs=
-----END PUBLIC KEY-----"""
RFC_JWK_D = "n4Ni-HpISpVObnQMW0wOhCKROaIKqKtW_2ZYb2p9KcU"
RFC_JWK_X = "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --------------------------------------------------------------------------- #
# The RFC vectors
# --------------------------------------------------------------------------- #


def test_rfc_9421_b_2_6_ed25519_signature():
    """The base and signature of Appendix B.2.6, byte for byte (Ed25519 is deterministic)."""
    key = botauth.load_private_key(RFC_PRIVATE_PEM)
    names = ["date", "@method", "@path", "@authority", "content-type", "content-length"]
    components = [botauth.Component(n) for n in names]
    params = botauth.signature_params(components, created=1618884473, keyid="test-key-ed25519")
    values = [
        "Tue, 20 Apr 2021 02:07:55 GMT",
        botauth.derived_value(
            "@method", method="POST", url="https://example.com/foo?param=Value&Pet=dog"
        ),
        botauth.derived_value(
            "@path", method="POST", url="https://example.com/foo?param=Value&Pet=dog"
        ),
        botauth.derived_value("@authority", method="POST", url="https://example.com/foo"),
        "application/json",
        "18",
    ]
    base = botauth.signature_base(list(zip(components, values, strict=True)), params)

    assert base.decode() == (
        '"date": Tue, 20 Apr 2021 02:07:55 GMT\n'
        '"@method": POST\n'
        '"@path": /foo\n'
        '"@authority": example.com\n'
        '"content-type": application/json\n'
        '"content-length": 18\n'
        '"@signature-params": ("date" "@method" "@path" "@authority" '
        '"content-type" "content-length");created=1618884473;keyid="test-key-ed25519"'
    )
    signature = base64.b64encode(key.sign(base)).decode()
    assert signature == (
        "wqcAqbmYJ2ji2glfAMaRy4gruYYnx2nEFN2HN6jrnDnQCK1u02Gb04v9EDgwUPiu4A0w6vuQv5lIp5WPpBKRCw=="
    )


def test_the_rfc_key_loads_from_pem_and_from_its_jwk_d_alike():
    from_pem = botauth.load_private_key(RFC_PRIVATE_PEM)
    from_seed = botauth.load_private_key(RFC_JWK_D)
    assert botauth.public_jwk(from_pem) == botauth.public_jwk(from_seed)
    assert botauth.public_jwk(from_pem) == {"kty": "OKP", "crv": "Ed25519", "x": RFC_JWK_X}
    public = serialization.load_pem_public_key(RFC_PUBLIC_PEM.encode())
    assert botauth.public_jwk(public)["x"] == RFC_JWK_X
    assert botauth.private_key_to_text(from_pem) == RFC_JWK_D


def test_rfc_8037_a_3_thumbprint():
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"}
    assert botauth.jwk_thumbprint(jwk) == "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"


def test_a_key_that_is_not_ed25519_is_refused():
    with pytest.raises(ValueError):
        botauth.load_private_key("c2hvcnQ")


# --------------------------------------------------------------------------- #
# Signature-Agent: the one place the Cloudflare-vs-draft choice lives
# --------------------------------------------------------------------------- #


def test_signature_agent_is_cloudflares_bare_quoted_string_not_the_drafts_dictionary():
    """Cloudflare fails `sig1="https://…"` (draft -01's dictionary form) and
    requires a bare sf-string. If this changes, change `signature_agent_header`."""
    assert botauth.signature_agent_header("https://makhzan.test") == '"https://makhzan.test"'
    assert botauth.signature_agent_header("https://Makhzan.TEST:443/") == '"https://makhzan.test"'
    assert "=" not in botauth.signature_agent_header("https://makhzan.test")


@pytest.mark.parametrize("origin", ["http://makhzan.test", "makhzan.test", ""])
def test_signature_agent_must_be_https(origin):
    with pytest.raises(ValueError):
        botauth.signature_agent_header(origin)


# --------------------------------------------------------------------------- #
# An independent verifier
# --------------------------------------------------------------------------- #

_INPUT = re.compile(r"^(?P<label>[a-z0-9_-]+)=(?P<params>\((?P<items>[^)]*)\)(?P<rest>.*))$")


def verify(request: httpx.Request, public_x: str) -> dict:
    """Check `request`'s signature the way a shop's edge would, without botauth.

    The base is rebuilt from the request as sent: `@authority` from its Host
    header, header fields by name. Returns the parsed parameters.
    """
    match = _INPUT.match(request.headers["Signature-Input"])
    assert match, request.headers["Signature-Input"]
    label = match["label"]
    items = re.findall(r'"([^"]+)"', match["items"])
    lines = []
    for item in items:
        if item == "@authority":
            value = request.headers["host"].lower()
        elif item == "@method":
            value = request.method
        elif item == "@path":
            value = request.url.raw_path.decode().split("?")[0]
        else:
            assert not item.startswith("@"), f"unexpected derived component {item}"
            value = request.headers[item].strip()
        lines.append(f'"{item}": {value}')
    lines.append(f'"@signature-params": {match["params"]}')
    base = "\n".join(lines).encode()

    sig = request.headers["Signature"]
    assert sig.startswith(f"{label}=:") and sig.endswith(":")
    signature = base64.b64decode(sig[len(label) + 2 : -1])
    Ed25519PublicKey.from_public_bytes(_b64url_decode(public_x)).verify(signature, base)

    params = dict(re.findall(r';([a-z]+)=("[^"]*"|\d+)', match["rest"]))
    params = {k: v.strip('"') for k, v in params.items()}
    params["components"] = items
    return params


def _independent_thumbprint(x: str) -> str:
    canonical = '{"crv":"Ed25519","kty":"OKP","x":"' + x + '"}'
    digest = hashlib.sha256(canonical.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def test_a_signed_request_verifies_independently():
    key = botauth.load_private_key(RFC_JWK_D)
    auth = WebBotAuth(botauth.Signer(key), "https://makhzan.test")
    request = httpx.Request("GET", "https://Shop.Test/products.json?page=2")
    signed = next(auth.auth_flow(request))

    params = verify(signed, RFC_JWK_X)
    assert signed.headers["Signature-Agent"] == '"https://makhzan.test"'
    assert params["components"] == ["@authority", "signature-agent"]
    assert "@query-params" not in signed.headers["Signature-Input"]
    assert ";req" not in signed.headers["Signature-Input"]
    assert params["tag"] == "web-bot-auth"
    assert params["alg"] == "ed25519"
    assert params["keyid"] == _independent_thumbprint(RFC_JWK_X)
    assert int(params["expires"]) - int(params["created"]) == 60
    assert len(_b64url_decode(params["nonce"])) == 32


def test_a_tampered_authority_fails_verification():
    key = botauth.load_private_key(RFC_JWK_D)
    auth = WebBotAuth(botauth.Signer(key), "https://makhzan.test")
    signed = next(auth.auth_flow(httpx.Request("GET", "https://shop.test/a")))
    signed.headers["host"] = "other.test"
    with pytest.raises(Exception):  # cryptography's InvalidSignature
        verify(signed, RFC_JWK_X)


def test_every_request_gets_a_fresh_nonce():
    key = botauth.load_private_key(RFC_JWK_D)
    auth = WebBotAuth(botauth.Signer(key), "https://makhzan.test")
    nonces = {
        verify(next(auth.auth_flow(httpx.Request("GET", "https://shop.test/a"))), RFC_JWK_X)[
            "nonce"
        ]
        for _ in range(5)
    }
    assert len(nonces) == 5


# --------------------------------------------------------------------------- #
# The key directory's response signature
# --------------------------------------------------------------------------- #


def test_the_directory_response_is_signed_by_every_key_it_lists():
    current = botauth.load_private_key(RFC_JWK_D)
    following = botauth.generate_private_key()
    headers = botauth.sign_directory_response(
        [current, following], "https://makhzan.test", now=1_700_000_000
    )
    body = json.loads(botauth.directory_body([current, following]))
    assert [k["x"] for k in body["keys"]] == [RFC_JWK_X, botauth.public_jwk(following)["x"]]

    inputs = headers["Signature-Input"].split(", ")
    signatures = headers["Signature"].split(", ")
    assert len(inputs) == len(signatures) == 2
    for raw_input, raw_sig, jwk in zip(inputs, signatures, body["keys"], strict=True):
        label, _, params = raw_input.partition("=")
        assert params.startswith('("@authority";req);created=1700000000;expires=1700000300;')
        assert 'tag="http-message-signatures-directory"' in params
        assert f'keyid="{_independent_thumbprint(jwk["x"])}"' in params
        base = f'"@authority";req: makhzan.test\n"@signature-params": {params}'.encode()
        signature = base64.b64decode(raw_sig.split("=:", 1)[1].rstrip(":"))
        Ed25519PublicKey.from_public_bytes(_b64url_decode(jwk["x"])).verify(signature, base)


def test_a_rotation_publishes_current_next_and_previous_once_each(monkeypatch):
    """Before the switch: current + next. After: current (the new key) + previous."""
    old, new = RFC_JWK_D, botauth.private_key_to_text(botauth.generate_private_key())
    new_x = botauth.public_jwk(botauth.load_private_key(new))["x"]
    monkeypatch.delenv(botauth.PREVIOUS_KEY_ENV, raising=False)

    monkeypatch.setenv(botauth.KEY_ENV, old)
    monkeypatch.setenv(botauth.NEXT_KEY_ENV, new)
    assert [botauth.public_jwk(k)["x"] for k in botauth.directory_keys()] == [RFC_JWK_X, new_x]

    monkeypatch.setenv(botauth.KEY_ENV, new)
    monkeypatch.delenv(botauth.NEXT_KEY_ENV)
    monkeypatch.setenv(botauth.PREVIOUS_KEY_ENV, old)
    assert [botauth.public_jwk(k)["x"] for k in botauth.directory_keys()] == [new_x, RFC_JWK_X]
    # Only the current key signs requests.
    assert botauth.public_jwk(botauth.configured_key())["x"] == new_x

    monkeypatch.setenv(botauth.NEXT_KEY_ENV, new)  # a leftover duplicate is published once
    assert len(botauth.directory_keys()) == 2


# --------------------------------------------------------------------------- #
# The CLI
# --------------------------------------------------------------------------- #


def test_keygen_prints_a_usable_key_and_its_public_half(capsys):
    assert botauth_cli(["keygen"]) == 0
    out = capsys.readouterr().out
    line = next(x for x in out.splitlines() if x.startswith(f"{botauth.KEY_ENV}="))
    key = botauth.load_private_key(line.split("=", 1)[1])
    jwk = botauth.public_jwk(key)
    assert json.dumps(jwk) in out
    assert botauth.jwk_thumbprint(jwk) in out


def test_headers_prints_a_signed_makhzanbot_request(capsys, monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://makhzan.test")
    monkeypatch.setenv(botauth.KEY_ENV, RFC_JWK_D)
    assert botauth_cli(["headers", "--sign", "https://shop.test/products.json"]) == 0
    lines = dict(x.split(": ", 1) for x in capsys.readouterr().out.splitlines())
    assert lines["User-Agent"].startswith("makhzanbot/1.0 (+https://makhzan.test/how-we-crawl;")
    request = httpx.Request("GET", "https://shop.test/products.json", headers=lines)
    verify(request, RFC_JWK_X)
