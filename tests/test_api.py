import pytest
import respx
from httpx import Response

from apps.club.models import Week
from apps.movies.models import Genre, Movie
from tests.conftest import (
    TMDB_MOVIE_URL,
    TMDB_SEARCH_URL,
    post_week,
)


@pytest.fixture
def tmdb_settings(settings):
    settings.TMDB_READ_ACCESS_TOKEN = "tmdb-token"


def mock_matrix_match():
    respx.get(TMDB_SEARCH_URL).mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "id": 603,
                        "title": "The Matrix",
                        "release_date": "1999-03-31",
                    }
                ]
            },
        )
    )
    respx.get(TMDB_MOVIE_URL).mock(
        return_value=Response(
            200,
            json={
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
            },
        )
    )


def test_missing_bot_token_is_rejected(client, db, payload, bot_headers):
    headers = {**bot_headers, "HTTP_AUTHORIZATION": "Bearer wrong"}

    response = post_week(client, payload, headers)

    assert response.status_code == 401
    assert Week.objects.count() == 0


def test_missing_idempotency_key_is_rejected(client, db, payload, bot_headers):
    headers = {k: v for k, v in bot_headers.items() if k != "HTTP_IDEMPOTENCY_KEY"}

    response = post_week(client, payload, headers)

    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["error"]


@respx.mock
def test_create_week_matches_tmdb(client, db, tmdb_settings, bot_headers, payload):
    mock_matrix_match()

    response = post_week(client, payload, bot_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["match_status"] == "matched"
    assert data["idempotent_replay"] is False
    assert data["movie"]["tmdb_id"] == 603
    assert data["movie"]["title"] == "The Matrix"
    assert data["movie"]["release_date"] == "1999-03-31"
    assert data["movie"]["poster_url"] == "https://image.tmdb.org/t/p/w500/matrix.jpg"
    assert data["movie"]["runtime"] == 136
    assert data["movie"]["budget"] == 63000000
    assert data["movie"]["revenue"] == 467222728
    assert data["movie"]["genres"] == ["Action", "Science Fiction"]
    assert data["selected_by"]["discord_id"] == "123"

    assert Week.objects.count() == 1
    assert Movie.objects.count() == 1
    assert Genre.objects.count() == 2


@respx.mock
def test_duplicate_key_returns_existing_week(client, db, tmdb_settings, bot_headers, payload):
    mock_matrix_match()

    first = post_week(client, payload, bot_headers)
    second = post_week(client, payload, bot_headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["idempotent_replay"] is True
    assert Week.objects.count() == 1


@respx.mock
def test_duplicate_key_with_different_payload_conflicts(
    client, db, tmdb_settings, bot_headers, payload
):
    mock_matrix_match()

    first = post_week(client, payload, bot_headers)
    assert first.status_code == 201

    changed = {
        **payload,
        "title": "The Matrix Reloaded",
    }
    second = post_week(client, changed, bot_headers)

    assert second.status_code == 409
    assert second.json()["week_id"] == first.json()["id"]
    assert Week.objects.count() == 1


@respx.mock
def test_unmatched_title_creates_week(client, db, tmdb_settings, bot_headers, payload):
    respx.get(TMDB_SEARCH_URL).mock(return_value=Response(200, json={"results": []}))

    response = post_week(client, payload, bot_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["match_status"] == "unmatched"
    assert data["movie"] is None
    assert Week.objects.count() == 1


@respx.mock
def test_tmdb_failure_still_creates_week(client, db, tmdb_settings, bot_headers, payload):
    respx.get(TMDB_SEARCH_URL).mock(return_value=Response(500))

    response = post_week(client, payload, bot_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["match_status"] == "error"
    assert "TMDB returned 500" in data["match_error"]
    assert data["movie"] is None
    assert Week.objects.count() == 1


@respx.mock
def test_retry_after_tmdb_failure_reenriches(client, db, tmdb_settings, bot_headers, payload):
    respx.get(TMDB_SEARCH_URL).mock(return_value=Response(500))
    first = post_week(client, payload, bot_headers)
    assert first.status_code == 201
    assert first.json()["match_status"] == "error"

    respx.get(TMDB_SEARCH_URL).mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "id": 603,
                        "title": "The Matrix",
                        "release_date": "1999-03-31",
                    }
                ]
            },
        )
    )
    respx.get(TMDB_MOVIE_URL).mock(
        return_value=Response(
            200,
            json={
                "id": 603,
                "title": "The Matrix",
                "release_date": "1999-03-31",
                "genres": [{"id": 28, "name": "Action"}],
            },
        )
    )

    second = post_week(client, payload, bot_headers)

    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["match_status"] == "matched"
    assert second.json()["idempotent_replay"] is True
    assert Week.objects.count() == 1


def test_health_endpoint(client, db):
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
