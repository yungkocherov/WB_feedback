from __future__ import annotations

import re
import logging
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from marketplace_reviews.models import Review, ProductInfo
from marketplace_reviews.parsers.base import BaseParser

logger = logging.getLogger(__name__)

_WB_URL_PATTERN = re.compile(r"wildberries\.ru/catalog/(\d+)")
_FEEDBACKS_RE = re.compile(r"feedbacks")
_CARD_DETAIL_RE = re.compile(r"cards/v4/detail")

_ANTI_BOT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
"""

_MAX_IDLE_SCROLLS = 20
_SCROLL_PAUSE_MS = 1000

# WB image CDN basket mapping
_BASKET_RANGES = [
    (143, "01"), (287, "02"), (431, "03"), (719, "04"), (1007, "05"),
    (1061, "06"), (1115, "07"), (1169, "08"), (1313, "09"), (1601, "10"),
    (1655, "11"), (1919, "12"), (2045, "13"), (2189, "14"), (2405, "15"),
    (2621, "16"), (2837, "17"), (3053, "18"), (3269, "19"), (3485, "20"),
    (3701, "21"), (3917, "22"), (4133, "23"), (4349, "24"), (4565, "25"),
]


def _image_url(nm_id: int) -> str:
    vol = nm_id // 100000
    part = nm_id // 1000
    basket = "25"
    for max_vol, num in _BASKET_RANGES:
        if vol <= max_vol:
            basket = num
            break
    return f"https://basket-{basket}.wbbasket.ru/vol{vol}/part{part}/{nm_id}/images/c246x328/1.webp"


class WildberriesParser(BaseParser):

    def parse_url(self, url: str) -> int:
        m = _WB_URL_PATTERN.search(url)
        if not m:
            raise ValueError(f"Cannot extract nmId from URL: {url}")
        return int(m.group(1))

    def fetch_reviews(self, product_id: int) -> list[Review]:
        _, reviews = self.fetch_product(product_id)
        return reviews

    def fetch_product(self, product_id: int) -> tuple[ProductInfo | None, list[Review]]:
        """Fetch product info and reviews together in one browser session."""
        url = f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx"
        return self._scrape(url, product_id)

    def _scrape(self, url: str, nm_id: int) -> tuple[ProductInfo | None, list[Review]]:
        seen_ids: set[str] = set()
        all_reviews: list[Review] = []
        product_info: dict = {}

        def on_response(response):
            try:
                if response.status != 200:
                    return
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return

                # Intercept card detail → product info
                if _CARD_DETAIL_RE.search(response.url):
                    body = response.json()
                    prods = body.get("products") or body.get("data", {}).get("products") or []
                    for p in prods:
                        if p.get("id") == nm_id and not product_info:
                            product_info.update(p)
                            logger.info("Got product info: %s — %s", p.get("brand"), p.get("name"))

                # Intercept feedbacks
                if _FEEDBACKS_RE.search(response.url):
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
                            "Intercepted %d new reviews (total: %d)",
                            added, len(all_reviews),
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

            logger.info("Opening product page for nmId=%d", nm_id)
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(6000)
            logger.info("Page loaded, %d reviews so far", len(all_reviews))

            self._click_all_reviews(page)
            page.wait_for_timeout(3000)

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

                if idle % 3 == 1:
                    self._click_load_more(page)

            logger.info("Done. Total reviews: %d", len(all_reviews))
            browser.close()

        # Build ProductInfo
        info = None
        if product_info:
            info = ProductInfo(
                nm_id=nm_id,
                name=product_info.get("name", ""),
                brand=product_info.get("brand", ""),
                image_url=_image_url(nm_id),
                rating=float(product_info.get("reviewRating", 0)),
                total_feedbacks=int(product_info.get("feedbacks", 0)),
            )

        return info, all_reviews

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
