import json
import re

import pandas as pd
import pytest

import browser_agent as ba
from conftest import COUPANG_RESULT, ROOT


def test_guess_name_col_skips_flag_columns(discovery):
    assert ba.guess_name_col(discovery) == "키워드"
    # Без точного «키워드» — похожая колонка, но не флаг X/O «신규진입 키워드»
    renamed = discovery.rename(columns={"키워드": "추천 키워드 목록"})
    assert ba.guess_name_col(renamed) == "추천 키워드 목록"


def test_parse_coupang():
    m = ba.parse_coupang(COUPANG_RESULT)
    assert set(m) == {"요가매트", "캠핑의자"}
    assert m["요가매트"]["low20"] == 8 and m["요가매트"]["rocket"] == 10
    assert [p["id"] for p in m["요가매트"]["products"]] == ["111", "222", "333"]
    assert m["요가매트"]["products"][0] == {"id": "111", "price": 25000, "reviews": 150, "title": "요가매트 두꺼운 10mm", "rocket": False}
    assert m["캠핑의자"]["products"] == []


def test_parse_coupang_legacy_product_without_rocket_flag():
    m = ba.parse_coupang("S|w|36|30|25000|80|160|8|10|6|111~25000~150~title")
    assert m["w"]["products"][0]["rocket"] is None


@pytest.mark.parametrize(
    "m, ok",
    [
        (None, None),
        ({"n": 0}, None),
        ({"n": 36, "low20": 5, "rocket": 69}, True),
        ({"n": 36, "low20": 4, "rocket": 10}, False),
        ({"n": 36, "low20": 8, "rocket": 70}, False),
        ({"n": 36, "low20": 8, "rocket": None}, True),
    ],
)
def test_verdict(m, ok):
    assert ba.verdict(m)[0] is ok


def test_best_products_skip_unconfirmed_rocket_and_brands():
    text = COUPANG_RESULT + "S|텐트|36|30|25000|80|160|9|10|6|444~25000~10~텐트~1;555~25000~5~텐트 대형~0\n"
    best = ba.best_products(text)
    assert [(p["word"], p["id"]) for p in best] == [("요가매트", "111"), ("요가매트", "222"), ("텐트", "555")]
    assert best[0]["url"] == "https://www.coupang.com/vp/products/111"


def test_parse_details():
    d = ba.parse_details(COUPANG_RESULT)
    assert d["111"] == {
        "weight": "1.2kg", "size": "180x60cm", "spec": "크기: 180x60cm; 중량: 1.2kg",
        "bought": 100, "bought_text": "100+", "page_price": 25000,
    }
    assert d["222"]["spec"] is None and d["222"]["bought_text"] == "50" and d["222"]["page_price"] == 9000


def test_parse_details_ignores_non_purchase_text():
    assert ba.parse_details("D|1||구매일로부터 6개월|")["1"]["bought"] is None


def test_error_text():
    assert ba.error_text(COUPANG_RESULT) is None
    assert ba.error_text("S|a|1\nERROR|Coupang ответил 403 Access Denied") == "Coupang ответил 403 Access Denied"


def test_extension_prompt_has_script_and_words():
    p = ba.extension_prompt(["요가매트", 'a"b'])
    assert ba.START_URL in p and "window.kf_run" in p and "window.kf_parseSearch" in p
    assert 'kf_run(["요가매트", "a\\"b"]);' in p
    assert "'ok';" not in p  # ответ «ok» нужен только агенту Claude Code


def test_agent_prompt_formats():
    ba.PROMPT.format(count=1, start_url=ba.START_URL, words_json=json.dumps(["w"]))


def test_js_rules_match_python():
    """Правила записаны дважды: в kf_rules файла coupang_parse.js и в browser_agent.py — числа должны совпадать."""
    js = (ROOT / "coupang_parse.js").read_text()
    rules = re.search(r"window\.kf_rules = \{(.*?)\};", js).group(1)
    assert {k: int(v) for k, v in re.findall(r"(\w+): (\d+)", rules)} == {
        "MIN_PRICE": ba.PRICE_MIN, "MAX_PRICE": ba.PRICE_MAX, "MIN_PAGE_PRICE": ba.PAGE_PRICE_MIN, "MAX_REV": ba.LOW_REVIEWS,
        "MIN_LOW": ba.MIN_LOW_IN_TOP20, "MAX_ROCKET": ba.MAX_ROCKET, "BEST": ba.BEST_PER_WORD, "DAILY_CAP": ba.DAILY_CAP,
    }


def test_bookmarklet_is_one_url():
    bm = ba.bookmarklet()
    assert bm.startswith("javascript:") and not any(c in bm for c in " \n\"'<>")
    assert "kf_parseSearch" in bm and "kf_pack" not in bm  # без сбора в фоне


def test_search_url():
    assert ba.search_url("요가 매트") == "https://www.coupang.com/np/search?q=%EC%9A%94%EA%B0%80%20%EB%A7%A4%ED%8A%B8&listSize=36"


def test_is_limit():
    assert ba.is_limit("Дневной лимит 20 слов на Coupang исчерпан — продолжите завтра")
    assert not ba.is_limit("Coupang ответил 403") and not ba.is_limit(None)


def test_agent_files_are_read(tmp_path, monkeypatch):
    """Ответы агента из agent_run/coupang (новые pack_*.txt и файлы прежней версии) читаются так же, как файл результата."""
    monkeypatch.setattr(ba, "COUPANG_DIR", tmp_path)
    assert ba.parse_coupang() == {}
    (tmp_path / "pack_1.txt").write_text("FILE pack_1.txt\n" + COUPANG_RESULT)
    (tmp_path / "batch_1.txt").write_text("텐트|36|30|25000|80|160|9|10|6|")
    (tmp_path / "error.txt").write_text("blocked")
    assert set(ba.parse_coupang()) == {"요가매트", "캠핑의자", "텐트"}
    assert ba.parse_details().keys() == {"111", "222"}
    assert ba.error_text() == "blocked"


def test_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "COUPANG_DIR", tmp_path)
    monkeypatch.setattr(ba, "read_state", lambda: {"words": ["요가매트", "캠핑의자"]})
    (tmp_path / "pack_1.txt").write_text(COUPANG_RESULT)
    done, text = ba.progress()
    assert text == "Проанализировано 4 из 4 · слова 2/2 · товары 2/2"
    assert done == 1


def test_products_csv_round_trip(discovery, tmp_path):
    """Без загрузки приложение берёт слова последней проверки из products.csv — заголовки с переносами должны пережить CSV."""
    path = tmp_path / "products.csv"
    discovery.to_csv(path, index=False)
    assert ba.guess_name_col(pd.read_csv(path)) == "키워드"


def test_parse_wing_and_conversion():
    w = ba.parse_wing("V|111|3,000|100\nV|222||\nV|bad|1|1")
    assert w == {"111": {"views": 3000, "sold": 100}, "222": {"views": None, "sold": None}}
    assert ba.conversion(3000, 100) == 3.33
    assert ba.conversion(None, 100) is None and ba.conversion(3000, None) is None and ba.conversion(0, 5) is None
