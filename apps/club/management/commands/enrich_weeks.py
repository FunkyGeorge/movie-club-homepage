from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.club.models import Week
from apps.club.services import enrich_week


class Command(BaseCommand):
    help = "Retry TMDB matching for imported or pending weeks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-run matching for every week, including matched and unmatched ones.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Process at most this many weeks.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many weeks would be processed without calling TMDB.",
        )

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")

        queryset = Week.objects.select_related("movie", "selected_by").order_by(
            "starts_on", "created_at"
        )
        if not options["all"]:
            queryset = queryset.filter(
                match_status__in=[Week.MatchStatus.PENDING, Week.MatchStatus.ERROR]
            )
        if options["limit"] is not None:
            queryset = queryset[: options["limit"]]

        weeks = list(queryset)

        if not weeks:
            self.stdout.write("No weeks need enrichment.")
            return

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no changes written."))
            self.stdout.write(f"Weeks to process: {len(weeks)}")
            return

        if not settings.TMDB_READ_ACCESS_TOKEN:
            raise CommandError("TMDB_READ_ACCESS_TOKEN is not configured.")

        counts = {
            Week.MatchStatus.MATCHED: 0,
            Week.MatchStatus.UNMATCHED: 0,
            Week.MatchStatus.ERROR: 0,
        }

        for week in weeks:
            enrich_week(week)
            counts[week.match_status] = counts.get(week.match_status, 0) + 1
            when = week.starts_on.isoformat() if week.starts_on else "no date"
            self.stdout.write(f"{week.pk} [{when}] {week.title}: {week.match_status}")

        self.stdout.write(
            self.style.SUCCESS(
                f"TMDB: {counts[Week.MatchStatus.MATCHED]} matched, "
                f"{counts[Week.MatchStatus.UNMATCHED]} unmatched, "
                f"{counts[Week.MatchStatus.ERROR]} errors."
            )
        )
