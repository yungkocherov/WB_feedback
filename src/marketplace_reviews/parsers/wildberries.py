from __future__ import annotations

import re
import time
import logging
from datetime import datetime, timezone

import requests

from marketplace_reviews.models import Review
from marketplace_reviews.parsers.base import BaseParser

logger = logging.getLogger(__name__)

_WB_URL_PATTERN = re.compile(r"wildberries\.ru/catalog/(\d+)")

_CARD_DETAIL_URL = "https://card.wb.ru/cards/v2/detail"
_FEEDBACKS_URL = "https://public-feedbacks.wildberries.ru/api/v1/feedbacks/site"

_PAGE_SIZE = 30
_REQUEST_DELAY = 0.35  # seconds between paginated requests


class WildberriesParser(BaseParser):

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.setdefault("User-Agent", "Mozilla/5.0")
        self._session.headers.setdefault("Referer", "https://www.wildberries.ru")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse_url(self, url: str) -> int:
        """Extract nmId from a Wildberries product URL."""
        m = _WB_URL_PATTERN.search(url)
        if not m:
            raise ValueError(f"Cannot extract nmId from URL: {url}")
        return int(m.group(1))

    def fetch_reviews(self, product_id: int) -> list[Review]:
        """Fetch all reviews for a product identified by nmId."""
        imt_id = self._resolve_imt_id(product_id)
        logger.info("nmId=%d → imtId=%d", product_id, imt_id)
        return self._fetch_all_feedbacks(imt_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_imt_id(self, nm_id: int) -> int:
        """Get imtId (root card id) required by the feedbacks endpoint."""
        resp = self._session.get(
            _CARD_DETAIL_URL,
            params={"appType": 1, "curr": "rub", "dest": -1257786, "nm": nm_id},
        )
        resp.raise_for_status()
        products = resp.json().get("data", {}).get("products", [])
        if not products:
            raise ValueError(f"Product not found for nmId={nm_id}")
        root = products[0].get("root")
        if root is None:
            raise ValueError(f"imtId (root) missing for nmId={nm_id}")
        return int(root)

    def _fetch_all_feedbacks(self, imt_id: int) -> list[Review]:
        """Paginate through the public feedbacks endpoint."""
        reviews: list[Review] = []
        skip = 0

        while True:
            payload = {
                "imtId": imt_id,
                "take": _PAGE_SIZE,
                "skip": skip,
                "order": "dateDesc",
            }
            resp = self._session.post(_FEEDBACKS_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

            feedbacks = data.get("feedbacks") or []
            if not feedbacks:
                break

            for fb in feedbacks:
                reviews.append(self._to_review(fb))

            logger.info("Fetched %d reviews (total so far: %d)", len(feedbacks), len(reviews))

            if len(feedbacks) < _PAGE_SIZE:
                break

            skip += _PAGE_SIZE
            time.sleep(_REQUEST_DELAY)

        return reviews

    @staticmethod
    def _to_review(fb: dict) -> Review:
        created = fb.get("createdDate", "")
        dt = datetime.fromisoformat(created) if created else datetime.now(timezone.utc)

        return Review(
            review_id=str(fb.get("id", "")),
            rating=int(fb.get("productValuation", 0)),
            created_at=dt,
            text=fb.get("text", ""),
            pros=fb.get("pros", ""),
            cons=fb.get("cons", ""),
        )
