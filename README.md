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
- `TMDB_IMAGE_BASE_URL` — optional TMDB image base URL; defaults to `w500`.
- `CLUB_JOIN_URL` — optional public join/contact URL for the homepage and About page.

A development `.env` is already present and is gitignored.

## Run

```bash
make migrate
make dev
```

The server listens on `http://127.0.0.1:8000`.

## Public site

The public site is available at `/`:

- `/` — current/latest pick, recent picks, and club stats
- `/archive/` — searchable archive with title, genre, and decade filters
- `/movies/<tmdb_id>/` — movie details and pick history
- `/stats/` — aggregate stats and charts
- `/about/` — club information and join/contact details

The archive includes every week, including picks that could not be matched to
TMDB; unmatched picks appear as cards with the title and dates but no movie
metadata, and link to a pick page where a TMDB ID can be added. Public pages
never display chooser names, usernames, Discord IDs, or other member identities.
Aggregated member counts are shown without identifying anyone. Stats and charts
use matched weeks only. Movie posters are loaded from the saved TMDB poster
paths on the homepage and archive cards.

Anyone can correct a bad TMDB match from the homepage current pick or a movie
detail page. The form only changes the selected week, re-fetches the movie from
TMDB, and redirects back to the refreshed details.

Generate the public chart assets after importing or re-syncing movies:

```bash
make public-charts
```

This writes the two public-safe charts to `static/charts/`. The member-level
charts remain in `charts/` and are not served by the public site.

Set `CLUB_JOIN_URL` to show a join link on the homepage and About page. Without
it, the site points visitors to the About page for joining instructions.

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

## Movie metadata

Movies store a TMDB `poster_path`, `runtime` in minutes, `budget` in USD, and
`revenue` as worldwide box office earnings in USD. These fields are populated
from TMDB whenever a movie is matched or re-synced. TMDB's zero runtime,
budget, and revenue values are treated as unknown and stored as `NULL`.
Posters are displayed through `TMDB_IMAGE_BASE_URL`, which defaults to TMDB's
`w500` image size.

To populate or refresh metadata for movies already in the database:

```bash
uv run python manage.py sync_movies
```

Useful options:

```bash
# Only movies missing a poster, runtime, budget, or revenue
uv run python manage.py sync_movies --missing

# Preview without calling TMDB
uv run python manage.py sync_movies --dry-run

# Limit a retry batch
uv run python manage.py sync_movies --missing --limit 25
```

## Charts

Generate a pie chart of genres from matched weeks:

```bash
make chart-genres
```

This writes `charts/genre-pie.png`. Each matched week counts once per genre, so
multi-genre films appear in every applicable slice. The chart shows the top
eight genres and groups the rest into **Other**; unmatched weeks are excluded.

To change the number of slices or the output path:

```bash
uv run python scripts/genre_pie_chart.py \
  --top 10 \
  --output charts/genre-pie-top10.png
```

Generate a line chart of unique movies by release year:

```bash
make chart-release-years
```

This writes `charts/release-years.png`. Movies without a release date are
excluded, and years with no picks are shown as zero.

To focus on a specific range or change the output path:

```bash
uv run python scripts/release_year_line_chart.py \
  --start-year 1980 \
  --end-year 2026 \
  --output charts/release-years-1980-2026.png
```

Generate a chart of each chooser's favorite genre:

```bash
make chart-favorite-genres
```

This writes `charts/member-favorite-genres.png`. Each member's favorite is the
genre that appears most often among their matched picks; the bar shows how many
of their picks contain it. Unmatched weeks are excluded.

To exclude a genre from the favorite calculation:

```bash
make chart-favorite-genres EXCLUDE=Drama
```

The total pick count still includes excluded-genre picks, so the percentage
shows how much of each chooser's overall selection falls into their favorite
remaining genre. To exclude multiple genres, separate them with commas:

```bash
make chart-favorite-genres EXCLUDE=Drama,Comedy
```

To change the output path:

```bash
uv run python scripts/member_favorite_genre_chart.py \
  --exclude Drama \
  --output charts/member-favorite-genres-alt.png
```

Generate a heatmap showing every genre's share of each chooser's picks:

```bash
make chart-genre-share
```

This writes `charts/genre-share-by-member.png`. Each cell is the percentage of
that chooser's matched picks containing the genre, and the highest share for
each genre is highlighted with a star. Picks can have multiple genres, so a
chooser's percentages across genres can add up to more than 100%.

To change the output path:

```bash
uv run python scripts/genre_share_heatmap.py \
  --output charts/genre-share-by-member-alt.png
```

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
