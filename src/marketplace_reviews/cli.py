"""CLI entry point.

Usage:
    mp-reviews <url> [<url> ...] [--csv output.csv] [--plot output.png]

Examples:
    mp-reviews https://www.wildberries.ru/catalog/12345678/detail.aspx
    mp-reviews https://www.wildberries.ru/catalog/12345678/detail.aspx --csv ratings.csv --plot ratings.png
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from marketplace_reviews.parsers.wildberries import WildberriesParser
from marketplace_reviews.aggregation import aggregate_weekly
from marketplace_reviews.export import save_csv, plot, to_dataframe


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mp-reviews",
        description="Fetch product reviews from Wildberries and build a weekly rating time series.",
    )
    p.add_argument("urls", nargs="+", help="Wildberries product URL(s)")
    p.add_argument("--csv", dest="csv_path", default=None, help="Save time series to CSV")
    p.add_argument("--plot", dest="plot_path", default=None, help="Save chart to PNG file")
    p.add_argument("--show", action="store_true", help="Show chart in a window")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    wb = WildberriesParser()

    for url in args.urls:
        print(f"\n{'='*60}")
        print(f"URL: {url}")
        print(f"{'='*60}")

        nm_id = wb.parse_url(url)
        print(f"Product nmId: {nm_id}")

        reviews = wb.fetch_reviews(nm_id)
        print(f"Total reviews fetched: {len(reviews)}")

        if not reviews:
            print("No reviews found, skipping.")
            continue

        weekly = aggregate_weekly(reviews)
        df = to_dataframe(weekly)

        print(f"\nWeekly ratings ({len(weekly)} weeks):")
        print(df.to_string(index=False))

        if args.csv_path:
            path = save_csv(weekly, Path(args.csv_path))
            print(f"\nCSV saved: {path}")

        save_path = Path(args.plot_path) if args.plot_path else None
        if save_path or args.show:
            plot(weekly, title=f"WB nmId={nm_id}", save_path=save_path)


if __name__ == "__main__":
    main()
