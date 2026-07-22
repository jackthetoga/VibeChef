# Recipe Finder

Recipe Finder turns PDF, EPUB, and TXT cookbooks into a searchable recipe library, then
matches those recipes against the ingredients in your fridge. Recipes can be
sorted and filtered by preparation time, nutrition, cuisine, cookbook, and
missing ingredient count.

## Stack

- FastAPI, SQLAlchemy 2, Alembic, PostgreSQL
- Redis and ARQ for cookbook ingestion jobs
- PyMuPDF and ebooklib for text extraction
- DeepSeek structured extraction, with a deterministic demo parser when no API key is set
- React, TypeScript, Vite, TanStack Query, and Tailwind CSS
- JWT access tokens with rotating HttpOnly refresh cookies for the web client

## Run with Docker

Docker is the only prerequisite.

```bash
cp backend/.env.example backend/.env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Paste the generated value into SECRET_KEY in backend/.env.
docker compose up --build
```

Open:

- Web app: <http://localhost:5173>
- API docs: <http://localhost:8000/docs>
- API health: <http://localhost:8000/api/v1/health>

Set `OPENAI_API_KEY` and explicitly opt in with `EXTERNAL_AI_ENABLED=true` in
`backend/.env` to extract arbitrary cookbooks (defaults to DeepSeek via
`OPENAI_BASE_URL` / `OPENAI_MODEL`). This sends cookbook text, pantry notes, and
uploaded pantry/receipt images to the configured provider; review its retention
and training terms before enabling it. Without opt-in, the app uses local
deterministic fallbacks intended for development.

PostgreSQL and Redis are private to the Compose network by default. To expose
them on loopback for host-side development tools, opt in explicitly:

```bash
docker compose -f docker-compose.yml -f docker-compose.host-access.yml up --build
```

## Local development

### Backend

Python 3.12+ and PostgreSQL/Redis are recommended:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Run the ingestion worker in a second terminal:

```bash
cd backend
source .venv/bin/activate
arq app.worker.WorkerSettings
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Tests and checks

```bash
docker compose run --rm api pytest
npm --prefix frontend test
npm --prefix frontend run build
```

## API design

The versioned API lives under `/api/v1`. FastAPI exposes an OpenAPI document at
`/openapi.json`; the frontend client types in `frontend/src/lib/api` mirror this
contract and can be moved into a shared package when the Expo app is added.

Uploaded source files are private and user-owned. Recipe list queries execute in
PostgreSQL and expose a computed `missing_count`, so filtering and sorting never
requires downloading the full cookbook or matching ingredients in the browser.

## Production notes

- Set `APP_ENV=production`; inject a unique `SECRET_KEY` and data-service
  credentials from a secret manager. Startup rejects missing, placeholder, or
  short signing keys.
- Store uploads in private object storage (S3-compatible) instead of the local
  Docker volume.
- Run migrations as a release step and run API and worker containers separately.
- Place only the web edge behind TLS; keep the API, worker, PostgreSQL, and
  Redis on private networks. Restrict `CORS_ORIGINS` and `ALLOWED_HOSTS` to the
  deployed hostname.
- Use a managed PostgreSQL and Redis service with backups and monitoring.
- Enforce provider-side LLM spend limits in addition to application quotas.
- The production backend image runs as a non-root user and excludes test/lint
  dependencies; do not deploy the development Compose targets.
