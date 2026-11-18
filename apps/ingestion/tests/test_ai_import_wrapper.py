"""`./makhzan ai import DIR` (scripts/lib/ai_import.sh), run in a scratch copy
with fake `docker`, `ssh` and `scp` on PATH that only log their arguments.

On the server the files are streamed into a fresh folder in the worker
container, as its own user, and removed afterwards; from a laptop they are
copied to a fresh folder on the server first, so a same-named server path is
never read. A folder with no scores files is refused before anything is
touched. Whatever fails, the temporary folder is removed and the failing
step's exit code is returned; a failing clean-up only warns.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

# FAKE_FAIL holds "pattern=code" entries separated by ";": a call whose
# "tool args" line contains the pattern exits with that code.
FAKE = """#!/usr/bin/env bash
line="$(basename "$0") $*"
printf '%s\\n' "$line" >> "$FAKE_LOG"
IFS=';' read -ra rules <<<"${FAKE_FAIL:-}"
for rule in "${rules[@]}"; do
  [ -n "$rule" ] || continue
  case "$line" in *"${rule%=*}"*) exit "${rule##*=}" ;; esac
done
case "$*" in
  *"mktemp -d /tmp/ai-import."*) echo /tmp/ai-import.T3ST ;;
  *"mktemp -d /tmp/makhzan-ai-import."*) echo /tmp/makhzan-ai-import.R3MT ;;
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


def _run(
    tmp_path: Path, repo: Path, args: list[str], cwd: Path, fail: str = ""
) -> tuple[int, list[str], str]:
    log = tmp_path / "calls.log"
    result = subprocess.run(
        [str(repo / "makhzan"), *args],
        cwd=cwd,
        env={
            **os.environ,
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
            "FAKE_LOG": str(log),
            "FAKE_FAIL": fail,
        },
        capture_output=True,
        text=True,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result.returncode, calls, result.stderr


def _scores(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "scores-kev.jsonl").write_text("{}\n")
    (folder / "scores-pplx.jsonl").write_text("{}\n")
    (folder / "notes.txt").write_text("not copied\n")
    return folder


CONTAINER_RM = "exec -T ingestion rm -rf /tmp/ai-import.T3ST"
SERVER_RM = "ssh op@server.example rm -rf /tmp/makhzan-ai-import.R3MT"


@pytest.mark.parametrize("server", [True, False])
def test_an_empty_folder_is_refused_before_anything_is_touched(tmp_path, server):
    repo = _tree(tmp_path, server=server)
    (tmp_path / "empty").mkdir()
    code, calls, _ = _run(tmp_path, repo, ["ai", "import", "empty"], cwd=tmp_path)
    assert code != 0
    assert calls == []


def test_on_the_server_files_are_streamed_to_a_fresh_container_folder(tmp_path):
    repo = _tree(tmp_path, server=True)
    _scores(tmp_path / "caller" / "run")
    code, calls, _ = _run(
        tmp_path, repo, ["ai", "import", "run", "--dry-run"], cwd=tmp_path / "caller"
    )
    assert code == 0
    assert any("exec -T ingestion mktemp -d /tmp/ai-import." in c for c in calls)
    # Written by the container's own user (no `cp`, which writes as root),
    # and only the scores files.
    assert not any(" cp " in c for c in calls)
    written = [c for c in calls if "sh -c cat > " in c]
    assert [c.rsplit(" ", 1)[1] for c in written] == [
        "/tmp/ai-import.T3ST/scores-kev.jsonl",
        "/tmp/ai-import.T3ST/scores-pplx.jsonl",
    ]
    assert not any(" -u root" in c for c in calls)
    assert any("python -m worker.ai import /tmp/ai-import.T3ST --dry-run" in c for c in calls)
    assert calls[-1].endswith(CONTAINER_RM)
    assert sum(CONTAINER_RM in c for c in calls) == 1


def test_a_relative_folder_is_read_where_the_operator_typed_it(tmp_path):
    repo = _tree(tmp_path, server=True)
    (tmp_path / "caller" / "run").mkdir(parents=True)  # empty where the operator is
    _scores(repo / "run")  # a same-named folder beside the script is not read
    code, calls, _ = _run(tmp_path, repo, ["ai", "import", "run"], cwd=tmp_path / "caller")
    assert code != 0 and calls == []


def test_the_container_folder_is_removed_when_the_import_fails(tmp_path):
    repo = _tree(tmp_path, server=True)
    _scores(tmp_path / "run")
    code, calls, _ = _run(
        tmp_path,
        repo,
        ["ai", "import", str(tmp_path / "run")],
        cwd=tmp_path,
        fail="worker.ai import=3",
    )
    assert code == 3
    assert calls[-1].endswith(CONTAINER_RM)


def test_the_container_folder_is_removed_when_a_copy_fails(tmp_path):
    repo = _tree(tmp_path, server=True)
    _scores(tmp_path / "run")
    code, calls, _ = _run(
        tmp_path,
        repo,
        ["ai", "import", str(tmp_path / "run")],
        cwd=tmp_path,
        fail="scores-kev.jsonl=4",
    )
    assert code == 4
    assert not any("python -m worker.ai import" in c for c in calls)
    assert calls[-1].endswith(CONTAINER_RM)


@pytest.mark.parametrize("import_fails, expected", [(False, 0), (True, 3)])
def test_a_failing_container_clean_up_warns_and_keeps_the_exit_code(
    tmp_path, import_fails, expected
):
    repo = _tree(tmp_path, server=True)
    _scores(tmp_path / "run")
    fail = "rm -rf=7" + (";worker.ai import=3" if import_fails else "")
    code, calls, err = _run(
        tmp_path, repo, ["ai", "import", str(tmp_path / "run")], cwd=tmp_path, fail=fail
    )
    assert code == expected
    assert "warning: could not remove /tmp/ai-import.T3ST" in err


def test_from_a_laptop_files_are_copied_to_the_server_first(tmp_path):
    repo = _tree(tmp_path, server=False)
    _scores(tmp_path / "caller" / "run")
    code, calls, _ = _run(
        tmp_path, repo, ["ai", "import", "run", "--verify"], cwd=tmp_path / "caller"
    )
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
    assert calls[-1] == SERVER_RM
    assert calls.count(SERVER_RM) == 1


def test_the_server_folder_is_removed_when_the_import_fails(tmp_path):
    repo = _tree(tmp_path, server=False)
    _scores(tmp_path / "run")
    code, calls, _ = _run(
        tmp_path,
        repo,
        ["ai", "import", str(tmp_path / "run")],
        cwd=tmp_path,
        fail="./makhzan ai import=3",
    )
    assert code == 3
    assert calls[-1] == SERVER_RM


def test_the_server_folder_is_removed_when_the_copy_fails(tmp_path):
    repo = _tree(tmp_path, server=False)
    _scores(tmp_path / "run")
    code, calls, _ = _run(
        tmp_path, repo, ["ai", "import", str(tmp_path / "run")], cwd=tmp_path, fail="scp =5"
    )
    assert code == 5
    assert not any(c.startswith("ssh -t ") for c in calls)
    assert calls[-1] == SERVER_RM


@pytest.mark.parametrize("import_fails, expected", [(False, 0), (True, 3)])
def test_a_failing_server_clean_up_warns_and_keeps_the_exit_code(tmp_path, import_fails, expected):
    repo = _tree(tmp_path, server=False)
    _scores(tmp_path / "run")
    fail = "rm -rf=7" + (";./makhzan ai import=3" if import_fails else "")
    code, _, err = _run(
        tmp_path, repo, ["ai", "import", str(tmp_path / "run")], cwd=tmp_path, fail=fail
    )
    assert code == expected
    assert "warning: could not remove op@server.example:/tmp/makhzan-ai-import.R3MT" in err
