run-dev:
	python3 -m alembic upgrade head
	uvicorn app.main:app --reload --port 7777

# Usage: make migrate msg="add user table"
migrate:
	python3 -m alembic revision --autogenerate -m "$(msg)"

migrate-up:
	python3 -m alembic upgrade head

migrate-down:
	python3 -m alembic downgrade -1

migrate-history:
	python3 -m alembic history --verbose

migrate-current:
	python3 -m alembic current

seed:
	python3 -m seeds.seed
