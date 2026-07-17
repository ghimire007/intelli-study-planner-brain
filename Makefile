ifeq ($(OS),Windows_NT)
    PYTHON = python
else
    PYTHON = python3
endif

run-dev:
	$(PYTHON) -m alembic upgrade head
	uvicorn app.main:app --reload --port 7777

# Usage: make migrate msg="add user table"
migrate:
	$(PYTHON) -m alembic revision --autogenerate -m "$(msg)"

migrate-up:
	$(PYTHON) -m alembic upgrade head

migrate-down:
	$(PYTHON) -m alembic downgrade -1

migrate-history:
	$(PYTHON) -m alembic history --verbose

migrate-current:
	$(PYTHON) -m alembic current

seed:
	$(PYTHON) -m seeds.seed
