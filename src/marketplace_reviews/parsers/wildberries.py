from __future__ import annotations

import json
import re
import logging
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

from marketplace_reviews.models import Review
from marketplace_reviews.parsers.base import BaseParser

logger = logging.getLogger(__name__)

_WB_URL_PATTERN = re.compile(r"wildberries\.ru/catalog/(\d+)")
_FEEDBACKS_URL_PATTERN = re.compile(r"feedbacks")

# How many consecutive empty scrolls before we stop
_MAX_IDLE_SCROLLS = 15
_SCROLL_PAUSE_MS = 800


class WildberriesParser(BaseParser):

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse_url(self, url: str) -> int:
        m = _WB_URL_PATTERN.search(url)
        if not m:
            raise ValueError(f"Cannot extract nmId from URL: {url}")
        return int(m.group(1))

    def fetch_reviews(self, product_id: int) -> list[Review]:
        url = f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx"
        return self._scrape_reviews(url)

    # ------------------------------------------------------------------
    # Playwright scraper
    # ------------------------------------------------------------------

    def _scrape_reviews(self, url: str) -> list[Review]:
        seen_ids: set[str] = set()
        all_reviews: list[Review] = []

        def _on_response(response):
            """Intercept XHR responses containing feedbacks."""
            try:
                if not _FEEDBACKS_URL_PATTERN.search(response.url):
                    return
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return

                body = response.json()
                feedbacks = body.get("feedbacks") or []
                for fb in feedbacks:
                    rid = str(fb.get("id", ""))
                    if rid and rid not in seen_ids:
                        all_reviews.append(self._to_review(fb))
                        seen_ids.add(rid)
            except Exception:
                pass

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="ru-RU",
            )
            page = context.new_page()
            page.on("response", _on_response)

            logger.info("Opening %s", url)
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2000)

            # Click the reviews tab to open feedbacks section
            self._open_reviews_tab(page)
            page.wait_for_timeout(2000)
            logger.info("Reviews tab opened, intercepted %d so far", len(all_reviews))

            # Click "Show all reviews" if such button exists
            self._click_show_all(page)
            page.wait_for_timeout(2000)

            # Scroll to load more reviews
            idle_count = 0
            prev_count = len(all_reviews)

            while idle_count < _MAX_IDLE_SCROLLS:
                page.evaluate("window.scrollBy(0, 3000)")
                page.wait_for_timeout(_SCROLL_PAUSE_MS)

                current = len(all_reviews)
                if current > prev_count:
                    idle_count = 0
                    prev_count = current
                    logger.info("Scrolling... %d reviews collected", current)
                else:
                    idle_count += 1

                # Try clicking "load more" button if present
                self._click_load_more(page)

            logger.info("Done scrolling. Total reviews: %d", len(all_reviews))
            browser.close()

        return all_reviews

    @staticmethod
    def _open_reviews_tab(page):
        """Click on the reviews/feedbacks tab."""
        selectors = [
            "button.product-page__tab[data-tab='feedback']",
            "[data-tab='feedback']",
            "a[href*='feedbacks']",
            "text=Отзыв",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1000):
                    el.click()
                    return
            except Exception:
                continue

    @staticmethod
    def _click_show_all(page):
        """Click 'Show all reviews' link if present."""
        selectors = [
            "text=Все отзывы",
            "text=Смотреть все",
            "text=Показать все",
            "a.comments__btn-all",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1000):
                    el.click()
                    return
            except Exception:
                continue

    @staticmethod
    def _click_load_more(page):
        """Click 'Load more' if present."""
        selectors = [
            "button.comments__more-btn",
            "text=Показать ещё",
            "text=Показать еще",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=300):
                    el.click()
                    return
            except Exception:
                continue

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
