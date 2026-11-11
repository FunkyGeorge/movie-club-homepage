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
from matplotlib.patches import Rectangle

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "charts" / "genre-share-by-member.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a heatmap of each member's genre selection share, "
            "highlighting the top selector for every genre."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output PNG path (default: {DEFAULT_OUTPUT.relative_to(PROJECT_ROOT)}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    from django.db.models import Count

    from apps.club.models import Member, Week
    from apps.movies.models import Genre

    members = list(
        Member.objects.filter(weeks__movie__isnull=False)
        .distinct()
        .order_by("display_name", "username")
    )
    if not members:
        raise SystemExit("No members with matched picks found. Import and enrich some weeks first.")

    total_members = Member.objects.count()
    genre_names = list(Genre.objects.order_by("name").values_list("name", flat=True))

    records = list(
        Week.objects.filter(movie__isnull=False).values_list(
            "selected_by_id",
            "movie__genres__name",
        )
    )
    frame = pd.DataFrame(records, columns=["member_id", "genre"]).dropna(subset=["genre"])
    if frame.empty:
        raise SystemExit("No matched picks with genres found. Import and enrich some weeks first.")

    member_labels = {member.id: str(member) for member in members}

    totals = {
        row["selected_by_id"]: row["total"]
        for row in Week.objects.filter(movie__isnull=False)
        .values("selected_by_id")
        .annotate(total=Count("id"))
    }

    counts = (
        frame.groupby(["member_id", "genre"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=[member.id for member in members], fill_value=0)
        .reindex(columns=genre_names, fill_value=0)
    )
    percentages = counts.div(pd.Series(totals), axis=0).fillna(0) * 100

    genre_totals = counts.sum(axis=0)
    genres = sorted(
        genre_names,
        key=lambda genre: (-int(genre_totals[genre]), genre),
    )
    percentages = percentages[genres].T.reindex(columns=[member.id for member in members])

    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    figure = Figure(figsize=(14, 9.5), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)

    values = percentages.to_numpy()
    image = axes.imshow(
        values,
        aspect="auto",
        cmap=colormaps["YlGnBu"],
        vmin=0,
        vmax=100,
    )

    axes.set_title("Genre Selection Share by Movie Chooser", fontsize=18, fontweight="bold", pad=16)
    axes.set_xticks(range(len(members)), [member_labels[member.id] for member in members])
    axes.set_yticks(range(len(genres)), genres)
    axes.tick_params(axis="x", length=0, pad=10)
    axes.tick_params(axis="y", length=0, pad=8)

    for row_index, genre in enumerate(genres):
        row = percentages.loc[genre]
        row_max = float(row.max())
        for column_index, member in enumerate(members):
            value = float(row[member.id])
            is_top = row_max > 0 and value >= row_max - 1e-9
            label = f"★ {value:.0f}%" if is_top else f"{value:.0f}%"
            text_color = "white" if value >= 50 else "#1f2937"
            axes.text(
                column_index,
                row_index,
                label,
                ha="center",
                va="center",
                fontsize=8.5,
                fontweight="bold" if is_top else "normal",
                color=text_color,
            )
            if is_top:
                axes.add_patch(
                    Rectangle(
                        (column_index - 0.5, row_index - 0.5),
                        1,
                        1,
                        fill=False,
                        edgecolor="#f59e0b",
                        linewidth=2.4,
                    )
                )

    axes.set_xticks([index - 0.5 for index in range(1, len(members))], minor=True)
    axes.set_yticks([index - 0.5 for index in range(1, len(genres))], minor=True)
    axes.grid(which="minor", color="white", linewidth=1.4)
    axes.tick_params(which="minor", bottom=False, left=False)
    for spine in axes.spines.values():
        spine.set_visible(False)

    colorbar = figure.colorbar(image, ax=axes, shrink=0.78, pad=0.02)
    colorbar.set_label("Percentage of chooser's matched picks", fontsize=10)
    colorbar.set_ticks([0, 25, 50, 75, 100])
    colorbar.ax.tick_params(labelsize=9)

    figure.text(
        0.5,
        -0.03,
        "Each cell = share of that chooser's matched picks containing the genre • "
        "★ = highest share for the genre • picks can have multiple genres • "
        f"{len(members)} of {total_members} members with matched picks",
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
    print(f"Members with matched picks: {len(members)} of {total_members}")
    print(f"Genres: {len(genres)}")
    for genre in genres:
        row = percentages.loc[genre]
        row_max = float(row.max())
        if row_max <= 0:
            print(f"  {genre}: no picks")
            continue
        leaders = [
            member_labels[member.id]
            for member in members
            if float(row[member.id]) >= row_max - 1e-9
        ]
        print(f"  {genre}: {', '.join(leaders)} ({row_max:.0f}%)")


if __name__ == "__main__":
    main()
