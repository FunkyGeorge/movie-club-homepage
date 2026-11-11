PGDATA ?= .pgdata
PGPORT ?= 5433
DB_NAME ?= movieclub
EXCLUDE ?=

.PHONY: db-init db-start db-stop db-create migrate dev test lint fmt chart-genres chart-release-years chart-favorite-genres chart-genre-share public-charts

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

chart-genres: db-create
	uv run python scripts/genre_pie_chart.py

chart-release-years: db-create
	uv run python scripts/release_year_line_chart.py

chart-favorite-genres: db-create
	uv run python scripts/member_favorite_genre_chart.py $(if $(EXCLUDE),--exclude "$(EXCLUDE)",)

chart-genre-share: db-create
	uv run python scripts/genre_share_heatmap.py

public-charts: db-create
	mkdir -p static/charts
	uv run python scripts/genre_pie_chart.py --output static/charts/genre-pie.png
	uv run python scripts/release_year_line_chart.py --output static/charts/release-years.png
