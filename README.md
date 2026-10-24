# Movie Club

A small Django server for a weekly movie club. The MVP creates a movie-week
from an HTTP request, resolves a TMDB match, fetches genres, and records who
selected the movie.

## Requirements

The development environment is declared in `flake.nix`:

```bash
nix develop
uv venv --python "$(which python3.12)"
uv sync
```

If flakes are not enabled, add this to `~/.config/nix/nix.conf`:

```ini
experimental-features = nix-command flakes
```

or invoke Nix with the flags explicitly:

```bash
nix --extra-experimental-features 'nix-command flakes' develop
```

`UV_PYTHON_DOWNLOADS=never` is set in the dev shell, so `uv` uses the Nix
Python instead of downloading its own.

## Database

### Option A: project-local Postgres (default)

The Makefile starts a local cluster in `.pgdata` on port `5433`:

```bash
make db-start
```

The default `.env` points at `127.0.0.1:5433`.

### Option B: NixOS-managed Postgres

Import `nix/system.nix` from your NixOS configuration:

```nix
imports = [ /home/george/Projects/movie-club/nix/system.nix ];
```

Rebuild, grant test-database permissions, and update `.env`:

```bash
sudo nixos-rebuild switch
sudo -u postgres psql -c 'ALTER ROLE george CREATEDB;'

# .env
DB_HOST=/run/postgresql
DB_PORT=5432
```

With Option B, run Django commands directly (`uv run python manage.py ...`)
instead of the `db-*` Make targets, which manage the project-local cluster.

## Configuration

```bash
cp .env.example .env
```

Set these values:

- `BOT_API_TOKEN` — shared secret the Discord bot sends to the server.
- `TMDB_READ_ACCESS_TOKEN` — TMDB v4 API Read Access Token.

A development `.env` is already present and is gitignored.

## Run

```bash
make migrate
make dev
```

The server listens on `http://127.0.0.1:8000`.

## API

Create a movie-week:

```bash
curl -i http://127.0.0.1:8000/api/weeks/ \
  -H 'Authorization: Bearer dev-bot-token' \
  -H 'Idempotency-Key: 1234567890123456789' \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "The Matrix",
    "selected_by": {
      "discord_id": "123456789012345678",
      "display_name": "George"
    }
  }'
```

The bot should use the Discord interaction ID as the `Idempotency-Key` and
reuse it on every retry.

Response statuses:

| Status | Meaning |
| --- | --- |
| `201` | Week created |
| `200` | Idempotent replay of the same request |
| `409` | Key reused with a different title or selector |
| `400` | Missing/invalid field or missing `Idempotency-Key` |
| `401` | Bad or missing bot token |

`match_status` is `matched`, `unmatched`, or `error`. A TMDB failure still
creates the week so the club can fix it later.

## Bulk import

Historical choices can be imported from a CSV with `start`, `end`, `selector`,
and `title` columns:

```csv
start,end,selector,title
12-25,12-31,George,Die Hard
01-01,01-07,Alex,The Matrix
```

Rows must be in chronological order. Because the dates do not include a year,
the importer needs a starting year:

```bash
uv run python manage.py import_weeks choices.csv \
  --start-year 2023 \
  --dry-run
```

The dry run validates every row and prints the inferred year boundaries,
members that would be created, and how many weeks are new. Once the plan looks
right, run it without `--dry-run`:

```bash
uv run python manage.py import_weeks choices.csv --start-year 2023
```

The importer automatically rolls the year forward when the month/day sequence
wraps, e.g. `12-29` followed by `01-05`, and handles weeks that cross New Year.
If the history has large gaps or skipped years, add a `year` column so the
years are explicit.

A `year` column is also accepted and overrides `--start-year` for that row:

```csv
year,start,end,selector,title
2024,01-01,01-07,George,The Matrix
```

Supported date formats include `YYYY-MM-DD`, `MM/DD`, `MM-DD`, `Jan 5`,
`January 5`, and common variants. Use `--date-format` if your source uses
something ambiguous such as `DD/MM`:

```bash
uv run python manage.py import_weeks choices.csv \
  --start-year 2023 \
  --date-format '%d/%m'
```

Other useful options:

- `--member-map members.csv` maps source names to existing display names.
  The map needs `source,target` columns.
- `--skip-tmdb` imports the rows without calling TMDB.
- `--delimiter` and `--encoding` support non-comma or non-UTF-8 exports.

Imported selectors that do not match an existing `Member.display_name` get a
legacy member with no Discord ID. They can be linked later.

Imports are idempotent: each row gets an `import_key`, so rerunning the same CSV
skips existing rows. If TMDB is not configured, imported weeks are left
`pending`; add the token and run:

```bash
uv run python manage.py enrich_weeks
```

Use `enrich_weeks --all` to re-run matching for every week, or
`enrich_weeks --dry-run` to see how many weeks would be processed.

## Admin

Create a superuser:

```bash
uv run python manage.py createsuperuser
```

Then visit `http://127.0.0.1:8000/admin/`.

- Edit a `Movie`'s TMDB ID to trigger a metadata and genre refresh.
- Use the `Week` action **Re-run TMDB search** if the original match was wrong.
- Use the `Movie` action **Re-sync metadata and genres from TMDB** to retry.
- Imported weeks show their historical `starts_on` / `ends_on` dates.

## Tests and checks

```bash
make test
make lint
```

Tests use the local Postgres cluster and mock TMDB with `respx`.

## Project layout

```
config/          Django settings, URLs, WSGI/ASGI
apps/club/       Member, Week, API endpoint, import/enrich commands, admin
apps/movies/     Movie, Genre, TMDB client and sync
tests/           API, model, and import tests
nix/system.nix   Optional NixOS module
flake.nix        Development shell
```
