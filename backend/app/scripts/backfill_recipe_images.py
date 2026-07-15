from __future__ import annotations

import argparse
import asyncio
import logging

from app.services.recipe_images import backfill_recipe_images, clear_corpus_cache


async def run(cookbook_id: str | None, force: bool) -> dict[str, int]:
    clear_corpus_cache()
    return await backfill_recipe_images(cookbook_id=cookbook_id, force=force)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Clear legacy category SVG image assignments and match the photorealistic "
            "photo corpus. Preserves cookbook-extracted images unless --force."
        )
    )
    parser.add_argument(
        "--cookbook-id",
        help="Limit backfill to a single cookbook UUID",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run extraction + corpus matching even for extracted images",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = asyncio.run(run(args.cookbook_id, args.force))
    logging.info("Recipe image backfill finished: %s", result)


if __name__ == "__main__":
    main()
