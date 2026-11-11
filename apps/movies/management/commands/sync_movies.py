from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.movies.models import Movie
from apps.movies.sync import sync_movie_metadata


class Command(BaseCommand):
    help = (
        "Refresh TMDB metadata for stored movies, including poster, runtime, budget, and revenue."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--missing",
            action="store_true",
            help="Only sync movies missing a poster, runtime, budget, or revenue.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Process at most this many movies.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many movies would be synced without calling TMDB.",
        )

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")

        queryset = Movie.objects.order_by("title")
        if options["missing"]:
            queryset = queryset.filter(
                Q(poster_path__isnull=True)
                | Q(poster_path="")
                | Q(runtime__isnull=True)
                | Q(budget__isnull=True)
                | Q(revenue__isnull=True)
            )
        if options["limit"] is not None:
            queryset = queryset[: options["limit"]]

        movies = list(queryset)
        if not movies:
            self.stdout.write("No movies need syncing.")
            return

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no changes written."))
            self.stdout.write(f"Movies to sync: {len(movies)}")
            return

        if not settings.TMDB_READ_ACCESS_TOKEN:
            raise CommandError("TMDB_READ_ACCESS_TOKEN is not configured.")

        succeeded = 0
        failed = 0

        for index, movie in enumerate(movies, start=1):
            if sync_movie_metadata(movie):
                succeeded += 1
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"Failed: {movie.title} ({movie.tmdb_id})"))

            if index % 25 == 0:
                self.stdout.write(f"Processed {index}/{len(movies)} movies...")

        self.stdout.write(
            self.style.SUCCESS(
                f"Sync complete: {succeeded} succeeded, {failed} failed. "
                "See sync_error for details."
            )
        )
