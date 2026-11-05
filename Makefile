.PHONY: init install infra up down api worker web migrate check test integration health build

init:
	python3 scripts/init_dev.py

install:
	uv sync --locked
	pnpm install --frozen-lockfile

infra:
	docker compose up -d --wait

up:
	docker compose --profile app up -d --build --wait
	docker compose exec api python manage.py check_services
	docker compose exec api python manage.py check_worker

down:
	docker compose --profile app down

api:
	uv run python services/backend/manage.py runserver 127.0.0.1:8000

worker:
	uv run --directory services/backend celery -A worker.app worker --loglevel=info --concurrency=2

web:
	pnpm dev

migrate:
	uv run python services/backend/manage.py migrate --noinput

check:
	uv run python services/backend/manage.py check
	uv run python -m compileall -q services/backend
	pnpm check

test:
	uv run pytest -m 'not integration'
	pnpm test

integration:
	uv run pytest -m integration

health:
	uv run python services/backend/manage.py check_services
	uv run python services/backend/manage.py check_worker

build:
	pnpm build
