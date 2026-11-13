"""Score labelled pairs with one served judge, for a list of prompt variants.

    python3 ml/bakeoff/judge.py --service rr-qwen3-0.6b --split validation \
        --pairs <private>/pairs.jsonl --pairtexts <private>/pairtexts.json \
        --variants I1-L1-0,I2-L1-0,I2-L3-4 --out ml/out/bakeoff

A variant is <instruction>-<rung>-<shots>: an instruction id from common.py (ignored by bge),
a context rung from contexts.py (L0..L3), and 0 or 4 few-shot examples. Few-shot examples are
the titles of labelled validation pairs from *other* folds (5-fold, common.folds), so no pair
is ever judged with itself or its fold as an example; the test split takes its examples from
validation. Every pair is scored in both orders (A, B) and (B, A).

Writes <out>/scores/<service>/<variant>.<split>.json = {"scores": {pair_id: [p_ab, p_ba]},
"meta": {...}} (pair ids and probabilities only) and <out>/prompts/<service>/<variant>.<split>.json
with every instruction exactly as sent (few-shot ones include example titles; ml/out is
git-ignored). Needs the service running (ml/docker-compose.yml). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from common import (  # noqa: E402
    KEV_QUESTIONS,
    QWEN_INSTRUCTIONS,
    fewshot_ids,
    folds,
    kev_fewshot,
    load_pairs,
    qwen_fewshot,
)
from makhzan_ml.client import Client  # noqa: E402

TEXTS_FOR = {"rr-bge": "bge", "rr-qwen3-0.6b": "qwen3-rr", "rr-qwen3-4b": "qwen3-rr",
             "kev-4b": "kev"}  # fmt: skip


def instruction_for(service: str, iid: str, examples: list[tuple[str, str, int]]):
    if service == "rr-bge":
        return None
    if service == "kev-4b":
        q = KEV_QUESTIONS[iid]
        return kev_fewshot(q, examples) if examples else q
    text = QWEN_INSTRUCTIONS[iid]
    return qwen_fewshot(text, examples) if examples else text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--service", required=True, choices=sorted(TEXTS_FOR))
    ap.add_argument("--split", required=True, choices=["validation", "test"])
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--pairtexts", type=Path, required=True)
    ap.add_argument("--variants", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument(
        "--throughput-only",
        action="store_true",
        help="time the variants at --batch-size; write <out>/throughput/ only, no scores",
    )
    args = ap.parse_args()

    allpairs = load_pairs(args.pairs)
    validation = [p for p in allpairs if p["split"] == "validation"]
    pairs = [p for p in allpairs if p["split"] == args.split]
    texts = json.loads(args.pairtexts.read_text())[TEXTS_FOR[args.service]]
    fold_of = folds(validation)
    # Kev takes one state per request: batch_size is then the number in flight (use 8).
    bs = args.batch_size
    client = Client(args.service, batch_size=bs, concurrency=args.concurrency)

    for variant in args.variants.split(","):
        iid, rung, shots = variant.split("-")
        groups: dict[int | None, list[dict]] = {}
        for p in pairs:
            key = fold_of[p["pair_id"]] if (int(shots) and args.split == "validation") else None
            groups.setdefault(key, []).append(p)
        scores: dict[str, list[float]] = {}
        prompts: dict[str, object] = {}
        example_ids: dict[str, list[str]] = {}
        started = time.time()
        n_scored = 0
        for key, members in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
            examples = []
            if int(shots):
                ids = fewshot_ids(validation, key)
                examples = [(*texts[pid]["L0"], y) for pid, y in ids]
                example_ids[str(key)] = [pid for pid, _ in ids]
            instruction = instruction_for(args.service, iid, examples)
            prompts[str(key)] = instruction
            batch = []
            for p in members:
                a, b = texts[p["pair_id"]][rung]
                batch += [(a, b), (b, a)]
            out = (
                client.score(batch, instruction) if instruction is not None else client.score(batch)
            )
            n_scored += len(batch)
            for i, p in enumerate(members):
                scores[p["pair_id"]] = [out[2 * i], out[2 * i + 1]]
        seconds = time.time() - started
        meta = {
            "service": args.service,
            "variant": variant,
            "split": args.split,
            "pairs_scored": n_scored,
            "seconds": round(seconds, 2),
            "pairs_per_s": round(n_scored / seconds, 2),
            "batch_size": bs,
            "concurrency": args.concurrency,
            "fewshot_example_pair_ids": example_ids,
        }
        if args.throughput_only:
            d = args.out / "throughput" / args.service
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{variant}.b{bs}.json").write_text(json.dumps(meta, indent=1))
            print(json.dumps({k: meta[k] for k in ("variant", "batch_size", "pairs_per_s")}))
            continue
        d = args.out / "scores" / args.service
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{variant}.{args.split}.json").write_text(
            json.dumps({"scores": scores, "meta": meta})
        )
        pd = args.out / "prompts" / args.service
        pd.mkdir(parents=True, exist_ok=True)
        (pd / f"{variant}.{args.split}.json").write_text(
            json.dumps(prompts, indent=1, ensure_ascii=False)
        )
        print(json.dumps({k: meta[k] for k in ("variant", "split", "seconds", "pairs_per_s")}))


if __name__ == "__main__":
    main()
