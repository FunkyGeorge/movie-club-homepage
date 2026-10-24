from __future__ import annotations

from datetime import date
from io import StringIO
from textwrap import dedent

import pytest
import respx
from django.core.management import CommandError, call_command
from httpx import Response

from apps.club.models import Member, Week
from apps.movies.models import Genre, Movie
from tests.conftest import TMDB_MOVIE_URL, TMDB_SEARCH_URL


def write_file(path, contents: str):
    path.write_text(dedent(contents).lstrip(), encoding="utf-8")
    return path


def run_import(path, *args: str) -> str:
    output = StringIO()
    call_command("import_weeks", str(path), *args, stdout=output)
    return output.getvalue()


def test_import_infers_year_rollover_and_creates_legacy_members(db, member, tmp_path):
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        12-25,12-31,George,Die Hard
        01-01,01-07,Alex,The Matrix
        01-08,01-14,George,Arrival
        """,
    )

    output = run_import(path, "--start-year", "2023", "--skip-tmdb")

    assert Week.objects.count() == 3

    first = Week.objects.get(starts_on=date(2023, 12, 25))
    second = Week.objects.get(starts_on=date(2024, 1, 1))
    third = Week.objects.get(starts_on=date(2024, 1, 8))

    assert first.ends_on == date(2023, 12, 31)
    assert second.ends_on == date(2024, 1, 7)
    assert third.ends_on == date(2024, 1, 14)
    assert first.period_label == "12-25 - 12-31"
    assert first.selected_by == member
    assert second.selected_by.display_name == "Alex"
    assert second.selected_by.discord_id is None
    assert second.selected_by.username.startswith("legacy_alex")
    assert third.selected_by == member

    assert len(first.import_key) == 64
    assert len({first.import_key, second.import_key, third.import_key}) == 3
    assert "Imported 3 weeks" in output


def test_import_handles_week_crossing_new_year(db, member, tmp_path):
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        12-29,01-04,George,New Year Movie
        """,
    )

    run_import(path, "--start-year", "2024", "--skip-tmdb")

    week = Week.objects.get()
    assert week.starts_on == date(2024, 12, 29)
    assert week.ends_on == date(2025, 1, 4)


def test_import_dry_run_writes_nothing(db, member, tmp_path):
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        01-01,01-07,George,The Matrix
        01-08,01-14,Alex,Arrival
        """,
    )

    output = run_import(path, "--start-year", "2024", "--skip-tmdb", "--dry-run")

    assert Week.objects.count() == 0
    assert Member.objects.count() == 1
    assert "Dry run" in output
    assert "Weeks to create: 2" in output
    assert "Members to create: 1" in output
    assert "New members: Alex" in output


def test_import_is_idempotent(db, member, tmp_path):
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        01-01,01-07,George,The Matrix
        01-08,01-14,Alex,Arrival
        """,
    )

    run_import(path, "--start-year", "2024", "--skip-tmdb")
    second = run_import(path, "--start-year", "2024", "--skip-tmdb")

    assert Week.objects.count() == 2
    assert "skipped 2" in second.lower()


def test_import_uses_year_column_without_start_year(db, member, tmp_path):
    path = write_file(
        tmp_path / "choices.csv",
        """
        year,start,end,selector,title
        2024,01-01,01-07,George,The Matrix
        2024,2024-01-08,2024-01-14,Alex,Arrival
        """,
    )

    run_import(path, "--skip-tmdb")

    assert Week.objects.get(starts_on=date(2024, 1, 1)).ends_on == date(2024, 1, 7)
    assert Week.objects.get(starts_on=date(2024, 1, 8)).ends_on == date(2024, 1, 14)


def test_import_member_map(db, member, tmp_path):
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        01-01,01-07,Georgie,The Matrix
        """,
    )
    member_map = write_file(
        tmp_path / "members.csv",
        """
        source,target
        Georgie,George
        """,
    )

    run_import(
        path,
        "--start-year",
        "2024",
        "--member-map",
        str(member_map),
        "--skip-tmdb",
    )

    week = Week.objects.get()
    assert week.selected_by == member
    assert not Member.objects.filter(display_name="Georgie").exists()


@respx.mock
def test_import_enriches_tmdb(db, member, tmp_path, settings):
    settings.TMDB_READ_ACCESS_TOKEN = "tmdb-token"
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        01-01,01-07,George,The Matrix
        """,
    )

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
                "genres": [
                    {"id": 28, "name": "Action"},
                    {"id": 878, "name": "Science Fiction"},
                ],
            },
        )
    )

    output = run_import(path, "--start-year", "2024")

    week = Week.objects.get()
    assert week.match_status == "matched"
    assert week.movie.tmdb_id == 603
    assert sorted(week.movie.genres.values_list("name", flat=True)) == [
        "Action",
        "Science Fiction",
    ]
    assert Movie.objects.count() == 1
    assert Genre.objects.count() == 2
    assert "1 matched" in output


def test_import_without_tmdb_token_leaves_pending(db, member, tmp_path, settings):
    settings.TMDB_READ_ACCESS_TOKEN = ""
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        01-01,01-07,George,The Matrix
        """,
    )

    output = run_import(path, "--start-year", "2024")

    week = Week.objects.get()
    assert week.match_status == "pending"
    assert "not configured" in output


def test_import_invalid_date_fails(db, tmp_path):
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        13/40,01-07,George,The Matrix
        """,
    )

    with pytest.raises(CommandError, match="could not parse date"):
        call_command(
            "import_weeks",
            str(path),
            "--start-year",
            "2024",
            "--skip-tmdb",
        )

    assert Week.objects.count() == 0


def test_import_requires_start_year_without_year_values(db, tmp_path):
    path = write_file(
        tmp_path / "choices.csv",
        """
        start,end,selector,title
        01-01,01-07,George,The Matrix
        """,
    )

    with pytest.raises(CommandError, match="start-year"):
        call_command("import_weeks", str(path), "--skip-tmdb")


@respx.mock
def test_enrich_weeks_retries_pending(db, member, settings):
    settings.TMDB_READ_ACCESS_TOKEN = "tmdb-token"
    week = Week.objects.create(title="The Matrix", selected_by=member)

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

    output = StringIO()
    call_command("enrich_weeks", stdout=output)

    week.refresh_from_db()
    assert week.match_status == "matched"
    assert week.movie.tmdb_id == 603
    assert "1 matched" in output.getvalue()


def test_enrich_weeks_requires_tmdb_token(db, member, settings):
    settings.TMDB_READ_ACCESS_TOKEN = ""
    Week.objects.create(title="The Matrix", selected_by=member)

    with pytest.raises(CommandError, match="TMDB_READ_ACCESS_TOKEN"):
        call_command("enrich_weeks")
