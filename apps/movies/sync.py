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


def sync_movie_metadata(movie: Movie) -> bool:
    """Fetch movie details from TMDB and refresh the stored metadata.

    Returns True on success. On failure the movie's ``sync_error`` is updated
    and the existing data is left in place.
    """
    if not movie.tmdb_id:
        return False

    try:
        payload = get_movie(movie.tmdb_id)
    except TMDBError as exc:
        Movie.objects.filter(pk=movie.pk).update(sync_error=str(exc))
        movie.sync_error = str(exc)
        logger.warning("TMDB metadata sync failed for %s: %s", movie.tmdb_id, exc)
        return False

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
    synced_at = timezone.now()

    # Use queryset.update() rather than save() so this does not re-trigger
    # the tmdb_id change hook on Movie.save().
    Movie.objects.filter(pk=movie.pk).update(
        title=title,
        release_date=release_date,
        last_synced_at=synced_at,
        sync_error="",
    )

    movie.title = title
    movie.release_date = release_date
    movie.last_synced_at = synced_at
    movie.sync_error = ""
    movie.genres.set(genre_objects)
    return True


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
        },
    )

    # New movies are synced by Movie.save(). Existing movies may have been
    # created before genre syncing existed, so fill in missing genres.
    if not created and not movie.genres.exists():
        sync_movie_metadata(movie)

    return movie
