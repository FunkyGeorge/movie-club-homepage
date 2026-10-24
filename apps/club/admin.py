from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from .models import Member, Week
from .services import enrich_week


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
    list_display = (
        "title",
        "starts_on",
        "ends_on",
        "selected_by",
        "movie",
        "match_status",
    )
    list_filter = ("match_status", "created_at")
    date_hierarchy = "starts_on"
    search_fields = (
        "title",
        "period_label",
        "import_key",
        "selected_by__display_name",
        "selected_by__discord_id",
        "movie__title",
    )
    autocomplete_fields = ("selected_by", "movie")
    list_select_related = ("selected_by", "movie")
    readonly_fields = (
        "idempotency_key",
        "import_key",
        "match_error",
        "created_at",
        "updated_at",
    )
    actions = ("rerun_tmdb_search",)

    @admin.action(description="Re-run TMDB search for selected weeks")
    def rerun_tmdb_search(self, request, queryset):
        counts = {
            Week.MatchStatus.MATCHED: 0,
            Week.MatchStatus.UNMATCHED: 0,
            Week.MatchStatus.ERROR: 0,
        }

        for week in queryset.select_related("selected_by"):
            enrich_week(week)
            counts[week.match_status] = counts.get(week.match_status, 0) + 1

        self.message_user(
            request,
            f"Re-search complete: {counts[Week.MatchStatus.MATCHED]} matched, "
            f"{counts[Week.MatchStatus.UNMATCHED]} unmatched, "
            f"{counts[Week.MatchStatus.ERROR]} errors.",
            level=messages.INFO,
        )
