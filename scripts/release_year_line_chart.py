from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import django
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, MultipleLocator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "charts" / "release-years.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a line chart of movie count by release year."
    )
    parser.add_argument(
        "--start-year",
        type=int,
        help="First release year to include (default: earliest in the database).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        help="Last release year to include (default: latest in the database).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output PNG path (default: {DEFAULT_OUTPUT.relative_to(PROJECT_ROOT)}).",
    )
    args = parser.parse_args()
    if args.start_year is not None and args.end_year is not None:
        if args.start_year > args.end_year:
            parser.error("--start-year must be before or equal to --end-year")
    return args


def main() -> None:
    args = parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from apps.movies.models import Movie

    release_dates = list(
        Movie.objects.exclude(release_date__isnull=True).values_list("release_date", flat=True)
    )
    if not release_dates:
        raise SystemExit("No movies with release dates found. Import and sync some movies first.")

    years = pd.Series([release_date.year for release_date in release_dates], dtype="int64")
    counts = years.value_counts().sort_index()

    start_year = args.start_year if args.start_year is not None else int(counts.index.min())
    end_year = args.end_year if args.end_year is not None else int(counts.index.max())
    all_years = pd.Index(range(start_year, end_year + 1), name="release_year")
    counts = counts.reindex(all_years, fill_value=0)

    total_movies = int(counts.sum())
    if total_movies == 0:
        raise SystemExit(f"No movies have release dates between {start_year} and {end_year}.")

    peak_year = int(counts.idxmax())
    peak_count = int(counts.max())
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    figure = Figure(figsize=(13, 6.5), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)

    axes.plot(
        counts.index,
        counts.values,
        color="#2563eb",
        linewidth=2.2,
        marker="o",
        markersize=4.5,
        markerfacecolor="white",
        markeredgewidth=1.5,
        markeredgecolor="#2563eb",
        label="Movies",
    )
    axes.fill_between(counts.index, counts.values, color="#2563eb", alpha=0.12)
    axes.axhline(0, color="#9ca3af", linewidth=0.8)

    axes.set_title("Movie Club Picks by Release Year", fontsize=18, fontweight="bold", pad=16)
    axes.set_xlabel("Release year")
    axes.set_ylabel("Number of movies")
    axes.grid(axis="y", color="#d1d5db", alpha=0.6)
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.xaxis.set_major_locator(MultipleLocator(5))
    axes.yaxis.set_major_locator(MaxNLocator(integer=True))
    axes.set_xlim(start_year - 1, end_year + 1)
    axes.set_ylim(0, max(peak_count + 2, 3))

    axes.annotate(
        f"Peak: {peak_year} — {peak_count} movies",
        xy=(peak_year, peak_count),
        xytext=(10, -24),
        textcoords="offset points",
        fontsize=9,
        color="#1f2937",
        arrowprops={"arrowstyle": "->", "color": "#6b7280", "linewidth": 1},
    )

    figure.text(
        0.5,
        -0.03,
        f"{total_movies} unique movies • release years {start_year}–{end_year} • "
        f"peak {peak_year} ({peak_count})",
        ha="center",
        fontsize=9,
        color="#6b7280",
    )
    figure.savefig(
        output,
        dpi=200,
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.2,
    )

    print(f"Wrote {output}")
    print(f"Unique movies: {total_movies}")
    print(f"Release years: {start_year}–{end_year}")
    print(f"Peak: {peak_year} ({peak_count} movies)")


if __name__ == "__main__":
    main()
