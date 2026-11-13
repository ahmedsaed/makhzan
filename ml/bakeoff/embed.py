"""Embed every catalogue listing with one served embedder, at one or more context rungs.

    <python with numpy> ml/bakeoff/embed.py --service emb-harrier --rungs L0,L1 \
        --texts <private>/texts.jsonl --work <private>/emb --out ml/out/bakeoff

Every text is embedded as a query with makhzan_ml.client.SAME_PRODUCT as the instruction
(title against title is symmetric, so both sides carry it, as each model card asks for
symmetric tasks). Vectors go to <work>/<service>.<rung>.npy (float16, unit length, rows in
<work>/ids.json order); timing and GPU memory to <out>/embed/<service>.<rung>.json.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from makhzan_ml.client import SAME_PRODUCT, Client  # noqa: E402


def gpu_used_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        return int(out.split()[0])
    except (OSError, subprocess.CalledProcessError, ValueError, IndexError):
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--service", required=True)
    ap.add_argument("--rungs", default="L0,L1")
    ap.add_argument("--texts", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    rows = [json.loads(line) for line in args.texts.open()]
    args.work.mkdir(parents=True, exist_ok=True)
    (args.work / "ids.json").write_text(json.dumps([r["id"] for r in rows]))
    client = Client(args.service, batch_size=args.batch_size, concurrency=args.concurrency)
    for rung in args.rungs.split(","):
        texts = [r[rung] for r in rows]
        started = time.time()
        vecs = client.embed(texts, instruction=SAME_PRODUCT)
        seconds = time.time() - started
        arr = np.asarray(vecs, dtype=np.float32)
        np.save(args.work / f"{args.service}.{rung}.npy", arr.astype(np.float16))
        meta = {
            "service": args.service,
            "rung": rung,
            "texts": len(texts),
            "dims": arr.shape[1],
            "seconds": round(seconds, 1),
            "texts_per_s": round(len(texts) / seconds, 1),
            "gpu_used_mib_after": gpu_used_mib(),
            "batch_size": args.batch_size,
            "concurrency": args.concurrency,
            "instruction": SAME_PRODUCT,
        }
        d = args.out / "embed"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{args.service}.{rung}.json").write_text(json.dumps(meta, indent=1))
        print(json.dumps(meta))


if __name__ == "__main__":
    main()
