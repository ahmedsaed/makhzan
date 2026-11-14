"""One client for every local model server, so bake-off code does not care which engine runs a model.

    from makhzan_ml.client import connect
    emb = connect("emb-qwen3")
    vecs = emb.embed(["ESP32 dev board 30 pin"], instruction=SAME_PRODUCT)   # L2-normalised
    judge = connect("rr-qwen3-4b")
    p = judge.score([("SG90 servo", "Tower Pro SG90 micro servo 9g")], instruction=SAME_PRODUCT)

`score` returns P(yes) in [0, 1] for "is B the same product as A", one per pair, in order. It
is not symmetric: score both orders if the caller wants that. `embed` returns unit vectors, so
a dot product is the cosine.

Standard library only (urllib, threads), so it runs on the host without a virtualenv; the
servers are the Docker services in ml/docker-compose.yml, all on 127.0.0.1.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

SAME_PRODUCT = (
    "Given two product listings from hardware shops, judge whether they are the same product: "
    "the same item, the same variant and the same pack size"
)
# Kev's `noul` instructions are a yes/no question about the state, not a task description.
SAME_PRODUCT_QUESTION = (
    "Are listing A and listing B the same product: the same item, the same variant and the "
    "same pack size?"
)

Pair = tuple[str, str]


@dataclass(frozen=True)
class Service:
    kind: str  # tei-embed | vllm-embed | tei-rerank | vllm-score | kev | vllm-chat
    port: int
    model: str  # what the server is asked for (vLLM served name / Kev model) or the HF id
    hf_id: str
    takes_instruction: bool


# Ports and names match ml/docker-compose.yml.
_Q3E, _HAR, _BGE = (
    "Qwen/Qwen3-Embedding-0.6B",
    "microsoft/harrier-oss-v1-270m",
    "BAAI/bge-reranker-v2-m3",
)
_Q3R6, _Q3R4 = "Qwen/Qwen3-Reranker-0.6B", "Qwen/Qwen3-Reranker-4B"
SERVICES: dict[str, Service] = {
    # GPU
    "emb-qwen3": Service("vllm-embed", 8101, "qwen3-embedding-0.6b", _Q3E, True),
    "emb-harrier": Service("vllm-embed", 8102, "harrier-oss-v1-270m", _HAR, True),
    "rr-bge": Service("tei-rerank", 8103, _BGE, _BGE, False),
    "rr-qwen3-0.6b": Service("vllm-score", 8104, "qwen3-reranker-0.6b", _Q3R6, True),
    "rr-qwen3-4b": Service("vllm-score", 8105, "qwen3-reranker-4b", _Q3R4, True),
    "kev-4b": Service("kev", 8106, "kev-latest", "jaredpalmer/kev-4b", True),
    "gen-qwen3-4b": Service(
        "vllm-chat", 8107, "qwen3-4b-instruct", "Qwen/Qwen3-4B-Instruct-2507", True
    ),
    "pplx-decider": Service(
        "decider", 8108, "pplx-decider-flash-v1.3", "perplexity-ai/pplx-decider-flash-v1.3", True
    ),
    "gen-qwen3.5-4b": Service("vllm-chat", 8109, "qwen3.5-4b", "Qwen/Qwen3.5-4B", True),
    # CPU
    "emb-qwen3-cpu": Service("vllm-embed", 8111, "qwen3-embedding-0.6b", _Q3E, True),
    "emb-harrier-cpu": Service("vllm-embed", 8112, "harrier-oss-v1-270m", _HAR, True),
    "rr-bge-cpu": Service("vllm-score", 8113, "bge-reranker-v2-m3", _BGE, False),
    "rr-qwen3-0.6b-cpu": Service("vllm-score", 8114, "qwen3-reranker-0.6b", _Q3R6, True),
    # engine comparison (the engine that lost for each model)
    "emb-qwen3-tei": Service("tei-embed", 8121, _Q3E, _Q3E, True),
    "emb-harrier-tei": Service("tei-embed", 8122, _HAR, _HAR, True),
    "rr-bge-vllm": Service("vllm-score", 8123, "bge-reranker-v2-m3", _BGE, False),
    "emb-qwen3-cpu-tei": Service("tei-embed", 8131, _Q3E, _Q3E, True),
    "emb-harrier-cpu-tei": Service("tei-embed", 8132, _HAR, _HAR, True),
    "rr-bge-cpu-tei": Service("tei-rerank", 8133, _BGE, _BGE, False),
}


class ModelError(RuntimeError):
    pass


def _post(url: str, body: dict, timeout: float) -> object:
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise ModelError(f"{url}: HTTP {e.code}: {e.read()[:500]!r}") from None


def _chunks(seq: Sequence, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


class Client:
    """`batch_size` items per HTTP request, `concurrency` requests in flight."""

    def __init__(
        self,
        name: str,
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        batch_size: int = 32,
        concurrency: int = 4,
        timeout: float = 600,
    ):
        if name not in SERVICES:
            raise KeyError(f"unknown service {name!r}; known: {', '.join(SERVICES)}")
        self.name, self.svc = name, SERVICES[name]
        self.base = f"http://{host}:{port or self.svc.port}"
        self.batch_size, self.concurrency, self.timeout = batch_size, concurrency, timeout

    # -- public API -------------------------------------------------------------------------
    def embed(self, texts: Sequence[str], instruction: str | None = None) -> list[list[float]]:
        if not self.svc.kind.endswith("-embed"):
            raise ModelError(f"{self.name} is a pair judge, not an embedder")
        if instruction:
            # Both are trained on an instruction prefix, spelled as on each model card: Qwen3
            # `Instruct: {task}\nQuery:{query}` (no space), Harrier `Instruct: {task}\nQuery: {q}`.
            # For title-vs-title matching (a symmetric task) every text is a query.
            sep = "" if self.svc.hf_id.startswith("Qwen/") else " "
            texts = [f"Instruct: {instruction}\nQuery:{sep}{t}" for t in texts]
        fn = self._embed_batch if self.svc.kind == "tei-embed" else self._vllm_embed_batch
        return self._map(fn, list(texts))

    def score(self, pairs: Sequence[Pair], instruction: str = SAME_PRODUCT) -> list[float]:
        if self.svc.kind.endswith("-embed"):
            raise ModelError(f"{self.name} is an embedder; use embed() and a dot product")
        if self.svc.kind == "kev":
            # One state per request (each pair is its own document); the server batches them,
            # so for Kev `batch_size` is the number of requests in flight.
            q = SAME_PRODUCT_QUESTION if instruction == SAME_PRODUCT else instruction
            return self._map(lambda b: [self._kev_one(p, q) for p in b], list(pairs), size=1)
        fn = self._tei_rerank_batch if self.svc.kind == "tei-rerank" else self._vllm_batch
        return self._map(lambda b: fn(b, instruction), list(pairs))

    # -- engines ----------------------------------------------------------------------------
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        return _post(
            f"{self.base}/embed",
            {"inputs": texts, "normalize": True, "truncate": True},
            self.timeout,
        )

    def _vllm_embed_batch(self, texts: list[str]) -> list[list[float]]:
        out = _post(
            f"{self.base}/v1/embeddings", {"model": self.svc.model, "input": texts}, self.timeout
        )
        vecs = [d["embedding"] for d in sorted(out["data"], key=lambda d: d["index"])]
        return [[x / n for x in v] for v in vecs for n in [math.sqrt(sum(x * x for x in v)) or 1.0]]

    def _tei_rerank_batch(self, pairs: list[Pair], _instruction: str) -> list[float]:
        # bge-reranker-v2-m3 takes no instruction. /predict scores arbitrary (a, b) pairs in one
        # call (/rerank wants one query for all texts); raw_scores gives the logit, and the
        # model card's normalisation is a sigmoid of it.
        out = _post(
            f"{self.base}/predict",
            {"inputs": [[a, b] for a, b in pairs], "raw_scores": True, "truncate": True},
            self.timeout,
        )
        return [_sigmoid(row[0]["score"]) for row in out]

    def _vllm_batch(self, pairs: list[Pair], instruction: str) -> list[float]:
        out = _post(
            f"{self.base}/score",
            {
                "model": self.svc.model,
                "queries": [a for a, _ in pairs],
                "documents": [b for _, b in pairs],
                # Read by templates/qwen3_reranker.jinja as the <Instruct> line.
                **(
                    {"chat_template_kwargs": {"instruction": instruction}}
                    if self.svc.takes_instruction
                    else {}
                ),
            },
            self.timeout,
        )
        data = sorted(out["data"], key=lambda d: d["index"])
        if len(data) != len(pairs):
            raise ModelError(f"{self.name}: asked {len(pairs)} pairs, got {len(data)} scores")
        return [d["score"] for d in data]

    def _kev_one(self, pair: Pair, question: str) -> float:
        a, b = pair
        out = _post(
            f"{self.base}/v1/systemone",
            {
                "model": self.svc.model,
                "state": f"Listing A: {a}\nListing B: {b}",
                "questions": {"same": {"type": "noul", "instructions": question}},
            },
            self.timeout,
        )
        return out["answers"]["same"]["noul"]

    def decide_noul(self, pairs: Sequence[Pair], question: str) -> list[tuple[float, float]]:
        """pplx-decider: (P(true) at the checkpoint's saved temperature, raw logit margin
        true - false) per pair, the state spelled as Kev's. `batch_size` pairs per call."""
        if self.svc.kind != "decider":
            raise ModelError(f"{self.name} is not a decider service")

        def batch(b: list[Pair]) -> list[tuple[float, float]]:
            reqs = [
                {"state": f"Listing A: {a}\nListing B: {c}",
                 "questions": {"same": {"type": "noul", "instructions": question}}}
                for a, c in b
            ]  # fmt: skip
            out = _post(f"{self.base}/v1/decide", {"requests": reqs}, self.timeout)
            res = []
            for r, lg in zip(out["responses"], out["logits"], strict=True):
                f, t = lg["same"]  # option order: false, true (pplx_decider.protocol.options)
                res.append((r["answers"]["same"]["noul"], t - f))
            return res

        return self._map(batch, list(pairs))

    def yes_no_margin(self, prompts: Sequence[str], top: int = 20) -> list[float]:
        """Generative service: log P(yes) - log P(no) at the first answer token of a chat turn,
        thinking off, greedy. Case and leading-space variants of each word are pooled
        (logsumexp). A word missing from the top `top` gets a bound: the smallest listed
        logprob minus log 2 (recorded as is; it only matters for saturated pairs)."""
        if self.svc.kind != "vllm-chat":
            raise ModelError(f"{self.name} is not a generative service")

        def lse(xs: list[float]) -> float:
            m = max(xs)
            return m + math.log(sum(math.exp(x - m) for x in xs))

        def one(prompt: str) -> float:
            out = _post(
                f"{self.base}/v1/chat/completions",
                {
                    "model": self.svc.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 1,
                    "logprobs": True,
                    "top_logprobs": top,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
                self.timeout,
            )
            tops = out["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
            floor = min(t["logprob"] for t in tops) - math.log(2)
            yes = [t["logprob"] for t in tops if t["token"].strip().lower() == "yes"]
            no = [t["logprob"] for t in tops if t["token"].strip().lower() == "no"]
            return (lse(yes) if yes else floor) - (lse(no) if no else floor)

        return self._map(lambda b: [one(p) for p in b], list(prompts), size=1)

    def think_yes_no_margin(
        self, prompts: Sequence[str], max_tokens: int = 2048, top: int = 20
    ) -> list[tuple[float | None, int]]:
        """As yes_no_margin, with thinking on: greedy generation, then the margin at the first
        yes/no token after `</think>`. Returns (margin or None when the thinking did not finish
        within max_tokens, completion tokens)."""
        if self.svc.kind != "vllm-chat":
            raise ModelError(f"{self.name} is not a generative service")

        def lse(xs: list[float]) -> float:
            m = max(xs)
            return m + math.log(sum(math.exp(x - m) for x in xs))

        def one(prompt: str) -> tuple[float | None, int]:
            out = _post(
                f"{self.base}/v1/chat/completions",
                {
                    "model": self.svc.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "logprobs": True,
                    "top_logprobs": top,
                    "chat_template_kwargs": {"enable_thinking": True},
                    "skip_special_tokens": False,
                },
                self.timeout,
            )
            used = out["usage"]["completion_tokens"]
            toks = out["choices"][0]["logprobs"]["content"]
            after = False
            for t in toks:
                if "</think>" in t["token"]:
                    after = True
                    continue
                if after and t["token"].strip().lower() in ("yes", "no"):
                    tops = t["top_logprobs"]
                    floor = min(x["logprob"] for x in tops) - math.log(2)
                    yes = [x["logprob"] for x in tops if x["token"].strip().lower() == "yes"]
                    no = [x["logprob"] for x in tops if x["token"].strip().lower() == "no"]
                    return (lse(yes) if yes else floor) - (lse(no) if no else floor), used
            return None, used

        return self._map(lambda b: [one(p) for p in b], list(prompts), size=1)

    # -- plumbing ---------------------------------------------------------------------------
    def chat_json(
        self, prompts: Sequence[str], schema: dict, system: str = "", max_tokens: int = 400
    ) -> list[dict]:
        """One JSON object per prompt from a generative service, decoded against `schema`
        (vLLM structured outputs), greedy. `batch_size` prompts are in flight at once."""
        if self.svc.kind != "vllm-chat":
            raise ModelError(f"{self.name} is not a generative service")

        def one(prompt: str) -> dict:
            messages = ([{"role": "system", "content": system}] if system else []) + [
                {"role": "user", "content": prompt}
            ]
            out = _post(
                f"{self.base}/v1/chat/completions",
                {
                    "model": self.svc.model,
                    "messages": messages,
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": "listing", "schema": schema},
                    },
                },
                self.timeout,
            )
            return json.loads(out["choices"][0]["message"]["content"])

        return self._map(lambda b: [one(p) for p in b], list(prompts), size=1)

    def _map(self, fn, items: list, size: int | None = None) -> list:
        batches = list(_chunks(items, size or self.batch_size))
        # One item per request (Kev): batch_size is then exactly the number in flight.
        workers = self.batch_size if size == 1 else self.concurrency
        if workers <= 1 or len(batches) == 1:
            results = [fn(b) for b in batches]
        else:
            with ThreadPoolExecutor(workers) as ex:
                results = list(ex.map(fn, batches))
        return [x for r in results for x in r]


def connect(name: str, **kw) -> Client:
    return Client(name, **kw)
