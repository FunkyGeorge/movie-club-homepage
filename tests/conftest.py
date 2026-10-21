import json

import pytest
from django.contrib.auth import get_user_model

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_MOVIE_URL = "https://api.themoviedb.org/3/movie/603"


@pytest.fixture
def member(db):
    return get_user_model().objects.create_user(
        username="discord_123",
        discord_id="123",
        display_name="George",
    )


@pytest.fixture
def bot_headers(settings):
    settings.BOT_API_TOKEN = "test-token"
    return {
        "HTTP_AUTHORIZATION": "Bearer test-token",
        "HTTP_IDEMPOTENCY_KEY": "test-key",
    }


@pytest.fixture
def payload():
    return {
        "title": "The Matrix",
        "selected_by": {
            "discord_id": "123",
            "display_name": "George",
        },
    }


def post_week(client, payload, headers):
    return client.post(
        "/api/weeks/",
        data=json.dumps(payload),
        content_type="application/json",
        **headers,
    )
