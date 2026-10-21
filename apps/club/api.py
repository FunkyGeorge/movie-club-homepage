from __future__ import annotations

import json
import logging
import secrets

from django.conf import settings
from django.db import IntegrityError, connection
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.movies.sync import resolve_movie
from apps.movies.tmdb import TMDBError

from .models import Member, Week

logger = logging.getLogger(__name__)

MAX_IDEMPOTENCY_KEY_LENGTH = 64


def _json_error(message: str, status: int, **extra) -> JsonResponse:
    payload = {"error": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _authenticate(request: HttpRequest) -> bool:
    configured = settings.BOT_API_TOKEN
    if not configured:
        return False

    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return False

    token = token.strip()
    if not token:
        return False

    return secrets.compare_digest(token, configured)


def _normalize_title(title: str) -> str:
    return " ".join(title.split())


def _payload_matches(week: Week, title: str, discord_id: str) -> bool:
    return week.title.casefold() == title.casefold() and week.selected_by.discord_id == discord_id


def _serialize_week(week: Week, *, replay: bool = False) -> dict:
    movie = week.movie
    return {
        "id": week.id,
        "title": week.title,
        "selected_by": {
            "discord_id": week.selected_by.discord_id,
            "display_name": week.selected_by.display_name,
        },
        "movie": None
        if movie is None
        else {
            "tmdb_id": movie.tmdb_id,
            "title": movie.title,
            "release_date": movie.release_date.isoformat() if movie.release_date else None,
            "genres": [genre.name for genre in movie.genres.all()],
        },
        "match_status": week.match_status,
        "match_error": week.match_error,
        "idempotent_replay": replay,
        "created_at": week.created_at.isoformat(),
    }


def _get_week(week_id: int) -> Week:
    return (
        Week.objects.select_related("selected_by", "movie")
        .prefetch_related("movie__genres")
        .get(pk=week_id)
    )


def _enrich_week(week: Week) -> None:
    try:
        movie = resolve_movie(week.title)
    except TMDBError as exc:
        # Keep any existing match on a transient TMDB failure.
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


@csrf_exempt
@require_POST
def create_week(request: HttpRequest) -> JsonResponse:
    if not _authenticate(request):
        return _json_error("Invalid or missing bot token.", 401)

    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        return _json_error("Idempotency-Key header is required.", 400)
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        return _json_error("Idempotency-Key is too long.", 400)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Request body must be valid JSON.", 400)

    if not isinstance(payload, dict):
        return _json_error("Request body must be a JSON object.", 400)

    title = payload.get("title")
    selected_by = payload.get("selected_by")

    if not isinstance(title, str) or not title.strip():
        return _json_error("title is required.", 400)
    if not isinstance(selected_by, dict):
        return _json_error("selected_by is required.", 400)

    discord_id = selected_by.get("discord_id")
    display_name = selected_by.get("display_name", "")

    if not isinstance(discord_id, str) or not discord_id.strip():
        return _json_error("selected_by.discord_id is required.", 400)
    if display_name is not None and not isinstance(display_name, str):
        return _json_error("selected_by.display_name must be a string.", 400)

    title = _normalize_title(title)
    discord_id = discord_id.strip()
    display_name = display_name.strip() if display_name else ""

    existing = (
        Week.objects.select_related("selected_by", "movie")
        .prefetch_related("movie__genres")
        .filter(idempotency_key=key)
        .first()
    )

    if existing is not None:
        if not _payload_matches(existing, title, discord_id):
            return _json_error(
                "Idempotency-Key was already used with a different payload.",
                409,
                week_id=existing.id,
            )

        if existing.match_status in (Week.MatchStatus.PENDING, Week.MatchStatus.ERROR):
            _enrich_week(existing)
            existing = _get_week(existing.id)

        return JsonResponse(_serialize_week(existing, replay=True), status=200)

    member, created = Member.objects.get_or_create(
        discord_id=discord_id,
        defaults={
            "username": f"discord_{discord_id}",
            "display_name": display_name or discord_id,
        },
    )
    if not created and display_name and member.display_name != display_name:
        member.display_name = display_name
        member.save(update_fields=["display_name"])

    try:
        week = Week.objects.create(
            title=title,
            selected_by=member,
            idempotency_key=key,
        )
    except IntegrityError:
        # A concurrent request won the race for this key.
        week = Week.objects.filter(idempotency_key=key).first()
        if week is None:
            raise
        week = _get_week(week.id)
        if not _payload_matches(week, title, discord_id):
            return _json_error(
                "Idempotency-Key was already used with a different payload.",
                409,
                week_id=week.id,
            )

        if week.match_status in (Week.MatchStatus.PENDING, Week.MatchStatus.ERROR):
            _enrich_week(week)
            week = _get_week(week.id)

        return JsonResponse(_serialize_week(week, replay=True), status=200)

    _enrich_week(week)
    week = _get_week(week.id)
    return JsonResponse(_serialize_week(week), status=201)


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("Health check failed")
        return _json_error("Database unavailable.", 503)

    return JsonResponse({"status": "ok"})
