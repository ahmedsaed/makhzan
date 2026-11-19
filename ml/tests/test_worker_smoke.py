"""The image smoke test's own logic, outside an image (CI runs the whole of it inside one)."""

from __future__ import annotations

import pytest
from makhzan_ml.worker import smoke


@pytest.mark.parametrize("model", ["kev", "pplx"])
def test_a_session_against_the_fake_broker_passes(model):
    smoke.check_session(model, importable=lambda key: True)


def test_weight_files_finds_a_checkpoint_and_ignores_small_files(tmp_path):
    (tmp_path / "snap").mkdir()
    shard = tmp_path / "snap" / "model-00001-of-00002.safetensors"
    with shard.open("wb") as f:
        f.truncate(smoke.WEIGHT_MIN_BYTES)
    (tmp_path / "tiny.pt").write_bytes(b"0" * 100)
    (tmp_path / "big.txt").write_bytes(b"0" * smoke.WEIGHT_MIN_BYTES)
    assert smoke.weight_files(str(tmp_path)) == [str(shard)]


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded")
def test_a_supervised_window_runs_in_a_child():
    smoke.check_supervisor("kev", importable=lambda key: True)


def test_the_proxy_check_passes():
    smoke.check_proxy()


def test_the_revision_check(monkeypatch):
    monkeypatch.setenv("MAKHZAN_IMAGE_REVISION", "abc")
    smoke.check_revision("abc")
    with pytest.raises(AssertionError):
        smoke.check_revision("def")
