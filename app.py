import json
import shutil
import time

import pandas as pd
import streamlit as st

import browser_agent
from scoring import AVOID_MAX, MAX_SCORE, RECOMMEND_MIN
from table_io import read_table
from table_score import MAX_REVIEWS, table_result

st.set_page_config(page_title="Coupang Product Analyzer", page_icon="🔎", layout="wide")
st.title("🔎 Анализ товаров Coupang")
st.caption(
    "Сразу после загрузки — оценка по данным таблицы. Затем ИИ-агент проверяет отобранные слова прямо на Coupang: "
    "в списке остаются только слова, где в топе выдачи есть товары с малым числом отзывов."
)

CATEGORIES = ("Рекомендуем", "Рассмотреть", "Избегать")
NOT_CONFIRMED = "Не подтверждено на Coupang"
NOT_CHECKED = "Не проверено на Coupang"
PENDING = "⏳ проверяется на Coupang"


def prepare(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Убирает слова с отзывами больше MAX_REVIEWS; возвращает таблицу и маску брендов."""
    if "Отзывы Coupang" in df.columns:
        df = df[~(pd.to_numeric(df["Отзывы Coupang"], errors="coerce") > MAX_REVIEWS)]
    if "Цена Coupang" in df.columns:
        price = pd.to_numeric(df["Цена Coupang"], errors="coerce")
        df = df[~((price < browser_agent.PRICE_MIN) | (price > browser_agent.PRICE_MAX))]  # без цены — остаётся
    brands = df["_brand"].notna() if "_brand" in df.columns else pd.Series(False, index=df.index)
    return df, brands


def picked_words(df: pd.DataFrame, brands: pd.Series) -> pd.DataFrame:
    return df[df["Рекомендация"].isin(["Рекомендуем", "Рассмотреть"]) & ~brands].sort_values("Итоговый балл", ascending=False)


def apply_coupang(df: pd.DataFrame, coupang: dict, pending: bool = False) -> pd.DataFrame:
    """Итог проверки на Coupang: не подтверждённые слова убираются из рекомендаций.

    pending — агент ещё работает: непроверенные пока слова остаются в списке с пометкой «проверяется».
    """
    df = df.copy()
    for idx, row in df.iterrows():
        if row["Рекомендация"] not in ("Рекомендуем", "Рассмотреть"):
            continue
        if pending and row["Название продукта"] not in coupang:
            df.at[idx, "Причина"] = f"{row['Причина']}; {PENDING}"
            continue
        ok, text = browser_agent.verdict(coupang.get(row["Название продукта"]))
        df.at[idx, "Причина"] = f"{row['Причина']}; {text}"
        if ok is None:
            df.at[idx, "Рекомендация"] = NOT_CHECKED
        elif not ok:
            df.at[idx, "Рекомендация"] = NOT_CONFIRMED
        m = coupang.get(row["Название продукта"]) or {}
        for col, key in (("Coupang: товаров ≤170 отзывов в топ-20", "low20"), ("Coupang: ср. цена", "price"), ("Coupang: ср. отзывы топ-10", "rev_avg"), ("Coupang: Rocket, %", "rocket")):
            df.at[idx, col] = m.get(key)
    return df


def best_table(picked: pd.DataFrame, pending: bool = False, text: str | None = None) -> None:
    """Лучшие товары подтверждённых слов: просмотры, покупки, конверсия, цена, вес, габарит, сезон (нет данных — пусто)."""
    words = set(picked["Название продукта"])
    season = dict(zip(picked["Название продукта"], picked.get("Сезон", pd.Series(dtype=object))))
    details = browser_agent.parse_details(text)
    rows = []
    for p in browser_agent.best_products(text):
        if p["word"] not in words:
            continue
        d = details.get(p["id"], {})
        price = d.get("page_price") or p["price"]
        if price and price < browser_agent.PAGE_PRICE_MIN:
            continue  # по прямой ссылке дешевле 10 000 ₩
        views, bought = d.get("views"), d.get("bought")
        title_size = browser_agent.SIZE_RE.search(p["title"] or "")
        rows.append(
            {
                "Ключевое слово": p["word"],
                "Товар": p["title"],
                "Просмотры": views,
                "Куплено": d.get("bought_text"),
                "Конверсия, %": round(100 * bought / views, 2) if views and bought is not None else None,
                "Цена Coupang, ₩": price,
                "Отзывы": p["reviews"],
                "Вес": d.get("weight"),
                "Габарит": d.get("size") or (title_size.group(0) if title_size else None),
                "Сезон": season.get(p["word"]),
                "Ссылка": p["url"],
            }
        )
    st.subheader("Лучшие товары")
    if not rows:
        st.info("Пока нет — агент ещё проверяет слова." if pending else "Подходящих товаров нет.")
        return
    best = pd.DataFrame(rows)
    st.dataframe(best, width="stretch", hide_index=True, column_config={"Ссылка": st.column_config.LinkColumn()})
    st.download_button("Скачать CSV — лучшие товары", best.to_csv(index=False).encode("utf-8-sig"), "best_products.csv", "text/csv")


def render(df: pd.DataFrame, coupang: dict | None = None, pending: bool = False, text: str | None = None) -> None:
    """text — загруженный coupang_result.txt онлайн-версии (без него данные Coupang берутся из папки агента)."""
    df, brands = prepare(df)
    if df.empty:
        st.warning("Нет слов для показа.")
        return
    if coupang is not None:
        df = apply_coupang(df, coupang, pending)

    st.subheader("Результаты анализа товаров Coupang")
    counts = df[~brands]["Рекомендация"].value_counts()
    shown = CATEGORIES + ((NOT_CONFIRMED,) if coupang is not None else ())
    cols = st.columns(len(shown) + 2)
    cols[0].metric("Проанализировано", len(df))
    for col, name in zip(cols[1:], shown):
        col.metric(name, int(counts.get(name, 0)))
    cols[-1].metric("Бренды (исключены)", int(brands.sum()))

    picked = picked_words(df, brands)
    words_json = json.dumps(picked["Название продукта"].tolist(), ensure_ascii=False)
    st.subheader("Список рекомендуемых слов")
    st.code(words_json, language="json")
    st.download_button("Скачать JSON", words_json, "keywords.json", "application/json")

    st.subheader("Оценки")
    table = picked.assign(**{"Итоговый балл": lambda d: d["Итоговый балл"].map(lambda x: f"{x:g}/{MAX_SCORE:g}")})
    st.dataframe(table[["Название продукта", "Итоговый балл", "Рекомендация", "Причина"]].head(5), width="stretch", hide_index=True)

    if coupang is not None:
        best_table(picked, pending, text)
        csv_words = picked.drop(columns=["_triggers", "_missing", "_brand"], errors="ignore")
        st.download_button("Скачать CSV — перспективные слова", csv_words.to_csv(index=False).encode("utf-8-sig"), "perspective_keywords.csv", "text/csv")

    with st.expander("Баллы по факторам"):
        detail = df.drop(columns=["_triggers", "_missing"]).rename(columns={"_brand": "Бренд"}).sort_values("Итоговый балл", ascending=False)
        st.dataframe(detail, width="stretch", hide_index=True)
        st.download_button("Скачать CSV", detail.to_csv(index=False).encode("utf-8-sig"), "analysis.csv", "text/csv")


def online_check(words: list[str]) -> str | None:
    """Онлайн-версия, где нет Claude Code: задание для расширения Claude in Chrome и загрузка его результата."""
    st.subheader("Проверка на Coupang через расширение Claude in Chrome")
    st.markdown(
        f"1. Скопируйте задание ниже (кнопка копирования — справа вверху блока).\n"
        f"2. В Chrome откройте боковую панель **Claude in Chrome**, вставьте задание и отправьте. "
        f"Если расширение спросит доступ к coupang.com — разрешите.\n"
        f"3. Сбор идёт сам на вкладке coupang.com ({len(words)} слов, около 10 секунд на слово или товар). Вкладку не закрывайте. "
        f"В конце скачается файл **{browser_agent.RESULT_FILE}**.\n"
        f"4. Загрузите этот файл сюда — появятся подтверждённые слова и лучшие товары."
    )
    st.code(browser_agent.extension_prompt(words), language="markdown", height=200)
    result = st.file_uploader(f"Файл результата {browser_agent.RESULT_FILE}", type=["txt"])
    return result.getvalue().decode("utf-8", errors="replace") if result is not None else None


@st.fragment(run_every=3)
def live_run(results: pd.DataFrame) -> None:
    """Пока агент работает: результаты по уже проверенным словам и ход проверки; обновляется каждые 3 секунды."""
    if not browser_agent.is_running():
        st.rerun(scope="app")  # агент закончил — перерисовать страницу с итогом
    render(results, browser_agent.parse_coupang(), pending=True)
    state = browser_agent.read_state()
    done, stage = browser_agent.progress()
    minutes = (time.time() - state["started"]) / 60
    st.progress(min(done, 1.0), text=f"{stage} · {minutes:.0f} мин")
    if st.button("⏹ Остановить агента"):
        browser_agent.stop()
        st.rerun(scope="app")


# ---------- Параметры ----------
with st.sidebar:
    st.header("ИИ-агент")
    st.caption(
        "Работает через ваш Claude Code и подписку, без API-ключа. Проверяет слова на Coupang в вашем Chrome "
        "(расширение Claude in Chrome)."
    )
    st.header("Пороги")
    st.markdown(
        f"- **Рекомендуем** — от {RECOMMEND_MIN:g} баллов\n"
        f"- **Рассмотреть** — больше {AVOID_MAX:g} и меньше {RECOMMEND_MIN:g}\n"
        f"- **Избегать** — {AVOID_MAX:g} и ниже или сработал триггер\n"
        f"- Слова, где отзывов на Coupang больше {MAX_REVIEWS}, исключаются\n"
        f"- Бренды и слова, похожие на бренд или имя (katana, alice, monica…), в список не попадают\n"
        f"- Цена товаров — от {browser_agent.PRICE_MIN // 1000} 000 до {browser_agent.PRICE_MAX // 1000} 000 ₩\n"
        f"- **Coupang** подтверждает слово, если в топ-20 выдачи (без рекламы) не меньше {browser_agent.MIN_LOW_IN_TOP20} "
        f"товаров с отзывами ≤{browser_agent.LOW_REVIEWS} и ценой в диапазоне"
        f", а синяя ракета меньше {browser_agent.MAX_ROCKET}% выдачи\n"
        f"- Товары с синей ракетой в список не попадают\n"
        f"- Товар убирается, если по прямой ссылке он дешевле {browser_agent.PAGE_PRICE_MIN // 1000} 000 ₩"
    )

uploaded = st.file_uploader("Таблица со словами", type=["xlsx", "xls", "csv"])
state = browser_agent.read_state()
running = browser_agent.is_running()

if uploaded is not None:
    try:
        data = read_table(uploaded.name, uploaded.getvalue())
    except Exception as e:
        st.error(f"Не удалось прочитать файл: {e}")
        st.stop()
    from_agent = state is not None and state["file"] == uploaded.name
else:
    # Без загрузки — показываем последнюю проверку на Coupang по сохранённым словам
    data = pd.read_csv(browser_agent.PRODUCTS) if state and browser_agent.PRODUCTS.exists() else None
    from_agent = data is not None

if data is not None:
    name_col = browser_agent.guess_name_col(data)
    if uploaded is not None:
        st.caption(f"В файле {len(data)} строк. Слова берутся из колонки «{str(name_col).replace(chr(10), ' ')}».")
    result = table_result(data, name_col)
    if result is None:
        if uploaded is not None:
            st.error("В таблице нет колонок для оценки (нужна хотя бы «최근 1개월 검색량»).")
        st.stop()
    checked = from_agent and not running
    if checked and not state.get("finished"):
        state["finished"] = True
        browser_agent.STATE.write_text(json.dumps(state, ensure_ascii=False))
    if checked and (err := browser_agent.error_text()):
        st.error(f"Агент остановился на Coupang: {err}")
    # Онлайн-версия (Streamlit Cloud): нет Claude Code — проверку делает расширение, результат загружается файлом ниже
    online = uploaded is not None and shutil.which("claude") is None
    results_box = st.container()  # результаты — над блоком проверки, хотя файл результата загружается после него
    online_text = None
    if online:
        df, brands = prepare(result["results"])
        online_text = online_check(picked_words(df, brands)["Название продукта"].tolist())
    # Проверка на Coupang — после результатов: кнопка запуска, а пока агент работает — результаты по мере проверки и полоса прогресса
    with results_box:
        if online_text is not None:
            if err := browser_agent.error_text(online_text):
                st.error(f"Сбор на Coupang остановился: {err}")
            render(result["results"], browser_agent.parse_coupang(online_text), text=online_text)
        elif from_agent and running:
            live_run(result["results"])
        else:
            render(result["results"], browser_agent.parse_coupang() if checked else None)
    if not (from_agent and running) and uploaded is not None and not online:
        df, brands = prepare(result["results"])
        words = picked_words(df, brands)["Название продукта"].tolist()
        if st.button(f"▶ Проверить на Coupang ({len(words)} слов)", type="primary", disabled=running or not words):
            rows = data[data[name_col].astype(str).str.strip().isin(words)]
            try:
                browser_agent.start(rows, uploaded.name)
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
