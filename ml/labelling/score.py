"""Score shortlist pairs with Kev-4B, title only, behind today's vetoes (the Phase D finalist).

    python3 ml/labelling/score.py --catalogue <work>/catalogue.jsonl \
        --vetoes <work>/vetoes.jsonl --out <work>/kev [--sample N] [--reuse <old scores>]

Settings are the bake-off's frozen `combination` (ml/out/bakeoff/frozen.json): kev-4b, variant
I2-L0-0 (`common.KEV_QUESTIONS["I2"]`, the title cleaned as contexts.py's L0, no examples), raw
P(yes); a vetoed pair scores 0 and is never sent. The bake-off scored both orders and kept the
minimum. To save half the GPU time without changing any decision, this scores in two passes:

1. `ab`: every non-vetoed pair in (a, b) order (a < b by listing id).
2. `ba`: only pairs whose `ab` score is at least --second-order-from (default 0.05, below the
   frozen best-F1 threshold 0.0772). For them the score is min(ab, ba), exactly the bake-off's.
   For the rest, min(ab, ba) <= ab < 0.05, so they sit below every threshold either way; their
   recorded score is ab, an upper bound on the bake-off's number (`orders` = 1).

Results are appended per chunk to <out>/ab.jsonl and <out>/ba.jsonl ({key: p}), so a run can be
stopped and resumed. --reuse takes earlier ab/ba files keyed the same way and keeps any score
whose two titles are unchanged (the key includes a hash of both titles).

`--pool vetoed --per-group N` scores vetoed pairs instead, to check the vetoes themselves: a
seeded simple random sample of N pairs (all if fewer) from each veto group (only-values,
only-price, only-form, multiple). The sample is written to <out>/frame.jsonl (ids and group)
and the group sizes to meta.json, so sample.py can weight it. Standard library.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "bakeoff"))
from common import KEV_QUESTIONS, SEED  # noqa: E402
from contexts import clean  # noqa: E402
from makhzan_ml.client import Client  # noqa: E402

QUESTION = KEV_QUESTIONS["I2"]
CHUNK = 2000
VETOES = ("values", "price", "form")


def veto_group(p: dict) -> str | None:
    """only-<veto> when exactly one of values/price/form fired, `multiple` for more."""
    fired = [k for k in VETOES if p["veto"][k]]
    if not fired:
        return None
    return f"only-{fired[0]}" if len(fired) == 1 else "multiple"


def pair_key(a: str, b: str, ta: str, tb: str) -> str:
    h = hashlib.sha1(f"{ta}\x00{tb}".encode()).hexdigest()[:12]
    return f"{a}|{b}|{h}"


def load_done(path: Path) -> dict[str, float]:
    done: dict[str, float] = {}
    if path.exists():
        for line in path.open():
            done.update(json.loads(line))
    return done


def run(client: Client, todo: list[tuple[str, str, str]], path: Path, label: str) -> float:
    """todo: (key, text_1, text_2). Returns seconds spent."""
    started = time.time()
    for i in range(0, len(todo), CHUNK):
        chunk = todo[i : i + CHUNK]
        t = time.time()
        out = client.score([(x, y) for _, x, y in chunk], QUESTION)
        with path.open("a") as f:
            f.write(json.dumps({k: round(p, 6) for (k, _, _), p in zip(chunk, out, strict=True)}))
            f.write("\n")
        rate = len(chunk) / (time.time() - t)
        left = (len(todo) - i - len(chunk)) / rate / 3600
        print(f"{label} {i + len(chunk)}/{len(todo)} {rate:.1f} pairs/s, ~{left:.2f} h left",
              flush=True)  # fmt: skip
    return time.time() - started


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--vetoes", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sample", type=int, default=0, help="score a seeded uniform sample only")
    ap.add_argument("--second-order-from", type=float, default=0.05)
    ap.add_argument("--in-flight", type=int, default=8)
    ap.add_argument("--reuse", type=Path, help="a directory holding earlier ab.jsonl / ba.jsonl")
    ap.add_argument("--only", choices=["ab", "ba"], help="run one pass only")
    ap.add_argument("--pool", choices=["open", "vetoed"], default="open")
    ap.add_argument("--per-group", type=int, default=2000, help="--pool vetoed: pairs a group")
    args = ap.parse_args()

    titles = {}
    for line in args.catalogue.open():
        r = json.loads(line)
        titles[r["id"]] = clean(r["title_en"] or r["title_ar"])
    pairs = [json.loads(line) for line in args.vetoes.open()]
    args.out.mkdir(parents=True, exist_ok=True)
    group_sizes: dict[str, int] = {}
    if args.pool == "vetoed":
        groups: dict[str, list[dict]] = {}
        for p in pairs:
            if p["any_veto"] and not p["veto"]["same_shop"]:
                groups.setdefault(veto_group(p), []).append(p)
        open_pairs = []
        with (args.out / "frame.jsonl").open("w") as frame:
            for name in sorted(groups):
                members = sorted(groups[name], key=lambda p: (p["a"], p["b"]))
                group_sizes[name] = len(members)
                rng = random.Random(f"{SEED}:{name}")
                for p in rng.sample(members, min(args.per_group, len(members))):
                    open_pairs.append(p)
                    frame.write(json.dumps({"a": p["a"], "b": p["b"], "group": name}) + "\n")
    else:
        open_pairs = [p for p in pairs if not p["any_veto"]]
    if args.sample:
        open_pairs = random.Random(SEED).sample(open_pairs, min(args.sample, len(open_pairs)))
    client = Client("kev-4b", batch_size=args.in_flight)
    meta_path = args.out / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.update(
        service="kev-4b", variant="I2-L0-0", question=QUESTION, pairs=len(pairs),
        vetoed=len(pairs) - sum(1 for p in pairs if not p["any_veto"]),
        open_pairs_scored=len(open_pairs), sample=args.sample, pool=args.pool,
        veto_group_sizes=group_sizes, per_group=args.per_group if group_sizes else None,
        second_order_from=args.second_order_from, in_flight=args.in_flight,
    )  # fmt: skip

    keyed = [
        (pair_key(p["a"], p["b"], titles[p["a"]], titles[p["b"]]), titles[p["a"]], titles[p["b"]])
        for p in open_pairs
    ]
    for order in ("ab", "ba"):
        if args.only and args.only != order:
            continue
        path = args.out / f"{order}.jsonl"
        done = load_done(path)
        reused = 0
        if args.reuse:
            old = load_done(args.reuse / f"{order}.jsonl")
            fresh = {k: old[k] for k, _, _ in keyed if k in old and k not in done}
            if fresh:
                with path.open("a") as f:
                    f.write(json.dumps(fresh) + "\n")
                done.update(fresh)
                reused = len(fresh)
        if order == "ab":
            todo = [(k, x, y) for k, x, y in keyed if k not in done]
        else:
            ab = load_done(args.out / "ab.jsonl")
            todo = [
                (k, y, x)
                for k, x, y in keyed
                if k not in done and ab.get(k, 0.0) >= args.second_order_from
            ]
        seconds = run(client, todo, path, order)
        meta[f"{order}_reused"] = meta.get(f"{order}_reused", 0) + reused
        meta[f"{order}_scored"] = meta.get(f"{order}_scored", 0) + len(todo)
        meta[f"{order}_seconds"] = round(meta.get(f"{order}_seconds", 0) + seconds, 1)
        meta_path.write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
