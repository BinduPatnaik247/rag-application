.PHONY: dev test lint migrate

dev:
	uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

test:
	pytest -q

lint:
	ruff check app tests

migrate:
	alembic upgrade head
