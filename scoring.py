"""Правила оценки слова: 10 факторов, 100-балльная шкала, триггеры «Избегать» и категории.

Исходная система продавца (максимум 40 баллов) умножена на 2,5. Сумма, полнота оценки и категория
всегда считаются здесь в коде по баллам факторов.
"""

FACTORS = {
    "seasonality": ("Сезонность", (7.5, 5, 0)),
    "trend": ("Тренд", (10, 7.5, 2.5, 0)),
    "oversize": ("Негабарит", (5, 0)),
    "demand": ("Спрос", (15, 12.5, 10, 5, 0)),
    "competition": ("Конкуренция", (10, 7.5, 0)),
    "complexity": ("Сложность", (10, 5, 0)),
    "growth": ("Синяя ракета", (7.5, 2.5, 0)),
    "ratio": ("Спрос / продавцы", (12.5, 10, 7.5)),
    "price": ("Средняя цена", (12.5, 7.5)),
    "reviews": ("Отзывы", (10, 5, 2.5, 0)),
}
MAX_SCORE = sum(max(points) for _, points in FACTORS.values())  # 100

TRIGGERS = {
    "reviews_over_5000": "отзывов больше 5000",
    "low_demand": "спрос ниже 2000",
    "growth_60_100": "синяя ракета 60–100%",
    "trend_down": "тренд вниз",
}

RECOMMEND_MIN = 62.5  # было ≥ 25 из 40
AVOID_MAX = 50  # было ≤ 20 из 40


def summarize(product: dict) -> dict:
    """Итоговый балл, полнота и категория — по правилам, из баллов факторов."""
    total = 0.0
    available = 0.0
    missing, invalid = [], []
    for key, (label, allowed) in FACTORS.items():
        points = product["factors"][key]["points"]
        if points is None:
            missing.append(label)
        elif points not in allowed:
            invalid.append(f"{label} ({points:g})")
        else:
            total += points
            available += max(allowed)

    triggers = [TRIGGERS[t] for t in dict.fromkeys(product["triggers"])]
    if triggers or total <= AVOID_MAX:
        category = "Избегать"
    elif total >= RECOMMEND_MIN:
        category = "Рекомендуем"
    else:
        category = "Рассмотреть"

    notes = []
    if triggers:
        notes.append("триггер: " + ", ".join(triggers))
    if missing or invalid:
        notes.append(f"неполная оценка ({available:g} из {MAX_SCORE:g} возможных), нет данных: " + ", ".join(missing + invalid))
    notes += product["boundary_flags"]
    return {
        "total": total,
        "available": available,
        "complete": not (missing or invalid),
        "category": category,
        "triggers": triggers,
        "missing": missing + invalid,
        "reason": "; ".join([product["reason"], *notes]),
    }
