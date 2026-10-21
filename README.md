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

## Admin

Create a superuser:

```bash
uv run python manage.py createsuperuser
```

Then visit `http://127.0.0.1:8000/admin/`.

- Edit a `Movie`'s TMDB ID to trigger a metadata and genre refresh.
- Use the `Week` action **Re-run TMDB search** if the original match was wrong.
- Use the `Movie` action **Re-sync metadata and genres from TMDB** to retry.

## Tests and checks

```bash
make test
make lint
```

Tests use the local Postgres cluster and mock TMDB with `respx`.

## Project layout

```
config/          Django settings, URLs, WSGI/ASGI
apps/club/       Member, Week, API endpoint, admin
apps/movies/     Movie, Genre, TMDB client and sync
tests/           API and model tests
nix/system.nix   Optional NixOS module
flake.nix        Development shell
```
