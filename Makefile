.PHONY: up down logs migrate test check

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api worker web

migrate:
	docker compose run --rm api alembic upgrade head

test:
	docker compose run --rm api pytest
	npm --prefix frontend test -- --run

check:
	docker compose run --rm api ruff check app tests
	docker compose run --rm api pytest
	npm --prefix frontend run lint
	npm --prefix frontend test -- --run
	npm --prefix frontend run build
