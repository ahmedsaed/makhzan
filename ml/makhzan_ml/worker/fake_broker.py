"""A small in-process broker that follows docs/ai/broker-api.md, for tests and the parity check.

It keeps jobs in memory and implements what a worker can observe: bearer auth (401),
model keys per worker (403), version checks at hello and lease (`ok: false`, 409
version), leases with lazy expiry and attempts, heartbeats that extend a lease or
answer 409 lease_lost, idempotent results keyed on the request hash (422 on a hash it
did not render for the job, or a score outside [0, 1]), and releases that count an
attempt only for reason "error". It is not the broker: no database, no pipelines, no
transitions; a job is done when each of its requests has a score.

Faults for tests: `fail(path, times, status=None, body=None)` drops the connection
(status None) or answers that status and body the next `times` calls to `path`; `lose_lease(job_id)` makes the
next heartbeat or result for that job a 409 lease_lost.

Binds 127.0.0.1 only, plain HTTP: the worker accepts http:// for a loopback address
and nothing else.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from makhzan_ml.worker.pins import PINS


def canonical_sha256(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class FakeJob:
    job_id: int
    model: str
    requests: list[dict]  # [{"order", "payload", "request_sha256"}]
    prompt_version: str = "K2-150@test"
    priority: int = 0
    status: str = "queued"
    lease_id: str | None = None
    leased_by: str | None = None
    expires: float = 0.0
    attempts: int = 0
    last_error: str | None = None
    scores: dict[str, dict] = field(default_factory=dict)  # order -> score

    def unscored(self) -> list[dict]:
        return [r for r in self.requests if r["order"] not in self.scores]


class FakeBroker:
    def __init__(
        self,
        tokens: dict[str, tuple[str, list[str]]],
        *,
        versions: dict[str, str] | None = None,
        lease_s: int = 900,
        heartbeat_s: int = 60,
        max_attempts: int = 3,
        clock=time.monotonic,
    ):
        self.tokens = tokens  # token -> (worker name, model keys)
        self.versions = versions or {k: p.model_version for k, p in PINS.items()}
        self.lease_s, self.heartbeat_s, self.max_attempts = lease_s, heartbeat_s, max_attempts
        self.clock = clock
        self.jobs: dict[int, FakeJob] = {}
        self.calls: list[tuple[str, dict]] = []
        self.sessions: dict[str, dict] = {}
        self.lock = threading.RLock()
        self._ids = itertools.count(1)
        self._faults: dict[str, list] = {}
        self._lost: set[int] = set()
        self._server: ThreadingHTTPServer | None = None

    # -- set-up ----------------------------------------------------------------------------

    def add_job(self, model: str, payloads: dict[str, dict], **kw) -> FakeJob:
        """A job with one request per order ({"ab": payload, "ba": payload})."""
        reqs = [
            {"order": o, "payload": p, "request_sha256": canonical_sha256(p)}
            for o, p in payloads.items()
        ]
        with self.lock:
            job = FakeJob(next(self._ids), model, reqs, **kw)
            self.jobs[job.job_id] = job
            return job

    def fail(
        self, path: str, times: int = 1, status: int | None = None, body: dict | None = None
    ) -> None:
        """The next `times` calls to `path` get no response (status None) or `status`."""
        with self.lock:
            fault = None if status is None else (status, body or {"error": "injected"})
            self._faults.setdefault(path, []).extend([fault] * times)

    def lose_lease(self, job_id: int) -> None:
        with self.lock:
            self._lost.add(job_id)

    def paths(self) -> list[str]:
        return [p for p, _ in self.calls]

    def bodies(self, path: str) -> list[dict]:
        return [b for p, b in self.calls if p == path]

    # -- server ----------------------------------------------------------------------------

    def start(self) -> str:
        broker = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):  # noqa: N802
                path = self.path.removeprefix("/ai/v1")
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                with broker.lock:
                    faults = broker._faults.get(path)
                    fault = faults.pop(0) if faults else "none"
                if fault is None:  # a dropped connection: no response at all
                    self.close_connection = True
                    self.connection.close()
                    return
                if fault != "none":
                    return self._send(*fault)
                auth = self.headers.get("Authorization", "")
                who = (
                    broker.tokens.get(auth.removeprefix("Bearer "))
                    if auth.startswith("Bearer ")
                    else None
                )
                if who is None:
                    return self._send(401, {"error": "unauthorized"})
                try:
                    body = json.loads(raw)
                except ValueError:
                    return self._send(422, {"error": "invalid", "detail": "not JSON"})
                with broker.lock:
                    broker.calls.append((path, body))
                    handler = {
                        "/hello": broker._hello,
                        "/lease": broker._lease,
                        "/heartbeat": broker._heartbeat,
                        "/results": broker._results,
                        "/release": broker._release,
                    }.get(path)
                    code, out = (
                        (404, {"error": "not found"}) if handler is None else handler(who, body)
                    )
                self._send(code, out)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()
        return f"http://127.0.0.1:{self._server.server_port}/ai/v1"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def __enter__(self) -> FakeBroker:
        self.url = self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- endpoints -------------------------------------------------------------------------

    def _queued_requests(self, model: str) -> int:
        return sum(len(j.unscored()) for j in self.jobs.values()
                   if j.model == model and j.status == "queued")  # fmt: skip

    def _hello(self, who, body):
        name, allowed = who
        models = body.get("models") or {}
        for key in models:
            if key not in allowed:
                return 403, {"error": "model_not_allowed", "model": key}
        session = uuid.uuid4().hex
        answer = {}
        for key, m in models.items():
            current = self.versions.get(key)
            ok = m.get("model_version") == current and m.get("weights_revision") == (
                PINS[key].weights_revision if key in PINS else None
            )
            answer[key] = {"model_version": current, "ok": ok,
                           "queued_requests": self._queued_requests(key)}  # fmt: skip
        self.sessions[session] = {"worker": name, "models": models, "ended": None}
        return 200, {"session": session, "models": answer, "lease_s": self.lease_s,
                     "heartbeat_s": self.heartbeat_s}  # fmt: skip

    def _reap(self) -> None:
        now = self.clock()
        for j in self.jobs.values():
            if j.status == "leased" and j.expires <= now:
                self._requeue(j, count=True, error="lease expired")

    def _requeue(self, j: FakeJob, *, count: bool, error: str | None = None) -> None:
        j.lease_id = j.leased_by = None
        j.expires = 0.0
        if count:
            j.attempts += 1
            j.last_error = error
        j.status = "dead" if j.attempts >= self.max_attempts else "queued"

    def _lease(self, who, body):
        name, allowed = who
        model = body.get("model")
        if model not in allowed:
            return 403, {"error": "model_not_allowed", "model": model}
        session = self.sessions.get(body.get("session"))
        if (
            body.get("model_version") != self.versions.get(model)
            or session is None
            or (session["models"].get(model) or {}).get("model_version") != self.versions[model]
        ):
            return 409, {"error": "version", "model": model, "current": self.versions.get(model)}
        self._reap()
        n = int(body.get("max_jobs") or 1)
        spr = float(body.get("seconds_per_request") or 1)
        left = float(body.get("seconds_left") or 0)
        lease_id = uuid.uuid4().hex
        picked, budget = [], 0.0
        for j in sorted(self.jobs.values(), key=lambda j: (-j.priority, j.job_id)):
            if len(picked) >= n:
                break
            if j.model != model or j.status != "queued":
                continue
            todo = j.unscored()
            if not todo:  # a job never carries zero orders
                j.status = "done"
                continue
            if picked and budget + len(todo) * spr > left:
                break
            budget += len(todo) * spr
            j.status, j.lease_id, j.leased_by = "leased", lease_id, name
            j.expires = self.clock() + self.lease_s
            picked.append(j)
        if not picked:
            return 200, {"lease_id": None, "jobs": []}
        jobs = [{"job_id": j.job_id, "prompt_version": j.prompt_version,
                 "requests": [dict(r) for r in j.unscored()]} for j in picked]  # fmt: skip
        return 200, {"lease_id": lease_id, "expires_at": "fake", "jobs": jobs}

    def _held(self, name, lease_id, job_id) -> FakeJob | None:
        j = self.jobs.get(job_id)
        if j is None or j.lease_id != lease_id or j.leased_by != name or job_id in self._lost:
            return None
        return j

    def _heartbeat(self, who, body):
        name, _ = who
        lease_ids = set(body.get("lease_ids") or [])
        lost = []
        for j in self.jobs.values():
            if j.job_id in self._lost and j.lease_id in lease_ids:
                lost.append(j.job_id)
            elif j.lease_id in lease_ids and j.leased_by == name and j.status == "leased":
                j.expires = self.clock() + self.lease_s
        if lost:
            return 409, {"error": "lease_lost", "job_ids": sorted(lost)}
        return 200, {"expires_at": "fake"}

    def _results(self, who, body):
        name, allowed = who
        j = self._held(name, body.get("lease_id"), body.get("job_id"))
        if j is None:
            return 409, {"error": "lease_lost", "job_ids": [body.get("job_id")]}
        if j.model not in allowed:
            return 403, {"error": "model_not_allowed", "model": j.model}
        rendered = {r["order"]: r["request_sha256"] for r in j.requests}
        scores = body.get("scores") or []
        for s in scores:
            if rendered.get(s.get("order")) != s.get("request_sha256"):
                return 422, {"error": "request_mismatch"}
            p = s.get("p")
            if not isinstance(p, (int, float)) or not 0 <= p <= 1:
                return 422, {"error": "invalid", "detail": "p outside [0, 1]"}
        accepted = duplicate = 0
        for s in scores:
            if s["order"] in j.scores:
                duplicate += 1
            else:
                j.scores[s["order"]] = {**s, "device": body.get("device"),
                                        "dtype": body.get("dtype"), "threads": body.get("threads")}  # fmt: skip
                accepted += 1
        if not j.unscored():
            j.status = "done"
            j.lease_id = j.leased_by = None
        return 200, {"accepted": accepted, "duplicate": duplicate, "job": j.status}

    def _release(self, who, body):
        name, _ = who
        session = self.sessions.get(body.get("session"))
        if session is not None and body.get("reason") == "graceful" and not body.get("job_ids"):
            session["ended"] = "graceful"
            return 200, {"released": 0}
        released = 0
        for job_id in body.get("job_ids") or []:
            j = self._held(name, body.get("lease_id"), job_id)
            if j is None:
                return 409, {"error": "lease_lost", "job_ids": [job_id]}
            self._requeue(j, count=body.get("reason") == "error", error=body.get("error"))
            released += 1
        if session is not None and body.get("reason") == "graceful":
            session["ended"] = "graceful"
        return 200, {"released": released}
