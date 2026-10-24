from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from apps.club.importers import ImportRow, ImportRowError, read_import_rows, read_member_map
from apps.club.models import Member, Week
from apps.club.services import enrich_week


class Command(BaseCommand):
    help = "Import historical movie club weeks from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=Path)
        parser.add_argument(
            "--start-year",
            type=int,
            help="Year for the first row when the CSV dates do not include years.",
        )
        parser.add_argument(
            "--date-format",
            help="Optional strptime format, e.g. '%%m/%%d' or '%%d/%%m'.",
        )
        parser.add_argument("--delimiter", default=",", help="CSV delimiter (default: comma).")
        parser.add_argument(
            "--encoding",
            default="utf-8-sig",
            help="CSV encoding (default: utf-8-sig).",
        )
        parser.add_argument(
            "--member-map",
            type=Path,
            help="Optional CSV with source,target selector names.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report without writing anything.",
        )
        parser.add_argument(
            "--skip-tmdb",
            action="store_true",
            help="Import rows without matching them against TMDB.",
        )

    def handle(self, *args, **options):
        try:
            rows = read_import_rows(
                options["csv_path"],
                start_year=options["start_year"],
                date_format=options["date_format"],
                delimiter=options["delimiter"],
                encoding=options["encoding"],
            )
            member_map = (
                read_member_map(
                    options["member_map"],
                    delimiter=options["delimiter"],
                    encoding=options["encoding"],
                )
                if options["member_map"]
                else {}
            )
        except ImportRowError as exc:
            raise CommandError(str(exc)) from exc

        if options["dry_run"]:
            self._dry_run(rows, member_map)
            return

        created_ids, created_members, skipped = self._write_rows(rows, member_map)

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(created_ids)} weeks, skipped {skipped} rows "
                f"(existing or duplicate), created {created_members} members."
            )
        )

        if not created_ids:
            return

        if options["skip_tmdb"]:
            self.stdout.write("TMDB enrichment skipped (--skip-tmdb).")
            return

        if not settings.TMDB_READ_ACCESS_TOKEN:
            self.stdout.write(
                self.style.WARNING(
                    "TMDB_READ_ACCESS_TOKEN is not configured; imported weeks are "
                    "pending. Add a token and run 'manage.py enrich_weeks'."
                )
            )
            return

        self._enrich(created_ids)

    def _dry_run(self, rows: list[ImportRow], member_map: dict[str, str]) -> None:
        unique_keys = {row.import_key for row in rows}
        existing_keys = set(
            Week.objects.filter(import_key__in=unique_keys).values_list("import_key", flat=True)
        )
        to_create = len(unique_keys - existing_keys)
        skipped = len(rows) - to_create

        new_rows = [row for row in rows if row.import_key not in existing_keys]
        targets = {self._target_name(row.selector, member_map) for row in new_rows}
        would_create_members = sorted(
            target for target in targets if self._find_member(target) is None
        )

        self.stdout.write(self.style.WARNING("Dry run: no changes written."))
        self.stdout.write(f"Rows read: {len(rows)}")
        self.stdout.write(f"Weeks to create: {to_create}")
        self.stdout.write(f"Rows skipped (existing or duplicate): {skipped}")
        self.stdout.write(f"Members to create: {len(would_create_members)}")
        if would_create_members:
            self.stdout.write(f"New members: {', '.join(would_create_members)}")
        self.stdout.write(
            f"Date range: {rows[0].starts_on.isoformat()} to {rows[-1].ends_on.isoformat()}"
        )

    def _write_rows(
        self,
        rows: list[ImportRow],
        member_map: dict[str, str],
    ) -> tuple[list[int], int, int]:
        created_ids: list[int] = []
        created_members = 0
        skipped = 0
        member_cache: dict[str, Member] = {}

        with transaction.atomic():
            for row in rows:
                if Week.objects.filter(import_key=row.import_key).exists():
                    skipped += 1
                    continue

                target = self._target_name(row.selector, member_map)
                cache_key = target.casefold()
                member = member_cache.get(cache_key)

                if member is None:
                    member = self._find_member(target)
                    if member is None:
                        member = self._create_legacy_member(target)
                        created_members += 1
                    member_cache[cache_key] = member

                week = Week.objects.create(
                    title=row.title,
                    starts_on=row.starts_on,
                    ends_on=row.ends_on,
                    period_label=row.period_label,
                    selected_by=member,
                    import_key=row.import_key,
                )
                created_ids.append(week.pk)

        return created_ids, created_members, skipped

    def _enrich(self, created_ids: list[int]) -> None:
        counts = {
            Week.MatchStatus.MATCHED: 0,
            Week.MatchStatus.UNMATCHED: 0,
            Week.MatchStatus.ERROR: 0,
        }
        weeks = (
            Week.objects.filter(pk__in=created_ids)
            .select_related("movie")
            .order_by("starts_on", "pk")
        )

        for week in weeks:
            enrich_week(week)
            counts[week.match_status] = counts.get(week.match_status, 0) + 1
            self.stdout.write(
                f"  {week.starts_on.isoformat()}: {week.title} -> {week.match_status}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"TMDB: {counts[Week.MatchStatus.MATCHED]} matched, "
                f"{counts[Week.MatchStatus.UNMATCHED]} unmatched, "
                f"{counts[Week.MatchStatus.ERROR]} errors."
            )
        )

    def _target_name(self, selector: str, member_map: dict[str, str]) -> str:
        return member_map.get(selector.casefold(), selector)

    def _find_member(self, display_name: str) -> Member | None:
        return Member.objects.filter(display_name__iexact=display_name).order_by("id").first()

    def _create_legacy_member(self, display_name: str) -> Member:
        base = f"legacy_{slugify(display_name) or 'member'}"[:140]
        username = base
        suffix = 2

        while Member.objects.filter(username=username).exists():
            suffix_text = f"_{suffix}"
            username = f"{base[: 140 - len(suffix_text)]}{suffix_text}"
            suffix += 1

        member = Member(username=username, display_name=display_name)
        member.set_unusable_password()
        member.save()
        return member
