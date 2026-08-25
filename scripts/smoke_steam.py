from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from connectors.steam import SteamClient
from contracts import Language


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-id", type=int, default=578080)
    parser.add_argument("--language", choices=[item.value for item in Language], default="en")
    parser.add_argument("--limit", type=int, choices=range(1, 101), default=10)
    args = parser.parse_args()
    items = SteamClient().fetch_reviews(
        args.app_id,
        Language(args.language),
        datetime.now(UTC) + timedelta(seconds=1),
        limit=args.limit,
    )
    if not items:
        raise SystemExit("Steam returned no reviews")
    if any(len(item.source_id) < 8 for item in items):
        raise SystemExit("Steam review IDs were not anonymized")
    print(f"Steam smoke passed: {len(items)} anonymized reviews")


if __name__ == "__main__":
    main()
