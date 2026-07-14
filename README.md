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
- JWT access tokens with rotating refresh tokens for web and future Expo clients

## Run with Docker

Docker is the only prerequisite.

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

Open:

- Web app: <http://localhost:5173>
- API docs: <http://localhost:8000/docs>
- API health: <http://localhost:8000/api/v1/health>

Set `OPENAI_API_KEY` in `backend/.env` to extract arbitrary cookbooks (defaults to
DeepSeek via `OPENAI_BASE_URL` / `OPENAI_MODEL`). Without it, the worker uses a
small deterministic parser intended for local development.

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

- Replace `SECRET_KEY` and database credentials.
- Store uploads in private object storage (S3-compatible) instead of the local
  Docker volume.
- Run migrations as a release step and run API and worker containers separately.
- Place the API behind TLS and restrict `CORS_ORIGINS` to deployed clients.
- Use a managed PostgreSQL and Redis service with backups and monitoring.
