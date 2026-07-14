from arq.connections import RedisSettings

from app.core.config import settings
from app.services.ingestion import process_cookbook as ingest_cookbook
from app.services.nutrition import estimate_nutrition_for_cookbook


async def process_cookbook(ctx: dict, cookbook_id: str) -> None:
    await ingest_cookbook(cookbook_id)


async def estimate_cookbook_nutrition(
    ctx: dict, cookbook_id: str, force: bool = False
) -> int:
    return await estimate_nutrition_for_cookbook(cookbook_id, force=force)


class WorkerSettings:
    functions = [process_cookbook, estimate_cookbook_nutrition]
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379/0")
    max_jobs = 2
    job_timeout = 30 * 60
    keep_result = 3600
    retry_jobs = False
