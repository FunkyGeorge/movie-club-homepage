PGDATA ?= .pgdata
PGPORT ?= 5433
DB_NAME ?= movieclub

.PHONY: db-init db-start db-stop db-create migrate dev test lint fmt

db-init:
	@test -d $(PGDATA) || initdb -D $(PGDATA) --auth=trust

db-start: db-init
	@pg_ctl -D $(PGDATA) status >/dev/null 2>&1 || \
		pg_ctl -D $(PGDATA) \
			-o "-p $(PGPORT) -k $(CURDIR)/$(PGDATA) -c listen_addresses=127.0.0.1" \
			-l $(PGDATA)/log start

db-stop:
	@pg_ctl -D $(PGDATA) stop

db-create: db-start
	@createdb -h 127.0.0.1 -p $(PGPORT) $(DB_NAME) 2>/dev/null || true

migrate: db-create
	uv run python manage.py migrate

dev: db-create
	uv run python manage.py runserver

test: db-create
	uv run pytest

lint:
	ruff check .

fmt:
	ruff format .
