"""A minimal HTTP front for pplx_decider.Decider (the model card's own inference code).

    POST /v1/decide   {"requests": [<decider request>, ...]}
                   -> {"responses": [<decider response>, ...], "logits": [{question: [..]}, ...]}
    GET  /health

One forward pass per call: the raw readout logits come from `Decider.logits`, and each answer is
the card's computation on them (`protocol.answer` of the softmax at the saved temperature), so
`responses` equals what `Decider.decide` returns for decision questions. Locate questions are
refused. Calls are serialised by the Decider's own lock; send several requests per call to batch.
Standard library HTTP; binds wherever --host says (compose publishes it on 127.0.0.1 only).
"""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch
from huggingface_hub import snapshot_download
from pplx_decider import Decider, RequestError
from pplx_decider import model as pplx_model
from pplx_decider.protocol import answer


def build(args: argparse.Namespace) -> Decider:
    path = snapshot_download(args.model, revision=args.revision)
    if args.device == "cpu" and args.dtype == "bf16":
        # The card's code picks bf16 on CUDA and fp32 elsewhere (Decider.__init__). bf16 on CPU is
        # our choice, not the card's: load the backbone in bf16 directly (fp32 first would need
        # ~18 GB) and cast the 255-row readout after. Parity vs the GPU scores is in ml/README.md.
        backbone = pplx_model._backbone
        pplx_model._backbone = lambda ckpt, cfg, _dtype: backbone(ckpt, cfg, torch.bfloat16)
    threads = int(os.environ.get("OMP_NUM_THREADS") or len(os.sched_getaffinity(0)))
    decider = Decider.from_pretrained(
        path, device=args.device, locate=False, batch_tokens=args.batch_tokens,
        cpu_threads=threads,
    )  # fmt: skip
    if args.device == "cpu" and args.dtype == "bf16":
        decider.readout.to(torch.bfloat16)
    return decider


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", required=True)
    ap.add_argument("--revision", required=True)
    ap.add_argument("--device", choices=["cuda", "cpu"], default=os.environ.get("DEVICE", "cuda"))
    ap.add_argument(
        "--dtype", choices=["auto", "fp32", "bf16"], default=os.environ.get("DTYPE", "auto"),
        help="auto (= fp32 on CPU): the card's choice, bf16 on CUDA; bf16: also on CPU",
    )  # fmt: skip
    ap.add_argument("--batch-tokens", type=int, default=int(os.environ.get("BATCH_TOKENS", 8192)))
    args = ap.parse_args()
    decider = build(args)
    scale = decider.temperature
    print(
        f"loaded {args.model}@{args.revision} on {args.device} "
        f"({next(decider.backbone.parameters()).dtype}) T={scale:.4f}",
        flush=True,
    )

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            self._send(200, {"ok": True}) if self.path == "/health" else self._send(404, {})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/decide":
                return self._send(404, {})
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                reqs = body["requests"]
                for r in reqs:
                    if any(q.get("type") == "locate" for q in r["questions"].values()):
                        raise RequestError("locate questions are not served here")
                logits = decider.logits(reqs)
                responses = []
                for r, lg in zip(reqs, logits, strict=True):
                    responses.append({"answers": {
                        k: answer(q, (torch.tensor(lg[k]) / scale).softmax(-1).tolist())
                        for k, q in r["questions"].items()
                    }})  # fmt: skip
                self._send(200, {"responses": responses, "logits": logits, "temperature": scale})
            except (RequestError, KeyError, ValueError, TypeError) as e:
                self._send(400, {"error": str(e)})

        def log_message(self, *a) -> None:
            pass

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
