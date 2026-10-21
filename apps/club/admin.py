from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from apps.movies.sync import resolve_movie
from apps.movies.tmdb import TMDBError

from .models import Member, Week


@admin.register(Member)
class MemberAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Discord", {"fields": ("discord_id", "display_name")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Discord", {"fields": ("discord_id", "display_name")}),
    )
    list_display = ("username", "display_name", "discord_id", "is_staff", "is_active")
    search_fields = ("username", "display_name", "discord_id")


@admin.register(Week)
class WeekAdmin(admin.ModelAdmin):
    list_display = ("title", "selected_by", "movie", "match_status", "created_at")
    list_filter = ("match_status", "created_at")
    search_fields = (
        "title",
        "selected_by__display_name",
        "selected_by__discord_id",
        "movie__title",
    )
    autocomplete_fields = ("selected_by", "movie")
    readonly_fields = ("idempotency_key", "match_error", "created_at", "updated_at")
    actions = ("rerun_tmdb_search",)

    @admin.action(description="Re-run TMDB search for selected weeks")
    def rerun_tmdb_search(self, request, queryset):
        matched = 0
        unmatched = 0
        errors = 0

        for week in queryset.select_related("selected_by"):
            try:
                movie = resolve_movie(week.title)
            except TMDBError as exc:
                # Keep any existing match on a transient TMDB failure.
                week.match_status = Week.MatchStatus.ERROR
                week.match_error = str(exc)
                errors += 1
            else:
                week.movie = movie
                if movie is None:
                    week.match_status = Week.MatchStatus.UNMATCHED
                    week.match_error = ""
                    unmatched += 1
                else:
                    week.match_status = Week.MatchStatus.MATCHED
                    week.match_error = ""
                    matched += 1

            week.save(update_fields=["movie", "match_status", "match_error", "updated_at"])

        self.message_user(
            request,
            f"Re-search complete: {matched} matched, {unmatched} unmatched, {errors} errors.",
            level=messages.INFO,
        )
