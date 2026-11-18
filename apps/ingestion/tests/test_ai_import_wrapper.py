"""`./makhzan ai import DIR` (scripts/lib/ai_import.sh), run in a scratch copy
with fake `docker`, `ssh` and `scp` on PATH that only log their arguments.

On the server the files go into a fresh folder in the worker container,
removed afterwards; from a laptop they are copied to a fresh folder on the
server first, so a same-named server path is never read. A folder with no
scores files is refused before anything is touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

FAKE = """#!/usr/bin/env bash
printf '%s\\n' "$(basename "$0") $*" >> "$FAKE_LOG"
case "$*" in
  *"mktemp -d /tmp/ai-import."*) echo /tmp/ai-import.T3ST ;;
  *"mktemp -d /tmp/makhzan-ai-import."*) echo /tmp/makhzan-ai-import.R3MT ;;
  *"worker.ai import"* | *"./makhzan ai import"*) [ -z "${FAKE_FAIL_IMPORT:-}" ] || exit 3 ;;
esac
exit 0
"""


def _tree(tmp_path: Path, *, server: bool) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts" / "lib").mkdir(parents=True)
    shutil.copy(ROOT / "makhzan", repo / "makhzan")
    for name in ("ops.sh", "ai_import.sh"):
        shutil.copy(ROOT / "scripts" / "lib" / name, repo / "scripts" / "lib" / name)
    if server:
        (repo / ".env.prod").write_text("CRAWL_ENABLED=true\n")
    else:
        (repo / ".env.local").write_text("DEPLOY_HOST=server.example\nDEPLOY_USER=op\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("docker", "ssh", "scp"):
        path = bin_dir / tool
        path.write_text(FAKE)
        path.chmod(0o755)
    return repo


def _run(tmp_path: Path, repo: Path, args: list[str], cwd: Path, **env) -> tuple[int, list[str]]:
    log = tmp_path / "calls.log"
    result = subprocess.run(
        [str(repo / "makhzan"), *args],
        cwd=cwd,
        env={
            **os.environ,
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "FAKE_LOG": str(log),
            **env,
        },
        capture_output=True,
        text=True,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result.returncode, calls


def _scores(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scores-kev.jsonl").write_text("{}\n")
    (folder / "scores-pplx.jsonl").write_text("{}\n")
    (folder / "notes.txt").write_text("not copied\n")
    return folder


@pytest.mark.parametrize("server", [True, False])
def test_an_empty_folder_is_refused_before_anything_is_touched(tmp_path, server):
    repo = _tree(tmp_path, server=server)
    (tmp_path / "empty").mkdir()
    code, calls = _run(tmp_path, repo, ["ai", "import", "empty"], cwd=tmp_path)
    assert code != 0
    assert calls == []


def test_on_the_server_files_go_to_a_fresh_container_folder_removed_after(tmp_path):
    repo = _tree(tmp_path, server=True)
    _scores(tmp_path / "caller" / "run")
    code, calls = _run(
        tmp_path, repo, ["ai", "import", "run", "--dry-run"], cwd=tmp_path / "caller"
    )
    assert code == 0
    assert any("exec -T ingestion mktemp -d /tmp/ai-import." in c for c in calls)
    copied = [c for c in calls if " cp " in c]
    # Resolved against where the operator ran it, and only the scores files.
    assert len(copied) == 2
    assert all(str(tmp_path / "caller" / "run") in c for c in copied)
    assert all("ingestion:/tmp/ai-import.T3ST/scores-" in c for c in copied)
    assert any("python -m worker.ai import /tmp/ai-import.T3ST --dry-run" in c for c in calls)
    assert calls[-1].endswith("exec -T ingestion rm -rf /tmp/ai-import.T3ST")


def test_the_container_folder_is_removed_when_the_import_fails(tmp_path):
    repo = _tree(tmp_path, server=True)
    _scores(tmp_path / "run")
    code, calls = _run(
        tmp_path, repo, ["ai", "import", str(tmp_path / "run")], cwd=tmp_path, FAKE_FAIL_IMPORT="1"
    )
    assert code == 3
    assert calls[-1].endswith("rm -rf /tmp/ai-import.T3ST")


def test_the_server_folder_is_removed_when_the_import_fails(tmp_path):
    repo = _tree(tmp_path, server=False)
    _scores(tmp_path / "run")
    code, calls = _run(
        tmp_path, repo, ["ai", "import", str(tmp_path / "run")], cwd=tmp_path, FAKE_FAIL_IMPORT="1"
    )
    assert code == 3
    assert calls[-1] == "ssh op@server.example rm -rf /tmp/makhzan-ai-import.R3MT"


def test_from_a_laptop_files_are_copied_to_the_server_first(tmp_path):
    repo = _tree(tmp_path, server=False)
    _scores(tmp_path / "caller" / "run")
    code, calls = _run(tmp_path, repo, ["ai", "import", "run", "--verify"], cwd=tmp_path / "caller")
    assert code == 0
    assert calls[0] == "ssh op@server.example mktemp -d /tmp/makhzan-ai-import.XXXXXX"
    scp = [c for c in calls if c.startswith("scp ")]
    assert len(scp) == 1
    assert str(tmp_path / "caller" / "run" / "scores-kev.jsonl") in scp[0]
    assert "notes.txt" not in scp[0]
    assert scp[0].endswith("op@server.example:/tmp/makhzan-ai-import.R3MT/")
    run = [c for c in calls if c.startswith("ssh -t ")]
    assert len(run) == 1
    # The server imports the copied folder, never a path named like the laptop's.
    assert "./makhzan ai import /tmp/makhzan-ai-import.R3MT --verify" in run[0]
    assert "caller/run" not in run[0]
    assert calls[-1] == "ssh op@server.example rm -rf /tmp/makhzan-ai-import.R3MT"
