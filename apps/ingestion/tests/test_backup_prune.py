"""Backup retention (scripts/lib/prune.sh), run in a scratch directory.

A dump holds what /privacy says is erased (a report's email after 90 days,
an address hash after 24 hours), and the page promises a backup keeps it at
most 30 days more. So a regular backup older than 30 days goes whenever a
backup is taken, but for the newest, so a server is never left with none.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PRUNE = ROOT / "scripts" / "lib" / "prune.sh"
DAY = 86_400

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _backups(tmp_path: Path, ages: dict[str, float]) -> Path:
    folder = tmp_path / "backups"
    folder.mkdir()
    now = time.time()
    for name, days in ages.items():
        path = folder / name
        path.write_bytes(b"dump")
        os.utime(path, (now - days * DAY, now - days * DAY))
    return folder


def _prune(tmp_path: Path, env: dict[str, str] | None = None) -> set[str]:
    subprocess.run(
        ["bash", "-c", f'. "{PRUNE}" && prune_backups'],
        cwd=tmp_path,
        check=True,
        env={**os.environ, **(env or {})},
    )
    return {p.name for p in (tmp_path / "backups").iterdir()}


def test_a_regular_backup_older_than_30_days_goes(tmp_path):
    _backups(
        tmp_path,
        {
            "makhzan-new.dump": 1,
            "makhzan-29d.dump": 29,
            "makhzan-31d.dump": 31,
            "makhzan-old.sql.gz": 90,
        },
    )
    assert _prune(tmp_path) == {"makhzan-new.dump", "makhzan-29d.dump"}


def test_the_newest_backup_stays_however_old(tmp_path):
    _backups(tmp_path, {"makhzan-a.dump": 40, "makhzan-b.dump": 60, "makhzan-c.sql.gz": 70})
    assert _prune(tmp_path) == {"makhzan-a.dump"}


def test_at_most_14_recent_ones(tmp_path):
    _backups(tmp_path, {f"makhzan-{i:02d}.dump": i for i in range(1, 18)})
    kept = _prune(tmp_path)
    assert kept == {f"makhzan-{i:02d}.dump" for i in range(1, 15)}


def test_safety_copies_keep_their_own_rule(tmp_path):
    _backups(
        tmp_path,
        {
            "makhzan-new.dump": 1,
            "makhzan-a-pre-restore.dump": 2,
            "makhzan-b-pre-restore.dump": 9,
            "makhzan-c-pre-restore.dump": 10,
            "makhzan-d-pre-restore.dump": 12,
        },
    )
    # A week of them, never fewer than 3: d is past both.
    assert _prune(tmp_path) == {
        "makhzan-new.dump",
        "makhzan-a-pre-restore.dump",
        "makhzan-b-pre-restore.dump",
        "makhzan-c-pre-restore.dump",
    }


def test_the_file_being_restored_is_never_pruned(tmp_path):
    folder = _backups(tmp_path, {"makhzan-new.dump": 1, "makhzan-keep.dump": 45})
    keep = str((folder / "makhzan-keep.dump").resolve())
    assert _prune(tmp_path, {"MAKHZAN_KEEP_FILE": keep}) == {
        "makhzan-new.dump",
        "makhzan-keep.dump",
    }
