from datetime import date, timedelta

import pytest
import respx
from django.urls import reverse
from django.utils import timezone
from httpx import Response

from apps.club.models import Week
from apps.movies.models import Genre, Movie
from apps.movies.tmdb import parse_movie_url

TMDB_MOVIE_603_URL = "https://api.themoviedb.org/3/movie/603"
TMDB_MOVIE_157336_URL = "https://api.themoviedb.org/3/movie/157336"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.themoviedb.org/movie/603-the-matrix", 603),
        ("https://www.themoviedb.org/movie/603", 603),
        ("http://themoviedb.org/movie/603-the-matrix/", 603),
        ("https://www.themoviedb.org/movie/603-the-matrix?language=en-US", 603),
        ("https://www.themoviedb.org/movie/603-the-matrix#cast", 603),
        ("https://example.com/movie/603", None),
        ("https://www.themoviedb.org/tv/1399", None),
        ("https://www.themoviedb.org/person/123", None),
        ("https://www.themoviedb.org/movie/not-an-id", None),
        ("603", None),
    ],
)
def test_parse_movie_url(url, expected):
    assert parse_movie_url(url) == expected


@pytest.fixture
def tmdb_settings(settings):
    settings.TMDB_READ_ACCESS_TOKEN = "tmdb-token"


@pytest.fixture
def arrival_week(member):
    movie = Movie.objects.bulk_create(
        [
            Movie(
                tmdb_id=329865,
                title="Arrival",
                release_date=date(2016, 11, 11),
                runtime=116,
            )
        ]
    )[0]
    today = timezone.localdate()
    return Week.objects.create(
        title="Arrival",
        starts_on=today - timedelta(days=2),
        ends_on=today + timedelta(days=2),
        selected_by=member,
        movie=movie,
        match_status=Week.MatchStatus.MATCHED,
    )


def interstellar_payload() -> dict:
    return {
        "id": 157336,
        "title": "Interstellar",
        "release_date": "2014-11-05",
        "poster_path": "/interstellar.jpg",
        "runtime": 169,
        "budget": 165000000,
        "revenue": 701729206,
        "genres": [
            {"id": 12, "name": "Adventure"},
            {"id": 18, "name": "Drama"},
        ],
    }


@pytest.fixture
def unmatched_week(member):
    return Week.objects.create(
        title="Point Break (1991)",
        starts_on=date(2021, 4, 25),
        ends_on=date(2021, 5, 2),
        selected_by=member,
        match_status=Week.MatchStatus.UNMATCHED,
    )


@respx.mock
def test_update_tmdb_reassigns_only_the_selected_week(client, arrival_week, tmdb_settings):
    original_movie_id = arrival_week.movie_id
    respx.get(TMDB_MOVIE_157336_URL).mock(return_value=Response(200, json=interstellar_payload()))

    response = client.post(
        reverse("update-tmdb"),
        {
            "week_id": arrival_week.pk,
            "tmdb_url": "https://www.themoviedb.org/movie/157336-interstellar",
            "redirect": "detail",
            "return_tmdb_id": 329865,
        },
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == reverse("movie-detail", args=[157336])

    arrival_week.refresh_from_db()
    assert arrival_week.movie_id != original_movie_id
    assert arrival_week.movie.tmdb_id == 157336
    assert arrival_week.movie.title == "Interstellar"
    assert arrival_week.movie.runtime == 169
    assert arrival_week.movie.budget == 165000000
    assert arrival_week.movie.revenue == 701729206
    assert arrival_week.match_status == Week.MatchStatus.MATCHED
    assert arrival_week.match_error == ""
    assert sorted(arrival_week.movie.genres.values_list("name", flat=True)) == [
        "Adventure",
        "Drama",
    ]
    assert Movie.objects.filter(pk=original_movie_id).exists()
    assert "Interstellar" in response.content.decode()


@respx.mock
def test_update_tmdb_reuses_an_existing_movie(client, arrival_week, tmdb_settings):
    matrix = Movie.objects.bulk_create([Movie(tmdb_id=603, title="Old title")])[0]
    respx.get(TMDB_MOVIE_603_URL).mock(
        return_value=Response(
            200,
            json={
                "id": 603,
                "title": "The Matrix",
                "release_date": "1999-03-31",
                "runtime": 136,
                "budget": 63000000,
                "revenue": 467222728,
                "genres": [{"id": 28, "name": "Action"}],
            },
        )
    )

    response = client.post(
        reverse("update-tmdb"),
        {
            "week_id": arrival_week.pk,
            "tmdb_url": "https://www.themoviedb.org/movie/603-the-matrix",
            "redirect": "detail",
            "return_tmdb_id": 329865,
        },
        follow=True,
    )

    assert response.status_code == 200
    arrival_week.refresh_from_db()
    matrix.refresh_from_db()
    assert arrival_week.movie_id == matrix.pk
    assert matrix.title == "The Matrix"
    assert matrix.genres.filter(name="Action").exists()
    assert Movie.objects.filter(tmdb_id=603).count() == 1
    assert Genre.objects.filter(tmdb_id=28, name="Action").exists()


@respx.mock
def test_update_tmdb_failure_leaves_the_week_unchanged(client, arrival_week, tmdb_settings):
    original_movie_id = arrival_week.movie_id
    respx.get("https://api.themoviedb.org/3/movie/999999").mock(
        return_value=Response(404, json={"status_code": 34})
    )

    response = client.post(
        reverse("update-tmdb"),
        {
            "week_id": arrival_week.pk,
            "tmdb_url": "https://www.themoviedb.org/movie/999999-missing",
            "redirect": "detail",
            "return_tmdb_id": 329865,
        },
        follow=True,
    )

    assert response.status_code == 200
    arrival_week.refresh_from_db()
    assert arrival_week.movie_id == original_movie_id
    assert "TMDB could not load that movie" in response.content.decode()
    assert not Movie.objects.filter(tmdb_id=999999).exists()


@respx.mock
def test_update_tmdb_from_home_redirects_home(client, arrival_week, tmdb_settings):
    respx.get(TMDB_MOVIE_157336_URL).mock(return_value=Response(200, json=interstellar_payload()))

    response = client.post(
        reverse("update-tmdb"),
        {
            "week_id": arrival_week.pk,
            "tmdb_url": "https://www.themoviedb.org/movie/157336-interstellar",
            "redirect": "home",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == reverse("home")
    assert "Interstellar" in response.content.decode()


@respx.mock
def test_unmatched_week_can_be_matched_from_pick_page(client, unmatched_week, tmdb_settings):
    respx.get(TMDB_MOVIE_157336_URL).mock(return_value=Response(200, json=interstellar_payload()))

    response = client.post(
        reverse("update-tmdb"),
        {
            "week_id": unmatched_week.pk,
            "tmdb_url": "https://www.themoviedb.org/movie/157336-interstellar",
            "redirect": "week",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain[-1][0] == reverse("movie-detail", args=[157336])
    unmatched_week.refresh_from_db()
    assert unmatched_week.movie.tmdb_id == 157336
    assert unmatched_week.movie.title == "Interstellar"
    assert unmatched_week.match_status == Week.MatchStatus.MATCHED
    assert "Interstellar" in response.content.decode()


@respx.mock
def test_unmatched_week_error_returns_to_pick_page(client, unmatched_week, tmdb_settings):
    respx.get("https://api.themoviedb.org/3/movie/999999").mock(
        return_value=Response(404, json={"status_code": 34})
    )

    response = client.post(
        reverse("update-tmdb"),
        {
            "week_id": unmatched_week.pk,
            "tmdb_url": "https://www.themoviedb.org/movie/999999-missing",
            "redirect": "week",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert response.redirect_chain[-1][0].split("?")[0] == reverse(
        "week-detail", args=[unmatched_week.pk]
    )
    unmatched_week.refresh_from_db()
    assert unmatched_week.movie_id is None
    assert "TMDB could not load that movie" in response.content.decode()


def test_movie_detail_and_home_show_the_tmdb_update_form(client, arrival_week):
    detail_response = client.get(reverse("movie-detail", args=[329865]))
    detail_content = detail_response.content.decode()
    assert detail_response.status_code == 200
    assert "Wrong movie? Update TMDB URL" in detail_content
    assert 'name="tmdb_url"' in detail_content
    assert f'name="week_id" value="{arrival_week.pk}"' in detail_content

    home_response = client.get(reverse("home"))
    home_content = home_response.content.decode()
    assert home_response.status_code == 200
    assert "Wrong movie? Update TMDB URL" in home_content
    assert 'name="tmdb_url"' in home_content
    assert f'name="week_id" value="{arrival_week.pk}"' in home_content


def test_invalid_tmdb_url_does_not_change_the_week(client, arrival_week):
    original_movie_id = arrival_week.movie_id

    response = client.post(
        reverse("update-tmdb"),
        {
            "week_id": arrival_week.pk,
            "tmdb_url": "https://example.com/movie/603",
            "redirect": "detail",
            "return_tmdb_id": 329865,
        },
        follow=True,
    )

    assert response.status_code == 200
    arrival_week.refresh_from_db()
    assert arrival_week.movie_id == original_movie_id
    content = response.content.decode()
    assert "Enter a full TMDB movie URL" in content
    assert '<details class="tmdb-fix" open>' in content


def test_update_tmdb_requires_post(client):
    response = client.get(reverse("update-tmdb"))

    assert response.status_code == 405
