"""What each dashboard view shows, read through the same functions as the terminal.

Every number on the crawl and catalog views comes from `worker.status`'s
`collect_*` functions (what `make status` prints), the AI view from
`makhzan_schemas.ai.status.collect` (what `./makhzan ai status` prints), the
pauses from `makhzan_schemas.crawl` and `worker.pause`, and reports and
rulings from the tables their CLIs read. What is here and nowhere else is
arrangement: the "needs attention" list, which only orders and words what
those functions found, and a few lookups the terminal has no command for
(the uncategorised browser, the product lookup, the AI merges to review).
"""

from __future__ import annotations

import math
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from makhzan_schemas import crawl
from makhzan_schemas import reports as report_rules
from makhzan_schemas.ai.decisions import STANDING
from makhzan_schemas.ai.pipelines import PIPELINES
from makhzan_schemas.enums import IngestionStatus, ListingStatus
from makhzan_schemas.models import (
    AdminAction,
    AiDecision,
    AiFlag,
    Category,
    GroupingOverride,
    IngestionRun,
    Listing,
    Product,
    ProductEvent,
    Report,
    Source,
    Supplier,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from worker import status
from worker.admin_jobs import PROBE, REGROUP_DRY_RUN, RUN_LIMIT
from worker.reports import REASON_TEXT

SEVERITY_ORDER = {"crit": 0, "warn": 1, "info": 2}

#: A product-page backlog this many runs deep is called out.
DETAILS_BEHIND_RUNS = 10
#: Data shown on the site older than this is critical, not a warning.
STALE_CRIT_DAYS = 45


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Shared pieces
# --------------------------------------------------------------------------- #


async def nav_counts(session) -> dict[str, int]:
    """The small counts beside the views' names: cheap queries only."""
    reports = await report_rules.count_new(session)
    blocked = await session.scalar(
        select(func.count())
        .select_from(GroupingOverride)
        .where(GroupingOverride.removed_at.is_(None), GroupingOverride.status == "blocked")
    )
    flags = await session.scalar(
        select(func.count()).select_from(AiFlag).where(AiFlag.status == "open")
    )
    since = _now() - timedelta(hours=48)
    failing = await session.scalar(
        select(func.count(func.distinct(IngestionRun.source))).where(
            IngestionRun.started_at >= since,
            IngestionRun.status.in_((IngestionStatus.FAILED, IngestionStatus.PARTIAL)),
        )
    )
    return {
        "crawl": failing or 0,
        "reports": reports or 0,
        "overrides": blocked or 0,
        "ai": flags or 0,
    }


async def crawl_switch(session) -> dict:
    """The crawl-wide switches: the worker's `CRAWL_ENABLED`, and the database pause."""
    configured = os.getenv("CRAWL_ENABLED")
    return {
        "env": await crawl.worker_crawl_enabled(session),
        "configured": configured if configured is not None else "true (unset)",
        "pause": await crawl.crawl_pause(session),
        # What the worker and /how-we-crawl go by: both switches.
        "on": await crawl.crawl_enabled_in(session),
    }


async def _latest_actions(session, action: str, limit: int = 200) -> dict[str, AdminAction]:
    """The newest action of a kind, by target."""
    rows = await session.scalars(
        select(AdminAction)
        .where(AdminAction.action == action)
        .order_by(AdminAction.id.desc())
        .limit(limit)
    )
    out: dict[str, AdminAction] = {}
    for row in rows:
        out.setdefault(row.target or "", row)
    return out


async def recent_jobs(session, limit: int = 10) -> list[AdminAction]:
    return list(
        await session.scalars(
            select(AdminAction)
            .where(AdminAction.status.is_not(None))
            .order_by(AdminAction.id.desc())
            .limit(limit)
        )
    )


async def recent_actions(session, limit: int = 30) -> list[AdminAction]:
    return list(
        await session.scalars(select(AdminAction).order_by(AdminAction.id.desc()).limit(limit))
    )


async def health() -> list[dict]:
    """The API's and the broker's health endpoints, as `./makhzan status` asks them."""
    checks = [
        ("API", os.getenv("ADMIN_API_HEALTH_URL", "http://api:8000/health")),
        ("AI broker", os.getenv("ADMIN_BROKER_HEALTH_URL", "http://broker:8100/ai/v1/health")),
    ]
    out = []
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in checks:
            try:
                ok = (await client.get(url)).status_code == 200
                out.append({"name": name, "url": url, "ok": ok, "error": None})
            except httpx.HTTPError as exc:
                out.append({"name": name, "url": url, "ok": False, "error": type(exc).__name__})
    return out


# --------------------------------------------------------------------------- #
# Crawl
# --------------------------------------------------------------------------- #


async def _sweeps(session) -> tuple[dict, list[dict]]:
    """Sweep progress for every source: `collect_sweep_progress`, plus sources never swept."""
    progress = await status.collect_sweep_progress(session, None)
    by_source = {e["source"]: e for e in progress["sources"]}
    rows = (await session.execute(select(Source).order_by(Source.source_id))).scalars().all()
    out = []
    for row in rows:
        entry = by_source.pop(row.source_id, None)
        if entry is None:
            entry = {
                "source": row.source_id,
                "done": 0,
                "total": progress["declared"]["partitions"].get(row.source_id, 0),
                "shop": (row.supplier or {}).get("slug") or row.source_id,
                "state": "paused" if status.is_paused(row.enabled, row.paused_at) else "never",
                "disabled": not row.enabled,
                "paused": (
                    {"at": row.paused_at, "by": row.paused_by, "note": row.pause_note}
                    if row.paused_at
                    else None
                ),
                "cycle_started_at": None,
                "active_since": None,
                "last_finished": None,
                "pending": [],
            }
        entry["base_url"] = row.base_url
        out.append(entry)
    out.extend(by_source.values())  # cursors of a source no longer in the table
    return progress["declared"], out


def _details_runs_to_catch_up(entry: dict) -> int | None:
    q, per_run = entry.get("queue"), entry.get("per_run")
    if not q or not per_run or entry.get("reader") != "pages_on":
        return None
    return math.ceil((q["changed"] + q["never_fetched"] + q["stale"]) / per_run)


async def crawl_view(session) -> dict:
    declared, sweeps = await _sweeps(session)
    details = await status.collect_product_details(session, None)
    for entry in details["sources"]:
        entry["runs_to_catch_up"] = _details_runs_to_catch_up(entry)
    return {
        "switch": await crawl_switch(session),
        "declared": declared,
        "sweeps": sweeps,
        "probes": await _latest_actions(session, PROBE),
        "runs_now": await _latest_actions(session, RUN_LIMIT),
        "runs": await status.collect_recent_runs(session, None, 8),
        "cycles": await status.collect_cycle_history(session, None),
        "budget": await status.collect_cycle_budget(session, None),
        "t1": await status.collect_short_page_end(session, None),
        "confirm": await status.collect_archive_confirmation(session, None),
        "identity": await status.collect_crawler_identity(session, None),
        "robots": await status.collect_robots_health(session, None),
        "stale_copy_days": status.STALE_COPY_WARN_DAYS,
        "drift": await status.collect_crosswalk_drift(session, None),
        "details": details,
        "jobs": await recent_jobs(session),
    }


# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #


def _item(sev: str, title: str, detail: str, href: str, actions: list | None = None) -> dict:
    return {"sev": sev, "title": title, "detail": detail, "href": href, "actions": actions or []}


def attention(view: dict) -> list[dict]:
    """What needs looking at first, most serious first, from what the collectors found."""
    items: list[dict] = []
    now = _now()
    sw = view["switch"]
    if not sw["on"]:
        why = (
            f"paused by {sw['pause'].get('by')}"
            + (f": {sw['pause']['note']}" if sw["pause"] and sw["pause"].get("note") else "")
            if sw["pause"]
            else "CRAWL_ENABLED is off in the worker's environment"
        )
        items.append(_item("warn", "The daily crawl is off", why, "/crawl"))
    for source_id, error in view["declared"]["errors"].items():
        items.append(
            _item("crit", f"{source_id} does not load", f"Not being swept: {error}", "/crawl")
        )

    catalog = {}
    for row in view["catalog"]:
        c = catalog.setdefault(row["shop"], {"total": 0, "verified": None})
        c["total"] += row["total"]
        if row["verified"] and (c["verified"] is None or row["verified"] > c["verified"]):
            c["verified"] = row["verified"]
    last_errors: dict[str, str] = {}
    for run in view["runs_all"]:
        if run["errors"] and run["source"] not in last_errors:
            last_errors[run["source"]] = run["errors"][0]

    for s in view["sweeps"]:
        if s["state"] == "stalled":
            items.append(
                _item(
                    "crit",
                    f"{s['source']}: sweep stalled",
                    f"An open cycle and no run finished in "
                    f"{status.STALLED_AFTER.total_seconds() / 3600:.0f} h: the cron, a crash "
                    "or a blocking host is holding it.",
                    "/crawl",
                    [("probe", s["source"])],
                )
            )
        elif s["state"] == "paused":
            # The catalogue is by shop (supplier slug), which need not be the source id.
            shop = catalog.get(s.get("shop") or s["source"]) or {}
            verified = shop.get("verified")
            days = (now - verified).days if verified else None
            detail = status.pause_text(s)
            if shop.get("total"):
                detail += f". {shop['total']:,} listings"
                if days is not None:
                    detail += f", last checked {days} days ago"
            if s["source"] in last_errors:
                detail += f". Last error: {last_errors[s['source']][:120]}"
            sev = "crit" if days is not None and days >= STALE_CRIT_DAYS else "warn"
            items.append(
                _item(sev, f"{s['source']} is paused", detail, "/crawl", [("probe", s["source"])])
            )

    for run in view["runs"]:
        if run["status"] in ("partial", "failed") and run["started_at"] >= now - timedelta(
            hours=48
        ):
            msg = run["errors"][0] if run["errors"] else (run["error"] or "no error recorded")
            if msg.rstrip().endswith(":"):
                # "partition p1: TimeoutError: " with an exception that carried no text.
                msg = f"{msg.rstrip()} (empty error message)"
            items.append(
                _item(
                    "warn",
                    f"{run['source']}: {run['status']} run",
                    f"{msg[:160]}",
                    "/crawl",
                )
            )

    for source, entry in view["robots"].items():
        for host, said in entry["hosts"].items():
            state = said.get("state")
            if state == "stale" and (said.get("copy_age_days") or 0) > view["stale_copy_days"]:
                items.append(
                    _item(
                        "warn",
                        f"{source}: robots.txt unreadable",
                        f"{host} served from a copy {said.get('copy_age_days')} days old",
                        "/crawl",
                    )
                )
            elif state not in ("fetched", "no_rules", "stale", None):
                items.append(
                    _item(
                        "crit",
                        f"{source}: robots.txt unavailable",
                        f"{host}: {said.get('error', '')}; the host is refused",
                        "/crawl",
                    )
                )

    for e in view["details"]["sources"]:
        n = e.get("runs_to_catch_up")
        if n and n >= DETAILS_BEHIND_RUNS:
            q = e["queue"]
            items.append(
                _item(
                    "warn",
                    f"{e['source']}: product details far behind",
                    f"{q['never_fetched']:,} never fetched, {q['changed']:,} changed, "
                    f"{q['stale']:,} stale; at {e['per_run']} a run that is about {n} runs.",
                    "/crawl",
                )
            )

    for d in view["drift"]:
        if d["unmapped"]:
            top = ", ".join(f"{name} ({n})" for name, n in list(d["unmapped"].items())[:3])
            items.append(
                _item(
                    "warn",
                    f"Crosswalk drift: {len(d['unmapped'])} unmapped at {d['source']}",
                    f"{sum(d['unmapped'].values()):,} listings, led by {top}.",
                    "/crawl#drift",
                )
            )
        if d["unused"]:
            items.append(
                _item(
                    "warn",
                    f"Crosswalk drift: {d['unused_count']} entries never matched at {d['source']}",
                    ", ".join(d["unused"][:6]),
                    "/crawl#drift",
                )
            )

    idx = view["index"]
    if idx["indexed"] is not None and idx["indexed"] != idx["products"]:
        items.append(
            _item(
                "warn",
                "Search index has drifted",
                f"{idx['products']:,} listed products, {idx['indexed']:,} indexed: the next "
                "rebuild catches up (or `make reindex`).",
                "/catalog",
            )
        )
    if view["counts"]["overrides"]:
        items.append(
            _item(
                "warn",
                f"{view['counts']['overrides']} override(s) BLOCKED",
                "An existing product wins over a ruling it contradicts.",
                "/overrides",
            )
        )
    ai = view["ai"]
    if "error" not in ai and ai.get("flags"):
        flags = ", ".join(f"{k} {n}" for k, n in ai["flags"].items())
        items.append(_item("warn", "AI flags open", flags, "/ai"))
    uncat = [(r["shop"], r["uncategorized"]) for r in view["catalog"] if r["uncategorized"]]
    if uncat:
        by_shop: dict[str, int] = {}
        for shop, n in uncat:
            by_shop[shop] = by_shop.get(shop, 0) + n
        ranked = sorted(by_shop.items(), key=lambda kv: -kv[1])
        items.append(
            _item(
                "info",
                f"{sum(by_shop.values()):,} uncategorised listings",
                ", ".join(f"{shop} {n:,}" for shop, n in ranked),
                "/catalog#uncat",
            )
        )
    if view["counts"]["reports"]:
        items.append(
            _item("info", f"{view['counts']['reports']} visitor report(s) open", "", "/reports")
        )
    return sorted(items, key=lambda i: SEVERITY_ORDER[i["sev"]])


async def overview(session, counts: dict) -> dict:
    declared, sweeps = await _sweeps(session)
    details = await status.collect_product_details(session, None)
    for entry in details["sources"]:
        entry["runs_to_catch_up"] = _details_runs_to_catch_up(entry)
    view = {
        "switch": await crawl_switch(session),
        "declared": declared,
        "sweeps": sweeps,
        "runs": await status.collect_recent_runs(session, None, 8),
        "runs_all": await status.collect_recent_runs(session, None, 60),
        "robots": await status.collect_robots_health(session, None),
        "stale_copy_days": status.STALE_COPY_WARN_DAYS,
        "drift": await status.collect_crosswalk_drift(session, None),
        "details": details,
        "catalog": await status.collect_catalog(session, None),
        "index": await status.collect_index_drift(session),
        "prices": await status.collect_price_history(session),
        "review": await status.collect_review_queue(session),
        "queue": status.collect_queue_depth(),
        "ai": await status.collect_ai_matching(session),
        "counts": counts,
        "health": await health(),
        "git_sha": os.getenv("GIT_SHA") or None,
        "oldest_report": await session.scalar(
            select(func.min(Report.created_at)).where(Report.status == "new")
        ),
    }
    view["attention"] = attention(view)
    view["shops"] = len({s["source"] for s in sweeps})
    view["paused_shops"] = sum(1 for s in sweeps if s["state"] == "paused")
    return view


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #

UNCAT_LIMIT = 100


def _web_url(url: str | None) -> str | None:
    """`url` if it is http(s), else None: never a `javascript:` or `data:` link."""
    if url and url.strip().lower().startswith(("https://", "http://")):
        return url.strip()
    return None


def _shop_category(attributes: dict | None) -> str:
    """The shop's own category for a listing, where its adapter keeps one."""
    path = (attributes or {}).get("shop_category_path")
    if isinstance(path, list):
        return " > ".join(str(p) for p in path)
    return str(path or "")


async def uncategorised(session, q: str, shop: str) -> dict:
    """Active listings with no category, searchable by title or shop category."""
    where = [Listing.status == ListingStatus.ACTIVE, Listing.category_id.is_(None)]
    if shop:
        where.append(Supplier.slug == shop)
    if q:
        like = f"%{q}%"
        where.append(
            or_(
                Listing.title_en.ilike(like),
                Listing.attributes["shop_category_path"].astext.ilike(like),
            )
        )
    base = select(Listing).join(Supplier, Supplier.id == Listing.supplier_id).where(*where)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        await session.scalars(
            base.options(selectinload(Listing.supplier))
            .order_by(Supplier.slug, Listing.title_en)
            .limit(UNCAT_LIMIT)
        )
    ).all()
    shops = list(
        await session.scalars(
            select(Supplier.slug)
            .join(Listing, Listing.supplier_id == Supplier.id)
            .where(Listing.status == ListingStatus.ACTIVE, Listing.category_id.is_(None))
            .group_by(Supplier.slug)
            .order_by(Supplier.slug)
        )
    )
    return {
        "total": total or 0,
        "shops": shops,
        "rows": [
            {
                "id": r.id,
                "title": r.title_en or r.title_ar or "(untitled)",
                "shop": r.supplier.slug if r.supplier else r.source,
                "category": _shop_category(r.attributes),
                "price": r.price,
                "currency": r.currency,
                # Linked only when it is a web address: the URL came from a shop.
                "url": _web_url(r.source_url),
            }
            for r in rows
        ],
        "limit": UNCAT_LIMIT,
    }


_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


async def lookup(session, q: str) -> dict:
    """A product, from its id, a listing id, a makhzan URL holding either, or a shop URL."""
    q = (q or "").strip()
    if not q:
        return {"q": q, "error": None, "product": None}
    listing = None
    product = None
    if found := _UUID.search(q):
        ident = uuid.UUID(found.group(0))
        product = await session.get(Product, ident)
        if product is None:
            listing = await session.get(Listing, ident)
    else:
        listing = await session.scalar(select(Listing).where(Listing.source_url == q).limit(1))
    if product is None and listing is not None and listing.product_id:
        product = await session.get(Product, listing.product_id)
    if product is None:
        return {"q": q, "error": "No product or listing matches that.", "product": None}
    redirected = None
    while product.merged_into is not None:
        redirected = redirected or product.id
        product = await session.get(Product, product.merged_into)
    category = await session.get(Category, product.category_id) if product.category_id else None
    listings = (
        await session.scalars(
            select(Listing)
            .where(Listing.product_id == product.id)
            .options(selectinload(Listing.supplier))
            .order_by(Listing.status, Listing.price.nulls_last())
        )
    ).all()
    events = (
        await session.scalars(
            select(ProductEvent)
            .where(or_(ProductEvent.product_id == product.id, ProductEvent.other_id == product.id))
            .order_by(ProductEvent.created_at.desc())
            .limit(20)
        )
    ).all()
    return {
        "q": q,
        "error": None,
        "product": product,
        "redirected_from": redirected,
        "category": f"{category.domain}:{category.slug}" if category else None,
        "listings": listings,
        "events": events,
        "site_url": (os.getenv("SITE_URL") or "").rstrip("/"),
    }


def _sort_catalog(rows: list[dict], shop: str, sort: str) -> list[dict]:
    rows = [r for r in rows if not shop or r["shop"] == shop]
    if sort == "shop":
        return sorted(rows, key=lambda r: (r["shop"], -r["total"]))
    key = {"uncat": "uncategorized", "noprice": "unpriced"}.get(sort, "total")
    return sorted(rows, key=lambda r: -r[key])


async def catalog_view(
    session, *, shop: str, sort: str, q: str, uncat_shop: str, look: str
) -> dict:
    rows = await status.collect_catalog(session, None)
    shown = _sort_catalog(rows, shop, sort)
    dry = await session.scalar(
        select(AdminAction)
        .where(AdminAction.action == REGROUP_DRY_RUN)
        .order_by(AdminAction.id.desc())
        .limit(1)
    )
    return {
        "rows": shown,
        "shops": sorted({r["shop"] for r in rows}),
        "shop": shop,
        "sort": sort,
        "totals": {
            k: sum(r[k] for r in shown)
            for k in ("total", "archived", "uncategorized", "unpriced", "on_request")
        },
        "index": await status.collect_index_drift(session),
        "prices": await status.collect_price_history(session),
        "dry_run": dry,
        "uncat": await uncategorised(session, q, uncat_shop),
        "q": q,
        "uncat_shop": uncat_shop,
        "lookup": await lookup(session, look),
    }


# --------------------------------------------------------------------------- #
# Reports and overrides
# --------------------------------------------------------------------------- #


def accept_preview(report: Report) -> str:
    """What accepting this report will do, in words, before it is clicked."""
    listings = ((report.snapshot or {}).get("product") or {}).get("listings") or []
    if report.reason == "offers_not_same":
        ticked = sum(1 for x in listings if x.get("ticked"))
        unticked = len(listings) - ticked
        return (
            f"Records up to {ticked * unticked} never_merge override(s): every ticked offer "
            "against every unticked one (as `./makhzan reports accept`)."
        )
    if report.reason == "same_as_other":
        return "Records one must_merge override between a listing of each product."
    if report.reason == "wrong_price_stock":
        return (
            "Marks the ticked offer(s) to be re-read first by their shop's next run: by id "
            "where the shop allows it, else at its partition's turn (see Re-checks pending "
            "below)."
        )
    return "Closes it; no ruling is recorded for this kind of report."


async def reports_view(session) -> dict:
    # The adapters say how each shop honours a re-check (worker/recheck.py).
    await status.collect_declared_partitions(session)
    month = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = await report_rules.new_reports(session, limit=50)
    recent = list(
        await session.scalars(
            select(Report)
            .where(Report.status != "new")
            .order_by(Report.reviewed_at.desc())
            .limit(10)
        )
    )
    return {
        "reports": [
            {"row": r, "reason": REASON_TEXT.get(r.reason, r.reason), "preview": accept_preview(r)}
            for r in rows
        ],
        "open": await report_rules.count_new(session),
        "closed_month": await session.scalar(
            select(func.count())
            .select_from(Report)
            .where(Report.status != "new", Report.reviewed_at >= month)
        ),
        "recent": [(r, REASON_TEXT.get(r.reason, r.reason)) for r in recent],
        "rechecks": await status.collect_rechecks(session),
    }


async def overrides_view(session) -> dict:
    rows = list(
        await session.scalars(
            select(GroupingOverride).order_by(GroupingOverride.id.desc()).limit(300)
        )
    )
    ids = {i for row in rows for i in (row.listing_a, row.listing_b, row.blocked_by) if i}
    listings = {
        listing.id: listing
        for listing in await session.scalars(
            select(Listing).where(Listing.id.in_(ids)).options(selectinload(Listing.supplier))
        )
    }
    last_regroup = await session.scalar(select(func.max(GroupingOverride.checked_at)))
    return {"rows": rows, "listings": listings, "last_regroup": last_regroup}


# --------------------------------------------------------------------------- #
# AI
# --------------------------------------------------------------------------- #

MERGES_LIMIT = 40


async def ai_merges(session) -> list[dict]:
    """Standing "same" decisions of a deciding pipeline, the ones in effect first.

    In effect means a listing's `matched_via` is `ai` through this decision:
    a pair the models merged that no rule would have (the regroup writes it,
    and only while the mode is live). With the mode off there are none in
    effect, and these are what going live would merge.
    """
    deciding = [p.name for p in PIPELINES.values() if p.decides]
    in_effect = select(Listing.matched_ai_decision_id).where(
        Listing.matched_via == "ai", Listing.matched_ai_decision_id.is_not(None)
    )
    rows = (
        await session.execute(
            select(AiDecision, AiDecision.id.in_(in_effect).label("merged"))
            .where(
                AiDecision.state == STANDING,
                AiDecision.outcome == "same",
                AiDecision.pipeline.in_(deciding),
            )
            .order_by(AiDecision.id.in_(in_effect).desc(), AiDecision.id.desc())
            .limit(MERGES_LIMIT)
        )
    ).all()
    ids = {i for d, _ in rows for i in (d.listing_a, d.listing_b)}
    listings = {
        x.id: x
        for x in await session.scalars(
            select(Listing).where(Listing.id.in_(ids)).options(selectinload(Listing.supplier))
        )
    }
    return [
        {
            "decision": d,
            "merged": bool(merged),
            "a": listings.get(d.listing_a),
            "b": listings.get(d.listing_b),
        }
        for d, merged in rows
    ]


def _queue_rows(data: dict) -> list[dict]:
    """`collect`'s queue by pipeline and stage, with the stage's model and its nights to drain."""
    rows = []
    for key, entry in sorted(data.get("queue", {}).items()):
        pipeline_name, stage = key.split(".", 1)
        model = None
        if (p := PIPELINES.get(pipeline_name)) is not None:
            try:
                model = p.stage(stage).model
            except ValueError:
                model = None
        rows.append(
            {
                "pipeline": pipeline_name,
                "stage": stage,
                "model": model,
                **entry,
                "nights": (data.get("nights") or {}).get(model),
            }
        )
    return rows


def _spark(daily: dict[str, int], now: datetime) -> dict:
    """The last 7 UTC days' scores, oldest first, as an SVG path 280 by 60."""
    days = [(now - timedelta(days=i)).date().isoformat() for i in range(6, -1, -1)]
    values = [int(daily.get(d, 0)) for d in days]
    top = max(values) or 1
    xs = [10 + i * (258 / 6) for i in range(7)]
    ys = [50 - 40 * v / top for v in values]
    line = " ".join(
        f"{'M' if i == 0 else 'L'}{x:.0f} {y:.0f}" for i, (x, y) in enumerate(zip(xs, ys))
    )
    return {
        "days": days,
        "counts": values,
        "line": line,
        "area": f"{line} L{xs[-1]:.0f} 50 L{xs[0]:.0f} 50Z",
        "last": (xs[-1], ys[-1]),
        "min": min(values),
        "max": max(values),
    }


async def ai_view(session) -> dict:
    data = await status.collect_ai_matching(session)
    flags = list(
        await session.scalars(
            select(AiFlag).where(AiFlag.status == "open").order_by(AiFlag.id.desc()).limit(50)
        )
    )
    ok = "error" not in data
    totals = {"same": 0, "not_same": 0, "stale": 0, "revoked": 0}
    for entry in (data.get("decisions") or {}).values():
        for key in totals:
            totals[key] += entry.get(key, 0)
    return {
        "status": data,
        "flags": flags,
        "merges": await ai_merges(session),
        "pipelines": PIPELINES,
        "queue": _queue_rows(data) if ok else [],
        "spark": _spark(data.get("daily") or {}, _now()) if ok else None,
        "totals": totals,
    }
