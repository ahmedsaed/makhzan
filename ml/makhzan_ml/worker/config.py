"""A worker's configuration: one TOML file says everything the broker does not.

Which model key it serves (one: the broker takes one model per session, so two models
are two workers), where the broker is and how it authenticates, the device,
dtype, threads and memory it may use, when it may run (one or more local-time windows,
or always), how many jobs a lease takes, and what it does on an empty queue. The broker
treats every worker the same; two workers on one machine overlap only if their windows
say so (owner decision, 2026-11-17). The reference is docs/ai/worker.md.

Parsing is strict: an unknown section or key is an error, never a setting silently
ignored, and every value is checked before anything is loaded or sent.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from makhzan_ml.worker.pins import BACKENDS, MODEL_KEYS, llamacpp_pins, pin_for

DEVICES = ("cpu", "gpu")
#: The validated setups (decision-review §4, P8): fp32 on CPU, bf16 on the GPU. Any other
#: pairing was never measured against the stored scores, so it is refused, not guessed.
DTYPES = {"cpu": ("fp32",), "gpu": ("bf16",)}
#: The llama.cpp backend's precision is the GGUF's, on either device (D20 as amended
#: 2026-11-26 accepts Kev-4B Q4_K_M and pplx Q4_K_S; docs/ai/kev-llamacpp.md, pplx-llamacpp.md).
#: Per model key, the dtype a llama.cpp worker must name: its pinned GGUF's quantisation.
LLAMACPP_DTYPES = {key: (pin.dtype,) for key, pin in llamacpp_pins().items()}
ON_EMPTY = ("exit", "wait")
OUTSIDE_WINDOW = ("exit", "wait")
#: Floors on the two intervals: a heartbeat or a poll every few milliseconds would only
#: load the broker.
MIN_HEARTBEAT_S = 5.0
MIN_POLL_S = 5.0
#: The home server's AMD card: compute held to clock states 0-2 runs at up to 950 mV; another
#: app on its video engine lifts it to 1,150 mV (2026-11-28).
DEFAULT_MAX_VDDGFX_MV = 1000

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
#: A compose service name: one DNS label, no dots, so it can only name a container on the
#: worker's own Docker network (resolved by Docker's embedded DNS), never a host elsewhere.
_SERVICE_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class ConfigError(ValueError):
    """The configuration cannot be used as written."""


# --- windows --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Window:
    """A daily local-time interval, start inclusive, end exclusive. `start > end`
    crosses midnight ("22:00-02:00")."""

    start: time
    end: time

    @classmethod
    def parse(cls, text: str) -> Window:
        parts = text.split("-")
        if len(parts) != 2 or not all(_HHMM.match(p.strip()) for p in parts):
            raise ConfigError(f"window {text!r}: expected HH:MM-HH:MM (24-hour, local time)")
        start, end = (time.fromisoformat(p.strip()) for p in parts)
        if start == end:
            raise ConfigError(f'window {text!r} is empty; use windows = "always" for no limit')
        return cls(start, end)

    def contains(self, t: time) -> bool:
        if self.start < self.end:
            return self.start <= t < self.end
        return t >= self.start or t < self.end

    def end_after(self, now: datetime) -> datetime:
        """The end of this window's occurrence that contains `now` (which it must)."""
        end = datetime.combine(now.date(), self.end, tzinfo=now.tzinfo)
        return end if end > now else end + timedelta(days=1)

    def start_after(self, now: datetime) -> datetime:
        """The first start of this window strictly after `now`."""
        start = datetime.combine(now.date(), self.start, tzinfo=now.tzinfo)
        return start if start > now else start + timedelta(days=1)

    def __str__(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


@dataclass(frozen=True)
class Schedule:
    """When the worker may run: `windows` is None for always."""

    windows: tuple[Window, ...] | None
    timezone: tzinfo | None = None  # None: the machine's local time
    on_empty: str = "exit"
    poll_s: float = 600.0
    #: Outside every window: "exit" (started by a timer), or "wait" (stay up, sleep until
    #: the next window, and run each window's session in a child process).
    outside_window: str = "exit"
    #: No new lease and no model load this close to a window's end (seconds), so a load or a
    #: lease cannot start at 04:59 and keep a model in memory past the window.
    no_new_lease_s: float = 0.0

    def now(self) -> datetime:
        return datetime.now(self.timezone) if self.timezone else datetime.now().astimezone()

    def is_open(self, now: datetime) -> bool:
        return self.windows is None or any(w.contains(now.time()) for w in self.windows)

    def closes_at(self, now: datetime) -> datetime | None:
        """When the open window containing `now` ends, following windows that touch or
        overlap it ("00:30-04:30" then "04:30-06:30" is one run to 06:30). None when
        always open; `now` itself when closed."""
        if self.windows is None:
            return None
        end = now
        for _ in range(len(self.windows) + 1):
            here = [w.end_after(end) for w in self.windows if w.contains(end.time())]
            if not here:
                break
            end = max(here)
        return end

    def opens_at(self, now: datetime) -> datetime | None:
        """When the next window opens after `now`: the earliest start strictly after it.
        None when always open. Called while closed, it is the window to sleep until; after
        `closes_at`, the one after the current run (touching windows were one run)."""
        if self.windows is None:
            return None
        return min(w.start_after(now) for w in self.windows)

    def zone_name(self) -> str:
        """The time zone the windows are read in, for the log."""
        if self.timezone is not None:
            return str(getattr(self.timezone, "key", None) or self.timezone)
        return datetime.now().astimezone().tzname() or "local"

    def describe(self) -> str:
        return "always" if self.windows is None else ",".join(map(str, self.windows))


# --- the configuration ----------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    name: str
    broker_url: str
    token: str = field(repr=False)
    model: str
    expect_versions: dict[str, str]
    device: str
    dtype: str
    threads: int | None
    nice: int
    memory_gib: float | None
    mmap: bool
    weights_cache: Path | None
    schedule: Schedule
    max_jobs: int
    lease_s: int
    heartbeat_s: float
    retry_max_s: float
    ca_file: Path | None = None
    token_file: Path | None = None
    #: Plain http:// to a compose service name is allowed (the broker proxy on the
    #: worker's internal Docker network); off, only addresses (see `_plain_http_ok`).
    broker_via_proxy: bool = False
    #: With broker_via_proxy: the host names plain http may go to (the proxy's service name).
    broker_proxy_hosts: tuple[str, ...] = ("broker-proxy",)
    #: "torch" (the model's own code, in this process) or "llamacpp" (a sidecar server).
    backend: str = "torch"
    #: llamacpp only: the sidecar's base URL, and the GGUF it serves, mounted read-only here
    #: too so the worker can check it is the pinned file.
    llamacpp_url: str | None = None
    gguf_path: Path | None = None
    #: llamacpp on a GPU: refuse to load unless the AMD card's clock limit is applied (every
    #: card's power_dpm_force_performance_level reads "manual"). On by default there; off for a
    #: machine whose GPU is not the limited card (the desktop's NVIDIA card).
    require_clock_limit: bool = False
    #: llamacpp: score only while the AMD card's core voltage (amdgpu hwmon in0_input) is at most
    #: this many mV; above it another app is using the card's video engine, which raises the
    #: voltage past the clock limit (docs/ai/worker.md, "The card's voltage"). 0 is off. On by
    #: default (1000) wherever require_clock_limit is.
    max_vddgfx_mv: int = 0
    #: With max_vddgfx_mv: after any reading above it, the card counts as busy until it has read
    #: at most the limit for this many seconds on end.
    vddgfx_clear_s: float = 60.0
    source: Path | None = None

    @property
    def pin(self):
        """The pin this worker serves: the model key's, on the configured backend."""
        return pin_for(self.model, self.backend)

    def hello_config(self) -> dict:
        """What hello reports of this configuration (broker-api.md §3.1)."""
        return {
            "window": self.schedule.describe(),
            "max_jobs": self.max_jobs,
            "lease_s": self.lease_s,
            "on_empty": self.schedule.on_empty,
            "outside_window": self.schedule.outside_window,
            "no_new_lease_s": self.schedule.no_new_lease_s,
            "memory_gib": self.memory_gib,
        }


_SCHEMA: dict[str, set[str]] = {
    "worker": {
        "name",
        "broker_url",
        "broker_via_proxy",
        "broker_proxy_hosts",
        "token",
        "token_file",
        "ca_file",
        "model",
        "models",
    },
    "compute": {
        "device",
        "dtype",
        "threads",
        "nice",
        "memory_gib",
        "mmap",
        "weights_cache",
        "backend",
        "llamacpp_url",
        "gguf_path",
        "require_clock_limit",
        "max_vddgfx_mv",
        "vddgfx_clear_s",
    },
    "schedule": {"windows", "timezone", "on_empty", "poll_s", "outside_window", "no_new_lease_s"},
    "leases": {"max_jobs", "lease_s", "heartbeat_s", "retry_max_s"},
}
_MODEL_KEYS = {"expect_version"}


def _unknown(where: str, got: dict, allowed: set[str]) -> None:
    extra = sorted(set(got) - allowed)
    if extra:
        raise ConfigError(f"[{where}]: unknown key(s) {extra} (allowed: {sorted(allowed)})")


def _typed(where: str, key: str, value: Any, kind: type | tuple[type, ...]) -> Any:
    # bool is an int in Python; never accept true where a number is meant.
    if isinstance(value, bool) and bool not in (kind if isinstance(kind, tuple) else (kind,)):
        raise ConfigError(f"[{where}] {key}: expected a number, got {value!r}")
    if not isinstance(value, kind):
        raise ConfigError(f"[{where}] {key}: expected {kind}, got {value!r}")
    return value


def _nonempty(where: str, key: str, value: Any) -> str:
    value = _typed(where, key, value, str)
    if not value.strip():
        raise ConfigError(f"[{where}] {key} is empty; leave the key out instead")
    return value


def _positive(where: str, key: str, value: Any, *, integer: bool = False) -> float:
    value = _typed(where, key, value, int if integer else (int, float))
    if value <= 0:
        raise ConfigError(f"[{where}] {key} must be positive, got {value!r}")
    return value


#: Tailscale's address ranges (CGNAT IPv4 and its ULA IPv6 prefix). Traffic to them goes
#: through the tailnet's WireGuard tunnel, encrypted and authenticated end to end.
TAILSCALE_NETS = (
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fd7a:115c:a1e0::/48"),
)


def _plain_http_ok(host: str) -> bool:
    """Where plain http:// may go: a loopback address (127.0.0.0/8 or ::1: the tests, the
    parity check, a broker on the same machine) or a Tailscale address (the broker, reached
    over the tailnet: owner decision 2026-11-17). Addresses only, never names, not even
    "localhost", so name resolution cannot redirect it."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or any(ip in net for net in TAILSCALE_NETS)


def _service_name(host: str) -> bool:
    """A compose service name: one label with a letter in it, and nothing the C resolver
    would read as an address ("1234", "0x7f000001" are 127.0.0.1-style IPv4 forms)."""
    if not _SERVICE_NAME.match(host) or not any(c.isalpha() for c in host):
        return False
    try:
        socket.inet_aton(host)
    except OSError:
        return True
    return False


DEFAULT_PROXY_HOSTS = ("broker-proxy",)
#: The default no_new_lease_s per device: a CPU load takes about 150 s and a request up to
#: about 104 s on the home server, so nothing new starts in a window's last 5 minutes. A GPU
#: loads in seconds.
NO_NEW_LEASE_S = {"cpu": 300.0, "gpu": 0.0}


def _proxy_hosts(worker: dict) -> tuple[str, ...]:
    hosts = worker.get("broker_proxy_hosts", list(DEFAULT_PROXY_HOSTS))
    if not isinstance(hosts, list) or not hosts:
        raise ConfigError("[worker] broker_proxy_hosts: a non-empty list of service names")
    for h in hosts:
        if not isinstance(h, str) or not _service_name(h):
            raise ConfigError(
                f"[worker] broker_proxy_hosts: {h!r} is not a compose service name (one "
                "label with a letter, no dots, not an address)"
            )
    return tuple(hosts)


def _broker_url(
    url: Any, *, via_proxy: bool = False, proxy_hosts: tuple[str, ...] = DEFAULT_PROXY_HOSTS
) -> str:
    url = _typed("worker", "broker_url", url, str).rstrip("/")
    parts = urlsplit(url)
    if not parts.hostname:
        raise ConfigError(f"[worker] broker_url {url!r} has no host")
    if "%" in parts.netloc:  # an IPv6 zone id (or an escape) in the host: never wanted
        raise ConfigError(f"[worker] broker_url {url!r}: no '%' (zone ids) in the host")
    try:
        parts.port  # a malformed port fails here, at load, not at the first call
    except ValueError as e:
        raise ConfigError(f"[worker] broker_url {url!r}: {e}") from None
    # The broker is reached over Tailscale, http://<tailscale-ip>:<port>: the tailnet's
    # WireGuard tunnel encrypts it. Plain HTTP is accepted for a Tailscale or loopback
    # address only; anything else must be https://. With broker_via_proxy, also the broker
    # proxy's own service name (broker_proxy_hosts, "broker-proxy"), safe only inside the
    # compose stack: on the worker's internal network (no other route out) that name can
    # only be the proxy, which forwards to the broker's Tailscale address and nowhere else.
    host = parts.hostname
    plain_ok = _plain_http_ok(host) or (via_proxy and host in proxy_hosts)
    if parts.scheme != "https" and not (parts.scheme == "http" and plain_ok):
        raise ConfigError(
            f"[worker] broker_url {url!r}: https://, or http:// to a Tailscale address "
            "(100.64.0.0/10, fd7a:115c:a1e0::/48) or a loopback one"
            + (
                f", or to the broker proxy ({', '.join(proxy_hosts)})"
                if via_proxy
                else "; a compose service name (the broker proxy) needs broker_via_proxy = true"
            )
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError("[worker] broker_url carries no credentials, query or fragment")
    return url


def _llamacpp_url(url: Any) -> str:
    """The sidecar's URL: plain http:// to a compose service name (the sidecar on the
    worker's internal network) or a loopback address (tests, parity). Nothing else: the
    worker sends catalogue text there."""
    url = _nonempty("compute", "llamacpp_url", url).rstrip("/")
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        parts.port
    except ValueError as e:
        raise ConfigError(f"[compute] llamacpp_url {url!r}: {e}") from None
    loopback = False
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if parts.scheme != "http" or not (loopback or _service_name(host)):
        raise ConfigError(
            f"[compute] llamacpp_url {url!r}: http:// to a compose service name (the sidecar) "
            "or a loopback address"
        )
    if parts.username or parts.password or parts.query or parts.fragment or parts.path:
        raise ConfigError("[compute] llamacpp_url is a base URL: no path, query or credentials")
    return url


def _token(worker: dict, base: Path) -> tuple[str, Path | None]:
    has_token, has_file = "token" in worker, "token_file" in worker
    if has_token == has_file:
        raise ConfigError("[worker]: set exactly one of token or token_file")
    if has_token:
        token = _typed("worker", "token", worker["token"], str).strip()
        path = None
    else:
        path = base / _typed("worker", "token_file", worker["token_file"], str)
        try:
            token = path.read_text().strip()
        except OSError as e:
            raise ConfigError(f"[worker] token_file {str(path)!r}: {e.strerror}") from None
    if not token or any(c.isspace() for c in token):
        raise ConfigError("[worker]: the token is empty or contains whitespace")
    return token, path


def parse(data: dict, *, base: Path = Path("."), source: Path | None = None) -> Config:
    """A `Config` from parsed TOML. Relative paths resolve against `base`."""
    _unknown("top level", {k for k in data if k != "model"}, set(_SCHEMA))
    for section, allowed in _SCHEMA.items():
        if not isinstance(data.get(section, {}), dict):
            raise ConfigError(f"[{section}] must be a table")
        _unknown(section, data.get(section, {}), allowed)
    worker = data.get("worker") or {}
    compute = data.get("compute") or {}
    schedule = data.get("schedule") or {}
    leases = data.get("leases") or {}
    model_tables = data.get("model") or {}

    name = _typed("worker", "name", worker.get("name"), str)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,62}", name):
        raise ConfigError(f"[worker] name {name!r}: lowercase letters, digits, '-', '_', '.'")
    via_proxy = _typed("worker", "broker_via_proxy", worker.get("broker_via_proxy", False), bool)
    proxy_hosts = _proxy_hosts(worker)
    if "broker_proxy_hosts" in worker and not via_proxy:
        raise ConfigError("[worker] broker_proxy_hosts is only read with broker_via_proxy = true")
    broker_url = _broker_url(worker.get("broker_url"), via_proxy=via_proxy, proxy_hosts=proxy_hosts)
    token, token_file = _token(worker, base)
    ca_file = None
    if "ca_file" in worker:
        ca_file = base / _nonempty("worker", "ca_file", worker["ca_file"])
        if not ca_file.is_file():
            raise ConfigError(f"[worker] ca_file {str(ca_file)!r} does not exist")

    # One model per worker: the broker takes exactly one per session (a hello naming more
    # is refused), so two models are two workers. `models = ["kev"]` is still read, for
    # configurations written before, as long as it names exactly one key.
    if ("model" in worker) == ("models" in worker):
        raise ConfigError('[worker]: set model = "kev" (one key; run two workers for two models)')
    if "model" in worker:
        model = _typed("worker", "model", worker["model"], str)
    else:
        models = worker["models"]
        models = [models] if isinstance(models, str) else models
        if not isinstance(models, list) or len(models) != 1 or not isinstance(models[0], str):
            raise ConfigError(
                f"[worker] models {models!r}: exactly one model key per worker (the broker "
                'takes one per session); write model = "kev", and run two workers for two'
            )
        model = models[0]
    if model not in MODEL_KEYS:
        raise ConfigError(
            f"[worker] model: unknown model key {model!r} (known: {list(MODEL_KEYS)})"
        )
    backend = compute.get("backend", "torch")
    if backend not in BACKENDS:
        raise ConfigError(f"[compute] backend {backend!r}: one of {list(BACKENDS)}")
    try:
        pin = pin_for(model, backend)
    except KeyError:
        raise ConfigError(f"[compute] backend {backend!r} cannot serve {model!r}") from None

    if not isinstance(model_tables, dict):
        raise ConfigError("[model.<key>] must be tables")
    expect: dict[str, str] = {}
    for key, table in model_tables.items():
        if key != model:
            raise ConfigError(f"[model.{key}] configures a model this worker does not serve")
        if not isinstance(table, dict):
            raise ConfigError(f"[model.{key}] must be a table")
        _unknown(f"model.{key}", table, _MODEL_KEYS)
        if "expect_version" in table:
            want = _typed(f"model.{key}", "expect_version", table["expect_version"], str)
            if want != pin.model_version:
                raise ConfigError(
                    f"[model.{key}] expect_version {want!r} is not what this worker serves "
                    f"({pin.model_version!r}); the image or the configuration is stale"
                )
            expect[key] = want

    device = compute.get("device", "cpu")
    if device not in DEVICES:
        raise ConfigError(f"[compute] device {device!r}: one of {list(DEVICES)}")
    dtypes = LLAMACPP_DTYPES[model] if backend == "llamacpp" else DTYPES[device]
    dtype = compute.get("dtype", dtypes[0])
    if dtype not in dtypes:
        raise ConfigError(
            f"[compute] dtype {dtype!r} on {device} ({backend}): only {list(dtypes)} is "
            "validated against the stored scores"
        )
    llamacpp_url = gguf_path = None
    require_clock_limit = False
    max_vddgfx_mv = 0
    vddgfx_clear_s = 60.0
    if backend == "llamacpp":
        require_clock_limit = _typed(
            "compute", "require_clock_limit", compute.get("require_clock_limit", device == "gpu"),
            bool,
        )  # fmt: skip
        max_vddgfx_mv = _typed(
            "compute", "max_vddgfx_mv",
            compute.get("max_vddgfx_mv", DEFAULT_MAX_VDDGFX_MV if require_clock_limit else 0), int,
        )  # fmt: skip
        if not 0 <= max_vddgfx_mv <= 2000:
            raise ConfigError(f"[compute] max_vddgfx_mv {max_vddgfx_mv}: 0 (off) to 2000 mV")
        vddgfx_clear_s = float(_typed("compute", "vddgfx_clear_s",
                                      compute.get("vddgfx_clear_s", 60), (int, float)))  # fmt: skip
        if not 0 <= vddgfx_clear_s <= 3600:
            raise ConfigError(f"[compute] vddgfx_clear_s {vddgfx_clear_s}: 0 to 3600 s")
        if "llamacpp_url" not in compute or "gguf_path" not in compute:
            raise ConfigError(
                '[compute] backend = "llamacpp" needs llamacpp_url (the sidecar) and gguf_path '
                "(the GGUF it serves, mounted read-only into the worker too)"
            )
        llamacpp_url = _llamacpp_url(compute["llamacpp_url"])
        gguf_path = base / _nonempty("compute", "gguf_path", compute["gguf_path"])
        for key in ("mmap", "weights_cache"):
            if key in compute:
                raise ConfigError(f'[compute] {key} is not read with backend = "llamacpp"')
    else:
        for key in ("llamacpp_url", "gguf_path", "require_clock_limit", "max_vddgfx_mv",
                    "vddgfx_clear_s"):  # fmt: skip
            if key in compute:
                raise ConfigError(f'[compute] {key} is only read with backend = "llamacpp"')
    threads = compute.get("threads")
    if threads is not None:
        threads = int(_positive("compute", "threads", threads, integer=True))
    nice = _typed("compute", "nice", compute.get("nice", 10 if device == "cpu" else 0), int)
    if not 0 <= nice <= 19:
        raise ConfigError(f"[compute] nice {nice}: 0 to 19 (a worker never raises its priority)")
    memory_gib = compute.get("memory_gib")
    if memory_gib is not None:
        memory_gib = float(_positive("compute", "memory_gib", memory_gib))
    # No mmap on CPU by default: a mapped 9-18 GB checkpoint is page cache the kernel may
    # evict and re-read from the HDD under memory pressure, and the cgroup does not count it.
    mmap = _typed("compute", "mmap", compute.get("mmap", device == "gpu"), bool)
    weights_cache = None
    if "weights_cache" in compute:
        weights_cache = base / _nonempty("compute", "weights_cache", compute["weights_cache"])

    windows_raw = schedule.get("windows", "always")
    if windows_raw == "always":
        windows = None
    else:
        if isinstance(windows_raw, str):
            windows_raw = [windows_raw]
        if not isinstance(windows_raw, list) or not windows_raw:
            raise ConfigError('[schedule] windows: "always" or a list of "HH:MM-HH:MM"')
        windows = tuple(Window.parse(_typed("schedule", "windows", w, str)) for w in windows_raw)
    tz = None
    if "timezone" in schedule:
        tz_name = _nonempty("schedule", "timezone", schedule["timezone"])
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError(f"[schedule] timezone {tz_name!r} is not a known zone") from None
    if windows is not None and tz is None:
        # A container's local time is UTC unless told otherwise: a window without a zone
        # would silently run at the wrong hours.
        raise ConfigError('[schedule] timezone is required with windows (e.g. "Africa/Cairo")')
    on_empty = schedule.get("on_empty", "exit")
    if on_empty not in ON_EMPTY:
        raise ConfigError(f"[schedule] on_empty {on_empty!r}: one of {list(ON_EMPTY)}")
    outside_window = schedule.get("outside_window", "exit")
    if outside_window not in OUTSIDE_WINDOW:
        raise ConfigError(
            f"[schedule] outside_window {outside_window!r}: one of {list(OUTSIDE_WINDOW)}"
        )
    poll_s = float(_positive("schedule", "poll_s", schedule.get("poll_s", 600)))
    no_new_lease_s = _typed(
        "schedule", "no_new_lease_s", schedule.get("no_new_lease_s", NO_NEW_LEASE_S[device]),
        (int, float),
    )  # fmt: skip
    if no_new_lease_s < 0:
        raise ConfigError(f"[schedule] no_new_lease_s {no_new_lease_s}: 0 or more")
    for w in windows or ():
        start = w.start.hour * 3600 + w.start.minute * 60
        length = (w.end.hour * 3600 + w.end.minute * 60 - start) % 86400
        if no_new_lease_s >= length:
            raise ConfigError(
                f"[schedule] no_new_lease_s {no_new_lease_s:.0f} leaves window {w} no time "
                "to lease anything"
            )
    if poll_s < MIN_POLL_S:
        raise ConfigError(f"[schedule] poll_s {poll_s}: at least {MIN_POLL_S:.0f} s")

    max_jobs = int(_positive("leases", "max_jobs", leases.get("max_jobs", 2), integer=True))
    lease_s = int(_positive("leases", "lease_s", leases.get("lease_s", 900), integer=True))
    if not 60 <= lease_s <= 7200:  # the broker refuses any other at hello (422)
        raise ConfigError(f"[leases] lease_s {lease_s}: from 60 to 7200 s")
    heartbeat_s = float(_positive("leases", "heartbeat_s", leases.get("heartbeat_s", 60)))
    if heartbeat_s < MIN_HEARTBEAT_S:
        raise ConfigError(f"[leases] heartbeat_s {heartbeat_s}: at least {MIN_HEARTBEAT_S:.0f} s")
    if heartbeat_s * 2 > lease_s:
        raise ConfigError(
            f"[leases] heartbeat_s {heartbeat_s} must be at most half of lease_s {lease_s}, "
            "or one late heartbeat loses the lease"
        )
    retry_max_s = float(_positive("leases", "retry_max_s", leases.get("retry_max_s", lease_s)))

    return Config(
        name=name,
        broker_url=broker_url,
        broker_via_proxy=via_proxy,
        broker_proxy_hosts=proxy_hosts,
        token=token,
        token_file=token_file,
        ca_file=ca_file,
        model=model,
        expect_versions=expect,
        device=device,
        dtype=dtype,
        threads=threads,
        nice=nice,
        memory_gib=memory_gib,
        mmap=mmap,
        weights_cache=weights_cache,
        schedule=Schedule(windows, tz, on_empty, poll_s, outside_window, float(no_new_lease_s)),
        max_jobs=max_jobs,
        lease_s=lease_s,
        heartbeat_s=heartbeat_s,
        retry_max_s=retry_max_s,
        backend=backend,
        llamacpp_url=llamacpp_url,
        gguf_path=gguf_path,
        require_clock_limit=require_clock_limit,
        max_vddgfx_mv=max_vddgfx_mv,
        vddgfx_clear_s=vddgfx_clear_s,
        source=source,
    )


def load(path: str | Path) -> Config:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text())
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror}") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from None
    return parse(data, base=path.parent, source=path)
