"""A worker's configuration: one TOML file says everything the broker does not.

Which model keys it serves, where the broker is and how it authenticates, the device,
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
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from makhzan_ml.worker.pins import PINS

DEVICES = ("cpu", "gpu")
#: The validated setups (decision-review §4, P8): fp32 on CPU, bf16 on the GPU. Any other
#: pairing was never measured against the stored scores, so it is refused, not guessed.
DTYPES = {"cpu": ("fp32",), "gpu": ("bf16",)}
ON_EMPTY = ("exit", "wait")
#: Floors on the two intervals: a heartbeat or a poll every few milliseconds would only
#: load the broker.
MIN_HEARTBEAT_S = 5.0
MIN_POLL_S = 5.0

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


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

    def __str__(self) -> str:
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


@dataclass(frozen=True)
class Schedule:
    """When the worker may run: `windows` is None for always."""

    windows: tuple[Window, ...] | None
    timezone: tzinfo | None = None  # None: the machine's local time
    on_empty: str = "exit"
    poll_s: float = 600.0

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

    def describe(self) -> str:
        return "always" if self.windows is None else ",".join(map(str, self.windows))


# --- the configuration ----------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    name: str
    broker_url: str
    token: str = field(repr=False)
    models: tuple[str, ...]
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
    seconds_per_request: float
    retry_max_s: float
    ca_file: Path | None = None
    token_file: Path | None = None
    source: Path | None = None

    def hello_config(self) -> dict:
        """What hello reports of this configuration (broker-api.md §3.1)."""
        return {
            "window": self.schedule.describe(),
            "max_jobs": self.max_jobs,
            "lease_s": self.lease_s,
            "on_empty": self.schedule.on_empty,
            "memory_gib": self.memory_gib,
        }


_SCHEMA: dict[str, set[str]] = {
    "worker": {"name", "broker_url", "token", "token_file", "ca_file", "models"},
    "compute": {"device", "dtype", "threads", "nice", "memory_gib", "mmap", "weights_cache"},
    "schedule": {"windows", "timezone", "on_empty", "poll_s"},
    "leases": {"max_jobs", "lease_s", "heartbeat_s", "seconds_per_request", "retry_max_s"},
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


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _broker_url(url: Any) -> str:
    url = _typed("worker", "broker_url", url, str).rstrip("/")
    parts = urlsplit(url)
    if not parts.hostname:
        raise ConfigError(f"[worker] broker_url {url!r} has no host")
    # Workers talk to the broker over TLS only. Plain HTTP is accepted for a loopback
    # address alone, which is where the tests and the parity check run their fake broker.
    if parts.scheme != "https" and not (parts.scheme == "http" and _loopback(parts.hostname)):
        raise ConfigError(f"[worker] broker_url {url!r} must be https://")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError("[worker] broker_url carries no credentials, query or fragment")
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
    broker_url = _broker_url(worker.get("broker_url"))
    token, token_file = _token(worker, base)
    ca_file = None
    if "ca_file" in worker:
        ca_file = base / _nonempty("worker", "ca_file", worker["ca_file"])
        if not ca_file.is_file():
            raise ConfigError(f"[worker] ca_file {str(ca_file)!r} does not exist")

    models = worker.get("models")
    if isinstance(models, str):
        models = [models]
    if not isinstance(models, list) or not models or not all(isinstance(m, str) for m in models):
        raise ConfigError('[worker] models: a non-empty list of model keys, e.g. ["kev"]')
    if len(set(models)) != len(models):
        raise ConfigError(f"[worker] models {models}: a key is listed twice")
    for m in models:
        if m not in PINS:
            raise ConfigError(f"[worker] models: unknown model key {m!r} (known: {sorted(PINS)})")

    if not isinstance(model_tables, dict):
        raise ConfigError("[model.<key>] must be tables")
    expect: dict[str, str] = {}
    for key, table in model_tables.items():
        if key not in models:
            raise ConfigError(f"[model.{key}] configures a model this worker does not serve")
        if not isinstance(table, dict):
            raise ConfigError(f"[model.{key}] must be a table")
        _unknown(f"model.{key}", table, _MODEL_KEYS)
        if "expect_version" in table:
            want = _typed(f"model.{key}", "expect_version", table["expect_version"], str)
            if want != PINS[key].model_version:
                raise ConfigError(
                    f"[model.{key}] expect_version {want!r} is not what this worker serves "
                    f"({PINS[key].model_version!r}); the image or the configuration is stale"
                )
            expect[key] = want

    device = compute.get("device", "cpu")
    if device not in DEVICES:
        raise ConfigError(f"[compute] device {device!r}: one of {list(DEVICES)}")
    dtype = compute.get("dtype", DTYPES[device][0])
    if dtype not in DTYPES[device]:
        raise ConfigError(
            f"[compute] dtype {dtype!r} on {device}: only {list(DTYPES[device])} is validated "
            "against the stored scores"
        )
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
    poll_s = float(_positive("schedule", "poll_s", schedule.get("poll_s", 600)))
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
    spr = float(_positive("leases", "seconds_per_request", leases.get("seconds_per_request", 90)))
    retry_max_s = float(_positive("leases", "retry_max_s", leases.get("retry_max_s", lease_s)))

    return Config(
        name=name,
        broker_url=broker_url,
        token=token,
        token_file=token_file,
        ca_file=ca_file,
        models=tuple(models),
        expect_versions=expect,
        device=device,
        dtype=dtype,
        threads=threads,
        nice=nice,
        memory_gib=memory_gib,
        mmap=mmap,
        weights_cache=weights_cache,
        schedule=Schedule(windows, tz, on_empty, poll_s),
        max_jobs=max_jobs,
        lease_s=lease_s,
        heartbeat_s=heartbeat_s,
        seconds_per_request=spr,
        retry_max_s=retry_max_s,
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
