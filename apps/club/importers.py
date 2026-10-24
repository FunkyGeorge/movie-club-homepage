from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

START_HEADERS = ("start", "start_date", "start_on", "from", "week_start")
END_HEADERS = ("end", "end_date", "end_on", "to", "week_end")
SELECTOR_HEADERS = (
    "selector",
    "selected_by",
    "member",
    "person",
    "chooser",
    "chosen_by",
)
TITLE_HEADERS = ("title", "movie", "movie_title", "movie_name", "film", "film_title")
YEAR_HEADERS = ("year",)
PERIOD_HEADERS = ("period", "period_label", "date_range", "week", "dates")

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%m/%d",
    "%m-%d",
    "%b %d",
    "%B %d",
    "%d %b",
    "%d %B",
)


class ImportRowError(ValueError):
    def __init__(self, message: str, line_number: int | None = None) -> None:
        self.line_number = line_number
        if line_number is not None:
            message = f"line {line_number}: {message}"
        super().__init__(message)


@dataclass(frozen=True)
class _RawRow:
    line_number: int
    start_text: str
    end_text: str
    selector: str
    title: str
    period_label: str
    year: int | None
    start_month: int
    start_day: int
    end_month: int
    end_day: int
    start_year: int | None
    end_year: int | None


@dataclass(frozen=True)
class ImportRow:
    line_number: int
    starts_on: date
    ends_on: date
    selector: str
    title: str
    period_label: str
    import_key: str


def read_import_rows(
    path: Path,
    *,
    start_year: int | None,
    date_format: str | None = None,
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
) -> list[ImportRow]:
    raw_rows: list[_RawRow] = []

    try:
        with path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            try:
                raw_headers = next(reader)
            except StopIteration:
                raise ImportRowError("CSV file is empty.") from None

            headers = [_normalize_header(header) for header in raw_headers]
            if not any(headers):
                raise ImportRowError("CSV file has no header row.")

            duplicate_headers = {
                header for header in headers if header and headers.count(header) > 1
            }
            if duplicate_headers:
                duplicates = ", ".join(sorted(duplicate_headers))
                raise ImportRowError(f"CSV contains duplicate columns: {duplicates}.")

            for aliases, label in (
                (START_HEADERS, "start"),
                (END_HEADERS, "end"),
                (SELECTOR_HEADERS, "selector"),
                (TITLE_HEADERS, "title"),
            ):
                if not _has_any(headers, aliases):
                    raise ImportRowError(f"CSV must contain a {label} column.")

            for values in reader:
                if not any(value.strip() for value in values):
                    continue

                row = dict(zip(headers, values, strict=False))
                line_number = reader.line_num

                start_text = _first_value(row, START_HEADERS)
                end_text = _first_value(row, END_HEADERS)
                selector = _clean_text(_first_value(row, SELECTOR_HEADERS))
                title = _clean_text(_first_value(row, TITLE_HEADERS))
                period_label = _clean_text(_first_value(row, PERIOD_HEADERS))

                if not start_text or not end_text:
                    raise ImportRowError("start and end dates are required.", line_number)
                if not selector:
                    raise ImportRowError("selector is required.", line_number)
                if not title:
                    raise ImportRowError("title is required.", line_number)
                if len(selector) > 100:
                    raise ImportRowError("selector is longer than 100 characters.", line_number)
                if len(title) > 255:
                    raise ImportRowError("title is longer than 255 characters.", line_number)

                year = _parse_year(_first_value(row, YEAR_HEADERS), line_number)

                try:
                    start_month, start_day, start_year_value = _parse_date_parts(
                        start_text, date_format
                    )
                    end_month, end_day, end_year_value = _parse_date_parts(end_text, date_format)
                except ValueError as exc:
                    raise ImportRowError(str(exc), line_number) from exc

                raw_rows.append(
                    _RawRow(
                        line_number=line_number,
                        start_text=start_text,
                        end_text=end_text,
                        selector=selector,
                        title=title,
                        period_label=period_label,
                        year=year,
                        start_month=start_month,
                        start_day=start_day,
                        end_month=end_month,
                        end_day=end_day,
                        start_year=start_year_value,
                        end_year=end_year_value,
                    )
                )
    except OSError as exc:
        raise ImportRowError(f"Could not read {path}: {exc}") from exc
    except UnicodeError as exc:
        raise ImportRowError(f"Could not decode {path} as {encoding}: {exc}") from exc
    except csv.Error as exc:
        raise ImportRowError(f"Could not parse CSV: {exc}") from exc

    if not raw_rows:
        raise ImportRowError("CSV contains no data rows.")

    return _assign_dates(raw_rows, start_year)


def read_member_map(
    path: Path,
    *,
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
) -> dict[str, str]:
    try:
        with path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            try:
                headers = [_normalize_header(header) for header in next(reader)]
            except StopIteration:
                raise ImportRowError("Member map is empty.") from None

            if "source" not in headers or "target" not in headers:
                raise ImportRowError("Member map must contain source and target columns.")

            source_index = headers.index("source")
            target_index = headers.index("target")
            mapping: dict[str, str] = {}

            for values in reader:
                if not any(value.strip() for value in values):
                    continue
                try:
                    source = _clean_text(values[source_index])
                    target = _clean_text(values[target_index])
                except IndexError:
                    raise ImportRowError(
                        "Member map row is missing a source or target.",
                        reader.line_num,
                    ) from None

                if not source or not target:
                    raise ImportRowError(
                        "Member map source and target are required.",
                        reader.line_num,
                    )
                if len(target) > 100:
                    raise ImportRowError(
                        "Member map target is longer than 100 characters.",
                        reader.line_num,
                    )

                key = source.casefold()
                if key in mapping and mapping[key] != target:
                    raise ImportRowError(
                        f"Member map has conflicting entries for {source!r}.",
                        reader.line_num,
                    )
                mapping[key] = target
    except OSError as exc:
        raise ImportRowError(f"Could not read member map {path}: {exc}") from exc
    except UnicodeError as exc:
        raise ImportRowError(f"Could not decode member map {path} as {encoding}: {exc}") from exc
    except csv.Error as exc:
        raise ImportRowError(f"Could not parse member map: {exc}") from exc

    return mapping


def _assign_dates(raw_rows: list[_RawRow], start_year: int | None) -> list[ImportRow]:
    if start_year is not None and not 1900 <= start_year <= 2200:
        raise ImportRowError("--start-year must be between 1900 and 2200.")

    current_year = start_year
    previous_start: date | None = None
    rows: list[ImportRow] = []

    for raw in raw_rows:
        if raw.start_year is not None:
            year = raw.start_year
        elif raw.year is not None:
            year = raw.year
        else:
            if current_year is None:
                raise ImportRowError(
                    "no year available for this row; pass --start-year or add a year column.",
                    raw.line_number,
                )
            if previous_start is not None and (raw.start_month, raw.start_day) < (
                previous_start.month,
                previous_start.day,
            ):
                current_year += 1
            year = current_year

        current_year = year

        try:
            starts_on = date(year, raw.start_month, raw.start_day)
        except ValueError as exc:
            raise ImportRowError(f"invalid start date: {exc}", raw.line_number) from exc

        if raw.end_year is not None:
            end_year = raw.end_year
        else:
            end_year = year
            if (raw.end_month, raw.end_day) < (raw.start_month, raw.start_day):
                end_year += 1

        try:
            ends_on = date(end_year, raw.end_month, raw.end_day)
        except ValueError as exc:
            raise ImportRowError(f"invalid end date: {exc}", raw.line_number) from exc

        if ends_on < starts_on:
            raise ImportRowError("end date is before start date.", raw.line_number)
        if previous_start is not None and starts_on < previous_start:
            raise ImportRowError(
                "rows must be in chronological order; sort the CSV by start date.",
                raw.line_number,
            )
        previous_start = starts_on

        period_label = raw.period_label or f"{raw.start_text} - {raw.end_text}"
        if len(period_label) > 255:
            raise ImportRowError(
                "period label is longer than 255 characters.",
                raw.line_number,
            )

        rows.append(
            ImportRow(
                line_number=raw.line_number,
                starts_on=starts_on,
                ends_on=ends_on,
                selector=raw.selector,
                title=raw.title,
                period_label=period_label,
                import_key=_import_key(starts_on, ends_on, raw.selector, raw.title),
            )
        )

    return rows


def _import_key(starts_on: date, ends_on: date, selector: str, title: str) -> str:
    payload = "|".join(
        (
            starts_on.isoformat(),
            ends_on.isoformat(),
            selector.casefold(),
            title.casefold(),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_year(value: str, line_number: int) -> int | None:
    if not value:
        return None
    try:
        year = int(value)
    except ValueError:
        raise ImportRowError(f"invalid year {value!r}.", line_number) from None
    if not 1900 <= year <= 2200:
        raise ImportRowError("year must be between 1900 and 2200.", line_number)
    return year


def _parse_date_parts(value: str, date_format: str | None) -> tuple[int, int, int | None]:
    formats = (date_format,) if date_format else DATE_FORMATS

    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        explicit_year = parsed.year if "%Y" in fmt or "%y" in fmt else None
        return parsed.month, parsed.day, explicit_year

    raise ValueError(
        f"could not parse date {value!r}; use YYYY-MM-DD, MM/DD, or pass --date-format"
    )


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _has_any(headers: list[str], aliases: tuple[str, ...]) -> bool:
    return any(alias in headers for alias in aliases)


def _first_value(row: dict[str, str], aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        value = (row.get(alias) or "").strip()
        if value:
            return value
    return ""
