"""Предварительная оценка по колонкам выгрузки (Itemscout Discovery) — сразу после загрузки файла.

Те же 10 факторов и 100-балльная шкала, что у агента; негабарит и сложность в таблице не бывают,
поэтому оценка всегда неполная. Итог агента по свежей статистике Itemscout потом заменяет её.
"""

import gzip
import re
from pathlib import Path

import pandas as pd

from scoring import FACTORS, summarize
from table_io import to_number

COLUMNS = {
    "search": "최근 1개월 검색량",
    "products": "네이버 상품수",
    "growth3": "예상3개월 검색량 상승률",
    "season": "계절성",
    "competition": "네이버 경쟁강도",
    "price": "쿠팡 평균가",
    "reviews": "쿠팡 평균리뷰수",
    "rocket": "쿠팡 로켓배송비율",
    "brand": "브랜드 키워드",
}
MAX_REVIEWS = 170  # слова, где отзывов на Coupang больше, исключаются

# Известные бренды (корейские рынки): слово, содержащее любое из них, считается брендом
BRANDS = """
nike 나이키 adidas 아디다스 puma 푸마 newbalance 뉴발란스 뉴발 underarmour 언더아머 reebok 리복 asics 아식스 fila 휠라
descente 데상트 northface 노스페이스 discovery 디스커버리 kolon 코오롱 blackyak 블랙야크 nepa 네파 eider 아이더
columbia 컬럼비아 patagonia 파타고니아 spao 스파오 topten 탑텐 uniqlo 유니클로 zara h&m 무신사 massimodutti 마시모두띠
lululemon 룰루레몬 루루레몬 andar 안다르 xexymix 젝시믹스 젝스믹스 젝시미스 mulawear 뮬라웨어 알로요가 alosports manduka 만두카
crocs 크록스 vans 반스 converse 컨버스 drmartens 닥터마틴 moncler 몽클레어 gucci 구찌 chanel 샤넬 louisvuitton 루이비통
prada 프라다 hermes 에르메스 dior 디올 gentlemonster 젠틀몬스터 casetify 케이스티파이 stussy 스투시 carhartt 칼하트
samsung 삼성 갤럭시 galaxy apple 아이폰 iphone 에어팟 airpods 아이패드 ipad lg전자 엘지 dyson 다이슨 xiaomi 샤오미
philips 필립스 tefal 테팔 cuckoo 쿠쿠 cuchen 쿠첸 braun logitech 로지텍 lego 레고 starbucks 스타벅스 ikea 이케아
locknlock 락앤락 corelle 코렐 hurom 휴롬 winix 위닉스 brita 브리타 gillette 질레트 oralb 오랄비 daiso 다이소 muji 무인양품
hanssem 한샘 sidiz 시디즈 duoback 듀오백 simmons 시몬스 tempur 템퍼 coway 코웨이 bodyfriend 바디프랜드 ceragem 세라젬
nintendo 닌텐도 sony 소니 playstation 플레이스테이션 canon 캐논 nikon 니콘 bose jbl marshall 마샬 hp asus 에이수스
lenovo 레노버 dji tesla 테슬라 hyundai 현대 kia 기아 bmw benz 벤츠 audi 아우디 volvo 볼보 pv5 disney 디즈니 sanrio 산리오
pokemon 포켓몬 kakao 카카오프렌즈 linefriends 라인프렌즈 bt21 무지개맨션 오즈이즈 잇존 위뜨 huit8 모어아웃 무브웜 스컬피그
""".split()
MODEL_CODE = re.compile(r"^(?=.*[a-z])(?=.*\d{3})[a-z0-9-]+$", re.IGNORECASE)  # латиница + 3 цифры подряд: iw5727, sm-s928

# Слова латиницей, которые не бренд: сокращения, единицы и современные товарные слова (их нет в старом словаре macOS)
GENERIC_LATIN = set("""
usb led lcd oled hdmi wifi bluetooth atm diy pvc abs tpu uv rgb mini pro max plus set size free cctv tds
laptop notebook smartphone smartwatch tablet airfryer keyboard mouse webcam headset earphone speaker
mask cushion pouch tumbler hoodie legging leggings sneakers slipper slippers pajama pajamas bikini
""".split())

# Имена и «звучные» слова, записанные хангылем (только из 3+ слогов, чтобы не задевать обычные слова)
NAME_LIKE_KO = """
앨리스 엘리스 모니카 카타나 엘립스 이클립스 소피아 올리비아 에밀리 클로이 이사벨 이자벨 샬롯 빅토리아 줄리아 레베카
제시카 안젤라 크리스틴 마이클 다니엘 데이비드 제임스 윌리엄 알렉스 올리버 루시아 엘레나 아멜리아 그레이스 스텔라
헤일리 나탈리 레이첼 에블린 오로라 비비안 캐서린 마틸다 클라라 로렌스 해리슨 벤자민 사무엘 조슈아 매튜 앤드류
""".split()


def _dictionary() -> tuple[set[str], set[str]]:
    """Словарь macOS: обычные слова (строчные) и имена собственные (только с заглавной: Alice, Monica).
    Копия /usr/share/dict/web2 лежит в words.gz — онлайн (Streamlit Cloud, Linux) своего словаря нет."""
    try:
        entries = gzip.decompress((Path(__file__).parent / "words.gz").read_bytes()).decode().split()
    except OSError:
        return set(), set()
    common = {e for e in entries if e.islower()}
    return common, {e.lower() for e in entries if e[:1].isupper() and e.lower() not in common}


DICT_COMMON, DICT_NAMES = _dictionary()


def _name_like(word: str) -> str | None:
    """Слово-латиница вне словаря (katana, elipse) или имя (alice, monica); хангылем — имя из NAME_LIKE_KO."""
    for token in re.findall(r"[a-z]{4,}", word):  # 1–3 буквы — сокращения: ph, atm, ml
        if token in GENERIC_LATIN:
            continue
        if token in DICT_NAMES:
            return f"похоже на имя или бренд: {token}"
        if DICT_COMMON and not {token, token.rstrip("s"), token[:-2]} & DICT_COMMON:
            return f"похоже на бренд: {token}"
    hit = next((n for n in NAME_LIKE_KO if n in word), None)
    return f"похоже на имя или бренд: {hit}" if hit else None

COMPETITION = {"낮음": ("Низкий", 10), "중간": ("Средний", 7.5), "높음": ("Высокий", 0)}
COMPETITION_TEXT = {"낮음": "низкая", "중간": "средняя", "높음": "высокая"}
SEASON = {"없음": ("Нет", 7.5), "있음": ("Да", 5)}


def title_brand(title: str) -> str | None:
    """Бренд в названии товара: известный бренд или латинское слово-имя (пробелы сохраняются: «PH TDS» — не одно слово)."""
    t = str(title).lower()
    hit = next((b for b in BRANDS if b in t.replace(" ", "")), None)
    return f"бренд: {hit}" if hit else _name_like(t)


def brand_reason(word: str, brand_flag: str | None = None) -> str | None:
    """Почему слово похоже на бренд (None — не похоже): метка таблицы, известный бренд, код модели, имя."""
    if str(brand_flag).strip().upper() in ("O", "Y"):
        return "бренд по таблице"
    w = word.lower().replace(" ", "")
    hit = next((b for b in BRANDS if b in w), None)
    if hit:
        return f"бренд: {hit}"
    if MODEL_CODE.match(w):
        return "похоже на код модели бренда"
    return _name_like(w)


def _col(data: pd.DataFrame, name: str):
    """Колонка по имени без учёта пробелов и переносов строк."""
    return next((c for c in data.columns if " ".join(str(c).split()) == name), None)


def _fmt(n: float) -> str:
    return f"{n:,.0f}".replace(",", " ")


def score_row(v: dict) -> dict:
    """Баллы по факторам из значений одной строки (None — нет данных)."""
    f = {k: {"value": None, "points": None} for k in FACTORS}
    triggers = []
    search, products, g3, price, reviews, rocket = (v.get(k) for k in ("search", "products", "growth3", "price", "reviews", "rocket"))

    if search is not None:
        f["demand"] = {"value": f"{_fmt(search)}", "points": 15 if search >= 30000 else 12.5 if search >= 10000 else 10 if search >= 4000 else 5 if search >= 2000 else 0}
        if search < 2000:
            triggers.append("low_demand")
    if search and products:
        ratio = search / products
        f["ratio"] = {"value": f"{ratio:.2f}", "points": 12.5 if ratio >= 1 else 10 if ratio >= 0.5 else 7.5}
    if g3 is not None:
        # Прогноз роста на 3 месяца: больше +5% — вверх, меньше −5% — вниз
        label, pts = ("Тренд Вверх", 10) if g3 > 0.05 else ("Тренд Вниз", 0) if g3 < -0.05 else ("Стабильный", 7.5)
        f["trend"] = {"value": f"{label} (прогноз {g3:+.0%})", "points": pts}
        if pts == 0:
            triggers.append("trend_down")
    if v.get("season") in SEASON:
        label, pts = SEASON[v["season"]]
        f["seasonality"] = {"value": label, "points": pts}
    if v.get("competition") in COMPETITION:
        label, pts = COMPETITION[v["competition"]]
        f["competition"] = {"value": label, "points": pts}
    if price:
        f["price"] = {"value": f"{_fmt(price)} KRW", "points": 12.5 if price > 15000 else 7.5}
    if reviews is not None:
        f["reviews"] = {"value": _fmt(reviews), "points": 10 if reviews < 500 else 5 if reviews < 2500 else 2.5 if reviews <= 5000 else 0}
        if reviews > 5000:
            triggers.append("reviews_over_5000")
    if rocket is not None:
        f["growth"] = {"value": f"{rocket:g}%", "points": 7.5 if rocket < 30 else 2.5 if rocket < 60 else 0}
        if rocket >= 60:
            triggers.append("growth_60_100")
    return {"factors": f, "triggers": triggers}


def _reason(v: dict) -> str:
    parts = []
    if v.get("search") is not None:
        parts.append(f"поиск {_fmt(v['search'])}/мес")
    if v.get("growth3") is not None:
        parts.append(f"прогноз на 3 мес {v['growth3']:+.0%}")
    if v.get("competition"):
        parts.append(f"конкуренция {COMPETITION_TEXT.get(v['competition'], v['competition'])}")
    if v.get("reviews") is not None:
        parts.append(f"отзывов {_fmt(v['reviews'])}")
    if v.get("rocket") is not None:
        parts.append(f"Rocket {v['rocket']:g}%")
    return ", ".join(parts)


def table_result(data: pd.DataFrame, name_col) -> dict | None:
    """Результат в том же виде, что у агента; None — в файле нет нужных колонок."""
    cols = {k: _col(data, name) for k, name in COLUMNS.items()}
    if cols["search"] is None:
        return None
    values = pd.DataFrame(index=data.index)
    for k, c in cols.items():
        if c is None:
            values[k] = None
        elif k in ("season", "competition", "brand"):
            values[k] = data[c].astype(str).str.strip()
        else:
            values[k] = to_number(data[c])
    if values["rocket"].notna().any() and values["rocket"].max() <= 1:
        values["rocket"] = values["rocket"] * 100  # доля 0.45 → 45%

    rows, seen = [], set()
    for idx, row in data.iterrows():
        word = str(row[name_col]).strip()
        if not word or word == "nan" or word in seen:
            continue
        seen.add(word)
        v = {k: (None if pd.isna(x) else x) for k, x in values.loc[idx].items()}
        product = {**score_row(v), "boundary_flags": [], "reason": _reason(v)}
        sm = summarize(product)
        rows.append(
            {
                "Название продукта": word,
                "Итоговый балл": sm["total"],
                "Рекомендация": sm["category"],
                "Причина": sm["reason"],
                "Полная оценка": sm["complete"],
                "_triggers": sm["triggers"],
                "_missing": sm["missing"],
                **{FACTORS[k][0]: product["factors"][k]["points"] for k in FACTORS},
                "Отзывы Coupang": v.get("reviews"),
                "Цена Coupang": v.get("price"),
                "Сезон": {"있음": "Сезонный", "없음": "Не сезонный"}.get(v.get("season")),
                "_brand": brand_reason(word, v.get("brand")),
            }
        )
    return {"results": pd.DataFrame(rows), "warnings": [], "research": None}
