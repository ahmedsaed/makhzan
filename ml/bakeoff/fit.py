"""Cut each labelled pair's rung texts to a model's documented length, and count the cuts.

Runs inside the vLLM image, which has transformers, with the weights cache mounted (offline):

    docker run --rm --user "$(id -u):$(id -g)" --entrypoint python3 -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 \
      -v "$PWD/ml/.cache/huggingface:/hf:z" -v "$PWD/ml:/ml:ro" \
      -v <private>:/work:z -v "$PWD/ml/out/bakeoff:/out:z" vllm/vllm-openai:v0.32.0 \
      /ml/bakeoff/fit.py --texts /work/texts.jsonl --pairs /work/pairs.jsonl \
      --out-texts /work/pairtexts.json --out-stats /out/truncation.json

Budgets (tokens for the two listings together; the rest of the limit is left for the template,
the instruction and few-shot examples):

- bge-reranker-v2-m3: 508 = the card's max_length 512 less its 4 special tokens.
- Qwen3-Reranker 0.6B / 4B: 3,328 = 4,096 less 768. The card's context is 32k; the bake-off
  serves 4,096 (the stock compose file serves 2,048, raised by an override for this run),
  which the longest labelled pair (about 2,600 tokens with full descriptions) fits.
- Kev-4B: 7,424 = Kev's validated 8,192 less 768.

A pair over budget is cut from the end of each text, so the description goes first, then the
spec table, then the structured fields; the title survives. Each side gets half, and a short
side gives what it does not use to the other.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from transformers import AutoTokenizer

MODELS = {
    "bge": ("BAAI/bge-reranker-v2-m3", 508),
    "qwen3-rr": ("Qwen/Qwen3-Reranker-0.6B", 3328),  # the 4B shares the tokenizer
    "kev": ("Qwen/Qwen3.5-4B-Base", 7424),
}
RUNGS = ("L0", "L1", "L2", "L3")


def fit(tok, a: str, b: str, budget: int) -> tuple[str, str, bool, int]:
    ia = tok(a, add_special_tokens=False)["input_ids"]
    ib = tok(b, add_special_tokens=False)["input_ids"]
    total = len(ia) + len(ib)
    if total <= budget:
        return a, b, False, total
    half = budget // 2
    if len(ia) <= half:
        cap_a, cap_b = len(ia), budget - len(ia)
    elif len(ib) <= half:
        cap_a, cap_b = budget - len(ib), len(ib)
    else:
        cap_a, cap_b = half, budget - half
    a2 = tok.decode(ia[:cap_a]) if len(ia) > cap_a else a
    b2 = tok.decode(ib[:cap_b]) if len(ib) > cap_b else b
    return a2, b2, True, total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--texts", type=Path, required=True)
    ap.add_argument("--pairs", type=Path, required=True)
    ap.add_argument("--out-texts", type=Path, required=True)
    ap.add_argument("--out-stats", type=Path, required=True)
    args = ap.parse_args()

    pairs = [json.loads(line) for line in args.pairs.open()]
    need = {p[s]["listing_id"] for p in pairs for s in ("a", "b")}
    texts = {}
    for line in args.texts.open():
        r = json.loads(line)
        if r["id"] in need:
            texts[r["id"]] = r

    out: dict = {}
    stats: dict = {}
    for name, (hf_id, budget) in MODELS.items():
        tok = AutoTokenizer.from_pretrained(hf_id)
        out[name] = {}
        cut = defaultdict(lambda: defaultdict(int))
        tokens = defaultdict(lambda: defaultdict(list))
        for p in pairs:
            ta, tb = texts[p["a"]["listing_id"]], texts[p["b"]["listing_id"]]
            row = {}
            for rung in RUNGS:
                a, b, was_cut, n = fit(tok, ta[rung], tb[rung], budget)
                row[rung] = [a, b]
                cut[p["split"]][rung] += was_cut
                tokens[p["split"]][rung].append(n)
            out[name][p["pair_id"]] = row
        stats[name] = {
            "hf_id": hf_id,
            "budget_tokens": budget,
            "truncated_pairs": cut,
            "pair_tokens": {
                split: {
                    rung: {
                        "mean": round(sum(v) / len(v), 1),
                        "p90": sorted(v)[int(0.9 * (len(v) - 1))],
                        "max": max(v),
                    }
                    for rung, v in by_rung.items()
                }
                for split, by_rung in tokens.items()
            },
        }
    args.out_texts.write_text(json.dumps(out))
    args.out_stats.write_text(json.dumps(stats, indent=1))
    print(json.dumps({k: v["truncated_pairs"] for k, v in stats.items()}))


if __name__ == "__main__":
    main()
