from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import django
import pandas as pd
from matplotlib import colormaps
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "charts" / "member-favorite-genres.png"


@dataclass(frozen=True)
class Favorite:
    member: str
    genre: str
    count: int
    total_picks: int

    @property
    def share(self) -> float:
        return self.count / self.total_picks if self.total_picks else 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a chart of each member's favorite movie genre."
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GENRE",
        help=(
            "Genre to ignore when choosing favorites. Repeat the option or "
            "separate multiple genres with commas."
        ),
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

    from apps.club.models import Member, Week

    excluded_labels = sorted(
        {genre.strip() for value in args.exclude for genre in value.split(",") if genre.strip()}
    )
    excluded_genres = {genre.casefold() for genre in excluded_labels}
    members = list(Member.objects.order_by("display_name", "username"))
    favorites: list[Favorite] = []

    for member in members:
        matched_weeks = Week.objects.filter(selected_by=member, movie__isnull=False)
        genre_names = pd.Series(
            matched_weeks.values_list("movie__genres__name", flat=True),
            dtype="string",
        ).dropna()
        if excluded_genres:
            genre_names = genre_names[~genre_names.str.casefold().isin(excluded_genres)]
        if genre_names.empty:
            continue

        genre_counts = genre_names.value_counts()
        genre, count = sorted(
            genre_counts.items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )[0]
        favorites.append(
            Favorite(
                member=str(member),
                genre=str(genre),
                count=int(count),
                total_picks=matched_weeks.count(),
            )
        )

    if not favorites:
        raise SystemExit("No matched picks with genres found. Import and enrich some weeks first.")

    favorites.sort(key=lambda favorite: (-favorite.count, favorite.member))

    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)

    figure = Figure(figsize=(12, 6.5), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)

    genre_order = sorted({favorite.genre for favorite in favorites})
    color_map = colormaps["tab10"]
    genre_colors = {
        genre: color_map(index / max(len(genre_order), 1))
        for index, genre in enumerate(genre_order)
    }

    members_labels = [favorite.member for favorite in favorites]
    counts = [favorite.count for favorite in favorites]
    colors = [genre_colors[favorite.genre] for favorite in favorites]

    axes.barh(
        members_labels,
        counts,
        color=colors,
        height=0.62,
        edgecolor="white",
        linewidth=1.2,
    )

    max_count = max(counts)
    axes.set_xlim(0, max_count + 20)
    axes.xaxis.set_major_locator(MaxNLocator(integer=True))
    axes.set_xlabel("Matched picks containing their favorite genre")
    axes.set_ylabel("Movie chooser")
    axes.set_title("Favorite Genre by Movie Chooser", fontsize=18, fontweight="bold", pad=16)
    axes.grid(axis="x", color="#d1d5db", alpha=0.6)
    axes.set_axisbelow(True)
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.invert_yaxis()

    for index, favorite in enumerate(favorites):
        axes.text(
            favorite.count + 0.6,
            index,
            f"{favorite.genre}  ·  {favorite.count}/{favorite.total_picks} picks "
            f"({favorite.share:.0%})",
            va="center",
            fontsize=9,
            color="#1f2937",
        )

    favorite_genre_counts = pd.Series(
        [favorite.genre for favorite in favorites], dtype="string"
    ).value_counts()
    top_favorite_count = int(favorite_genre_counts.iloc[0])
    top_favorites = sorted(
        str(genre)
        for genre, count in favorite_genre_counts.items()
        if int(count) == top_favorite_count
    )
    if len(top_favorites) == 1:
        top_note = f"most common favorite: {top_favorites[0]} ({top_favorite_count} members)"
    else:
        top_note = (
            f"most common favorites: {', '.join(top_favorites)} ({top_favorite_count} members each)"
        )
    exclusion_note = f"Excluding {', '.join(excluded_labels)} • " if excluded_labels else ""
    footer = (
        f"{exclusion_note}{len(favorites)} of {len(members)} members with matched picks • "
        f"{top_note} • each pick counts once per genre"
    )
    figure.text(0.5, -0.03, footer, ha="center", fontsize=9, color="#6b7280")
    figure.savefig(
        output,
        dpi=200,
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.2,
    )

    print(f"Wrote {output}")
    if excluded_labels:
        print(f"Excluded genres: {', '.join(excluded_labels)}")
    print(f"Members with matched picks: {len(favorites)} of {len(members)}")
    for favorite in favorites:
        print(
            f"  {favorite.member}: {favorite.genre} "
            f"({favorite.count}/{favorite.total_picks}, {favorite.share:.0%})"
        )


if __name__ == "__main__":
    main()
