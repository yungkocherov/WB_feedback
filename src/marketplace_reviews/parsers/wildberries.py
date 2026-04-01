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

_CARD_DETAIL_URL = "https://card.wb.ru/cards/v4/detail"
_FEEDBACKS_PAGINATED_URL = "https://public-feedbacks.wildberries.ru/api/v1/feedbacks/site"
_FEEDBACKS_FALLBACK_URL = "https://feedbacks1.wb.ru/feedbacks/v1/{imt_id}"

_TAKE = 30
_MAX_SKIP = 990  # public endpoint returns 400 when skip > ~1000
_REQUEST_DELAY = 0.35


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

        try:
            reviews = self._fetch_paginated(imt_id)
            logger.info("Paginated endpoint: got %d reviews", len(reviews))
        except Exception as e:
            logger.warning("Paginated endpoint failed (%s), falling back", e)
            reviews = self._fetch_fallback(imt_id)

        return reviews

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
        body = resp.json()
        products = body.get("data", {}).get("products") or body.get("products") or []
        if not products:
            raise ValueError(f"Product not found for nmId={nm_id}")
        root = products[0].get("root")
        if root is None:
            raise ValueError(f"imtId (root) missing for nmId={nm_id}")
        return int(root)

    def _fetch_paginated(self, imt_id: int) -> list[Review]:
        """Fetch reviews via POST endpoint with skip/take pagination.

        Fetches from both directions (newest-first and oldest-first) to
        maximise coverage — up to ~2000 unique reviews.
        """
        seen_ids: set[str] = set()
        all_reviews: list[Review] = []

        for order in ("dateDesc", "dateAsc"):
            skip = 0
            while skip <= _MAX_SKIP:
                resp = self._session.post(
                    _FEEDBACKS_PAGINATED_URL,
                    json={"imtId": imt_id, "take": _TAKE, "skip": skip, "order": order},
                    headers={"x-service-name": "site"},
                )
                resp.raise_for_status()
                feedbacks = resp.json().get("feedbacks") or []

                if not feedbacks:
                    break

                for fb in feedbacks:
                    rid = str(fb.get("id", ""))
                    if rid not in seen_ids:
                        all_reviews.append(self._to_review(fb))
                        seen_ids.add(rid)

                logger.info(
                    "order=%s skip=%d batch=%d total=%d",
                    order, skip, len(feedbacks), len(all_reviews),
                )

                if len(feedbacks) < _TAKE:
                    break

                skip += _TAKE
                time.sleep(_REQUEST_DELAY)

        return all_reviews

    def _fetch_fallback(self, imt_id: int) -> list[Review]:
        """Fallback: single GET to feedbacks1.wb.ru (max ~50 reviews)."""
        url = _FEEDBACKS_FALLBACK_URL.format(imt_id=imt_id)
        resp = self._session.get(url)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "json" not in content_type:
            raise ValueError(
                f"WB feedbacks returned non-JSON (Content-Type: {content_type}). "
                f"The endpoint may be blocked from your network."
            )

        feedbacks = resp.json().get("feedbacks") or []
        logger.info("Fallback: fetched %d reviews for imtId=%d", len(feedbacks), imt_id)
        return [self._to_review(fb) for fb in feedbacks]

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
