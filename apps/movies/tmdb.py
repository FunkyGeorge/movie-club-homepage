from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

_TMDB_MOVIE_HOSTS = {"themoviedb.org", "www.themoviedb.org"}
_TMDB_MOVIE_PATH = re.compile(r"^/movie/(?P<tmdb_id>\d+)(?:-[^/]*)?/?$")


class TMDBError(Exception):
    """Raised when TMDB cannot be reached or returns an unexpected response."""


def _headers() -> dict[str, str]:
    token = settings.TMDB_READ_ACCESS_TOKEN
    if not token:
        raise TMDBError("TMDB_READ_ACCESS_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {token}",
        "accept": "application/json",
    }


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{settings.TMDB_API_BASE_URL}{path}"

    try:
        with httpx.Client(timeout=5.0, headers=_headers()) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise TMDBError(f"TMDB returned {exc.response.status_code} for {path}") from exc
    except httpx.HTTPError as exc:
        raise TMDBError(f"TMDB request failed: {exc}") from exc

    try:
        return response.json()
    except ValueError as exc:
        raise TMDBError(f"TMDB returned invalid JSON for {path}") from exc


def parse_movie_url(value: str) -> int | None:
    """Extract a TMDB movie ID from a themoviedb.org movie page URL."""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.hostname not in _TMDB_MOVIE_HOSTS:
        return None
    match = _TMDB_MOVIE_PATH.match(parsed.path)
    if match is None:
        return None
    tmdb_id = int(match.group("tmdb_id"))
    return tmdb_id if tmdb_id > 0 else None


def search_movie(title: str) -> list[dict[str, Any]]:
    data = _get(
        "/search/movie",
        {
            "query": title,
            "include_adult": "false",
            "language": "en-US",
            "page": 1,
        },
    )
    return data.get("results", [])


def get_movie(tmdb_id: int) -> dict[str, Any]:
    return _get(f"/movie/{tmdb_id}")
