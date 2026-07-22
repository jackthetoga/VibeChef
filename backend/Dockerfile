FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip
COPY pyproject.toml ./
COPY uv.lock ./
COPY app ./app

FROM base AS development
# Editable install so bind-mounted ./backend:/app is what API and worker import.
RUN pip install --no-cache-dir -e ".[dev]"

COPY alembic.ini ./
COPY alembic ./alembic
RUN mkdir -p /app/uploads

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS production

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/uploads \
    && chown -R appuser:appuser /data/uploads

COPY alembic.ini ./
COPY alembic ./alembic

ENV APP_ENV=production \
    AUTO_CREATE_TABLES=false \
    DEV_SYNC_INGESTION=false \
    UPLOAD_DIR=/data/uploads \
    PATH=/app/.venv/bin:$PATH
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
