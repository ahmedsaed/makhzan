"""Dump every ACTIVE listing from a local database copy to JSON lines, for the bake-off.

    python3 ml/bakeoff/catalogue.py --out <private dir>/catalogue.jsonl

Reads through `docker exec <container> psql` (read-only SELECT), so it needs no driver on the
host. The output holds catalogue text: write it outside the repo (the scratchpad) or under
ml/out, which git ignores. Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

SQL = r"""
COPY (
  SELECT json_build_object(
    'id', l.id, 'supplier_id', l.supplier_id, 'source', l.source,
    'external_id', l.external_id, 'domain', l.domain,
    'title_en', l.title_en, 'title_ar', l.title_ar,
    'part_number', l.part_number, 'brand', l.brand, 'price', l.price,
    'stock_signal', l.stock_signal, 'product_id', l.product_id,
    'first_seen_at', l.first_seen_at, 'category', c.name_en,
    'description', l.description_en,
    'attributes', l.attributes - 'documents' - 'videos' - 'variants'
  )
  FROM listings l LEFT JOIN categories c ON c.id = l.category_id
  WHERE l.status = 'ACTIVE'
  ORDER BY l.source, l.external_id, l.id
) TO STDOUT
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--container", default="makhzan-db-1")
    ap.add_argument("--user", default="makhzan")
    ap.add_argument("--db", default="makhzan")
    args = ap.parse_args()
    cmd = ["docker", "exec", "-i", args.container, "psql", "-U", args.user, "-d", args.db]
    cmd += ["-v", "ON_ERROR_STOP=1", "-At", "-c", SQL]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    # COPY's text format escapes backslashes; json_build_object output only needs them undone.
    lines = [line.replace("\\\\", "\\") for line in out.splitlines() if line.strip()]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} listings -> {args.out}")


if __name__ == "__main__":
    main()
