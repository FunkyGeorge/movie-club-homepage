from datetime import date, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.club.models import Week
from apps.movies.models import Genre, Movie


@pytest.fixture
def public_data(member):
    action = Genre.objects.create(tmdb_id=28, name="Action")
    drama = Genre.objects.create(tmdb_id=18, name="Drama")

    matrix = Movie.objects.bulk_create(
        [
            Movie(
                tmdb_id=603,
                title="The Matrix",
                release_date=date(1999, 3, 31),
                poster_path="/matrix.jpg",
                runtime=136,
            )
        ]
    )[0]
    matrix.genres.add(action)

    arrival = Movie.objects.bulk_create(
        [
            Movie(
                tmdb_id=329865,
                title="Arrival",
                release_date=date(2016, 11, 11),
                poster_path="/arrival.jpg",
                runtime=116,
            )
        ]
    )[0]
    arrival.genres.add(drama)

    today = timezone.localdate()
    current = Week.objects.create(
        title="Arrival",
        starts_on=today - timedelta(days=2),
        ends_on=today + timedelta(days=2),
        selected_by=member,
        movie=arrival,
        match_status=Week.MatchStatus.MATCHED,
    )
    older = Week.objects.create(
        title="The Matrix",
        starts_on=date(2020, 1, 1),
        ends_on=date(2020, 1, 7),
        selected_by=member,
        movie=matrix,
        match_status=Week.MatchStatus.MATCHED,
    )
    hidden = Week.objects.create(
        title="Hidden Pick",
        starts_on=date(2021, 1, 1),
        ends_on=date(2021, 1, 7),
        selected_by=member,
        movie=None,
        match_status=Week.MatchStatus.UNMATCHED,
    )

    return {
        "current": current,
        "older": older,
        "hidden": hidden,
        "matrix": matrix,
        "arrival": arrival,
    }


def assert_no_member_identity(response):
    content = response.content.decode()
    assert "George" not in content
    assert "discord_123" not in content
    assert "Selected by" not in content


def test_home_shows_current_pick_and_recent_history(client, public_data):
    response = client.get(reverse("home"))

    assert response.status_code == 200
    assert "Arrival" in response.content.decode()
    assert "Now showing" in response.content.decode()
    assert "https://image.tmdb.org/t/p/w500/arrival.jpg" in response.content.decode()
    assert "https://image.tmdb.org/t/p/w500/matrix.jpg" in response.content.decode()
    assert "The Matrix" in response.content.decode()
    assert "Hidden Pick" not in response.content.decode()
    assert_no_member_identity(response)


@pytest.mark.parametrize("url_name", ["stats", "about"])
def test_public_info_pages_hide_member_identity(client, public_data, url_name):
    response = client.get(reverse(url_name))

    assert response.status_code == 200
    assert_no_member_identity(response)


def test_stats_page_includes_public_charts(client, public_data):
    response = client.get(reverse("stats"))

    assert response.status_code == 200
    assert b"charts/genre-pie.png" in response.content
    assert b"charts/release-years.png" in response.content


def test_archive_includes_unmatched_weeks_and_filters(client, public_data):
    response = client.get(reverse("archive"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "3 picks" in content
    assert "Arrival" in content
    assert "The Matrix" in content
    assert "Hidden Pick" in content
    assert "movie-card-unmatched" in content
    assert reverse("week-detail", args=[public_data["hidden"].pk]) in content
    assert "Jan 1, 2021 – Jan 7, 2021" in content
    assert_no_member_identity(response)

    response = client.get(reverse("archive"), {"genre": "Action"})
    content = response.content.decode()
    assert "The Matrix" in content
    assert "Arrival" not in content
    assert "Hidden Pick" not in content

    response = client.get(reverse("archive"), {"decade": "1990"})
    content = response.content.decode()
    assert "The Matrix" in content
    assert "Arrival" not in content
    assert "Hidden Pick" not in content

    response = client.get(reverse("archive"), {"q": "Arrival"})
    content = response.content.decode()
    assert "Arrival" in content
    assert "The Matrix" not in content
    assert "Hidden Pick" not in content

    response = client.get(reverse("archive"), {"q": "Hidden"})
    content = response.content.decode()
    assert "Hidden Pick" in content
    assert "Arrival" not in content
    assert "The Matrix" not in content


def test_unmatched_week_detail_shows_tmdb_form_without_chooser(client, public_data):
    hidden = public_data["hidden"]
    response = client.get(reverse("week-detail", args=[hidden.pk]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Hidden Pick" in content
    assert "Jan 1, 2021 – Jan 7, 2021" in content
    assert "This pick has not been matched to a TMDB movie yet" in content
    assert reverse("update-tmdb") in content
    assert f'name="week_id" value="{hidden.pk}"' in content
    assert_no_member_identity(response)


def test_matched_week_detail_redirects_to_movie_detail(client, public_data):
    week = public_data["current"]

    response = client.get(reverse("week-detail", args=[week.pk]))

    assert response.status_code == 302
    assert response.url == reverse("movie-detail", args=[week.movie.tmdb_id])


def test_movie_detail_shows_pick_history_without_chooser(client, public_data):
    response = client.get(reverse("movie-detail", args=[public_data["matrix"].tmdb_id]))

    assert response.status_code == 200
    assert "The Matrix" in response.content.decode()
    assert "Picked 1 time" in response.content.decode()
    assert_no_member_identity(response)
