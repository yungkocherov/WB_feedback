"""Flask web service for marketplace reviews analysis."""

from __future__ import annotations

import base64
import io
import logging

from flask import Flask, render_template, request, jsonify

from marketplace_reviews.parsers.wildberries import WildberriesParser
from marketplace_reviews.aggregation import aggregate_weekly
from marketplace_reviews.export import to_dataframe

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

app = Flask(__name__)
wb = WildberriesParser()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    url = request.form.get("url", "").strip()
    if not url:
        return jsonify(error="Вставьте ссылку на товар"), 400

    try:
        nm_id = wb.parse_url(url)
        reviews = wb.fetch_reviews(nm_id)

        if not reviews:
            return jsonify(error="Отзывов не найдено"), 404

        weekly = aggregate_weekly(reviews)
        df = to_dataframe(weekly)

        chart_b64 = _render_chart(df, nm_id)

        rows = df.to_dict(orient="records")
        for r in rows:
            r["week_start"] = r["week_start"].strftime("%Y-%m-%d")

        return jsonify(
            nm_id=nm_id,
            total_reviews=len(reviews),
            weeks=len(weekly),
            rows=rows,
            chart=chart_b64,
        )
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("Unhandled error in /analyze")
        return jsonify(error=f"Ошибка: {e}"), 500


def _render_chart(df, nm_id: int) -> str:
    fig, ax1 = plt.subplots(figsize=(10, 4))

    color_rating = "#2563eb"
    color_count = "#9ca3af"

    ax1.bar(df["week_start"], df["review_count"], width=5, alpha=0.3, color=color_count)
    ax1.set_ylabel("Кол-во отзывов", color=color_count)
    ax1.tick_params(axis="y", labelcolor=color_count)

    ax2 = ax1.twinx()
    ax2.plot(df["week_start"], df["avg_rating"], marker="o", markersize=3,
             color=color_rating, linewidth=1.5)
    ax2.set_ylabel("Средняя оценка", color=color_rating)
    ax2.set_ylim(0.5, 5.5)
    ax2.tick_params(axis="y", labelcolor=color_rating)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate(rotation=45)

    plt.title(f"Еженедельный рейтинг — WB {nm_id}")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def main():
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    main()
