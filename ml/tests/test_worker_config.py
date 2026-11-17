"""The worker's TOML configuration: what parses, what is refused, and the schedule."""

from __future__ import annotations

import re
import tomllib
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from makhzan_ml.worker.config import ConfigError, Schedule, Window, load, parse
from makhzan_ml.worker.pins import PINS

DOCS = Path(__file__).resolve().parents[2] / "docs" / "ai" / "worker.md"
CAIRO = ZoneInfo("Africa/Cairo")


def base(**sections) -> dict:
    data = {
        "worker": {
            "name": "home-kev",
            "broker_url": "https://broker.example.test/ai/v1",
            "token": "secret-token",
            "models": ["kev"],
        }
    }
    for name, values in sections.items():
        data.setdefault(name, {}).update(values)
    return data


def refused(data: dict, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        parse(data)


# --- defaults and the happy path -----------------------------------------------------------


def test_minimal_config_takes_the_validated_cpu_defaults():
    cfg = parse(base())
    assert cfg.models == ("kev",)
    assert (cfg.device, cfg.dtype, cfg.mmap, cfg.nice) == ("cpu", "fp32", False, 10)
    assert cfg.schedule.windows is None and cfg.schedule.on_empty == "exit"
    assert (cfg.max_jobs, cfg.lease_s, cfg.heartbeat_s) == (2, 900, 60)
    assert cfg.retry_max_s == cfg.lease_s
    assert "secret-token" not in repr(cfg)


def test_gpu_defaults_to_bf16_with_mmap_and_normal_priority():
    cfg = parse(base(compute={"device": "gpu"}))
    assert (cfg.dtype, cfg.mmap, cfg.nice) == ("bf16", True, 0)


def test_full_config(tmp_path):
    (tmp_path / "tok").write_text("  abc123\n")
    cache = tmp_path / "cache"
    cache.mkdir()
    toml = f"""
[worker]
name = "desk-pplx"
broker_url = "https://broker.example.test/ai/v1/"
token_file = "tok"
models = ["pplx"]

[model.pplx]
expect_version = "{PINS["pplx"].model_version}"

[compute]
device = "cpu"
dtype = "fp32"
threads = 6
nice = 12
memory_gib = 20
weights_cache = "cache"

[schedule]
windows = ["22:30-02:00", "13:00-14:00"]
timezone = "Africa/Cairo"
on_empty = "wait"
poll_s = 300

[leases]
max_jobs = 4
lease_s = 600
heartbeat_s = 30
seconds_per_request = 100
retry_max_s = 1200
"""
    path = tmp_path / "w.toml"
    path.write_text(toml)
    cfg = load(path)
    assert cfg.token == "abc123" and cfg.token_file == tmp_path / "tok"
    assert cfg.broker_url == "https://broker.example.test/ai/v1"
    assert cfg.expect_versions == {"pplx": PINS["pplx"].model_version}
    assert (cfg.threads, cfg.nice, cfg.memory_gib, cfg.weights_cache) == (6, 12, 20.0, cache)
    assert cfg.schedule.describe() == "22:30-02:00,13:00-14:00"
    assert cfg.schedule.timezone == CAIRO
    assert (cfg.schedule.on_empty, cfg.schedule.poll_s) == ("wait", 300.0)
    assert (cfg.max_jobs, cfg.lease_s, cfg.heartbeat_s) == (4, 600, 30.0)
    assert (cfg.seconds_per_request, cfg.retry_max_s) == (100.0, 1200.0)
    assert cfg.hello_config()["window"] == "22:30-02:00,13:00-14:00"


def test_a_single_model_and_a_single_window_may_be_strings():
    cfg = parse(base(worker={"models": "kev"}, schedule={"windows": "00:30-04:30"}))
    assert cfg.models == ("kev",) and cfg.schedule.describe() == "00:30-04:30"


def test_two_models_on_one_worker():
    assert parse(base(worker={"models": ["kev", "pplx"]})).models == ("kev", "pplx")


# --- refusals ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data, match",
    [
        ({**base(), "extra": {}}, "unknown key"),
        (base(worker={"colour": "red"}), r"\[worker\]: unknown key"),
        (base(compute={"gpus": 1}), r"\[compute\]: unknown key"),
        (base(leases={"batch": 8}), r"\[leases\]: unknown key"),
        ({**base(), "model": {"kev": {"temperature": 2}}}, r"\[model.kev\]: unknown key"),
    ],
)
def test_unknown_keys_are_errors_not_ignored(data, match):
    refused(data, match)


def test_token_or_token_file_exactly_one(tmp_path):
    both = base(worker={"token_file": "x"})
    refused(both, "exactly one of token or token_file")
    neither = base()
    del neither["worker"]["token"]
    refused(neither, "exactly one of token or token_file")
    missing = base(worker={"token_file": str(tmp_path / "absent")})
    del missing["worker"]["token"]
    refused(missing, "token_file")
    empty = tmp_path / "empty"
    empty.write_text("\n")
    blank = base(worker={"token_file": str(empty)})
    del blank["worker"]["token"]
    refused(blank, "empty")


@pytest.mark.parametrize(
    "url, ok",
    [
        ("https://broker.example.test/ai/v1", True),
        ("http://127.0.0.1:8123/ai/v1", True),
        ("http://localhost:8123/ai/v1", True),
        ("http://[::1]:8123/ai/v1", True),
        ("http://broker.example.test/ai/v1", False),
        ("http://192.0.2.5/ai/v1", False),
        ("ftp://broker.example.test/", False),
        ("https://user:pw@broker.example.test/ai/v1", False),
        ("https:///ai/v1", False),
    ],
)
def test_broker_url_is_https_except_on_loopback(url, ok):
    data = base(worker={"broker_url": url})
    if ok:
        parse(data)
    else:
        refused(data, "broker_url")


def test_model_keys_are_checked():
    refused(base(worker={"models": ["kev", "gpt"]}), "unknown model key 'gpt'")
    refused(base(worker={"models": ["kev", "kev"]}), "listed twice")
    refused(base(worker={"models": []}), "non-empty list")
    refused({**base(), "model": {"pplx": {}}}, "does not serve")


def test_expect_version_must_be_what_the_worker_serves():
    good = {**base(), "model": {"kev": {"expect_version": PINS["kev"].model_version}}}
    assert parse(good).expect_versions == {"kev": PINS["kev"].model_version}
    stale = {**base(), "model": {"kev": {"expect_version": "kev-4b@000000000000+kev-0000000+T1.0"}}}
    refused(stale, "stale")


@pytest.mark.parametrize(
    "compute, match",
    [
        ({"device": "tpu"}, "device"),
        ({"device": "cpu", "dtype": "bf16"}, "only \\['fp32'\\] is validated"),
        ({"device": "gpu", "dtype": "fp32"}, "only \\['bf16'\\] is validated"),
        ({"threads": 0}, "threads must be positive"),
        ({"threads": 2.5}, "threads"),
        ({"threads": True}, "expected a number"),
        ({"nice": -5}, "nice"),
        ({"nice": 25}, "nice"),
        ({"memory_gib": -1}, "memory_gib must be positive"),
        ({"mmap": "no"}, "mmap"),
    ],
)
def test_compute_values_are_checked(compute, match):
    refused(base(compute=compute), match)


@pytest.mark.parametrize(
    "schedule, match",
    [
        ({"windows": ["0:30-4:30"]}, "HH:MM-HH:MM"),
        ({"windows": ["00:30"]}, "HH:MM-HH:MM"),
        ({"windows": ["24:00-01:00"]}, "HH:MM-HH:MM"),
        ({"windows": ["03:00-03:00"]}, "empty"),
        ({"windows": []}, "always"),
        ({"windows": "sometimes"}, "HH:MM-HH:MM"),
        ({"timezone": "Mars/Olympus"}, "not a known zone"),
        ({"on_empty": "sleep"}, "on_empty"),
        ({"poll_s": 0}, "poll_s must be positive"),
    ],
)
def test_schedule_values_are_checked(schedule, match):
    refused(base(schedule=schedule), match)


@pytest.mark.parametrize(
    "leases, match",
    [
        ({"max_jobs": 0}, "max_jobs"),
        ({"lease_s": 100, "heartbeat_s": 60}, "at most half of lease_s"),
        ({"heartbeat_s": -1}, "heartbeat_s must be positive"),
        ({"seconds_per_request": 0}, "seconds_per_request"),
        ({"retry_max_s": 0}, "retry_max_s"),
    ],
)
def test_lease_values_are_checked(leases, match):
    refused(base(leases=leases), match)


def test_bad_toml_is_a_config_error(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[worker\nname = 1")
    with pytest.raises(ConfigError):
        load(path)
    with pytest.raises(ConfigError, match="No such file"):
        load(tmp_path / "absent.toml")


# --- windows and the schedule --------------------------------------------------------------


def at(hh: int, mm: int, day: int = 17) -> datetime:
    return datetime(2026, 11, day, hh, mm, tzinfo=CAIRO)


def test_window_contains_start_but_not_end():
    w = Window.parse("00:30-04:30")
    assert w.contains(time(0, 30)) and w.contains(time(4, 29))
    assert not w.contains(time(4, 30)) and not w.contains(time(0, 29))


def test_window_crossing_midnight():
    w = Window.parse("22:00-02:00")
    assert w.contains(time(23, 0)) and w.contains(time(0, 0)) and w.contains(time(1, 59))
    assert not w.contains(time(2, 0)) and not w.contains(time(21, 59))
    s = Schedule((w,), CAIRO)
    assert s.closes_at(at(23, 30)) == at(2, 0, day=18)
    assert s.closes_at(at(1, 0, day=18)) == at(2, 0, day=18)
    assert not s.is_open(at(12, 0))


def test_touching_windows_run_on_as_one():
    s = Schedule((Window.parse("00:30-04:30"), Window.parse("04:30-06:30")), CAIRO)
    assert s.closes_at(at(1, 0)) == at(6, 30)
    overlapping = Schedule((Window.parse("23:00-01:00"), Window.parse("00:30-03:00")), CAIRO)
    assert overlapping.closes_at(at(23, 15)) == at(3, 0, day=18)


def test_always_never_closes():
    s = Schedule(None)
    assert s.is_open(at(13, 0)) and s.closes_at(at(13, 0)) is None


def test_a_closed_schedule_closes_now():
    s = Schedule((Window.parse("00:30-04:30"),), CAIRO)
    assert s.closes_at(at(12, 0)) == at(12, 0)


# --- the documented examples ---------------------------------------------------------------


def documented_configs() -> list[tuple[str, str]]:
    text = DOCS.read_text()
    blocks = re.findall(r"```toml\n(# (\S+)\.toml\n.*?)```", text, re.S)
    return [(name, body) for body, name in blocks]


def test_the_docs_carry_the_four_example_workers():
    names = [n for n, _ in documented_configs()]
    for want in ("home-kev", "home-pplx", "desk-kev", "desk-pplx"):
        assert want in names


@pytest.mark.parametrize("name, body", documented_configs())
def test_every_documented_example_parses(name, body):
    data = tomllib.loads(body)
    # The examples name a token file on the worker's machine; give it a value here.
    data["worker"].pop("token_file", None)
    data["worker"]["token"] = "example"
    data.get("compute", {}).pop("weights_cache", None)
    cfg = parse(data)
    assert cfg.name == name
    if name.startswith("desk-"):
        assert cfg.device == "gpu"
    if name.startswith("home-"):
        assert (cfg.device, cfg.threads, cfg.mmap) == ("cpu", 6, False)


@pytest.mark.parametrize(
    "data",
    [
        base(worker={"ca_file": ""}),
        base(compute={"weights_cache": " "}),
        base(schedule={"timezone": ""}),
    ],
)
def test_an_empty_string_is_refused_not_dropped(data):
    refused(data, "is empty")


@pytest.mark.parametrize("zone", ["UTC", "Etc/UTC", "Africa/Cairo"])
def test_windows_work_in_fixed_offset_zones(zone):
    tz = ZoneInfo(zone)
    s = Schedule((Window.parse("22:00-02:00"),), tz)
    now = datetime(2026, 11, 17, 23, 0, tzinfo=tz)
    assert s.is_open(now) and s.closes_at(now) == datetime(2026, 11, 18, 2, 0, tzinfo=tz)


def test_windows_work_without_a_zone():
    s = Schedule((Window.parse("00:00-23:59"),))
    now = s.now()  # the machine's local time, a fixed offset
    assert s.is_open(now) == (now.time() < time(23, 59))
