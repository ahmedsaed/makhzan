"""Tests for ml/ code that has to stay right: the AI-matching worker.

Run with the ingestion environment (`make test-worker`), which also has
`makhzan_schemas`, so the worker's pins and request hashing are checked against the
registry they copy. No database and no model: the worker is driven against
`makhzan_ml.worker.fake_broker` with a fake judge and a fake clock.
"""

from __future__ import annotations

import sys
from pathlib import Path

ML = Path(__file__).resolve().parent.parent
if str(ML) not in sys.path:
    sys.path.insert(0, str(ML))


import pytest  # noqa: E402 - after the path setup above


@pytest.fixture(autouse=True)
def _fake_sysfs(tmp_path_factory, monkeypatch):
    """No test reads this machine's /sys: a GPU llama.cpp worker checks the card's clock mode
    and voltage there, and a developer's own GPU (an iGPU reading 1,200 mV, say) would make the
    voltage guard wait forever. The default is the home server's card, limited and computing at
    clock state 2; a test that needs another card points judges.SYSFS at its own tree."""
    from makhzan_ml.worker import judges

    root = tmp_path_factory.mktemp("sys")
    dev = root / "class" / "drm" / "card1" / "device"
    hw = dev / "hwmon" / "hwmon0"
    hw.mkdir(parents=True)
    (dev / "power_dpm_force_performance_level").write_text("manual\n")
    (hw / "name").write_text("amdgpu\n")
    (hw / "in0_input").write_text("950\n")
    monkeypatch.setattr(judges, "SYSFS", root)
