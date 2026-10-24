"""Скрипты Coupang в браузере (Playwright): закладка ручной проверки и сбор в фоне на одних и тех же страницах.

Страницы coupang.com подменяются локальными (page.route) — настоящий Coupang не открывается, сеть не нужна.
"""

import json
from urllib.parse import unquote

import pytest

import browser_agent as ba
from conftest import ROOT

pytest.importorskip("playwright.sync_api")

WORD = "요가매트"
SEARCH = f"https://www.coupang.com/np/search?q={WORD}&listSize=36"


def item(pid: int, price: int, rev: int, rocket=False, ad=False) -> str:
    img = '<img src="//image.coupangcdn.com/badge/rocket_logo.png">' if rocket else '<img data-src="//image.coupangcdn.com/x.jpg">'
    return (
        f'<li><a href="/vp/products/{pid}?itemId={pid}1&vendorItemId={pid}2">{img}<div class="name">요가매트 상품 {pid} 두꺼운</div>'
        f'<strong>{price:,}원</strong><span>({rev})</span>{"<span>광고</span>" if ad else ""}</a></li>'
    )


# Реклама + 20 органических: 101–106 подходят, 107 подходит, но с синей ракетой, 108–120 — 500 отзывов
ITEMS = [item(900, 20000, 10, ad=True)] + [item(p, 25000, r) for p, r in zip(range(101, 107), (150, 90, 60, 30, 20, 10))]
ITEMS += [item(107, 30000, 160, rocket=True)] + [item(p, 25000, 500) for p in range(108, 121)]
SEARCH_HTML = f'<html><body><h1>쿠팡 검색</h1><ul id="product-list">{"".join(ITEMS)}</ul></body></html>'
# Топ-10: 9 × 25 000 и 30 000 → 25 500; отзывы (150+90+60+30+20+10+160+3×500)/10 = 202; Rocket 1 из 21 → 5%
S_LINE = (
    f"S|{WORD}|21|20|25500|202|500|7|5|1|"
    "101~25000~150~요가매트 상품 101 두꺼운~0;102~25000~90~요가매트 상품 102 두꺼운~0;103~25000~60~요가매트 상품 103 두꺼운~0"
)


def product_html(price: int) -> str:
    return (
        f'<html><body><h1>요가매트 상품</h1><span class="final-price-amount">{price:,}원</span><div>100명 이상</div><div>구매했어요</div>'
        "<p>필수 표기 정보</p><table><tr><td>종류</td><td>요가매트</td></tr><tr><td>크기</td><td>180x60cm</td></tr><tr><td>중량</td><td>1.2kg</td></tr></table></body></html>"  # как на Coupang: подписи и значения — td
    )


PRICES = {"101": 25000, "102": 9000, "103": 28000}
ESSENTIALS = {"essentials": [{"title": "크기", "description": "180x60cm"}, {"title": "중량", "description": "1.2kg"}]}


@pytest.fixture
def coupang(page):
    """page с подменённым coupang.com; requests — список загруженных путей."""
    requests = []

    def handle(route):
        url = route.request.url
        if not url.startswith("https://www.coupang.com/"):
            return route.abort()
        path = url.removeprefix("https://www.coupang.com")
        requests.append(path)
        if path.startswith("/np/search"):
            return route.fulfill(body=SEARCH_HTML, content_type="text/html; charset=utf-8")
        if path.startswith("/next-api/products/btf"):
            return route.fulfill(body=json.dumps(ESSENTIALS), content_type="application/json")
        if path.startswith("/vp/products/"):
            pid = path.split("/")[3].split("?")[0]
            return route.fulfill(body=product_html(PRICES.get(pid, 25000)), content_type="text/html; charset=utf-8")
        return route.fulfill(body="User-agent: *", content_type="text/plain")

    page.route("**/*", handle)
    page.requests = requests
    return page


def click_bookmark(page) -> None:
    """Как нажатие закладки: код из javascript:-ссылки выполняется на открытой странице."""
    page.evaluate("code => (0, eval)(code)", unquote(ba.bookmarklet().removeprefix("javascript:")))


def manual(page) -> dict:
    return page.evaluate("JSON.parse(localStorage.getItem('kf_manual'))")


def panel(page):
    return page.locator("#kf-panel .box")  # содержимое — в Shadow DOM


def test_bookmark_records_search_page_without_requests(coupang):
    coupang.goto(SEARCH)
    loaded = list(coupang.requests)
    click_bookmark(coupang)
    assert coupang.requests == loaded  # закладка только читает страницу
    assert manual(coupang)["S"] == {WORD: S_LINE}
    assert "«요가매트» записано: ✅ подтверждено — подходящих товаров в топ-20: 7, Rocket 5%." in panel(coupang).inner_text()
    links = panel(coupang).get_by_role("link")
    assert links.count() == 3
    assert links.first.get_attribute("href") == "/vp/products/101?itemId=1011&vendorItemId=1012"
    assert "Сегодня новых слов: 1 из 20 · записано слов 1, товаров 0" in panel(coupang).inner_text()


def test_bookmark_twice_keeps_one_panel_and_one_word(coupang):
    coupang.goto(SEARCH)
    click_bookmark(coupang)
    click_bookmark(coupang)
    assert coupang.locator("#kf-panel").count() == 1
    assert coupang.evaluate("kf_dayWords()") == [WORD]


def test_bookmark_records_product_page(coupang):
    coupang.goto("https://www.coupang.com/vp/products/101?itemId=1011&vendorItemId=1012")
    click_bookmark(coupang)
    assert manual(coupang)["D"] == {"101": "D|101|크기: 180x60cm  중량: 1.2kg|100명 이상 구매|25000"}
    assert "Товар 101 записан: цена 25 000 ₩, 100명 이상 구매." in panel(coupang).inner_text()
    coupang.goto("https://www.coupang.com/vp/products/102")
    click_bookmark(coupang)
    assert "Дешевле 10 000 ₩" in panel(coupang).inner_text()
    assert manual(coupang)["D"].keys() == {"101", "102"}


def test_bookmark_on_other_page(coupang):
    coupang.goto("https://www.coupang.com/robots.txt")
    click_bookmark(coupang)
    assert "Откройте на Coupang поиск по слову" in panel(coupang).inner_text()


def test_bookmark_daily_cap(coupang):
    coupang.goto(SEARCH)
    full = [f"w{i}" for i in range(ba.DAILY_CAP)]
    coupang.evaluate("w => localStorage.setItem('kf_day', JSON.stringify({ d: (() => { const t = new Date(); return `${t.getFullYear()}-${t.getMonth() + 1}-${t.getDate()}`; })(), w }))", full)
    click_bookmark(coupang)
    assert f"Дневной лимит {ba.DAILY_CAP} слов на Coupang исчерпан — продолжите завтра. Слово не записано" in panel(coupang).inner_text()
    assert manual(coupang) is None
    # Вчерашний счёт не мешает
    coupang.evaluate("w => localStorage.setItem('kf_day', JSON.stringify({ d: '2000-1-1', w }))", full)
    click_bookmark(coupang)
    assert WORD in manual(coupang)["S"]


def test_bookmark_download_reads_in_app(coupang):
    coupang.goto(SEARCH)
    click_bookmark(coupang)
    for pid in ("101", "102"):
        coupang.goto(f"https://www.coupang.com/vp/products/{pid}")
        click_bookmark(coupang)
    with coupang.expect_download() as dl:
        coupang.get_by_role("button", name="Скачать coupang_result.txt").click()
    assert dl.value.suggested_filename == ba.RESULT_FILE
    text = open(dl.value.path()).read()
    assert ba.verdict(ba.parse_coupang(text)[WORD])[0] is True
    assert [p["id"] for p in ba.best_products(text)] == ["101", "102", "103"]
    assert ba.parse_details(text)["101"]["bought_text"] == "100+" and ba.parse_details(text)["102"]["page_price"] == 9000


def test_bookmark_clear_needs_second_click(coupang):
    coupang.goto(SEARCH)
    click_bookmark(coupang)
    clear = coupang.get_by_role("button", name="Очистить")
    clear.click()
    assert manual(coupang) is not None
    coupang.get_by_role("button", name="Точно очистить всё?").click()
    assert manual(coupang) is None


def load_collector(page) -> None:
    for name in ("coupang_parse.js", "coupang_snippet.js"):
        assert page.evaluate("code => (0, eval)(code)", (ROOT / name).read_text()) == "ok"
    page.evaluate("window.kf_sleep = () => Promise.resolve()")  # без пауз против блокировки


def test_collector_matches_bookmark(coupang):
    """Сбор в фоне читает те же страницы так же, как закладка; товар дешевле 10 000 ₩ по прямой ссылке пропускается."""
    coupang.goto("https://www.coupang.com/robots.txt")
    load_collector(coupang)
    out = coupang.evaluate(f"kf_pack(['{WORD}'])").splitlines()
    assert out[0] == S_LINE.replace(";102~25000~90~요가매트 상품 102 두꺼운~0", "")  # смотрит только первых BEST кандидатов
    assert out[1:] == ["D|101|크기: 180x60cm  중량: 1.2kg|100명 이상 구매|25000", "D|103|크기: 180x60cm  중량: 1.2kg|100명 이상 구매|28000"]
    assert coupang.evaluate("kf_dayWords()") == [WORD]
    # Повтор — из кэша: без запросов и без лимита
    n = len(coupang.requests)
    assert coupang.evaluate(f"kf_pack(['{WORD}'])").splitlines() == out
    assert len(coupang.requests) == n


def test_collector_daily_cap(coupang):
    coupang.goto("https://www.coupang.com/robots.txt")
    load_collector(coupang)
    coupang.evaluate("kf_rules.DAILY_CAP = 1")
    out = coupang.evaluate(f"kf_pack(['{WORD}', '캠핑의자'])")
    assert out.splitlines()[-1] == "ERROR|Дневной лимит 1 слов на Coupang исчерпан — продолжите завтра"
    assert ba.is_limit(ba.error_text(out))
    assert sum(r.startswith("/np/search") for r in coupang.requests) == 1
