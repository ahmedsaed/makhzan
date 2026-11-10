"""Web Bot Auth: RFC 9421 HTTP Message Signatures with an Ed25519 key.

One implementation for both sides of the crawler's identity:

  - the ingestion worker signs every request a `makhzanbot` source sends
    (`worker/botauth.py` wraps this as an httpx `Auth`), and
  - the API serves the public keys at
    `/.well-known/http-message-signatures-directory`, a response signed the
    same way (`app/routers/wellknown.py`).

A shop's edge (Cloudflare, Shopify) reads the `Signature-Agent` header, fetches
our key directory from it, and checks the `Signature` against the key whose
JWK thumbprint is the `keyid`. Nothing here is secret but the private key,
which comes from the environment (`MAKHZANBOT_SIGNING_KEY`, or a file named by
`MAKHZANBOT_SIGNING_KEY_FILE`) and never from either repository.

Only what makhzan needs of RFC 9421 is implemented: derived components
`@authority`, `@method`, `@path`, plain header fields, the `req` flag, and
string/integer parameters. It is tested against the RFC's own Ed25519 vector
(Appendix B.2.6) and verified by an independent re-derivation in the tests.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

#: `tag` on every signed crawler request (draft-ietf-webbotauth-httpsig-protocol).
REQUEST_TAG = "web-bot-auth"
#: `tag` on the key directory's own response signature.
DIRECTORY_TAG = "http-message-signatures-directory"
#: Where the directory lives on the site, and the media type it must carry.
DIRECTORY_PATH = "/.well-known/http-message-signatures-directory"
DIRECTORY_MEDIA_TYPE = "application/http-message-signatures-directory+json"

#: What a crawler request signs. `@authority` binds the signature to the shop it
#: was sent to and `signature-agent` to the directory that holds our key; both
#: are what Cloudflare documents and what Shopify's own signatures cover.
#: `@method` and `@path` are deliberately left out: verifiers are young and a
#: component one of them does not expect fails the whole signature, while the
#: 60-second `expires` and a fresh `nonce` already bound a replay. Never add
#: `@query-params` (Cloudflare rejects it) or a `req` flag on a request.
REQUEST_COMPONENTS: tuple[str, ...] = ("@authority", "signature-agent")

#: Seconds a request signature stays valid. Cloudflare: "a minute is often sufficient".
REQUEST_LIFETIME = 60
#: Seconds the directory's response signature stays valid. Longer than a
#: request's, because the response may sit in a cache for `max-age` (60 s).
DIRECTORY_LIFETIME = 300

KEY_ENV = "MAKHZANBOT_SIGNING_KEY"
#: The next key during a rotation: published in the directory, not used to sign
#: requests until it is promoted to `KEY_ENV`.
NEXT_KEY_ENV = "MAKHZANBOT_SIGNING_KEY_NEXT"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #


def generate_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_key_to_text(key: Ed25519PrivateKey) -> str:
    """The key as one line for an env file: the 32-byte seed, base64url (JWK `d`)."""
    raw = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    return _b64url(raw)


def load_private_key(text: str) -> Ed25519PrivateKey:
    """A key as `private_key_to_text` writes it, or a PKCS #8 PEM (what openssl writes)."""
    text = text.strip()
    if text.startswith("-----BEGIN"):
        key = serialization.load_pem_private_key(text.encode("ascii"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("the signing key must be an Ed25519 key")
        return key
    raw = _b64url_decode(text)
    if len(raw) != 32:
        raise ValueError("an Ed25519 private key is 32 bytes (base64url, 43 characters)")
    return Ed25519PrivateKey.from_private_bytes(raw)


def public_jwk(key: Ed25519PrivateKey | Ed25519PublicKey) -> dict[str, str]:
    """The public key as a JWK (RFC 8037): only the members a thumbprint covers."""
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw)}


def jwk_thumbprint(jwk: dict[str, str]) -> str:
    """RFC 7638 SHA-256 thumbprint, base64url: the `keyid` verifiers look a key up by.

    The hash input is the required members only (for an OKP key: crv, kty, x),
    in lexicographic order, with no whitespace (RFC 8037 §2, Appendix A.3).
    """
    required = {name: jwk[name] for name in ("crv", "kty", "x")}
    canonical = json.dumps(required, separators=(",", ":"), sort_keys=True)
    return _b64url(hashlib.sha256(canonical.encode("utf-8")).digest())


def _env_secret(name: str) -> str | None:
    """`NAME`, or the contents of the file `NAME_FILE` points at (Docker secrets)."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    path = os.environ.get(f"{name}_FILE", "").strip()
    if path:
        with open(path, encoding="ascii") as handle:
            return handle.read().strip() or None
    return None


def configured_key(name: str = KEY_ENV) -> Ed25519PrivateKey | None:
    """The signing key from the environment, or None when there is none."""
    text = _env_secret(name)
    return load_private_key(text) if text else None


def directory_keys() -> list[Ed25519PrivateKey]:
    """Every key the directory publishes: the current one, then the next during a rotation."""
    keys = [configured_key(KEY_ENV), configured_key(NEXT_KEY_ENV)]
    seen: set[str] = set()
    out: list[Ed25519PrivateKey] = []
    for key in keys:
        if key is None:
            continue
        kid = jwk_thumbprint(public_jwk(key))
        if kid not in seen:
            seen.add(kid)
            out.append(key)
    return out


# --------------------------------------------------------------------------- #
# RFC 9421 serialisation
# --------------------------------------------------------------------------- #


def _sf_string(value: str) -> str:
    """A structured-field string (RFC 8941 §3.3.3): ASCII, quotes and backslashes escaped."""
    if not value.isascii() or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise ValueError(f"not a structured-field string: {value!r}")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass(frozen=True)
class Component:
    """A covered component: a derived one (`@authority`) or a header field (`date`)."""

    name: str
    #: The `req` flag: in a response, the component is taken from the request.
    req: bool = False

    def identifier(self) -> str:
        return _sf_string(self.name) + (";req" if self.req else "")


def signature_params(
    components: list[Component],
    *,
    created: int,
    keyid: str,
    expires: int | None = None,
    nonce: str | None = None,
    alg: str | None = None,
    tag: str | None = None,
) -> str:
    """The `@signature-params` value, which is also what `Signature-Input` carries.

    Parameters are written in the order given here; RFC 9421 lets the signer
    choose, and the same string goes into both the base and the header.
    """
    inner = "(" + " ".join(c.identifier() for c in components) + ")"
    params = [f";created={int(created)}"]
    if expires is not None:
        params.append(f";expires={int(expires)}")
    if nonce is not None:
        params.append(f";nonce={_sf_string(nonce)}")
    params.append(f";keyid={_sf_string(keyid)}")
    if alg is not None:
        params.append(f";alg={_sf_string(alg)}")
    if tag is not None:
        params.append(f";tag={_sf_string(tag)}")
    return inner + "".join(params)


def authority(url: str) -> str:
    """`@authority` (RFC 9421 §2.2.3): lowercase host, port only when not the default."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    default = {"http": 80, "https": 443}.get(parts.scheme.lower())
    if parts.port is not None and parts.port != default:
        host = f"{host}:{parts.port}"
    return host


def derived_value(name: str, *, method: str, url: str) -> str:
    """The value of a derived component for a request to `url`."""
    if name == "@authority":
        return authority(url)
    if name == "@method":
        return method.upper()
    if name == "@path":
        return urlsplit(url).path or "/"
    raise ValueError(f"unsupported derived component {name}")


def signature_base(lines: list[tuple[Component, str]], params: str) -> bytes:
    """The bytes that are signed (RFC 9421 §2.5)."""
    out = [f"{c.identifier()}: {value}" for c, value in lines]
    out.append(f'"@signature-params": {params}')
    return "\n".join(out).encode("ascii")


def _header_value(headers, name: str) -> str:
    value = headers.get(name)
    if value is None:
        raise ValueError(f"cannot sign {name!r}: the message has no such header")
    # §2.1: leading and trailing whitespace is stripped from each field value.
    return value.strip()


# --------------------------------------------------------------------------- #
# The Signature-Agent header
# --------------------------------------------------------------------------- #


def signature_agent_header(origin: str) -> str:
    """The `Signature-Agent` value naming where our key directory lives.

    A known conflict, settled here and only here: draft-ietf-webbotauth-
    httpsig-protocol-01 (2026-10) says a signer MUST send the dictionary form,
    `sig1="https://…"`, while Cloudflare's verifier (docs updated 2026-10-08)
    *fails* the dictionary form and requires a bare quoted string,
    `"https://…"`. Cloudflare fronts most of the shops that object to unknown
    bots, so its form wins for now. Re-check at each draft revision and each
    Cloudflare docs update; when they agree, change this function and its test.
    """
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"Signature-Agent must be an https:// origin, got {origin!r}")
    return _sf_string(f"https://{authority(origin)}")


# --------------------------------------------------------------------------- #
# Signing
# --------------------------------------------------------------------------- #


def _signature_header(label: str, signature: bytes) -> str:
    return f"{label}=:{base64.b64encode(signature).decode('ascii')}:"


@dataclass(frozen=True)
class Signer:
    """Signs with one Ed25519 key; `keyid` is its JWK thumbprint."""

    key: Ed25519PrivateKey

    @property
    def keyid(self) -> str:
        return jwk_thumbprint(public_jwk(self.key))

    def sign_request(
        self,
        method: str,
        url: str,
        headers,
        *,
        label: str = "sig1",
        now: float | None = None,
        nonce: str | None = None,
    ) -> dict[str, str]:
        """`Signature-Input` and `Signature` for one request, signed now.

        `headers` must already carry `Signature-Agent`. Call once per request
        sent: a retry and every redirect hop get a fresh `created`, `expires`
        and `nonce`.
        """
        created = int(time.time() if now is None else now)
        components = [Component(name) for name in REQUEST_COMPONENTS]
        params = signature_params(
            components,
            created=created,
            expires=created + REQUEST_LIFETIME,
            nonce=nonce if nonce is not None else _b64url(secrets.token_bytes(32)),
            keyid=self.keyid,
            alg="ed25519",
            tag=REQUEST_TAG,
        )
        lines = [
            (
                c,
                derived_value(c.name, method=method, url=url)
                if c.name.startswith("@")
                else _header_value(headers, c.name),
            )
            for c in components
        ]
        signature = self.key.sign(signature_base(lines, params))
        return {
            "Signature-Input": f"{label}={params}",
            "Signature": _signature_header(label, signature),
        }


def directory_body(keys: list[Ed25519PrivateKey]) -> bytes:
    """The JWKS the directory serves: one public JWK per key, current first."""
    return json.dumps({"keys": [public_jwk(k) for k in keys]}, separators=(",", ":")).encode()


def sign_directory_response(
    keys: list[Ed25519PrivateKey], site_url: str, *, now: float | None = None
) -> dict[str, str]:
    """`Signature-Input`/`Signature` for the directory response, one signature per key.

    Each key proves it is held by whoever serves the directory: the signature
    covers the request's `@authority` (the `req` flag), taken from the
    configured site, never from the Host header the proxy forwarded.
    """
    created = int(time.time() if now is None else now)
    component = Component("@authority", req=True)
    value = authority(site_url)
    inputs, signatures = [], []
    for i, key in enumerate(keys, start=1):
        label = f"sig{i}"
        params = signature_params(
            [component],
            created=created,
            expires=created + DIRECTORY_LIFETIME,
            nonce=_b64url(secrets.token_bytes(32)),
            keyid=jwk_thumbprint(public_jwk(key)),
            alg="ed25519",
            tag=DIRECTORY_TAG,
        )
        signature = key.sign(signature_base([(component, value)], params))
        inputs.append(f"{label}={params}")
        signatures.append(_signature_header(label, signature))
    return {"Signature-Input": ", ".join(inputs), "Signature": ", ".join(signatures)}
