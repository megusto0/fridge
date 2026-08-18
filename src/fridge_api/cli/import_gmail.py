from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx

from fridge_api.parsers.magnit_email import MagnitReceiptParseError, parse_magnit_receipt_email
from fridge_api.schemas import ReceiptImportRequest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a Magnit fiscal receipt from Gmail through Himalaya."
    )
    parser.add_argument("message_id", help="Himalaya message ID from the inbox")
    parser.add_argument(
        "--api-url",
        default=os.getenv("FRIDGE_API_URL", "http://127.0.0.1:8011"),
        help="Fridge API base URL",
    )
    parser.add_argument("--owner-id", default=os.getenv("FRIDGE_OWNER_ID"))
    parser.add_argument(
        "--himalaya-bin",
        default=os.getenv("HIMALAYA_BIN", "himalaya"),
        help="Himalaya executable or wrapper",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and summarize without writing to Fridge",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Import directly through the configured database instead of HTTP",
    )
    return parser


def _fetch_message(himalaya_bin: str, message_id: str) -> bytes:
    command = [himalaya_bin, "message", "read", "--raw", message_id]
    try:
        result = subprocess.run(command, check=True, capture_output=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Himalaya executable not found: {himalaya_bin}") from exc
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Himalaya failed: {error or exc.returncode}") from exc
    return result.stdout


def _ensure_worker() -> None:
    fridge_root = Path("/media/megusto/storage/fridge")
    worker = fridge_root / ".venv" / "bin" / "fridge-enrichment-worker"
    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "fridge-enrichment-worker.service"]
    )
    if active.returncode == 0 or not worker.is_file():
        return
    subprocess.Popen(
        [str(worker), "--once", "--limit", "50"],
        cwd=str(fridge_root),
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def _summary(payload: ReceiptImportRequest) -> dict[str, object]:
    return {
        "provider": payload.provider,
        "purchased_at": payload.purchased_at.isoformat(),
        "merchant": payload.merchant_name,
        "total_minor": payload.total_minor,
        "fiscal": {
            "fn": payload.fiscal_fn,
            "fd": payload.fiscal_fd,
            "fp": payload.fiscal_fp,
        },
        "lines": len(payload.items),
        "inventory_lines": sum(item.inventory_effect for item in payload.items),
        "non_inventory_lines": sum(not item.inventory_effect for item in payload.items),
    }


def main() -> None:
    args = _parser().parse_args()
    try:
        raw_message = _fetch_message(args.himalaya_bin, args.message_id)
        payload = parse_magnit_receipt_email(raw_message)
        summary = _summary(payload)
        if args.dry_run:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return
        if not args.owner_id:
            raise RuntimeError("--owner-id or FRIDGE_OWNER_ID is required for import")
        owner_id = uuid.UUID(args.owner_id)
        if args.direct:
            from fridge_api.db import SessionLocal
            from fridge_api.services.receipts import import_receipt

            with SessionLocal() as session:
                imported = import_receipt(session, owner_id, payload)
            print(imported.model_dump_json(indent=2))
            if imported.created or imported.enrichment_jobs_created:
                _ensure_worker()
            return
        response = httpx.post(
            f"{args.api_url.rstrip('/')}/receipts/import-email",
            content=raw_message,
            headers={
                "Content-Type": "message/rfc822",
                "X-User-Id": str(owner_id),
            },
            timeout=30,
        )
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except (MagnitReceiptParseError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
