"""The home server's sidecar units (ml/deploy/home-server): sidecar-window.sh starts one judge's
llama.cpp sidecar only on a clock-limited card with its groups set, stops the other first, and at
boot starts whichever window's sidecar is due; the installer's times keep exactly one sidecar up
around each worker's window, with room for the window's last request, every night of the year."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from makhzan_ml.worker import judges
from makhzan_ml.worker.config import parse

DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "home-server"
SCRIPT = DEPLOY / "sidecar-window.sh"
INSTALLER = DEPLOY / "install-sidecar-timers.sh"


def fake_env(tmp_path: Path, mode: str | None) -> tuple[dict, Path]:
    """A fake docker that logs its arguments, a fake sysfs whose amdgpu card is in `mode` (None: no
    amdgpu card at all), and a stack folder whose .env sets the card's groups."""
    log = tmp_path / "docker.log"
    docker = tmp_path / "docker"
    docker.write_text(f'#!/bin/sh\necho "$PWD|$*" >> {log}\n')
    docker.chmod(0o755)
    sysfs = tmp_path / "sys"
    hwmon = sysfs / "class/drm/card1/device/hwmon/hwmon3"
    hwmon.mkdir(parents=True)
    (hwmon / "name").write_text("amdgpu\n" if mode is not None else "nouveau\n")
    if mode is not None:
        (sysfs / "class/drm/card1/device/power_dpm_force_performance_level").write_text(mode + "\n")
    stack = tmp_path / "stack"
    stack.mkdir()
    (stack / ".env").write_text("UID=1000\nRENDER_GID=992\nVIDEO_GID='44'\n")
    env = {**os.environ, "DOCKER": str(docker), "SYSFS": str(sysfs), "MAKHZAN_AI_DIR": str(stack),
           "BOOT_WAIT_S": "0"}  # fmt: skip
    return env, log


def run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def up(stack: str, model: str) -> str:
    profile = "llamacpp" if model == "kev" else "llamacpp-pplx"
    return f"{stack}|compose --profile {profile} up -d {model}-llamacpp"


# --- the script ---------------------------------------------------------------------------


@pytest.mark.parametrize("args", [("start", "kev"), ("start-kev",)])
def test_starting_kev_stops_pplx_first_then_starts_kev(tmp_path, args):
    env, log = fake_env(tmp_path, "manual")
    r = run(env, *args)
    assert r.returncode == 0, r.stderr
    stack = env["MAKHZAN_AI_DIR"]
    assert calls(log) == [
        f"{stack}|compose --profile llamacpp-pplx stop pplx-llamacpp",
        up(stack, "kev"),
    ]


def test_starting_pplx_stops_kev_first_and_stopping_touches_only_its_own(tmp_path):
    env, log = fake_env(tmp_path, "manual")
    assert run(env, "start", "pplx").returncode == 0
    assert run(env, "stop-pplx").returncode == 0
    stack = env["MAKHZAN_AI_DIR"]
    assert calls(log) == [
        f"{stack}|compose --profile llamacpp stop kev-llamacpp",
        up(stack, "pplx"),
        f"{stack}|compose --profile llamacpp-pplx stop pplx-llamacpp",
    ]


@pytest.mark.parametrize("mode", ["auto", "high", None])
def test_a_card_without_the_clock_limit_is_refused_and_nothing_runs(tmp_path, mode):
    env, log = fake_env(tmp_path, mode)
    r = run(env, "start", "kev")
    assert r.returncode == 3
    assert "REFUSED" in r.stdout and "99-amdgpu-clock-limit.rules" in r.stdout
    assert calls(log) == []
    # Stopping needs no clock limit: it only takes load off the card.
    assert run(env, "stop", "kev").returncode == 0 and len(calls(log)) == 1


@pytest.mark.parametrize(
    "env_text",
    ["UID=1000\n", "RENDER_GID=\nVIDEO_GID=44\n", "RENDER_GID=992\nVIDEO_GID=''\n", ""],
)
def test_a_start_without_the_card_groups_in_env_is_refused(tmp_path, env_text):
    # Without them the sidecar cannot open /dev/dri (and, with -dev Vulkan0, exits at start).
    env, log = fake_env(tmp_path, "manual")
    Path(env["MAKHZAN_AI_DIR"], ".env").write_text(env_text)
    r = run(env, "start", "pplx")
    assert r.returncode == 4 and "RENDER_GID and VIDEO_GID" in r.stdout
    assert calls(log) == []


@pytest.mark.parametrize(
    "now, due",
    [("005459", None), ("005500", "kev"), ("010020", "kev"), ("050259", "kev"), ("050300", None),
     ("050329", None), ("050330", "pplx"), ("070259", "pplx"), ("070300", None), ("120000", None),
     ("235959", None)],
)  # fmt: skip
def test_at_boot_the_due_sidecar_starts_through_the_same_checks(tmp_path, now, due):
    env, log = fake_env(tmp_path, "manual")
    r = run({**env, "NOW": now}, "boot")
    assert r.returncode == 0, r.stdout + r.stderr
    if due is None:
        assert calls(log) == [] and "nothing to start" in r.stdout
    else:
        assert calls(log)[-1] == up(env["MAKHZAN_AI_DIR"], due)


def test_a_boot_before_the_clock_limit_applies_starts_nothing(tmp_path):
    env, log = fake_env(tmp_path, "auto")
    r = run({**env, "NOW": "020000"}, "boot")
    assert r.returncode == 3 and "REFUSED" in r.stdout and calls(log) == []


@pytest.mark.parametrize("args", [(), ("start",), ("start", "onnx"), ("restart", "kev"), ("kev",),
                                  ("start", "kev", "now")])  # fmt: skip
def test_bad_arguments_are_refused(tmp_path, args):
    env, log = fake_env(tmp_path, "manual")
    assert run(env, *args).returncode == 2
    assert calls(log) == []


# --- the schedule -------------------------------------------------------------------------


def installer_times() -> dict[str, list[int]]:
    """The installer's timer times, in seconds after midnight (Africa/Cairo), per timer."""
    text = INSTALLER.read_text()
    assert "TZONE=Africa/Cairo" in text
    spec = re.search(r'^TIMERS="([^"]+)"$', text, re.M).group(1)
    times = {}
    for item in spec.split():
        name, ats = item.split(":", 1)
        times[name] = []
        for at in ats.split(","):
            h, m, s = (int(x) for x in at.split(":"))
            times[name].append(h * 3600 + m * 60 + s)
    return times


def window(name: str) -> tuple[int, int, str, str]:
    data = tomllib.loads((DEPLOY / f"{name}.toml").read_text())
    data["worker"].pop("token_file")
    data["worker"]["token"] = "example"
    cfg = parse(data)
    [w] = cfg.schedule.windows
    assert str(cfg.schedule.timezone) == "Africa/Cairo"
    to_s = lambda t: t.hour * 3600 + t.minute * 60  # noqa: E731
    return to_s(w.start), to_s(w.end), cfg.model, cfg.device


def test_the_timers_keep_one_sidecar_up_around_each_window():
    times = installer_times()
    assert set(times) == {"start-kev", "stop-kev", "start-pplx", "stop-pplx"}
    t = {name: ats[0] for name, ats in times.items()}  # each timer's normal-night time
    kev_open, kev_close, _, kev_device = window("home-kev")
    pplx_open, pplx_close, _, pplx_device = window("home-pplx")
    assert kev_device == pplx_device == "gpu"
    # A window's last request, started at the very end, runs at most the GPU timeout, then up to
    # 3 x 10 s of last posts and a 10 s join; the sidecar must outlive the request.
    last_kev = kev_close + judges.LLAMACPP_REQUEST_S[("kev", "gpu")]
    last_pplx = pplx_close + judges.LLAMACPP_REQUEST_S[("pplx", "gpu")]
    # Each sidecar is up (and given a minute to load) before its window opens.
    assert t["start-kev"] <= kev_open - 60
    assert t["start-pplx"] <= pplx_open - 60
    # ... and stays up past its window's last possible request.
    assert t["stop-kev"] >= last_kev + 60
    assert t["stop-pplx"] >= last_pplx + 60
    # One model on the card: Kev's is stopped before pplx's starts (the script also stops it).
    assert t["stop-kev"] < t["start-pplx"]
    # The worker's own ready wait covers a sidecar still loading when its window opens.
    assert pplx_open - t["start-pplx"] + judges.LLAMACPP_READY_S >= 120
    # The boot unit's ranges are the timers' (sidecar-window.sh's boot()).
    script = SCRIPT.read_text()
    assert '-ge 5500 ] && [ "$now" -lt 50300 ]' in script  # 00:55:00-05:03:00
    assert '-ge 50330 ] && [ "$now" -lt 70300 ]' in script  # 05:03:30-07:03:00


def test_every_night_has_a_kev_start_even_when_the_clocks_spring_forward():
    """Egypt's DST starts at 00:00 local on the last Friday of April (to 01:00), so 00:55 does not
    exist that night; the second start at 01:00:20 does, and the worker's ready wait (120 s from
    01:00) covers a sidecar started then and loading for under a minute."""
    cairo, utc = ZoneInfo("Africa/Cairo"), ZoneInfo("UTC")
    starts = installer_times()["start-kev"]
    kev_open = window("home-kev")[0]
    assert len(starts) >= 2

    def exists(day: date, secs: int) -> bool:  # a wall-clock time no clock change skipped
        naive = datetime.combine(day, datetime.min.time()) + timedelta(seconds=secs)
        back = naive.replace(tzinfo=cairo).astimezone(utc).astimezone(cairo)
        return back.replace(tzinfo=None) == naive

    skipped = []
    for n in range(2 * 365):
        day = date(2026, 1, 1) + timedelta(days=n)
        valid = [s for s in starts if exists(day, s)]
        assert valid, f"no Kev sidecar start exists on {day}"
        if not exists(day, starts[0]):
            skipped.append(day)
            assert min(valid) - kev_open + 60 <= judges.LLAMACPP_READY_S
    # Meaningful: the 2026 and 2027 spring-forward nights were found.
    assert date(2026, 4, 24) in skipped and len(skipped) == 2


def test_the_installer_renders_the_units(tmp_path):
    units = tmp_path / "units"
    units.mkdir()
    r = subprocess.run(
        ["sh", str(INSTALLER)],
        env={**os.environ, "MAKHZAN_UNITS_DIR": str(units), "SUDO_USER": "someone"},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    names = sorted(p.name for p in units.iterdir())
    want = ["makhzan-sidecar@.service", "makhzan-sidecar-boot.service"]
    assert names == sorted(want + [f"makhzan-sidecar-{n}.timer" for n in installer_times()])
    kev = (units / "makhzan-sidecar-start-kev.timer").read_text()
    assert kev.count("OnCalendar=") == 2 and "OnCalendar=*-*-* 01:00:20 Africa/Cairo" in kev
    boot = (units / "makhzan-sidecar-boot.service").read_text()
    assert "After=docker.service" in boot and "sidecar-window.sh boot" in boot
    assert "User=someone" in boot and "WantedBy=multi-user.target" in boot


def test_docker_never_restarts_a_sidecar_and_no_card_is_a_startup_error():
    """The timers and the boot unit own the sidecars' lifecycle, through the script's checks."""
    text = (DEPLOY / "compose.yml").read_text()
    for name, end in (
        ("kev-llamacpp", "\n  # pplx on the AMD card"),
        ("pplx-llamacpp", "\nnetworks:"),
    ):
        block = text[text.index(f"\n  {name}:\n") : text.index(end)]
        assert '    restart: "no"\n' in block
        assert "      - -dev\n      - Vulkan0\n" in block
