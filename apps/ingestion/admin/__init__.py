"""makhzan's internal admin dashboard (docs/admin.md).

A small FastAPI + Jinja app run from the ingestion image as its own service,
reached only over Tailscale. It reads through the same functions as `make
status` and `./makhzan` (worker.status, worker.reports, worker.overrides,
worker.ai, worker.pause) and queues its long jobs to the worker
(worker.admin_jobs).
"""
