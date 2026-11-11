"""Data-retention cleanup CLI (``python -m app.cli.cleanup``)."""

import argparse
import asyncio
import logging

from app.services.maintenance import cleanup

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


async def run(apply: bool) -> int:
    counts = await cleanup(dry_run=not apply)
    mode = "APPLIED" if apply else "DRY RUN (nothing deleted)"
    print(f"Retention cleanup — {mode}")
    for table in ("login_attempt", "refresh_token", "email_attempt", "email_outbox"):
        print(f"  {table:16} {counts.get(table, 0)} row(s)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune old telemetry and emails.")
    parser.add_argument(
        "--apply", action="store_true", help="really delete (default is a dry run)"
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.apply)))


if __name__ == "__main__":
    main()
