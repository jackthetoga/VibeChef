from __future__ import annotations

import argparse
import asyncio
import logging

from app.services.nutrition import (
    estimate_nutrition_for_all_recipes,
    estimate_nutrition_for_cookbook,
)


async def run(cookbook_id: str | None, force: bool) -> int:
    if cookbook_id:
        return await estimate_nutrition_for_cookbook(cookbook_id, force=force)
    return await estimate_nutrition_for_all_recipes(force=force)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill recipe nutrition estimates")
    parser.add_argument(
        "--cookbook-id",
        help="Limit estimation to a single cookbook UUID",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-estimate even when printed/manual nutrition is present",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    updated = asyncio.run(run(args.cookbook_id, args.force))
    logging.info("Nutrition backfill finished: updated=%s", updated)


if __name__ == "__main__":
    main()
