"""The card's voltage guard (`max_vddgfx_mv`): no lease and no request while another app has
the AMD card's video engine, which lifts its core voltage past what the clock limit allows.

On 2026-11-28 Jellyfin's trickplay job took the video engine at 05:00 Cairo; the card went from
950 to 1,150 mV under the clock limit, and pplx's full load there tripped the card's power feed
and reset the server at 05:05:54. The voltage is read from a fake sysfs tree here.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from makhzan_ml.worker import judges, run
from makhzan_ml.worker.config import ConfigError, parse
from makhzan_ml.worker.fake_broker import FakeBroker
from test_worker_lifecycle import CAIRO, TOKEN, FakeClock, config, make_worker, pair

LIMIT = 1000


@pytest.fixture
def broker():
    with FakeBroker({TOKEN: ("home-kev", ["kev", "pplx"])}) as b:
        yield b


@pytest.fixture
def sleeps():
    return []


def card(tmp_path, mv: int | None, *, name: str = "amdgpu"):
    """A fake /sys with one card whose hwmon reads `mv` (None: no hwmon at all)."""
    root = tmp_path / "sys"
    dev = root / "class" / "drm" / "card1" / "device"
    dev.mkdir(parents=True)
    if mv is not None:
        hw = dev / "hwmon" / "hwmon3"
        hw.mkdir(parents=True)
        (hw / "name").write_text(name + "\n")
        (hw / "in0_input").write_text(f"{mv}\n")
    return root


def set_mv(root, mv: int) -> None:
    (root / "class/drm/card1/device/hwmon/hwmon3/in0_input").write_text(f"{mv}\n")


class HookedClock(FakeClock):
    """A FakeClock that calls `hook(elapsed)` after every advance: the voltage changes with time."""

    def __init__(self, start, hook=None):
        super().__init__(start)
        self.hook = hook

    def advance(self, seconds):
        super().advance(seconds)
        if self.hook:
            self.hook(self.mono)


@pytest.fixture
def sysfs(tmp_path, monkeypatch):
    def make(mv, **kw):
        root = card(tmp_path, mv, **kw)
        monkeypatch.setattr(judges, "SYSFS", root)
        return root

    return make


def guarded(broker, sleeps, clock=None, fake=None, **sections):
    # The lifecycle harness runs the torch backend (a fake judge): the guard is set directly,
    # as the llama.cpp configuration's default sets it.
    return make_worker(broker, sleeps, clock=clock, fake=fake,
                       cfg_overrides={"max_vddgfx_mv": LIMIT}, **sections)  # fmt: skip


def test_reading_takes_the_amdgpu_hwmon_only(tmp_path):
    root = card(tmp_path, 1150)
    other = root / "class/drm/card1/device/hwmon/hwmon2"
    other.mkdir(parents=True)
    (other / "name").write_text("nvme\n")
    (other / "in0_input").write_text("5000\n")
    assert judges.read_vddgfx_mv(root) == 1150


@pytest.mark.parametrize("mv, name", [(None, "amdgpu"), (900, "radeon")])
def test_reading_without_an_amdgpu_hwmon_is_unavailable(tmp_path, mv, name):
    with pytest.raises(judges.SensorUnavailable):
        judges.read_vddgfx_mv(card(tmp_path, mv, name=name))


def test_a_busy_card_is_waited_for_before_any_lease(broker, sleeps, sysfs):
    root = sysfs(1150)
    jobs = [broker.add_job("kev", pair(n)) for n in range(2)]
    leased_at: list[float] = []

    def hook(elapsed):
        if elapsed >= 90:  # the transcode ends after a minute and a half
            set_mv(root, 900)

    clock = HookedClock(datetime(2026, 11, 17, 6, 0, tzinfo=CAIRO), hook)
    worker, fake, _ = guarded(broker, sleeps, clock=clock)
    orig = worker.broker.lease
    worker.broker.lease = lambda body: (leased_at.append(clock.mono), orig(body))[1]
    assert worker.run() == run.EXIT_OK
    # Nothing leased while the card was busy, nor until it had read low for the hold (60 s)
    # after its last high reading (at most one sample before the transcode ended at 90 s).
    assert leased_at and leased_at[0] >= 90 - run.CARD_SAMPLE_S + 60
    assert all(j.status == "done" for j in jobs) and len(fake.scored) == 4
    assert run.CARD_CONFIRM_S in clock.waits and run.CARD_SAMPLE_S in clock.waits
    assert worker.card_wait_s >= leased_at[0] - run.CARD_CONFIRM_S - 1


def test_one_high_reading_not_confirmed_is_not_a_busy_card(broker, sleeps, sysfs):
    root = sysfs(1050)  # passing through on a state change; the next reading is back down
    broker.add_job("kev", pair(1))

    def hook(_elapsed):
        set_mv(root, 950)

    clock = HookedClock(datetime(2026, 11, 17, 6, 0, tzinfo=CAIRO), hook)
    worker, fake, _ = guarded(broker, sleeps, clock=clock)
    assert worker.run() == run.EXIT_OK
    assert len(fake.scored) == 2 and run.CARD_SAMPLE_S not in clock.waits
    assert worker.card_wait_s == 0


def test_the_window_end_while_waiting_leases_nothing(broker, sleeps, sysfs):
    sysfs(1150)  # busy all window
    job = broker.add_job("kev", pair(1))
    clock = FakeClock(datetime(2026, 11, 17, 6, 0, tzinfo=CAIRO))
    worker, fake, _ = guarded(broker, sleeps, clock=clock, schedule={"windows": ["06:00-06:02"]})
    assert worker.run() == run.EXIT_OK
    assert worker.stop_reason == "the window has ended"
    assert broker.bodies("/lease") == [] and fake.loads == [] and fake.scored == []
    assert job.status == "queued" and job.attempts == 0
    # The waits never ran past the window's end.
    assert clock.now() == datetime(2026, 11, 17, 6, 2, tzinfo=CAIRO)


def test_a_stop_while_waiting_ends_the_session(broker, sleeps, sysfs):
    sysfs(1150)
    broker.add_job("kev", pair(1))
    clock = HookedClock(datetime(2026, 11, 17, 6, 0, tzinfo=CAIRO))
    worker, fake, _ = guarded(broker, sleeps, clock=clock)
    clock.hook = lambda elapsed: elapsed >= 60 and worker.request_stop("SIGTERM")
    assert worker.run() == run.EXIT_OK
    assert worker.stop_reason == "SIGTERM" and fake.scored == []
    assert broker.bodies("/lease") == []


def test_a_card_taken_mid_job_gives_the_job_back_then_waits(broker, sleeps, sysfs):
    root = sysfs(950)
    job = broker.add_job("kev", pair(1))
    busy_from: list[float] = []
    leased_at: list[float] = []

    def hook(elapsed):
        if busy_from and elapsed - busy_from[0] >= 60:
            set_mv(root, 950)

    clock = HookedClock(datetime(2026, 11, 17, 6, 0, tzinfo=CAIRO), hook)
    worker, fake, _ = guarded(broker, sleeps, clock=clock)
    orig = worker.broker.lease
    worker.broker.lease = lambda body: (leased_at.append(clock.mono), orig(body))[1]

    def on_score(i):
        if i == 0:  # Jellyfin starts during the first order
            set_mv(root, 1150)
            busy_from.append(clock.mono)

    fake.on_score = on_score
    assert worker.run() == run.EXIT_OK
    # The order in flight finished and was kept; "ba" was not sent at 1,150 mV: the job went
    # back gracefully (no attempt), and came back once the card was free.
    graceful = [b for b in broker.bodies("/release") if b.get("job_ids")]
    assert graceful and graceful[0]["job_ids"] == [job.job_id]
    assert graceful[0]["reason"] == "graceful"
    assert job.attempts == 0 and job.last_error is None and job.status == "done"
    assert len(fake.scored) == 2 and len(broker.bodies("/lease")) >= 2
    # Back only once the card had read low for the hold after the transcode ended (60 s on).
    assert not worker.failed_jobs and worker.card_wait_s > 0
    assert leased_at[1] >= busy_from[0] + 60 - run.CARD_SAMPLE_S + 60


def test_a_gap_between_video_runs_does_not_end_the_wait(broker, sleeps, sysfs):
    """Trickplay runs one ffmpeg per item and the video engine idles a second or two between
    them: a low reading in a gap is not the end of the job."""
    root = sysfs(1150)
    broker.add_job("kev", pair(1))
    busy = [(0, 40), (42, 80), (81, 125), (127, 200)]  # four items, short gaps between
    last_busy_end = busy[-1][1]
    leased_at: list[float] = []

    def hook(elapsed):
        set_mv(root, 1150 if any(a <= elapsed < b for a, b in busy) else 900)

    clock = HookedClock(datetime(2026, 11, 17, 6, 0, tzinfo=CAIRO), hook)
    worker, fake, _ = guarded(broker, sleeps, clock=clock)
    orig = worker.broker.lease
    worker.broker.lease = lambda body: (leased_at.append(clock.mono), orig(body))[1]
    assert worker.run() == run.EXIT_OK
    # A lease came only after a full hold of low readings past the last item.
    assert leased_at and leased_at[0] >= last_busy_end + 60 - run.CARD_SAMPLE_S
    assert len(fake.scored) == 2


def test_a_failed_read_is_retried_before_it_is_fatal(broker, sleeps, sysfs, monkeypatch):
    sysfs(950)
    broker.add_job("kev", pair(1))
    real, fails = judges.read_vddgfx_mv, [2]  # two failures, then a reading

    def flaky(root=None):
        if fails[0]:
            fails[0] -= 1
            raise judges.SensorUnavailable("EIO")
        return real(root)

    monkeypatch.setattr(judges, "read_vddgfx_mv", flaky)
    clock = FakeClock(datetime(2026, 11, 17, 6, 0, tzinfo=CAIRO))
    worker, fake, _ = guarded(broker, sleeps, clock=clock)
    assert worker.run() == run.EXIT_OK and len(fake.scored) == 2
    assert clock.waits.count(run.CARD_RETRY_S) == 2


def test_a_suspended_card_reads_idle(tmp_path):
    root = card(tmp_path, 1150)
    (root / "class/drm/card1/device/power").mkdir()
    (root / "class/drm/card1/device/power/runtime_status").write_text("suspended\n")
    assert judges.read_vddgfx_mv(root) == 0


def test_an_unreadable_hwmon_is_skipped_while_another_amdgpu_card_reads(tmp_path):
    root = card(tmp_path, 950)
    # card0: an APU's amdgpu hwmon without in0_input, and another hwmon whose name is unreadable.
    apu = root / "class/drm/card0/device/hwmon"
    (apu / "hwmon0").mkdir(parents=True)
    (apu / "hwmon0" / "name").write_text("amdgpu\n")
    (apu / "hwmon1").mkdir()  # no name file at all
    assert judges.read_vddgfx_mv(root) == 950


def test_the_highest_amdgpu_card_counts(tmp_path):
    root = card(tmp_path, 950)
    apu = root / "class/drm/card0/device/hwmon/hwmon0"
    apu.mkdir(parents=True)
    (apu / "name").write_text("amdgpu\n")
    (apu / "in0_input").write_text("1200\n")
    assert judges.read_vddgfx_mv(root) == 1200


@pytest.mark.parametrize("mv", [None, 900])
def test_an_unreadable_sensor_refuses_to_score(broker, sleeps, sysfs, mv, caplog):
    sysfs(mv, name="amdgpu" if mv is None else "k10temp")
    job = broker.add_job("kev", pair(1))
    worker, fake, _ = guarded(broker, sleeps)
    assert worker.run() == run.EXIT_CONFIG
    assert fake.scored == [] and broker.bodies("/lease") == []
    assert job.status == "queued" and job.attempts == 0
    assert "cannot be read" in caplog.text


def test_off_reads_nothing(broker, sleeps, sysfs):
    sysfs(None)  # no sensor at all: never read with the guard off
    broker.add_job("kev", pair(1))
    worker, fake, _ = make_worker(broker, sleeps)
    assert worker.cfg.max_vddgfx_mv == 0
    assert worker.run() == run.EXIT_OK and len(fake.scored) == 2


# --- configuration -------------------------------------------------------------------------


def llamacpp(url, tmp_path, **compute):
    data = config(url)
    data["compute"] = {"backend": "llamacpp", "device": "gpu", "llamacpp_url": "http://127.0.0.1:8080",
                       "gguf_path": str(tmp_path / "x.gguf"), **compute}  # fmt: skip
    return data


@pytest.mark.parametrize(
    "compute, want",
    [
        ({}, 1000),  # on by default with the clock limit (a GPU)
        ({"require_clock_limit": False}, 0),  # not the limited card: off
        ({"device": "cpu"}, 0),
        ({"max_vddgfx_mv": 1100}, 1100),
        ({"max_vddgfx_mv": 0}, 0),  # off, explicitly
    ],
)
def test_the_default_follows_the_clock_limit(tmp_path, compute, want):
    data = llamacpp("http://127.0.0.1:8100/ai/v1", tmp_path, **compute)
    if data["compute"]["device"] == "cpu":
        data["compute"]["dtype"] = "q4_k_m"
    assert parse(data).max_vddgfx_mv == want


@pytest.mark.parametrize("value", [-1, 3601, True, "60"])
def test_a_bad_clear_time_is_refused(tmp_path, value):
    with pytest.raises(ConfigError, match="vddgfx_clear_s"):
        parse(llamacpp("http://127.0.0.1:8100/ai/v1", tmp_path, vddgfx_clear_s=value))


def test_the_clear_time_defaults_to_a_minute(tmp_path):
    assert parse(llamacpp("http://127.0.0.1:8100/ai/v1", tmp_path)).vddgfx_clear_s == 60
    data = llamacpp("http://127.0.0.1:8100/ai/v1", tmp_path, vddgfx_clear_s=120)
    assert parse(data).vddgfx_clear_s == 120


@pytest.mark.parametrize("value", [-1, 2001, True, 1000.0, "1000"])
def test_a_bad_limit_is_refused(tmp_path, value):
    with pytest.raises(ConfigError, match="max_vddgfx_mv"):
        parse(llamacpp("http://127.0.0.1:8100/ai/v1", tmp_path, max_vddgfx_mv=value))


def test_the_limit_is_only_read_with_llamacpp():
    data = config("http://127.0.0.1:8100/ai/v1")
    data["compute"]["max_vddgfx_mv"] = 1000
    with pytest.raises(ConfigError, match="max_vddgfx_mv"):
        parse(data)


def test_the_home_servers_configs_take_the_default():
    from test_worker_deploy import DEPLOY

    import tomllib

    for name in ("home-h2o", "home-pplx"):
        data = tomllib.loads((DEPLOY / f"{name}.toml").read_text())
        data["worker"]["token"] = "t"
        data["worker"].pop("token_file", None)
        assert parse(data).max_vddgfx_mv == 1000, name
