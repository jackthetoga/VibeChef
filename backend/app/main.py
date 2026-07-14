import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.router import api_router
from app.core.config import settings
from app.db.session import engine
from app.models import Base

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_create_tables and not settings.is_production:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    app.state.arq_pool = None
    if settings.redis_url:
        try:
            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            await pool.ping()
            app.state.arq_pool = pool
        except Exception as exc:
            logger.warning("Redis is unavailable; background ingestion queue disabled: %s", exc)
            app.state.arq_pool = None
    yield
    if app.state.arq_pool is not None:
        await app.state.arq_pool.aclose()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "health": f"{settings.api_prefix}/health",
        "docs": "/docs",
        "web_app": "http://localhost:5173",
    }


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_, __: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "Resource conflict"})


@app.get(f"{settings.api_prefix}/health", tags=["health"])
async def health() -> dict[str, str]:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return {"status": "ok"}
