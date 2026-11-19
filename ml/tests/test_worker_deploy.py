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


def test_the_compose_windows_never_overlap():
    """One model at a time on the machine: Kev's and pplx's windows must not share a minute."""
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
    for minute in range(24 * 60):
        t = time(minute // 60, minute % 60)
        assert not (
            any(w.contains(t) for w in kev.schedule.windows)
            and any(w.contains(t) for w in pplx.schedule.windows)
        ), f"both windows are open at {t}"
