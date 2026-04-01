from __future__ import annotations

import pandas as pd

from marketplace_reviews.models import Review, WeeklyRating


def aggregate_weekly(reviews: list[Review]) -> list[WeeklyRating]:
    """Group reviews by ISO week and compute average rating per week."""
    if not reviews:
        return []

    df = pd.DataFrame(
        {"rating": [r.rating for r in reviews], "created_at": [r.created_at for r in reviews]}
    )
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    df["week_start"] = df["created_at"].dt.to_period("W").apply(lambda p: p.start_time)

    grouped = (
        df.groupby("week_start")["rating"]
        .agg(["mean", "count"])
        .reset_index()
        .sort_values("week_start")
    )

    return [
        WeeklyRating(
            week_start=row.week_start.to_pydatetime(),
            avg_rating=round(row["mean"], 2),
            review_count=int(row["count"]),
        )
        for row in grouped.itertuples()
    ]
