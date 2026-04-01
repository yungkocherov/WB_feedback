from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Review:
    review_id: str
    rating: int  # 1‑5
    created_at: datetime
    text: str = ""
    pros: str = ""
    cons: str = ""


@dataclass(frozen=True, slots=True)
class WeeklyRating:
    week_start: datetime
    avg_rating: float
    review_count: int
