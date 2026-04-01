from __future__ import annotations

from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from marketplace_reviews.models import WeeklyRating


def to_dataframe(weekly: list[WeeklyRating]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "week_start": [w.week_start for w in weekly],
            "avg_rating": [w.avg_rating for w in weekly],
            "review_count": [w.review_count for w in weekly],
        }
    )


def save_csv(weekly: list[WeeklyRating], path: Path) -> Path:
    df = to_dataframe(weekly)
    df.to_csv(path, index=False)
    return path


def plot(weekly: list[WeeklyRating], title: str = "", save_path: Path | None = None) -> None:
    df = to_dataframe(weekly)
    if df.empty:
        print("No data to plot.")
        return

    fig, ax1 = plt.subplots(figsize=(12, 5))

    color_rating = "#2563eb"
    color_count = "#9ca3af"

    ax1.bar(df["week_start"], df["review_count"], width=5, alpha=0.3, color=color_count, label="Reviews")
    ax1.set_ylabel("Review count", color=color_count)
    ax1.tick_params(axis="y", labelcolor=color_count)

    ax2 = ax1.twinx()
    ax2.plot(df["week_start"], df["avg_rating"], marker="o", markersize=3, color=color_rating, linewidth=1.5, label="Avg rating")
    ax2.set_ylabel("Avg rating", color=color_rating)
    ax2.set_ylim(0.5, 5.5)
    ax2.tick_params(axis="y", labelcolor=color_rating)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=45)

    plt.title(title or "Weekly average rating")
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        print(f"Plot saved to {save_path}")
    else:
        plt.show()

    plt.close(fig)
