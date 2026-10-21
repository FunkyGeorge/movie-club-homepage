from django.contrib import admin, messages

from .models import Genre, Movie
from .sync import sync_movie_metadata


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "tmdb_id")
    search_fields = ("name",)


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ("title", "tmdb_id", "release_date", "last_synced_at", "sync_error")
    search_fields = ("title",)
    filter_horizontal = ("genres",)
    readonly_fields = ("last_synced_at", "sync_error")
    actions = ("resync_metadata",)

    @admin.action(description="Re-sync metadata and genres from TMDB")
    def resync_metadata(self, request, queryset):
        succeeded = 0
        failed = 0

        for movie in queryset:
            if sync_movie_metadata(movie):
                succeeded += 1
            else:
                failed += 1

        self.message_user(
            request,
            f"Sync complete: {succeeded} succeeded, {failed} failed. "
            "See sync_error for details.",
            level=messages.INFO,
        )
