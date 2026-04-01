# Marketplace Reviews

Сбор отзывов с маркетплейсов и построение временных рядов оценок.

## Поддерживаемые маркетплейсы

- **Wildberries** — через публичный API (без авторизации)

## Установка

```bash
pip install -e .
```

## Использование

```bash
# Базовый запуск — вывод таблицы в консоль
mp-reviews https://www.wildberries.ru/catalog/12345678/detail.aspx

# Сохранить в CSV
mp-reviews https://www.wildberries.ru/catalog/12345678/detail.aspx --csv ratings.csv

# Сохранить график
mp-reviews https://www.wildberries.ru/catalog/12345678/detail.aspx --plot ratings.png

# Несколько товаров
mp-reviews URL1 URL2 URL3 --csv ratings.csv

# Подробный вывод
mp-reviews URL -v
```

## Выходные данные

Временной ряд формата:

| week_start | avg_rating | review_count |
|------------|-----------|--------------|
| 2024-01-01 | 4.52      | 23           |
| 2024-01-08 | 4.31      | 17           |

## Архитектура

```
src/marketplace_reviews/
├── cli.py              # CLI точка входа
├── models.py           # Dataclass-модели (Review, WeeklyRating)
├── aggregation.py      # Агрегация по неделям
├── export.py           # CSV экспорт + matplotlib визуализация
└── parsers/
    ├── base.py         # Абстрактный базовый парсер
    └── wildberries.py  # Реализация для WB
```

Для добавления нового маркетплейса достаточно создать новый парсер в `parsers/`, реализующий интерфейс `BaseParser`.
