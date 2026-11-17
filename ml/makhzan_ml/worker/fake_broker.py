"""A small in-process broker that follows docs/ai/broker-api.md, for tests and the parity check.

It keeps jobs in memory and implements what a worker can observe, as the phase 2 broker
answers it (`app.broker.main` in apps/api):

- bearer auth (401), model keys per worker (403), version checks at hello (`ok: false`)
  and at lease (409 version);
- hello answers `lease_s` from the worker's `config.lease_s` (default 900) and
  `heartbeat_s = min(60, lease_s / 3)`;
- leases sized by `seconds_left` minus a 60 s margin, with lazy expiry and attempts;
- heartbeats that extend every live lease named and answer 409 lease_lost (with the lost
  `job_ids` and `lease_ids`) when a named lease or job is no longer held;
- results that are idempotent on the request hash (a retry after the job is done is a
  200 counted duplicate), `job` "leased" until both orders are scored, then "done" with
  `next`; 422 request_mismatch for the leaseholder only, 422 invalid for a bad body;
- releases that need the lease and at least one job, counting an attempt only for
  reason "error";
- sessions that end "released" (a graceful release) or "empty" (an empty lease).

It is not the broker: no database, no pipelines, no transitions (`next` is always
`{"action": "record"}`).

Faults for tests: `fail(path, times, status=None, body=None, headers=None)` drops the
connection (status None) or answers that status, body and headers the next `times` calls
to `path`; `lose_lease(job_id)` makes the job no longer held by its worker.

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

BODY_LIMIT = 256 * 1024


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


def _invalid(detail: str) -> tuple[int, dict]:
    return 422, {"error": "invalid", "detail": detail}


class FakeBroker:
    def __init__(
        self,
        tokens: dict[str, tuple[str, list[str]]],
        *,
        versions: dict[str, str] | None = None,
        max_attempts: int = 3,
        clock=time.monotonic,
    ):
        self.tokens = tokens  # token -> (worker name, model keys)
        self.versions = versions or {k: p.model_version for k, p in PINS.items()}
        self.max_attempts = max_attempts
        self.clock = clock
        self.jobs: dict[int, FakeJob] = {}
        self.calls: list[tuple[str, dict]] = []
        self.sessions: dict[str, dict] = {}
        self.lock = threading.RLock()
        self._ids = itertools.count(1)
        self._faults: dict[str, list] = {}
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
        self,
        path: str,
        times: int = 1,
        status: int | None = None,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> None:
        """The next `times` calls to `path` get no response (status None) or `status`."""
        with self.lock:
            fault = None if status is None else (status, body or {"error": "injected"}, headers)
            self._faults.setdefault(path, []).extend([fault] * times)

    def lose_lease(self, job_id: int) -> None:
        """The job's lease expired and moved on: re-queued, no longer the worker's."""
        with self.lock:
            j = self.jobs[job_id]
            self._requeue(j, count=True, error="lease expired")

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

            def _send(self, code: int, body: dict, headers: dict | None = None) -> None:
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
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
                token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else None
                who = broker.tokens.get(token) if token else None
                if who is None:
                    return self._send(401, {"error": "unauthorized"})
                if length > BODY_LIMIT:
                    return self._send(*_invalid("body too large"))
                try:
                    body = json.loads(raw)
                except ValueError:
                    return self._send(*_invalid("not JSON"))
                with broker.lock:
                    broker.calls.append((path, body))
                    handler = {
                        "/hello": broker._hello,
                        "/lease": broker._lease,
                        "/heartbeat": broker._heartbeat,
                        "/results": broker._results,
                        "/release": broker._release,
                    }.get(path)
                    if handler is None:
                        code, out = 404, {"error": "not found"}
                    else:
                        code, out = handler(who, body)
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

    def _session(self, name: str, body: dict) -> dict | None:
        s = self.sessions.get(body.get("session"))
        return s if s is not None and s["worker"] == name else None

    def _hello(self, who, body):
        name, allowed = who
        models = body.get("models")
        if not isinstance(models, dict) or not models:
            return _invalid("models")
        for key in models:
            if key not in allowed:
                return 403, {"error": "model_not_allowed", "model": key}
        lease_s = int((body.get("config") or {}).get("lease_s") or 900)
        session = uuid.uuid4().hex
        answer = {}
        for key, m in models.items():
            current = self.versions.get(key)
            ok = m.get("model_version") == current and m.get("weights_revision") == (
                PINS[key].weights_revision if key in PINS else None
            )
            answer[key] = {"model_version": current, "ok": ok,
                           "queued_requests": self._queued_requests(key)}  # fmt: skip
        self.sessions[session] = {"worker": name, "models": models, "lease_s": lease_s,
                                  "end_reason": None}  # fmt: skip
        return 200, {"session": session, "models": answer, "lease_s": lease_s,
                     "heartbeat_s": min(60, lease_s / 3)}  # fmt: skip

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
        session = self._session(name, body)
        if (
            body.get("model_version") != self.versions.get(model)
            or session is None
            or (session["models"].get(model) or {}).get("model_version") != self.versions[model]
        ):
            return 409, {"error": "version", "model": model, "current": self.versions.get(model)}
        self._reap()
        n = int(body.get("max_jobs") or 1)
        spr, left = body.get("seconds_per_request"), body.get("seconds_left")
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
            cost = len(todo) * float(spr) if spr and left is not None else 0.0
            if cost and budget + cost > float(left) - 60:
                continue  # does not fit: stays queued
            budget += cost
            j.status, j.lease_id, j.leased_by = "leased", lease_id, name
            j.expires = self.clock() + session["lease_s"]
            picked.append(j)
        if not picked:
            session["end_reason"] = "empty"
            return 200, {"lease_id": None, "jobs": []}
        session["end_reason"] = None  # a lease with jobs reopens the session
        jobs = [{"job_id": j.job_id, "prompt_version": j.prompt_version,
                 "requests": [dict(r) for r in j.unscored()]} for j in picked]  # fmt: skip
        return 200, {"lease_id": lease_id, "expires_at": "fake", "jobs": jobs}

    def _holds(self, name: str, lease_id, job: FakeJob | None) -> bool:
        return job is not None and job.lease_id == lease_id and job.leased_by == name

    def _heartbeat(self, who, body):
        name, _ = who
        session = self._session(name, body)
        if session is None:
            return _invalid("session")
        lease_ids = list(body.get("lease_ids") or [])
        job_ids = list(body.get("job_ids") or [])
        now = self.clock()
        live = [j for j in self.jobs.values()
                if j.lease_id in lease_ids and j.leased_by == name and j.status == "leased"]  # fmt: skip
        for j in live:
            j.expires = now + session["lease_s"]
        lost_leases = sorted(lid for lid in lease_ids if not any(j.lease_id == lid for j in live))
        lost_jobs = sorted(i for i in job_ids if not any(j.job_id == i for j in live))
        expires = "fake" if live else None
        if lost_leases or lost_jobs:
            return 409, {"error": "lease_lost", "job_ids": lost_jobs, "lease_ids": lost_leases,
                         "expires_at": expires}  # fmt: skip
        return 200, {"expires_at": expires}

    def _results(self, who, body):
        name, allowed = who
        scores = body.get("scores")
        if not isinstance(scores, list) or not 1 <= len(scores) <= 2:
            return _invalid("scores")
        for s in scores:
            p = s.get("p")
            if s.get("order") not in ("ab", "ba") or not isinstance(p, (int, float)):
                return _invalid("score")
            if not 0 <= p <= 1:
                return _invalid("p outside [0, 1]")
        j = self.jobs.get(body.get("job_id"))
        if j is not None and j.model not in allowed:
            return 403, {"error": "model_not_allowed", "model": j.model}
        rendered = {r["order"]: r["request_sha256"] for r in j.requests} if j else {}
        posted = {s["order"]: s.get("request_sha256") for s in scores}
        if not self._holds(name, body.get("lease_id"), j):
            # A retry after the job is done is a duplicate, not a lost lease.
            if (
                j is not None
                and j.status == "done"
                and all(rendered.get(o) == h and o in j.scores for o, h in posted.items())
            ):
                return 200, {"accepted": 0, "duplicate": len(scores), "job": "done", "next": None}
            return 409, {"error": "lease_lost", "job_ids": [body.get("job_id")]}
        if any(rendered.get(o) != h for o, h in posted.items()):
            return 422, {"error": "request_mismatch"}
        accepted = duplicate = 0
        for s in scores:
            if s["order"] in j.scores:
                duplicate += 1
            else:
                j.scores[s["order"]] = {**s, "device": body.get("device"),
                                        "dtype": body.get("dtype"), "threads": body.get("threads")}  # fmt: skip
                accepted += 1
        if j.unscored():
            return 200, {"accepted": accepted, "duplicate": duplicate, "job": "leased",
                         "next": None}  # fmt: skip
        j.status = "done"
        j.lease_id = j.leased_by = None
        return 200, {"accepted": accepted, "duplicate": duplicate, "job": "done",
                     "next": {"action": "record"}}  # fmt: skip

    def _release(self, who, body):
        name, _ = who
        session = self._session(name, body)
        job_ids = body.get("job_ids")
        if session is None or not body.get("lease_id") or not isinstance(job_ids, list):
            return _invalid("session, lease_id and job_ids are required")
        if not job_ids:
            return _invalid("job_ids: at least one")
        if body.get("reason", "graceful") not in ("graceful", "error"):
            return _invalid("reason")
        for job_id in job_ids:
            if not self._holds(name, body["lease_id"], self.jobs.get(job_id)):
                return 409, {"error": "lease_lost", "job_ids": [job_id]}
        for job_id in job_ids:
            reason = body.get("reason", "graceful")
            self._requeue(self.jobs[job_id], count=reason == "error", error=body.get("error"))
        if body.get("reason", "graceful") == "graceful":
            session["end_reason"] = "released"
        return 200, {"released": len(job_ids)}
