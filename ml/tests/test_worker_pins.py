"""The worker's copies of the registry, held to the registry; and the judges' guards."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
from makhzan_ml.worker import judges, pins, run
from makhzan_ml.worker.fake_broker import canonical_sha256
from makhzan_ml.worker.pins import PINS
from makhzan_schemas.ai import pipelines, policy, prompt


def test_production_pins_are_the_policy_models():
    # What production serves (owner, 2026-11-27; H2O first since D25): the llama.cpp pins, equal
    # to policy.MODELS.
    assert set(pins.ACTIVE_BACKEND) == set(policy.MODELS) == {"h2o", "pplx"}
    for key, model in policy.MODELS.items():
        pin = pins.production_pin(key)
        assert pin.backend == pins.ACTIVE_BACKEND[key] == model.scoring["backend"] == "llamacpp"
        assert pin.repo == model.repo
        assert pin.weights_revision == model.weights_revision
        assert pin.model_version == model.model_version
        assert pin.temperature == model.scoring["temperature"]
        assert pin.gguf_sha256 == model.scoring["gguf_sha256"]
        assert pin.code.endswith(policy.LLAMACPP_IMAGE_DIGEST)


def test_the_torch_pins_are_the_policys_rollback():
    assert set(PINS) == set(policy.TORCH_MODELS)
    for key, model in policy.TORCH_MODELS.items():
        pin = PINS[key]
        assert pin.backend == "torch"
        assert pin.repo == model.repo
        assert pin.weights_revision == model.weights_revision
        assert pin.model_version == model.model_version
        assert pin.temperature == model.scoring["temperature"]
    assert PINS["kev"].code == policy.KEV_CODE


ML = Path(__file__).resolve().parent.parent


def _arg(dockerfile: str, name: str) -> str:
    found = re.findall(rf"^ARG {name}=(\S+)$", (ML / dockerfile).read_text(), re.M)
    assert len(found) == 1, f"{dockerfile}: ARG {name} appears {len(found)} times"
    return found[0]


@pytest.mark.parametrize("dockerfile", ["kev/Dockerfile", "kev/Dockerfile.cpu-lean"])
def test_the_kev_images_build_the_pinned_kev_code(dockerfile):
    # The image records this ARG as MAKHZAN_KEV_COMMIT, and the worker refuses a Kev that
    # differs from pins.KEV_CODE: a bump in one place alone builds an image that never scores.
    assert _arg(dockerfile, "KEV_COMMIT") == pins.KEV_CODE


def test_the_lean_images_serve_the_pinned_revisions():
    kev = (ML / "kev/Dockerfile.cpu-lean").read_text()
    assert _arg("kev/Dockerfile.cpu-lean", "KEV_REVISION") == pins.KEV_REVISION
    assert f"jaredpalmer/kev-4b@{pins.KEV_REVISION}" in kev  # the CMD, which cannot use the ARG
    pplx = (ML / "pplx/Dockerfile.cpu-lean").read_text()
    assert _arg("pplx/Dockerfile.cpu-lean", "REVISION") == pins.PPLX_REVISION
    assert f'"--revision", "{pins.PPLX_REVISION}"' in pplx


def test_every_stage_model_can_be_served():
    for p in pipelines.PIPELINES.values():
        for stage in p.stages:
            assert stage.model in pins.MODEL_KEYS
            assert pins.production_pin(stage.model).model_version == stage.model_version


def test_the_kev_rollback_of_d25_is_the_policys():
    alt = pins.pin_for("kev", "llamacpp")
    model = policy.LLAMACPP_KEV
    assert (alt.repo, alt.weights_revision, alt.model_version) == (
        model.repo, model.weights_revision, model.model_version,
    )  # fmt: skip
    assert alt.gguf_sha256 == model.scoring["gguf_sha256"]


def record(n: int) -> dict:
    return prompt.record({
        "id": f"00000000-0000-0000-0000-00000000000{n}",
        "title_en": f"Ceramic capacitor 100nF 50V {n} – 10 pcs “X7R”",
        "category": "Capacitors",
        "brand": None,
        "part_number": None,
        "specs": {"Capacitance": "100 nF", "Voltage": "50 V"},
        "description_en": "<p>Ceramic &amp; reliable.</p> مكثف",
    })  # fmt: skip


@pytest.mark.parametrize("variant", sorted(prompt.VARIANTS))
def test_the_worker_hashes_requests_as_the_broker_does(variant):
    for request in prompt.requests(variant, record(1), record(2)).values():
        assert run.canonical_json(request) == prompt.canonical_json(request)
        assert run.request_sha256(request) == prompt.request_sha256(request).hex()
        assert canonical_sha256(request) == prompt.request_sha256(request).hex()


def test_a_rendered_request_has_the_one_question_the_judges_read():
    for variant in prompt.VARIANTS:
        request = prompt.requests(variant, record(1), record(2))["ab"]
        assert judges.question_key(request) == "same"
    with pytest.raises(ValueError):
        judges.question_key({"state": "x", "questions": {}})
    with pytest.raises(ValueError):
        judges.question_key({"state": "x", "questions": {"a": {}, "b": {}}})


@pytest.mark.parametrize("bad", [1.5, -0.01, math.nan, math.inf])
def test_a_score_outside_the_unit_interval_is_an_error(bad):
    judge = judges.Judge("kev", lambda _p: (bad, {}))
    with pytest.raises(ValueError, match="outside"):
        judge.score({})


def test_the_mapped_weights_check_can_fire():
    judges.selfcheck()


def test_mapped_weights_reads_proc_maps(tmp_path):
    hub = tmp_path / "hub"
    snap = hub / "models--org--m" / "snapshots" / ("a" * 40)
    blob = hub / "models--org--m" / "blobs" / ("b" * 64)
    snap.mkdir(parents=True)
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"x")
    (snap / "model.safetensors").symlink_to(blob)
    maps = "\n".join([
        f"7f00-7f01 r--s 00000000 08:01 1 {blob}",
        "7f02-7f03 r-xp 00000000 08:01 2 /usr/lib/libc.so.6",
        "7f04-7f05 r--s 00000000 08:01 3 /elsewhere/extra.safetensors (deleted)",
        "7f06-7f07 rw-p 00000000 00:00 0",
    ])  # fmt: skip
    assert judges.mapped_weights(maps, [hub]) == sorted(
        [str(blob.resolve()), "/elsewhere/extra.safetensors"]
    )
    assert judges.mapped_weights("7f02-7f03 r-xp 0 0 2 /usr/lib/libc.so.6", [hub]) == []


def test_prepare_environment_keeps_the_worker_offline_and_capped(monkeypatch, tmp_path):
    for k in ("HF_HOME", "CUDA_VISIBLE_DEVICES", "OMP_NUM_THREADS", "HF_HUB_OFFLINE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HF_HUB_CACHE", "/somewhere/else")
    judges.prepare_environment(judges.Runtime("cpu", "fp32", 6, False, tmp_path))
    import os

    assert os.environ["HF_HOME"] == str(tmp_path) and "HF_HUB_CACHE" not in os.environ
    assert os.environ["HF_HUB_OFFLINE"] == "1" and os.environ["CUDA_VISIBLE_DEVICES"] == ""
    assert os.environ["OMP_NUM_THREADS"] == "6" and os.environ["MKL_NUM_THREADS"] == "6"
