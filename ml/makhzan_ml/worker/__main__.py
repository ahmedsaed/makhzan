"""`python -m makhzan_ml.worker --config PATH [--check]`: one worker session."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from makhzan_ml.worker import run
from makhzan_ml.worker.config import ConfigError, load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m makhzan_ml.worker", description=__doc__)
    ap.add_argument("--config", required=True, help="the worker's TOML file")
    ap.add_argument("--check", action="store_true", help="validate the configuration and exit")
    ap.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        cfg = load(args.config)
    except ConfigError as e:
        logging.error("configuration: %s", e)
        return run.EXIT_CONFIG
    if args.check:
        from makhzan_ml.worker.judges import importable

        if not importable(cfg.model):
            logging.error(
                "configuration: this image cannot load %r (each model image holds one "
                "model's code)",
                cfg.model,
            )
            return run.EXIT_CONFIG
        logging.info(
            "configuration ok: %s serves %s on %s %s, window %s, on_empty %s",
            cfg.name,
            cfg.model,
            cfg.device,
            cfg.dtype,
            cfg.schedule.describe(),
            cfg.schedule.on_empty,
        )
        return run.EXIT_OK
    worker = run.Worker(cfg, image=os.environ.get("MAKHZAN_IMAGE"))
    worker.install_signal_handlers()
    return worker.run()


if __name__ == "__main__":
    sys.exit(main())
