"""makhzan API entrypoint.

Directory/discovery backend. Serves the consumer search/browse API and the
supplier-portal API. Reads from Postgres + Meilisearch; the ingestion worker
(apps/ingestion) is what writes new listings.
"""

import os

from app.routers import (
    categories,
    crawler,
    history,
    listings,
    products,
    search,
    sitemap,
    suppliers,
    wellknown,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="makhzan API", version="0.1.0")

# The Next.js frontend calls this API from the browser (a different origin),
# so CORS must allow it. Configurable via WEB_ORIGINS (comma-separated).
_origins = os.getenv("WEB_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(search.router)
app.include_router(listings.router)
app.include_router(products.router)
app.include_router(categories.router)
app.include_router(suppliers.router)
app.include_router(sitemap.router)
app.include_router(crawler.router)
app.include_router(history.router)
app.include_router(wellknown.router)
