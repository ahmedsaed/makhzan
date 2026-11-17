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
