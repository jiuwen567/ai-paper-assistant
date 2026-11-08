.PHONY: init install infra dev down api worker web migrate check test integration health build

DEV_WATCH ?= 1
DEV_COMPOSE_FILES ?= $(if $(COMPOSE_FILE),$(COMPOSE_FILE),compose.yaml):compose.dev.yaml
DEV_COMPOSE = COMPOSE_FILE="$(DEV_COMPOSE_FILES)" docker compose --profile app

init:
	python3 scripts/init_dev.py

install:
	uv sync --locked
	pnpm install --frozen-lockfile

infra:
	docker compose up -d --wait

dev: init
	$(DEV_COMPOSE) up -d --build --wait
	$(DEV_COMPOSE) exec api python manage.py check_services
	$(DEV_COMPOSE) exec api python manage.py check_worker
	@if [ "$(DEV_WATCH)" = "1" ]; then $(DEV_COMPOSE) watch --no-up; fi

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
	python3 scripts/check_architecture.py
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
