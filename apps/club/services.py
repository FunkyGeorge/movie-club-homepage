from __future__ import annotations

from apps.movies.sync import resolve_movie
from apps.movies.tmdb import TMDBError

from .models import Week


def enrich_week(week: Week) -> Week:
    """Try to resolve a week's title against TMDB and store the result.

    A TMDB failure is recorded on the week rather than raised. Any existing
    match is kept when a transient failure occurs.
    """
    try:
        movie = resolve_movie(week.title)
    except TMDBError as exc:
        week.match_status = Week.MatchStatus.ERROR
        week.match_error = str(exc)
    else:
        week.movie = movie
        if movie is None:
            week.match_status = Week.MatchStatus.UNMATCHED
            week.match_error = ""
        else:
            week.match_status = Week.MatchStatus.MATCHED
            week.match_error = ""

    week.save(update_fields=["movie", "match_status", "match_error", "updated_at"])
    return week
