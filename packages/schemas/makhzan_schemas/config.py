"""Where makhzan's supplier configuration lives.

Two kinds of file are configuration rather than code: the list of sources to
crawl (`sources.toml`) and the per-supplier category crosswalks
(`crosswalks/*.toml`). Both describe *which* shops makhzan aggregates and how
their catalogues map onto ours, and neither belongs to the platform itself — a
fork of the code gets a directory with no suppliers, not someone else's.

Each location is an environment variable, because the real configuration lives
outside this repository, in a private checkout. Unset, they fall back to the
repository's own `config/`, which holds only `sources.example.toml`: a clone
runs, with the fixture source and no crosswalks, rather than failing.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The repository's `config/` directory. packages/schemas/makhzan_schemas/config.py
#: is three levels below the root; the images preserve that layout under /workspace.
REPO_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def crosswalk_dir() -> Path:
    """Directory of crosswalk files, one `<name>.toml` per crosswalk."""
    return Path(os.environ.get("MAKHZAN_CROSSWALKS") or REPO_CONFIG_DIR / "crosswalks")


def sources_file() -> Path:
    """The file the Source table is seeded from."""
    return Path(os.environ.get("MAKHZAN_SOURCES") or REPO_CONFIG_DIR / "sources.example.toml")
