from __future__ import annotations

import re
import logging
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from marketplace_reviews.models import Review
from marketplace_reviews.parsers.base import BaseParser

logger = logging.getLogger(__name__)

_WB_URL_PATTERN = re.compile(r"wildberries\.ru/catalog/(\d+)")
_FEEDBACKS_RE = re.compile(r"feedbacks")

_ANTI_BOT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
"""

_MAX_IDLE_SCROLLS = 20
_SCROLL_PAUSE_MS = 1000


class WildberriesParser(BaseParser):

    def parse_url(self, url: str) -> int:
        m = _WB_URL_PATTERN.search(url)
        if not m:
            raise ValueError(f"Cannot extract nmId from URL: {url}")
        return int(m.group(1))

    def fetch_reviews(self, product_id: int) -> list[Review]:
        url = f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx"
        return self._scrape_reviews(url, product_id)

    def _scrape_reviews(self, url: str, nm_id: int) -> list[Review]:
        seen_ids: set[str] = set()
        all_reviews: list[Review] = []

        def on_response(response):
            try:
                if not _FEEDBACKS_RE.search(response.url):
                    return
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return

                body = response.json()
                feedbacks = body.get("feedbacks") or []
                added = 0
                for fb in feedbacks:
                    rid = str(fb.get("id", ""))
                    if rid and rid not in seen_ids:
                        all_reviews.append(self._to_review(fb))
                        seen_ids.add(rid)
                        added += 1
                if added:
                    logger.info(
                        "Intercepted %d new reviews from %s (total: %d)",
                        added, response.url[:80], len(all_reviews),
                    )
            except Exception as e:
                logger.debug("Response handler error: %s", e)

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
            page.add_init_script(_ANTI_BOT_SCRIPT)
            page.on("response", on_response)

            # 1. Load product page — this triggers initial feedbacks load
            logger.info("Opening product page for nmId=%d", nm_id)
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(6000)
            logger.info("Product page loaded, got %d reviews from initial XHR", len(all_reviews))

            # 2. Click "See all reviews" if available
            self._click_all_reviews(page)
            page.wait_for_timeout(3000)

            # 3. Scroll to load more reviews
            idle = 0
            prev = len(all_reviews)
            while idle < _MAX_IDLE_SCROLLS:
                page.evaluate("window.scrollBy(0, 3000)")
                page.wait_for_timeout(_SCROLL_PAUSE_MS)

                cur = len(all_reviews)
                if cur > prev:
                    idle = 0
                    prev = cur
                else:
                    idle += 1

                # Periodically try "show more" button
                if idle % 3 == 1:
                    self._click_load_more(page)

            logger.info("Scraping done. Total reviews: %d", len(all_reviews))
            browser.close()

        return all_reviews

    @staticmethod
    def _click_all_reviews(page):
        for sel in [
            "a.comments__btn-all",
            "text=Смотреть все отзывы",
            "text=Все отзывы",
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click()
                    logger.info("Clicked: %s", sel)
                    return
            except Exception:
                continue

    @staticmethod
    def _click_load_more(page):
        for sel in [
            "button.comments__more-btn",
            "text=Показать ещё",
            "text=Показать еще",
        ]:
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
