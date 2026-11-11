from io import StringIO

import pytest
import respx
from django.core.management import call_command
from httpx import Response

from apps.movies.models import Genre, Movie
from apps.movies.sync import sync_movie_metadata

TMDB_MOVIE_550_URL = "https://api.themoviedb.org/3/movie/550"
TMDB_MOVIE_603_URL = "https://api.themoviedb.org/3/movie/603"


@pytest.fixture
def tmdb_settings(settings):
    settings.TMDB_READ_ACCESS_TOKEN = "tmdb-token"


def matrix_payload() -> dict:
    return {
        "id": 603,
        "title": "The Matrix",
        "release_date": "1999-03-31",
        "poster_path": "/matrix.jpg",
        "runtime": 136,
        "budget": 63000000,
        "revenue": 467222728,
        "genres": [
            {"id": 28, "name": "Action"},
            {"id": 878, "name": "Science Fiction"},
        ],
    }


@respx.mock
def test_changing_tmdb_id_refreshes_metadata_and_genres(db, tmdb_settings):
    # bulk_create bypasses Movie.save(), so this row starts without a sync.
    movie = Movie.objects.bulk_create([Movie(tmdb_id=1, title="Wrong title")])[0]

    respx.get(TMDB_MOVIE_603_URL).mock(return_value=Response(200, json=matrix_payload()))

    movie.tmdb_id = 603
    movie.save()

    movie.refresh_from_db()
    assert movie.title == "The Matrix"
    assert movie.release_date.isoformat() == "1999-03-31"
    assert movie.poster_path == "/matrix.jpg"
    assert movie.poster_url == "https://image.tmdb.org/t/p/w500/matrix.jpg"
    assert movie.runtime == 136
    assert movie.budget == 63000000
    assert movie.revenue == 467222728
    assert movie.sync_error == ""
    assert sorted(movie.genres.values_list("name", flat=True)) == [
        "Action",
        "Science Fiction",
    ]
    assert Genre.objects.count() == 2


@respx.mock
def test_zero_tmdb_financial_values_are_stored_as_unknown(db, tmdb_settings):
    movie = Movie.objects.bulk_create([Movie(tmdb_id=550, title="Fight Club")])[0]

    respx.get(TMDB_MOVIE_550_URL).mock(
        return_value=Response(
            200,
            json={
                "id": 550,
                "title": "Fight Club",
                "release_date": "1999-10-15",
                "runtime": 0,
                "budget": 0,
                "revenue": 0,
                "genres": [],
            },
        )
    )

    assert sync_movie_metadata(movie) is True

    movie.refresh_from_db()
    assert movie.runtime is None
    assert movie.budget is None
    assert movie.revenue is None


@respx.mock
def test_sync_movies_command_populates_missing_metadata(db, tmdb_settings):
    movie = Movie.objects.bulk_create([Movie(tmdb_id=603, title="Wrong title")])[0]

    respx.get(TMDB_MOVIE_603_URL).mock(return_value=Response(200, json=matrix_payload()))

    output = StringIO()
    call_command("sync_movies", "--missing", stdout=output)

    movie.refresh_from_db()
    assert movie.title == "The Matrix"
    assert movie.runtime == 136
    assert movie.budget == 63000000
    assert movie.revenue == 467222728
    assert "1 succeeded, 0 failed" in output.getvalue()
