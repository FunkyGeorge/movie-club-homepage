from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import django
import pandas as pd
from matplotlib import colormaps
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "charts" / "genre-pie.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a pie chart of movie club genres.")
    parser.add_argument(
        "--top",
        type=int,
        default=8,
        help="Number of genres to show before grouping the rest into Other (default: 8).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output PNG path (default: {DEFAULT_OUTPUT.relative_to(PROJECT_ROOT)}).",
    )
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be at least 1")
    return args


def main() -> None:
    args = parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from apps.club.models import Week

    matched_weeks = Week.objects.exclude(movie__isnull=True).count()
    genre_names = list(
        Week.objects.exclude(movie__isnull=True).values_list("movie__genres__name", flat=True)
    )
    counts = pd.Series(genre_names, dtype="string").dropna().value_counts()

    if counts.empty:
        raise SystemExit("No matched weeks with genres found. Import and enrich some weeks first.")

    top = counts.head(args.top)
    remainder = int(counts.iloc[args.top :].sum())
    if remainder:
        top = pd.concat([top, pd.Series({"Other": remainder})])

    labels = [str(label) for label in top.index]
    values = [int(value) for value in top.values]
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    figure = Figure(figsize=(11, 7), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)

    color_map = colormaps["tab20"]
    colors = [color_map(i / max(len(values) - 1, 1)) for i in range(len(values))]

    wedges, _, _ = axes.pie(
        values,
        colors=colors,
        startangle=90,
        counterclock=False,
        autopct=lambda pct: f"{pct:.1f}%" if pct >= 3 else "",
        pctdistance=0.72,
        textprops={"fontsize": 9, "color": "#1f2937", "fontweight": "bold"},
        wedgeprops={"linewidth": 1.5, "edgecolor": "white"},
    )
    axes.set_aspect("equal")
    axes.set_title("Movie Club Picks by Genre", fontsize=18, fontweight="bold", pad=18)

    legend_labels = [f"{label} — {value}" for label, value in zip(labels, values, strict=True)]
    axes.legend(
        wedges,
        legend_labels,
        title="Genre (picks)",
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        frameon=False,
        fontsize=10,
        title_fontsize=11,
    )
    figure.text(
        0.5,
        0.01,
        f"{matched_weeks} matched weeks • films count once per genre • top {args.top} + Other",
        ha="center",
        fontsize=9,
        color="#6b7280",
    )
    figure.savefig(output, dpi=200, facecolor="white", bbox_inches="tight")

    print(f"Wrote {output}")
    print(f"Matched weeks: {matched_weeks}")
    print(f"Genre assignments: {int(counts.sum())}")
    for label, value in top.items():
        print(f"  {label}: {value}")


if __name__ == "__main__":
    main()
