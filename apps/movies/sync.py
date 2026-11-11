from __future__ import annotations

import logging
from datetime import date

from django.utils import timezone

from .models import Genre, Movie
from .tmdb import TMDBError, get_movie, search_movie

logger = logging.getLogger(__name__)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _positive_int(value: object) -> int | None:
    """Return a positive integer, treating TMDB's zero values as unknown."""
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _image_path(value: object) -> str | None:
    """Return a TMDB image path, ignoring empty or malformed values."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value.startswith("/") else None


def _apply_movie_payload(movie: Movie, payload: dict) -> None:
    """Apply a TMDB movie payload to a stored movie."""
    genre_objects = []
    for genre in payload.get("genres") or []:
        tmdb_id = genre.get("id")
        name = genre.get("name")
        if not tmdb_id or not name:
            continue
        obj, _ = Genre.objects.update_or_create(
            tmdb_id=tmdb_id,
            defaults={"name": name},
        )
        genre_objects.append(obj)

    title = payload.get("title") or movie.title
    release_date = _parse_date(payload.get("release_date"))
    poster_path = _image_path(payload.get("poster_path"))
    runtime = _positive_int(payload.get("runtime"))
    budget = _positive_int(payload.get("budget"))
    revenue = _positive_int(payload.get("revenue"))
    synced_at = timezone.now()

    # Use queryset.update() rather than save() so this does not re-trigger
    # the tmdb_id change hook on Movie.save().
    Movie.objects.filter(pk=movie.pk).update(
        title=title,
        release_date=release_date,
        poster_path=poster_path,
        runtime=runtime,
        budget=budget,
        revenue=revenue,
        last_synced_at=synced_at,
        sync_error="",
    )

    movie.title = title
    movie.release_date = release_date
    movie.poster_path = poster_path
    movie.runtime = runtime
    movie.budget = budget
    movie.revenue = revenue
    movie.last_synced_at = synced_at
    movie.sync_error = ""
    movie.genres.set(genre_objects)


def sync_movie_metadata(movie: Movie, *, payload: dict | None = None) -> bool:
    """Fetch movie details from TMDB and refresh the stored metadata.

    Returns True on success. On failure the movie's ``sync_error`` is updated
    and the existing data is left in place.
    """
    if not movie.tmdb_id:
        return False

    if payload is None:
        try:
            payload = get_movie(movie.tmdb_id)
        except TMDBError as exc:
            Movie.objects.filter(pk=movie.pk).update(sync_error=str(exc))
            movie.sync_error = str(exc)
            logger.warning("TMDB metadata sync failed for %s: %s", movie.tmdb_id, exc)
            return False

    _apply_movie_payload(movie, payload)
    return True


def resolve_movie_by_id(tmdb_id: int) -> Movie:
    """Fetch a TMDB ID and return its stored movie, creating it if needed.

    Raises TMDBError when the ID cannot be fetched from TMDB.
    """
    payload = get_movie(tmdb_id)
    movie, _ = Movie.objects.get_or_create(
        tmdb_id=tmdb_id,
        defaults={"title": payload.get("title") or f"TMDB movie {tmdb_id}"},
    )
    # Reuse the payload we already fetched so existing rows are refreshed and
    # newly created rows do not depend on their automatic save-time sync.
    _apply_movie_payload(movie, payload)
    return movie


def resolve_movie(title: str) -> Movie | None:
    """Search TMDB for the best match and return a linked Movie.

    Returns None when TMDB has no results. Raises TMDBError when the search
    itself fails.
    """
    results = search_movie(title)
    if not results:
        return None

    result = results[0]
    tmdb_id = result.get("id")
    if not tmdb_id:
        return None

    movie, created = Movie.objects.get_or_create(
        tmdb_id=tmdb_id,
        defaults={
            "title": result.get("title") or title,
            "release_date": _parse_date(result.get("release_date")),
            "poster_path": _image_path(result.get("poster_path")),
        },
    )

    # New movies are synced by Movie.save(). Existing movies may have been
    # created before genre syncing existed, so fill in missing genres.
    if not created and not movie.genres.exists():
        sync_movie_metadata(movie)

    return movie
