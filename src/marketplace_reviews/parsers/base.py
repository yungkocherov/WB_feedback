from __future__ import annotations

from abc import ABC, abstractmethod

from marketplace_reviews.models import Review


class BaseParser(ABC):
    """Interface every marketplace parser must implement."""

    @abstractmethod
    def parse_url(self, url: str) -> int:
        """Extract the product identifier from a marketplace URL."""

    @abstractmethod
    def fetch_reviews(self, product_id: int) -> list[Review]:
        """Download all reviews for a given product."""
