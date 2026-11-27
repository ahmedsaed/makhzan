"""The home server's sidecar timers (ml/deploy/home-server): sidecar-window.sh starts one judge's
llama.cpp sidecar only on a clock-limited card and stops the other first; the installer's times
keep exactly one sidecar up around each worker's window, with room for the window's last request."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
from makhzan_ml.worker import judges
from makhzan_ml.worker.config import parse

DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "home-server"
SCRIPT = DEPLOY / "sidecar-window.sh"


def fake_env(tmp_path: Path, mode: str | None) -> tuple[dict, Path]:
    """A fake docker that logs its arguments, and a fake sysfs whose amdgpu card is in `mode`
    (None: no amdgpu card at all)."""
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
    env = {**os.environ, "DOCKER": str(docker), "SYSFS": str(sysfs), "MAKHZAN_AI_DIR": str(stack)}
    return env, log


def run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


@pytest.mark.parametrize("args", [("start", "kev"), ("start-kev",)])
def test_starting_kev_stops_pplx_first_then_starts_kev(tmp_path, args):
    env, log = fake_env(tmp_path, "manual")
    r = run(env, *args)
    assert r.returncode == 0, r.stderr
    stack = env["MAKHZAN_AI_DIR"]
    assert calls(log) == [
        f"{stack}|compose --profile llamacpp-pplx stop pplx-llamacpp",
        f"{stack}|compose --profile llamacpp up -d kev-llamacpp",
    ]


def test_starting_pplx_stops_kev_first_and_stopping_touches_only_its_own(tmp_path):
    env, log = fake_env(tmp_path, "manual")
    assert run(env, "start", "pplx").returncode == 0
    assert run(env, "stop-pplx").returncode == 0
    stack = env["MAKHZAN_AI_DIR"]
    assert calls(log) == [
        f"{stack}|compose --profile llamacpp stop kev-llamacpp",
        f"{stack}|compose --profile llamacpp-pplx up -d pplx-llamacpp",
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


@pytest.mark.parametrize("args", [(), ("start",), ("start", "onnx"), ("restart", "kev"), ("kev",),
                                  ("start", "kev", "now")])  # fmt: skip
def test_bad_arguments_are_refused(tmp_path, args):
    env, log = fake_env(tmp_path, "manual")
    assert run(env, *args).returncode == 2
    assert calls(log) == []


def installer_times() -> dict[str, int]:
    """The installer's timer times, in seconds after midnight (Africa/Cairo)."""
    text = (DEPLOY / "install-sidecar-timers.sh").read_text()
    assert "TZONE=Africa/Cairo" in text
    spec = re.search(r'^TIMERS="([^"]+)"$', text, re.M).group(1)
    times = {}
    for item in spec.split():
        name, at = item.split(":", 1)
        h, m, s = (int(x) for x in at.split(":"))
        times[name] = h * 3600 + m * 60 + s
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
    t = installer_times()
    assert set(t) == {"start-kev", "stop-kev", "start-pplx", "stop-pplx"}
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
