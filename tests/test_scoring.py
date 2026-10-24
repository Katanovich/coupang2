import pandas as pd
import pytest

from scoring import MAX_SCORE, summarize
from table_io import read_table, to_number
from table_score import brand_reason, score_row, table_result, title_brand


def test_max_score_is_100():
    assert MAX_SCORE == 100


def product(points: dict, triggers=()):
    from scoring import FACTORS

    return {
        "factors": {k: {"points": points.get(k)} for k in FACTORS},
        "triggers": list(triggers),
        "boundary_flags": [],
        "reason": "r",
    }


@pytest.mark.parametrize(
    "points, triggers, category",
    [
        ({"demand": 15, "ratio": 12.5, "trend": 10, "seasonality": 7.5, "competition": 10, "price": 12.5, "reviews": 10}, (), "Рекомендуем"),
        ({"demand": 15, "ratio": 12.5, "trend": 10, "seasonality": 7.5, "competition": 10, "price": 7.5}, (), "Рекомендуем"),  # ровно 62.5
        ({"demand": 15, "ratio": 12.5, "trend": 10, "seasonality": 7.5, "competition": 7.5}, (), "Рассмотреть"),  # 52.5
        ({"demand": 15, "ratio": 12.5, "trend": 10, "seasonality": 7.5, "competition": 5 + 0}, (), "Избегать"),  # 5 — недопустимый балл
        ({"demand": 15, "ratio": 12.5, "trend": 10, "seasonality": 7.5, "price": 7.5}, (), "Рассмотреть"),
        ({"demand": 15, "ratio": 12.5, "trend": 10, "seasonality": 5, "price": 7.5}, (), "Избегать"),  # ровно 50
        ({"demand": 15, "ratio": 12.5, "trend": 10, "seasonality": 7.5, "competition": 10, "price": 12.5, "reviews": 10}, ("trend_down",), "Избегать"),
    ],
)
def test_summarize_category(points, triggers, category):
    assert summarize(product(points, triggers))["category"] == category


def test_summarize_reports_missing_and_triggers():
    sm = summarize(product({"demand": 0}, ["low_demand", "low_demand"]))
    assert not sm["complete"]
    assert sm["triggers"] == ["спрос ниже 2000"]
    assert "Негабарит" in sm["missing"] and "Сложность" in sm["missing"]
    assert sm["reason"].startswith("r; триггер: спрос ниже 2000; неполная оценка (15 из 100")


@pytest.mark.parametrize(
    "search, points", [(30000, 15), (29999, 12.5), (10000, 12.5), (4000, 10), (2000, 5), (1999, 0)]
)
def test_demand_thresholds(search, points):
    assert score_row({"search": search})["factors"]["demand"]["points"] == points


@pytest.mark.parametrize("g3, points", [(0.06, 10), (0.05, 7.5), (-0.05, 7.5), (-0.06, 0)])
def test_trend_thresholds(g3, points):
    r = score_row({"growth3": g3})
    assert r["factors"]["trend"]["points"] == points
    assert ("trend_down" in r["triggers"]) == (points == 0)


@pytest.mark.parametrize("reviews, points", [(499, 10), (500, 5), (2499, 5), (2500, 2.5), (5000, 2.5), (5001, 0)])
def test_review_thresholds(reviews, points):
    assert score_row({"reviews": reviews})["factors"]["reviews"]["points"] == points


@pytest.mark.parametrize("rocket, points", [(29, 7.5), (30, 2.5), (59, 2.5), (60, 0)])
def test_rocket_thresholds(rocket, points):
    assert score_row({"rocket": rocket})["factors"]["growth"]["points"] == points


@pytest.mark.parametrize(
    "word, flag, expected",
    [
        ("요가매트", "X", None),
        ("젤리슈즈", "O", "бренд по таблице"),
        ("나이키 양말", None, "бренд: 나이키"),
        ("Nike socks", None, "бренд: nike"),
        ("iw5727", None, "похоже на код модели бренда"),
        ("sm-s928", None, "похоже на код модели бренда"),
        ("katana bag", None, "похоже на бренд: katana"),
        ("alice", None, "похоже на имя или бренд: alice"),
        ("모니카원피스", None, "похоже на имя или бренд: 모니카"),
        # Обычные слова, в которых есть кусок бренда, брендами не считаются
        ("파인애플", None, None),
        ("브라운 가방", None, None),
        ("알로에젤", None, None),
        ("보스턴백", None, None),
        ("bluetooth speaker", None, None),
        ("ph meter", None, None),
        ("yoga mats", None, None),
    ],
)
def test_brand_reason(word, flag, expected):
    assert brand_reason(word, flag) == expected


def test_title_brand_keeps_spaces():
    assert title_brand("PH TDS EC 측정기") is None
    assert title_brand("나이키 요가매트") == "бренд: 나이키"


def test_table_result(discovery):
    df = table_result(discovery, "키워드")["results"].set_index("Название продукта")
    assert df.index.is_unique and len(df) == 8
    assert df.loc["요가매트", "Итоговый балл"] == 85  # «35,000» прочитано как число
    assert df.loc["요가매트", "Рекомендация"] == "Рекомендуем"
    assert df.loc["캠핑의자", "Итоговый балл"] == 57.5
    assert df.loc["캠핑의자", "Рекомендация"] == "Рассмотреть"
    assert df.loc["캠핑의자", "Синяя ракета"] == 2.5  # доля 0.4 → 40%
    assert df.loc["캠핑의자", "Сезон"] == "Сезонный"
    assert df.loc["등산스틱", "Рекомендация"] == "Избегать"
    assert df["_brand"].notna().tolist() == [False, False, False, True, True, True, False, False]


def test_table_result_needs_search_column(discovery):
    assert table_result(discovery.drop(columns=["최근\n1개월\n검색량"]), "키워드") is None


def test_read_table_encodings(discovery):
    for enc in ("utf-8-sig", "cp949"):
        assert read_table("x.csv", discovery.to_csv(index=False).encode(enc)).equals(read_table("x.csv", discovery.to_csv(index=False).encode("utf-8")))


def test_read_table_excel(tmp_path, discovery):
    path = tmp_path / "x.xlsx"
    discovery.to_excel(path, index=False)
    assert read_table(path.name, path.read_bytes())["키워드"].tolist() == discovery["키워드"].tolist()


def test_to_number():
    assert to_number(pd.Series(["12,345", "35%", " 7 ", "", "abc"])).tolist()[:3] == [12345, 35, 7]
    assert to_number(pd.Series(["", "abc"])).isna().all()
