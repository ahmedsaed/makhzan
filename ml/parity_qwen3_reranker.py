"""Check that the vLLM-served Qwen3-Reranker returns the model card's number.

The card scores a pair with transformers: format the prompt, take the last-token logits of
"no" and "yes", softmax over the two, P(yes). vLLM gets there through a conversion
(hf_overrides + a score template), so this reproduces the card's code and compares it with
scores bench.py saved from the server. Run it inside the vLLM image, which has torch and
transformers (see README, "Checks"):

    python parity_qwen3_reranker.py --model Qwen/Qwen3-Reranker-0.6B \
        --data validation.jsonl --served scores-rr-qwen3-0.6b.json [--n 64]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench import load_pairs  # noqa: E402
from makhzan_ml.client import SAME_PRODUCT  # noqa: E402
from quant import compare  # noqa: E402

# Verbatim from the Qwen3-Reranker model card.
PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--served", type=Path, required=True)
    ap.add_argument("--n", type=int, default=0, help="first n pairs only (0 = all)")
    ap.add_argument("--title-only", dest="with_specs", action="store_false")
    ap.add_argument("--dtype", choices=["bfloat16", "float32"], default="bfloat16")
    ap.add_argument("--save", type=Path, help="write the reference scores here ({pair_id: p})")
    args = ap.parse_args()

    ids, pairs = load_pairs(args.data, args.with_specs)
    if args.n:
        ids, pairs = ids[: args.n], pairs[: args.n]
    tok = AutoTokenizer.from_pretrained(args.model, padding_side="left")
    model = (
        AutoModelForCausalLM.from_pretrained(args.model, dtype=getattr(torch, args.dtype))
        .cuda()
        .eval()
    )
    yes, no = tok.convert_tokens_to_ids("yes"), tok.convert_tokens_to_ids("no")

    ref = {}
    for i in range(0, len(pairs), 8):
        texts = [
            PREFIX + f"<Instruct>: {SAME_PRODUCT}\n<Query>: {a}\n<Document>: {b}" + SUFFIX
            for a, b in pairs[i : i + 8]
        ]
        batch = tok(texts, padding=True, return_tensors="pt").to("cuda")
        with torch.no_grad():
            logits = model(**batch).logits[:, -1, :]
        p = torch.log_softmax(torch.stack([logits[:, no], logits[:, yes]], 1).float(), 1)[
            :, 1
        ].exp()
        ref.update(zip(ids[i : i + 8], p.tolist()))

    if args.save:
        args.save.write_text(json.dumps(ref, indent=0))
    served = json.loads(args.served.read_text())
    print(
        json.dumps(
            {"reference": f"transformers {args.dtype}, model-card formula", **compare(ref, served)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
