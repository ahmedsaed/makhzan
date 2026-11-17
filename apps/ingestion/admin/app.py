"""The admin dashboard: FastAPI routes, server-rendered with Jinja.

    uvicorn admin.app:app --host 0.0.0.0 --port 8200     # compose service `admin`
    make admin                                           # locally, on :8200

Reached only over Tailscale, by the server's tailnet address and `ADMIN_BIND`
(docs/admin.md); there is no public proxy in front of it. One password
(`ADMIN_PASSWORD_HASH`), a signed session cookie, a CSRF token on every POST
and a login limit (admin/auth.py).

Every GET reads; every POST is an action, audited in `admin_actions` with who
(`ADMIN_NAME` and the client address), what and when, through the same
functions as the CLI: worker.pause, worker.reports, worker.overrides,
worker.ai, makhzan_schemas.ai. Jobs that take time or talk to shops (a
`limit=` run, the probe, a regroup dry run) are queued to the worker
(worker.admin_jobs) and the page polls their row. Nothing here deploys,
restarts or touches infrastructure.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from makhzan_schemas import crawl
from makhzan_schemas import overrides as rulings
from makhzan_schemas.ai import flow
from makhzan_schemas.ai.mode import MODES, ai_mode, set_ai_mode
from makhzan_schemas.ai.policy import ACTIVE as ACTIVE_POLICY
from makhzan_schemas.ai.policy import MODELS
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import AdminAction, Source
from sqlalchemy import select
from worker import ai as ai_cli
from worker import pause
from worker.admin_jobs import (
    MAX_LIMIT,
    PROBE,
    REGROUP_DRY_RUN,
    RUN_LIMIT,
    expire_lost,
    job_id,
)
from worker.overrides import OverrideRefused, add_override
from worker.reports import review_reports, ruling_line

from admin import auth, data
from admin.render import filters

HERE = Path(__file__).parent

app = FastAPI(title="makhzan admin", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters.update(filters)
#: Appended to the static files' URLs, so a deploy's CSS and JS are not served from a stale cache.
templates.env.globals["static_v"] = str(
    int(max((HERE / "static" / name).stat().st_mtime for name in ("admin.css", "admin.js")))
)

limiter = auth.LoginLimiter()
#: Password checks running at once: each holds 128 MiB of scrypt for half a second.
VERIFY_SLOTS = asyncio.Semaphore(2)

FLASH_COOKIE = "mk_admin_flash"
NAV = [
    ("status", "/", "Overview"),
    ("crawl", "/crawl", "Crawl"),
    ("catalog", "/catalog", "Catalog"),
    ("reports", "/reports", "Reports"),
    ("overrides", "/overrides", "Overrides"),
    ("ai", "/ai", "AI matching"),
]


# --------------------------------------------------------------------------- #
# Settings, read per request so a test (or a recreated container) sees the current env
# --------------------------------------------------------------------------- #


def password_hash() -> str | None:
    return os.getenv("ADMIN_PASSWORD_HASH") or None


def secret() -> str | None:
    return os.getenv("ADMIN_SECRET") or None


def actor() -> str:
    return (os.getenv("ADMIN_NAME") or "admin").strip()[:100] or "admin"


def cookie_secure() -> bool:
    return os.getenv("ADMIN_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}


def session_hours() -> float:
    try:
        return float(os.getenv("ADMIN_SESSION_HOURS", "12"))
    except ValueError:
        return 12.0


def configured() -> bool:
    return bool(password_hash() and secret())


def client_of(request: Request) -> str:
    return request.client.host if request.client else "unknown"


#: Who an action is recorded as, on the rows it writes (`created_by` and the like).
def who() -> str:
    return actor()


# --------------------------------------------------------------------------- #
# Headers, sessions, CSRF, flash
# --------------------------------------------------------------------------- #

#: Scripts only from this origin, never inline. Inline style attributes are
#: allowed (the progress bars' widths); every value in them is a number.
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


#: The largest request body read, checked on Content-Length and again while
#: reading: every form here is a few fields.
MAX_BODY = 64 * 1024


def allowed_hosts() -> set[str]:
    """`ADMIN_ALLOWED_HOSTS`, comma-separated (`100.x.y.z:8200,admin.tailnet`); empty: any."""
    return {h.strip().lower() for h in os.getenv("ADMIN_ALLOWED_HOSTS", "").split(",") if h.strip()}


def _host_allowed(host: str) -> bool:
    hosts = allowed_hosts()
    if not hosts:
        return True
    host = host.lower()
    return host in hosts or host.rsplit(":", 1)[0] in hosts


@app.middleware("http")
async def headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    if not _host_allowed(request.headers.get("host", "")):
        return HTMLResponse("Unknown host.", status_code=400)
    length = request.headers.get("content-length")
    if length is not None and (not length.isdigit() or int(length) > MAX_BODY):
        return HTMLResponse("Request body too large.", status_code=413)
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    # same-origin, not no-referrer: under no-referrer browsers send `Origin: null`
    # on form posts, which the same-origin check must refuse.
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


def current_session(request: Request) -> auth.Session | None:
    return auth.read_session(request.cookies.get(auth.SESSION_COOKIE), password_hash(), secret())


async def form_of(request: Request) -> dict[str, str]:
    """An urlencoded form's fields, first value each (no multipart: nothing here uploads).

    Read in chunks and refused past `MAX_BODY`, whatever Content-Length said
    (a chunked body has none).
    """
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise HTTPException(413, "Request body too large.")
        chunks.append(chunk)
    body = b"".join(chunks).decode("utf-8", errors="replace")
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin or origin == "null":
        return origin is None
    return origin.split("://", 1)[-1] == request.headers.get("host")


async def checked_form(request: Request) -> tuple[auth.Session, dict[str, str]]:
    """The form of an authenticated, same-origin POST with the session's CSRF token."""
    session = current_session(request)
    if session is None:
        raise HTTPException(401, "Sign in first.")
    if not _same_origin(request):
        raise HTTPException(403, "Cross-origin request refused.")
    fields = await form_of(request)
    if not auth.tokens_match(fields.get("csrf"), session.csrf):
        raise HTTPException(403, "The form's CSRF token is missing or stale; reload the page.")
    return session, fields


def flash(response: Response, message: str, kind: str = "ok") -> Response:
    key = secret() or ""
    response.set_cookie(
        FLASH_COOKIE,
        auth.sign({"m": message[:600], "k": kind}, key),
        httponly=True,
        samesite="strict",
        secure=cookie_secure(),
        max_age=60,
    )
    return response


def back(to: str, message: str, kind: str = "ok") -> Response:
    """Post/redirect/get, with a one-shot message."""
    return flash(RedirectResponse(to, status_code=303), message, kind)


async def audit(
    session,
    request: Request,
    action: str,
    target: str | None = None,
    detail: dict | None = None,
    *,
    job: bool = False,
) -> AdminAction:
    row = AdminAction(
        actor=actor(),
        client=client_of(request)[:64],
        action=action,
        target=(target or None) and str(target)[:200],
        detail=detail or {},
        status="queued" if job else None,
    )
    session.add(row)
    await session.flush()
    return row


async def refuse(
    request: Request,
    to: str,
    action: str,
    target: str | None,
    message: str,
    detail: dict | None = None,
) -> Response:
    """Audit an action the dashboard refused (`detail.refused`), then go back and say why."""
    async with SessionLocal() as db:
        await audit(db, request, action, target, {**(detail or {}), "refused": message[:500]})
        await db.commit()
    return back(to, message, "error")


async def sweep_lost_jobs() -> None:
    """Mark jobs the worker's queue has lost as failed (`admin_jobs.expire_lost`).

    Asked whenever a page shows jobs or polls one, so a lost job stops being
    shown as queued. Redis unreachable: nothing is marked.
    """
    from redis import asyncio as aioredis

    try:
        client = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        try:

            async def exists(key: str) -> bool:
                return bool(await client.exists(key))

            async with SessionLocal() as db:
                if await expire_lost(db, exists):
                    await db.commit()
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — a page must not fail because Redis is down
        return


async def enqueue_admin_job(action_id: int) -> None:
    """Queue `worker.admin_jobs.admin_job` for the row. Replaced in tests."""
    from arq import create_pool
    from arq.connections import RedisSettings

    redis = await create_pool(
        RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
    )
    try:
        await redis.enqueue_job("admin_job", action_id, _job_id=job_id(action_id))
    finally:
        await redis.aclose()


async def page(request: Request, template: str, view: str, context: dict, status_code=200):
    session = current_session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    async with SessionLocal() as db:
        counts = await data.nav_counts(db)
    note = auth.unsign(request.cookies.get(FLASH_COOKIE), secret() or "")
    response = templates.TemplateResponse(
        request,
        template,
        {
            "view": view,
            "nav": NAV,
            "counts": counts,
            "csrf": session.csrf,
            "actor": actor(),
            "client": client_of(request),
            "flash": note,
            "now": datetime.now(timezone.utc),
            **context,
        },
        status_code=status_code,
    )
    if note is not None:
        response.delete_cookie(FLASH_COOKIE)
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if request.url.path.endswith(".json"):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
    if exc.status_code == 401 and request.method == "GET":
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(
        templates.get_template("error.html").render(status=exc.status_code, message=exc.detail),
        status_code=exc.status_code,
    )


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


def _login_page(request: Request, error: str | None = None, status_code: int = 200) -> Response:
    token, cookie = auth.new_pre_token(secret() or "unconfigured")
    response = templates.TemplateResponse(
        request,
        "login.html",
        {"error": error, "csrf": token, "configured": configured()},
        status_code=status_code,
    )
    response.set_cookie(
        auth.PRE_COOKIE,
        cookie,
        httponly=True,
        samesite="strict",
        secure=cookie_secure(),
        max_age=600,
    )
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if current_session(request) is not None:
        return RedirectResponse("/", status_code=303)
    return _login_page(request)


@app.post("/login")
async def login(request: Request):
    client = client_of(request)
    if not configured():
        return _login_page(request, "Not configured: run `./makhzan admin password`.", 503)
    if not _same_origin(request):
        raise HTTPException(403, "Cross-origin request refused.")
    fields = await form_of(request)
    expected = auth.read_pre_token(request.cookies.get(auth.PRE_COOKIE), secret())
    if not auth.tokens_match(fields.get("csrf"), expected):
        return _login_page(request, "The form expired; try again.", 403)
    wait = limiter.retry_after(client)
    if wait:
        response = _login_page(
            request, f"Too many failed attempts. Try again in {wait // 60 + 1} min.", 429
        )
        response.headers["Retry-After"] = str(wait)
        return response
    # Counted before the check and refunded if it succeeds: concurrent attempts
    # are each counted as they arrive, so they cannot slip past the limit
    # together while the first ones are still being verified.
    attempt = limiter.failed(client)
    try:
        # Half a second and 128 MiB of scrypt each: off the event loop, and at
        # most VERIFY_SLOTS at once, whatever arrives.
        async with VERIFY_SLOTS:
            right = await run_in_threadpool(
                auth.verify_password, fields.get("password", ""), password_hash()
            )
    except auth.HashUnusable as exc:
        limiter.refund(client, attempt)
        return _login_page(request, f"The stored password hash cannot be checked: {exc}", 503)
    if not right:
        async with SessionLocal() as db:
            await audit(db, request, "login.failed")
            await db.commit()
        return _login_page(request, "Wrong password.", 401)
    limiter.refund(client, attempt)
    limiter.succeeded(client)
    value, _ = auth.new_session(password_hash(), secret(), session_hours())
    async with SessionLocal() as db:
        await audit(db, request, "login")
        await db.commit()
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE,
        value,
        httponly=True,
        samesite="strict",
        secure=cookie_secure(),
        max_age=int(session_hours() * 3600),
    )
    response.delete_cookie(auth.PRE_COOKIE)
    return response


@app.post("/logout")
async def logout(request: Request):
    await checked_form(request)
    async with SessionLocal() as db:
        await audit(db, request, "logout")
        await db.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE)
    return response


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    if current_session(request) is None:
        return RedirectResponse("/login", status_code=303)
    async with SessionLocal() as db:
        counts = await data.nav_counts(db)
        view = await data.overview(db, counts)
    return await page(request, "overview.html", "status", {"o": view})


@app.get("/crawl", response_class=HTMLResponse)
async def crawl_view(request: Request):
    if current_session(request) is None:
        return RedirectResponse("/login", status_code=303)
    await sweep_lost_jobs()
    async with SessionLocal() as db:
        view = await data.crawl_view(db)
    return await page(request, "crawl.html", "crawl", {"c": view, "max_limit": MAX_LIMIT})


@app.get("/catalog", response_class=HTMLResponse)
async def catalog_view(
    request: Request,
    shop: str = "",
    sort: str = "total",
    q: str = "",
    ushop: str = "",
    lookup: str = "",
):
    if current_session(request) is None:
        return RedirectResponse("/login", status_code=303)
    await sweep_lost_jobs()
    async with SessionLocal() as db:
        view = await data.catalog_view(
            db, shop=shop, sort=sort, q=q.strip()[:200], uncat_shop=ushop, look=lookup[:500]
        )
    return await page(request, "catalog.html", "catalog", {"k": view})


@app.get("/reports", response_class=HTMLResponse)
async def reports_view(request: Request):
    if current_session(request) is None:
        return RedirectResponse("/login", status_code=303)
    async with SessionLocal() as db:
        view = await data.reports_view(db)
    return await page(request, "reports.html", "reports", {"r": view})


@app.get("/overrides", response_class=HTMLResponse)
async def overrides_view(request: Request, remove: int | None = None):
    if current_session(request) is None:
        return RedirectResponse("/login", status_code=303)
    async with SessionLocal() as db:
        view = await data.overrides_view(db)
    return await page(request, "overrides.html", "overrides", {"v": view, "removing": remove})


async def _ai_page(request: Request, **extra):
    async with SessionLocal() as db:
        view = await data.ai_view(db)
    return await page(
        request,
        "ai.html",
        "ai",
        {"a": view, "models": sorted(MODELS), "policy": ACTIVE_POLICY, **extra},
    )


@app.get("/ai", response_class=HTMLResponse)
async def ai_view(request: Request):
    if current_session(request) is None:
        return RedirectResponse("/login", status_code=303)
    return await _ai_page(request)


@app.get("/activity", response_class=HTMLResponse)
async def activity(request: Request):
    if current_session(request) is None:
        return RedirectResponse("/login", status_code=303)
    async with SessionLocal() as db:
        rows = await data.recent_actions(db, 200)
    return await page(request, "activity.html", "activity", {"rows": rows})


@app.get("/jobs/{action_id}.json")
async def job_state(request: Request, action_id: int):
    if current_session(request) is None:
        raise HTTPException(401, "Sign in first.")
    await sweep_lost_jobs()
    async with SessionLocal() as db:
        row = await db.get(AdminAction, action_id)
    if row is None or row.status is None:
        raise HTTPException(404, "No such job.")
    return {"id": row.id, "status": row.status, "error": row.error}


# --------------------------------------------------------------------------- #
# Crawl actions
# --------------------------------------------------------------------------- #


@app.post("/crawl/pause")
async def crawl_pause(request: Request):
    _, fields = await checked_form(request)
    note = fields.get("note", "").strip()[:500] or None
    async with SessionLocal() as db:
        await crawl.set_crawl_pause(db, True, by=who(), note=note)
        await audit(db, request, "crawl.pause", None, {"note": note})
        await db.commit()
    return back(
        "/crawl",
        "Crawl paused: no daily job is queued, and a run going now stops before its next page.",
    )


@app.post("/crawl/resume")
async def crawl_resume(request: Request):
    await checked_form(request)
    async with SessionLocal() as db:
        await crawl.set_crawl_pause(db, False, by=who())
        await audit(db, request, "crawl.resume")
        env = await crawl.worker_crawl_enabled(db)
        await db.commit()
    if not env:
        return back(
            "/crawl",
            "Pause cleared, but CRAWL_ENABLED is off in the worker's environment, which this "
            "page cannot change: `./makhzan crawl on` on the server.",
            "warn",
        )
    return back("/crawl", "Crawl resumed: the next daily run queues every enabled shop.")


async def _source_or_404(db, source_id: str) -> Source:
    row = await db.scalar(select(Source).where(Source.source_id == source_id))
    if row is None:
        raise HTTPException(404, f"No source {source_id!r}.")
    return row


@app.post("/shops/{source_id}/pause")
async def shop_pause(request: Request, source_id: str):
    _, fields = await checked_form(request)
    note = fields.get("note", "").strip()[:500] or None
    async with SessionLocal() as db:
        await _source_or_404(db, source_id)
        await pause.pause_source(db, source_id, by=who(), note=note)
        await audit(db, request, "shop.pause", source_id, {"note": note})
        await db.commit()
    return back("/crawl", f"{source_id} paused; its cursors are kept.")


@app.post("/shops/{source_id}/resume")
async def shop_resume(request: Request, source_id: str):
    await checked_form(request)
    async with SessionLocal() as db:
        row = await _source_or_404(db, source_id)
        await pause.resume_source(db, source_id)
        await audit(db, request, "shop.resume", source_id)
        await db.commit()
    extra = "" if row.enabled else " It is still disabled in sources.toml, which keeps it off."
    return back("/crawl", f"{source_id} resumed from its next daily run.{extra}")


async def _queue_job(request: Request, action: str, target: str | None, detail: dict) -> int:
    async with SessionLocal() as db:
        row = await audit(db, request, action, target, detail, job=True)
        await db.commit()
        action_id = row.id
    try:
        await enqueue_admin_job(action_id)
    except Exception as exc:  # noqa: BLE001 — said on the row and on the page
        async with SessionLocal() as db:
            row = await db.get(AdminAction, action_id)
            row.status, row.error = "failed", f"could not queue it: {type(exc).__name__}: {exc}"
            row.finished_at = datetime.now(timezone.utc)
            await db.commit()
        raise HTTPException(503, f"Could not reach the worker's queue: {exc}") from exc
    return action_id


@app.post("/shops/{source_id}/run")
async def shop_run(request: Request, source_id: str):
    _, fields = await checked_form(request)
    try:
        limit = int(fields.get("limit", ""))
    except ValueError:
        limit = 0
    if not 1 <= limit <= MAX_LIMIT:
        return await refuse(
            request,
            "/crawl",
            RUN_LIMIT,
            source_id,
            f"Limit must be between 1 and {MAX_LIMIT}.",
            {"limit": fields.get("limit", "")[:20]},
        )
    async with SessionLocal() as db:
        await _source_or_404(db, source_id)
    await _queue_job(request, RUN_LIMIT, source_id, {"limit": limit})
    return back(
        "/crawl",
        f"Queued an ephemeral run of {source_id} with limit={limit}: cursors untouched, "
        "nothing archived.",
    )


@app.post("/shops/{source_id}/probe")
async def shop_probe(request: Request, source_id: str):
    await checked_form(request)
    async with SessionLocal() as db:
        await _source_or_404(db, source_id)
    await _queue_job(request, PROBE, source_id, {})
    return back(
        "/crawl",
        f"Queued the probe for {source_id}: robots.txt first, then browser, makhzanbot and "
        "signed, at least 15 s apart and through the crawl's own per-host gate.",
    )


# --------------------------------------------------------------------------- #
# Catalog actions
# --------------------------------------------------------------------------- #


@app.post("/catalog/regroup-dry-run")
async def regroup_dry_run(request: Request):
    await checked_form(request)
    await _queue_job(request, REGROUP_DRY_RUN, None, {})
    return back("/catalog", "Queued a regroup dry run: it reads every listing and writes nothing.")


# --------------------------------------------------------------------------- #
# Reports and overrides
# --------------------------------------------------------------------------- #


@app.post("/reports/{report_id}/{verdict}")
async def review(request: Request, report_id: int, verdict: str):
    await checked_form(request)
    if verdict not in ("accept", "reject"):
        raise HTTPException(404, "Accept or reject.")
    status = "accepted" if verdict == "accept" else "rejected"

    async def audited(db, done) -> None:
        detail = {
            "overrides": [{"id": a.row.id, "outcome": a.outcome} for a in done.added],
            "withdrawn": done.withdrawn,
        }
        if done.refused:
            detail["refused"] = done.refused
        await audit(db, request, f"report.{verdict}", str(report_id), detail)

    async with SessionLocal() as db:
        (done,) = await review_reports(db, [report_id], status, by=who(), audit=audited)
    if done.refused:
        return back("/reports", f"R-{report_id} not {status}: {done.refused}.", "error")
    lines = [f"R-{report_id} {status}."] + [ruling_line(a) for a in done.added]
    if done.withdrawn:
        lines.append(f"Withdrew {done.withdrawn} override(s) it had made.")
    return back("/reports", " ".join(lines))


def _listing_id(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value.strip())
    except (ValueError, AttributeError):
        return None


@app.post("/overrides/add")
async def override_add(request: Request):
    _, fields = await checked_form(request)
    a, b = _listing_id(fields.get("a", "")), _listing_id(fields.get("b", ""))
    kind = fields.get("kind", "")
    note = fields.get("note", "").strip()[:2000]
    forced = fields.get("forced") == "on"
    errors = []
    if a is None or b is None:
        errors.append("Both listings must be full listing ids.")
    if kind not in rulings.KINDS:
        errors.append("Kind is never_merge or must_merge.")
    if not note:
        errors.append("A note is required: say why.")
    asked = {"a": fields.get("a", "")[:64], "b": fields.get("b", "")[:64], "kind": kind[:16]}
    if errors:
        return await refuse(request, "/overrides", "override.add", None, " ".join(errors), asked)
    async with SessionLocal() as db:
        try:
            added = await add_override(db, a, b, kind, forced=forced, note=note, by=who())
        except OverrideRefused as refused:
            await db.rollback()
            return await refuse(request, "/overrides", "override.add", None, str(refused), asked)
        await audit(
            db,
            request,
            "override.add",
            str(added.row.id),
            {"a": str(a), "b": str(b), "kind": kind, "forced": forced, "outcome": added.outcome},
        )
        await db.commit()
    return back("/overrides", ruling_line(added), "error" if added.outcome == "conflict" else "ok")


@app.post("/overrides/{override_id}/remove")
async def override_remove(request: Request, override_id: int):
    _, fields = await checked_form(request)
    note = fields.get("note", "").strip()[:2000]
    if not note:
        return await refuse(
            request,
            f"/overrides?remove={override_id}#ov-{override_id}",
            "override.remove",
            str(override_id),
            "A note is required to remove an override.",
        )
    async with SessionLocal() as db:
        row = await rulings.remove(db, override_id, removed_by=who(), note=note)
        if row is None:
            raise HTTPException(404, f"No override #{override_id}.")
        await audit(db, request, "override.remove", str(override_id), {"note": note})
        await db.commit()
    return back(
        "/overrides",
        f"Removed #{override_id} (row kept); the next regroup undoes it and cites it.",
    )


# --------------------------------------------------------------------------- #
# AI
# --------------------------------------------------------------------------- #


@app.post("/ai/mode")
async def ai_set_mode(request: Request):
    _, fields = await checked_form(request)
    value = fields.get("mode", "")
    if value not in MODES:
        return await refuse(
            request, "/ai", "ai.mode", value[:16], f"The mode is one of {', '.join(MODES)}."
        )
    if fields.get("confirm") != "yes":
        return await refuse(request, "/ai", "ai.mode", value, "Confirm the change of mode first.")
    async with SessionLocal() as db:
        before = await ai_mode(db)
        await set_ai_mode(db, value)
        await audit(db, request, "ai.mode", value, {"before": before})
        await db.commit()
    return back(
        "/ai", f"AI matching mode: {before} -> {value}. It takes effect at the next regroup."
    )


@app.post("/ai/workers/add")
async def ai_worker_add(request: Request):
    _, fields = await checked_form(request)
    name = fields.get("name", "").strip()
    models = [m for m in MODELS if fields.get(f"model_{m}") == "on"]
    if not (3 <= len(name) <= 32) or not all(c.isalnum() or c in "-_" for c in name):
        return await refuse(
            request,
            "/ai",
            "ai.worker.add",
            name[:64],
            "Name it with 3-32 letters, digits, hyphens or underscores.",
        )
    async with SessionLocal() as db:
        try:
            token = await ai_cli.add_worker(db, name, models)
        except ai_cli.Refused as refused:
            await db.rollback()
            return await refuse(request, "/ai", "ai.worker.add", name, str(refused))
        await audit(db, request, "ai.worker.add", name, {"models": models})
        await db.commit()
    # Rendered, not redirected: the token is shown this once and never put in a URL.
    return await _ai_page(request, issued={"name": name, "token": token, "models": models})


@app.post("/ai/workers/{name}/revoke")
async def ai_worker_revoke(request: Request, name: str):
    _, fields = await checked_form(request)
    if fields.get("confirmed") != "yes":
        return await refuse(
            request, "/ai", "ai.worker.revoke", name, f"Click revoke twice to revoke {name}."
        )
    async with SessionLocal() as db:
        try:
            await ai_cli.revoke_worker(db, name)
        except ai_cli.Refused as refused:
            await db.rollback()
            return await refuse(request, "/ai", "ai.worker.revoke", name, str(refused))
        await audit(db, request, "ai.worker.revoke", name)
        await db.commit()
    return back("/ai", f"Revoked {name}: its token is refused from now on; its leases requeue.")


@app.post("/ai/flags/{flag_id}/dismiss")
async def ai_flag_dismiss(request: Request, flag_id: int):
    _, fields = await checked_form(request)
    note = fields.get("note", "").strip()[:2000]
    if not note:
        return await refuse(
            request, "/ai", "ai.flag.dismiss", str(flag_id), "A note is required to dismiss a flag."
        )
    async with SessionLocal() as db:
        missing = await ai_cli.dismiss_flags(db, [flag_id], note=note, by=who())
        if missing:
            await db.rollback()
            return await refuse(
                request, "/ai", "ai.flag.dismiss", str(flag_id), f"#{flag_id} is not an open flag."
            )
        await audit(db, request, "ai.flag.dismiss", str(flag_id), {"note": note})
        await db.commit()
    return back("/ai", f"Flag #{flag_id} dismissed.")


@app.post("/ai/decisions/{decision_id}/revoke")
async def ai_decision_revoke(request: Request, decision_id: int):
    """No confirm (owner), but a note, as `./makhzan ai revoke --note` requires (owner)."""
    _, fields = await checked_form(request)
    note = fields.get("note", "").strip()[:2000]
    if not note:
        return await refuse(
            request,
            "/ai",
            "ai.decision.revoke",
            str(decision_id),
            "A note is required to revoke a decision: say why.",
        )
    async with SessionLocal() as db:
        decision, cancelled, refusal = await flow.revoke_decision(
            db, decision_id, by=who(), note=note
        )
        if refusal:
            await db.rollback()
            return await refuse(
                request, "/ai", "ai.decision.revoke", str(decision_id), refusal, {"note": note}
            )
        await audit(db, request, "ai.decision.revoke", str(decision_id), {"note": note})
        await db.commit()
    return back(
        "/ai",
        f"Revoked #{decision_id}; {cancelled} queued job(s) cancelled. The next regroup undoes "
        "what it joined.",
    )


@app.post("/ai/redecide")
async def ai_redecide(request: Request):
    await checked_form(request)
    async with SessionLocal() as db:
        result = await ai_cli.redecide(db, ACTIVE_POLICY)
        await audit(db, request, "ai.redecide_dry_run", ACTIVE_POLICY, {"counts": result["counts"]})
        await db.commit()
    return await _ai_page(request, redecided=result)
