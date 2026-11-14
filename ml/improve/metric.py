"""The one metric every improvement experiment is scored on, and the helpers to compute it.

The metric: how many cross-shop matches a rule could merge automatically at a *proven*
precision of at least 0.98, estimated for the real shortlist population (Phase E, 231,444
pairs). A rule is a function pair -> accept. On the labelled pairs (unsure excluded):

- **cells.** Every labelled pair was drawn by simple random sampling within one cell: a
  stratum (kev_positive, borderline, confident_no) or, for the two-phase veto strata, a veto
  group x Kev band. N_c, the cell's population size, is the sum of 1/pi over its sampled pairs.
- **estimate.** Accepted true matches in the population = sum over accepted `same` pairs of
  1/pi, rescaled per cell for the unsure pairs dropped (N_c / decided_c).
- **bound.** Within one cell the plain one-sided 95% Clopper-Pearson lower bound on the raw
  counts applies. Across cells (a rule that accepts pairs outside kev_positive) the bound is
  1 - sum_c w_c * UCB_c / sum_c w_c, w_c the estimated accepted pairs in cell c and UCB_c the
  one-sided Clopper-Pearson upper bound on its error rate at alpha_c = 0.05 * w_c / sum w
  (Bonferroni, weight-proportional). For a rule inside one cell it is exactly the plain bound.
  It treats w_c as known, so it is approximate when several cells carry weight.
- **certified** when the bound is >= 0.98; the metric is then the estimate, else 0.

Standard library only.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bakeoff"))
from common import clopper_pearson_lower  # noqa: E402

GATE = 0.98
ALPHA = 0.05  # one-sided


def cp_lower(k: int, n: int, alpha: float = ALPHA) -> float:
    """One-sided (1 - alpha) Clopper-Pearson lower bound."""
    return clopper_pearson_lower(k, n, alpha=2 * alpha) if n else float("nan")


def load_pairs(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open()]


def cell_sizes(pairs: Iterable[dict]) -> tuple[dict[str, float], dict[str, int]]:
    """Population size and decided sample size of every cell."""
    size: dict[str, float] = defaultdict(float)
    decided: dict[str, int] = defaultdict(int)
    for p in pairs:
        size[p["cell"]] += 1 / p["inclusion_prob"]
        decided[p["cell"]] += p["y"] is not None
    return dict(size), dict(decided)


def evaluate(pairs: list[dict], accept: Callable[[dict], bool], subset=None) -> dict:
    """Score one rule. `subset` (pair ids) restricts the evaluation, e.g. to a fold; the cell
    sizes always come from every pair so the estimate stays a population estimate (a fold's
    estimate is then the fold's share, rescaled by its decided count)."""
    size, _ = cell_sizes(pairs)
    use = [p for p in pairs if subset is None or p["pair_id"] in subset]
    decided: dict[str, int] = defaultdict(int)
    for p in use:
        decided[p["cell"]] += p["y"] is not None
    acc: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # cell -> [same, errors]
    for p in use:
        if p["y"] is None or not accept(p):
            continue
        acc[p["cell"]][0 if p["y"] else 1] += 1
    w = {c: size[c] * (s + e) / decided[c] for c, (s, e) in acc.items()}
    matches = sum(size[c] * s / decided[c] for c, (s, _) in acc.items())
    accepted = sum(w.values())
    same = sum(s for s, _ in acc.values())
    errors = sum(e for _, e in acc.values())
    if accepted:
        bound = 1.0
        for c, (s, e) in acc.items():
            share = w[c] / accepted
            bound -= share * (1 - cp_lower(s, s + e, ALPHA * share))
    else:
        bound = float("nan")
    kp = acc.get("kev_positive", [0, 0])
    return {
        "used": same + errors,
        "same": same,
        "errors": errors,
        "precision_raw": same / (same + errors) if same + errors else float("nan"),
        "precision_weighted": matches / accepted if accepted else float("nan"),
        "bound": bound,
        "kev_positive": {"same": kp[0], "errors": kp[1], "cp_lower": cp_lower(kp[0], sum(kp))},
        "cells": {c: {"same": s, "errors": e} for c, (s, e) in sorted(acc.items())},
        "est_matches": round(matches),
        "est_accepted": round(accepted),
        "certified": bool(accepted) and bound >= GATE,
        "metric": round(matches) if accepted and bound >= GATE else 0,
    }


def sweep(
    pairs: list[dict],
    accept_at: Callable[[float], Callable[[dict], bool]],
    thresholds: Iterable[float],
    subset=None,
) -> tuple[float | None, dict, list[dict]]:
    """Evaluate a family of rules; return the threshold with the largest certified estimate
    (ties: the higher threshold), its result, and every row."""
    rows = []
    best_t, best = None, None
    for t in thresholds:
        r = evaluate(pairs, accept_at(t), subset)
        r["threshold"] = t
        rows.append(r)
        if r["certified"] and (best is None or r["metric"] >= best["metric"]):
            best_t, best = t, r
    if best is None:  # nothing certified: report the threshold with the highest bound
        best = max(rows, key=lambda r: r["bound"] if r["bound"] == r["bound"] else -1)
        best_t = best["threshold"]
    return best_t, best, rows


THRESHOLDS = [round(0.5 + i * 0.005, 3) for i in range(100)] + [0.9975, 0.999]


def fmt(r: dict) -> str:
    return (
        f"t={r.get('threshold')} used={r['used']} same={r['same']} err={r['errors']} "
        f"P={r['precision_raw']:.3f} Pw={r['precision_weighted']:.3f} bound={r['bound']:.4f} "
        f"kpCP={r['kev_positive']['cp_lower']:.4f} est={r['est_matches']} metric={r['metric']}"
    )
