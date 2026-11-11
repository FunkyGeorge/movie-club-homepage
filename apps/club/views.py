from __future__ import annotations

from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Q, QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.movies.models import Genre, Movie
from apps.movies.sync import resolve_movie_by_id, sync_movie_metadata
from apps.movies.tmdb import TMDBError

from .models import Week


def _matched_weeks() -> QuerySet[Week]:
    return (
        Week.objects.filter(
            match_status=Week.MatchStatus.MATCHED,
            movie__isnull=False,
        )
        .select_related("movie")
        .prefetch_related("movie__genres")
    )


def _archive_weeks() -> QuerySet[Week]:
    return Week.objects.select_related("movie").prefetch_related("movie__genres")


def _current_week() -> Week | None:
    today = timezone.localdate()
    current = (
        _matched_weeks()
        .filter(starts_on__lte=today, ends_on__gte=today)
        .order_by("-starts_on", "-created_at")
        .first()
    )
    if current is not None:
        return current
    return _matched_weeks().order_by("-starts_on", "-created_at").first()


def _public_stats() -> dict[str, object]:
    matched = _matched_weeks()
    genre_counts = Counter(
        name for name in matched.values_list("movie__genres__name", flat=True) if name
    )
    average_runtime = (
        Movie.objects.filter(weeks__match_status=Week.MatchStatus.MATCHED)
        .distinct()
        .aggregate(average=Avg("runtime"))["average"]
    )
    return {
        "total_picks": matched.count(),
        "unique_movies": matched.values("movie_id").distinct().count(),
        "members": matched.values("selected_by_id").distinct().count(),
        "average_runtime": average_runtime or 0,
        "top_genres": [
            {"name": name, "count": count} for name, count in genre_counts.most_common(5)
        ],
    }


def _chart_available(filename: str) -> bool:
    return (settings.BASE_DIR / "static" / "charts" / filename).exists()


def home(request: HttpRequest) -> HttpResponse:
    current = _current_week()
    recent = _matched_weeks().order_by("-starts_on", "-created_at")
    if current is not None:
        recent = recent.exclude(pk=current.pk)

    today = timezone.localdate()
    current_is_active = bool(
        current
        and current.starts_on
        and current.ends_on
        and current.starts_on <= today <= current.ends_on
    )

    return render(
        request,
        "club/home.html",
        {
            "current": current,
            "current_is_active": current_is_active,
            "recent_weeks": recent[:6],
            "stats": _public_stats(),
            "join_url": settings.CLUB_JOIN_URL,
        },
    )


def archive(request: HttpRequest) -> HttpResponse:
    weeks = _archive_weeks()
    selected_query = request.GET.get("q", "").strip()
    selected_genre = request.GET.get("genre", "").strip()
    selected_decade = request.GET.get("decade", "").strip()

    if selected_query:
        weeks = weeks.filter(
            Q(title__icontains=selected_query) | Q(movie__title__icontains=selected_query)
        )
    if selected_genre:
        weeks = weeks.filter(movie__genres__name=selected_genre)
    if selected_decade:
        try:
            decade_start = int(selected_decade)
        except ValueError:
            selected_decade = ""
        else:
            weeks = weeks.filter(
                movie__release_date__year__gte=decade_start,
                movie__release_date__year__lt=decade_start + 10,
            )

    weeks = weeks.order_by("-starts_on", "-created_at").distinct()
    page_obj = Paginator(weeks, 24).get_page(request.GET.get("page"))

    release_years = (
        _matched_weeks()
        .exclude(movie__release_date__isnull=True)
        .values_list("movie__release_date__year", flat=True)
        .distinct()
    )
    decades = sorted(
        {str(year // 10 * 10) for year in release_years if year},
        key=int,
        reverse=True,
    )

    return render(
        request,
        "club/archive.html",
        {
            "page_obj": page_obj,
            "genres": Genre.objects.order_by("name").values_list("name", flat=True),
            "decades": decades,
            "selected_query": selected_query,
            "selected_genre": selected_genre,
            "selected_decade": selected_decade,
        },
    )


def movie_detail(request: HttpRequest, tmdb_id: int) -> HttpResponse:
    movie = get_object_or_404(
        Movie.objects.prefetch_related("genres"),
        tmdb_id=tmdb_id,
    )
    weeks = (
        movie.weeks.filter(match_status=Week.MatchStatus.MATCHED)
        .select_related("movie")
        .order_by("-starts_on", "-created_at")
    )
    return render(
        request,
        "club/movie_detail.html",
        {
            "movie": movie,
            "weeks": weeks,
            "pick_count": weeks.count(),
        },
    )


def week_detail(request: HttpRequest, week_id: int) -> HttpResponse:
    week = get_object_or_404(
        Week.objects.select_related("movie"),
        pk=week_id,
    )
    if week.movie_id:
        return redirect("movie-detail", tmdb_id=week.movie.tmdb_id)
    return render(
        request,
        "club/week_detail.html",
        {"week": week},
    )


@require_POST
def update_tmdb(request: HttpRequest) -> HttpResponse:
    """Re-match a week to a different TMDB movie and refresh its metadata."""
    raw_week_id = request.POST.get("week_id", "").strip()
    if not raw_week_id.isdigit():
        messages.error(request, "That pick could not be found.")
        return redirect("home")

    week = get_object_or_404(
        Week.objects.select_related("movie"),
        pk=int(raw_week_id),
    )
    redirect_to = request.POST.get("redirect", "detail")
    return_tmdb_id = request.POST.get("return_tmdb_id", "").strip()

    def back():
        if redirect_to == "home":
            return redirect("home")
        if redirect_to == "week":
            return redirect("week-detail", week_id=week.pk)
        if return_tmdb_id.isdigit():
            return redirect("movie-detail", tmdb_id=int(return_tmdb_id))
        if week.movie_id:
            return redirect("movie-detail", tmdb_id=week.movie.tmdb_id)
        return redirect("home")

    raw_tmdb_id = request.POST.get("tmdb_id", "").strip()
    try:
        tmdb_id = int(raw_tmdb_id)
    except ValueError:
        messages.error(request, "Enter a numeric TMDB ID.")
        return back()

    if tmdb_id < 1:
        messages.error(request, "Enter a positive TMDB ID.")
        return back()

    if week.movie_id and week.movie.tmdb_id == tmdb_id:
        if not sync_movie_metadata(week.movie):
            messages.error(
                request,
                f"Could not refresh TMDB data for {week.movie.title}: {week.movie.sync_error}",
            )
            return back()
        messages.success(request, f"TMDB details refreshed for {week.movie.title}.")
    else:
        try:
            movie = resolve_movie_by_id(tmdb_id)
        except TMDBError as exc:
            messages.error(request, f"TMDB lookup failed: {exc}")
            return back()

        week.movie = movie
        week.match_status = Week.MatchStatus.MATCHED
        week.match_error = ""
        week.save(update_fields=["movie", "match_status", "match_error", "updated_at"])
        messages.success(request, f"TMDB match updated to {movie.title}.")

    if redirect_to == "home":
        return redirect("home")
    return redirect("movie-detail", tmdb_id=week.movie.tmdb_id)


def stats(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "club/stats.html",
        {
            "stats": _public_stats(),
            "genre_chart_available": _chart_available("genre-pie.png"),
            "release_year_chart_available": _chart_available("release-years.png"),
        },
    )


def about(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "club/about.html",
        {"join_url": settings.CLUB_JOIN_URL},
    )
