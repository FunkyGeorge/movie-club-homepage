import pytest
import respx
from httpx import Response

from apps.movies.models import Genre, Movie

TMDB_MOVIE_603_URL = "https://api.themoviedb.org/3/movie/603"


@pytest.fixture
def tmdb_settings(settings):
    settings.TMDB_READ_ACCESS_TOKEN = "tmdb-token"


@respx.mock
def test_changing_tmdb_id_refreshes_genres(db, tmdb_settings):
    # bulk_create bypasses Movie.save(), so this row starts without a sync.
    movie = Movie.objects.bulk_create(
        [Movie(tmdb_id=1, title="Wrong title")]
    )[0]

    respx.get(TMDB_MOVIE_603_URL).mock(
        return_value=Response(
            200,
            json={
                "id": 603,
                "title": "The Matrix",
                "release_date": "1999-03-31",
                "genres": [
                    {"id": 28, "name": "Action"},
                    {"id": 878, "name": "Science Fiction"},
                ],
            },
        )
    )

    movie.tmdb_id = 603
    movie.save()

    movie.refresh_from_db()
    assert movie.title == "The Matrix"
    assert movie.release_date.isoformat() == "1999-03-31"
    assert movie.sync_error == ""
    assert sorted(movie.genres.values_list("name", flat=True)) == [
        "Action",
        "Science Fiction",
    ]
    assert Genre.objects.count() == 2
