from __future__ import annotations

import argparse
import json
import time

from fridge_api.config import get_settings
from fridge_api.db import SessionLocal
from fridge_api.services.enrichment.worker import EnrichmentWorker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enrich Fridge products with nutrition and images")
    parser.add_argument(
        "--once", action="store_true", help="Drain currently available jobs and exit"
    )
    parser.add_argument("--limit", type=int, default=100, help="Maximum jobs per drain cycle")
    parser.add_argument("--poll-interval", type=float, default=None)
    parser.add_argument(
        "--reprocess-placeholders",
        action="store_true",
        help="Re-enrich products that still have dummy 150/5/5/10 nutrition",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    settings = get_settings()
    worker = EnrichmentWorker(settings=settings, session_factory=SessionLocal)
    recovered = worker.recover_stale_jobs()
    processed = 0
    placeholders: list[dict[str, object]] = []
    try:
        if args.reprocess_placeholders:
            placeholders = worker.reprocess_placeholders(limit=args.limit)
        while True:
            cycle = 0
            while cycle < args.limit and worker.process_next():
                cycle += 1
                processed += 1
            if args.once:
                print(
                    json.dumps(
                        {
                            "processed": processed,
                            "recovered": recovered,
                            "placeholders": placeholders,
                        },
                        ensure_ascii=False,
                    )
                )
                return
            time.sleep(args.poll_interval or settings.enrichment_poll_seconds)
    except KeyboardInterrupt:
        print(
            json.dumps(
                {"processed": processed, "recovered": recovered, "placeholders": placeholders},
                ensure_ascii=False,
            )
        )
    finally:
        worker.close()


if __name__ == "__main__":
    main()
