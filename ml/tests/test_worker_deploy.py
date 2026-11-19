"""The home server's compose stack (ml/deploy/home-server): its worker TOMLs parse, wait for
their windows through the broker proxy, and never share a minute."""

from __future__ import annotations

import tomllib
from datetime import time
from pathlib import Path

import pytest
from makhzan_ml.worker.config import parse
from makhzan_ml.worker.pins import PINS

DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "home-server"


@pytest.mark.parametrize("name, model", [("home-kev", "kev"), ("home-pplx", "pplx")])
def test_the_compose_examples_parse_and_wait_for_their_windows(tmp_path, name, model):
    data = tomllib.loads((DEPLOY / f"{name}.toml").read_text())
    data["worker"].pop("token_file")
    data["worker"]["token"] = "example"
    data["compute"].pop("weights_cache")
    cfg = parse(data)
    assert (cfg.name, cfg.model) == (name, model)
    assert cfg.broker_url == "http://broker-proxy:8100/ai/v1" and cfg.broker_via_proxy
    assert cfg.schedule.outside_window == "wait"
    assert cfg.expect_versions == {model: PINS[model].model_version}
    assert (cfg.device, cfg.threads, cfg.mmap, cfg.memory_gib) == ("cpu", 6, False, 20)


#: The gap the owner's one-model rule needs after a window before the other worker's opens:
#: Kev's graceful stop can run about 4 minutes past its window's end (a request in flight, up to
#: about 104 s on the home server's CPU, or a model load, about 150 s, then up to 3 x 10 s of
#: last posts and a 10 s heartbeat join), and the next worker loads on its first lease.
MIN_GAP_MINUTES = 5
DAY = 24 * 60


def held_minutes(windows, pad: int) -> set[int]:
    """The minutes of the day a worker may hold its model: its windows, plus `pad` minutes
    after each end."""
    held = set()
    for w in windows:
        start = w.start.hour * 60 + w.start.minute
        length = (w.end.hour * 60 + w.end.minute - start) % DAY
        held.update((start + m) % DAY for m in range(length + pad))
    return held


def gap_clashes(first, second) -> set[int]:
    """Minutes where `second`'s window is open while `first` is in a window or within
    MIN_GAP_MINUTES of its end."""
    return held_minutes(first, MIN_GAP_MINUTES) & held_minutes(second, 0)


def hhmm(m: int) -> str:
    return f"{time(m // 60, m % 60):%H:%M}"


def test_the_compose_windows_never_overlap_and_leave_a_gap():
    """One model at a time on the machine (31 GB, other services running): the windows never
    share a minute, and after either worker's window ends the other's does not open for at
    least MIN_GAP_MINUTES, while the first one's graceful stop may still hold its model."""
    kev, pplx = (
        parse(
            {
                **tomllib.loads((DEPLOY / f"{n}.toml").read_text()),
                "worker": {
                    "name": n,
                    "broker_url": "https://b.example.test",
                    "token": "t",
                    "model": m,
                },
            }
        )  # fmt: skip
        for n, m in (("home-kev", "kev"), ("home-pplx", "pplx"))
    )

    kw, pw = kev.schedule.windows, pplx.schedule.windows
    both = held_minutes(kw, 0) & held_minutes(pw, 0)
    assert not both, f"both windows are open at {sorted(map(hhmm, both))}"
    for first, second, name in ((kw, pw, "kev"), (pw, kw, "pplx")):
        clash = gap_clashes(first, second)
        assert not clash, (
            f"the other worker's window opens less than {MIN_GAP_MINUTES} minutes after "
            f"{name}'s ends, at {sorted(map(hhmm, clash))}"
        )


@pytest.mark.parametrize(
    "first, second, ok",
    [
        (["01:00-05:00"], ["05:00-07:00"], False),  # touching: Kev's stop runs into it
        (["01:00-05:00"], ["05:04-07:00"], False),
        (["01:00-05:00"], ["05:05-07:00"], True),
        (["01:00-05:00"], ["04:00-07:00"], False),  # overlapping
        (["22:00-00:00"], ["00:03-02:00"], False),  # across midnight
        (["22:00-00:00"], ["00:05-02:00"], True),
    ],
)
def test_the_gap_check_itself(first, second, ok):
    from makhzan_ml.worker.config import Window

    a = [Window.parse(w) for w in first]
    b = [Window.parse(w) for w in second]
    assert (not gap_clashes(a, b)) is ok
