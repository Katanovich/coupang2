"""Сквозной тест в браузере (Playwright): от загрузки выгрузки до лучших товаров.

Приложение запускается из копии проекта во временной папке: настоящий agent_run/ не читается и не меняется.
Онлайн-версия — без claude в PATH, версия на Mac — с подставным claude вместо агента.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from conftest import COUPANG_RESULT, ROOT

playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect

APP_FILES = [p.name for p in (*ROOT.glob("*.py"), *ROOT.glob("*.js"))] + ["words.gz", ".streamlit"]


def serve(work, extra_path: str = ""):
    """Приложение из копии проекта в work; PATH — интерпретатор и extra_path (там может лежать подставной claude)."""
    for name in APP_FILES:
        (shutil.copytree if (ROOT / name).is_dir() else shutil.copy)(ROOT / name, work / name)
    with socket.socket() as s:
        s.bind(("localhost", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "PATH": f"{extra_path}{os.path.dirname(sys.executable)}:/usr/bin:/bin"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port), "--server.headless", "true"],
        cwd=work, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://localhost:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(url + "/_stcore/health", timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("Streamlit не запустился")
    return proc, url


@pytest.fixture(scope="module")
def app_url(tmp_path_factory):
    # Без claude в PATH: shutil.which("claude") не находит Claude Code → онлайн-версия
    proc, url = serve(tmp_path_factory.mktemp("app"))
    yield url
    proc.terminate()
    proc.wait(10)


@pytest.fixture
def local_app(tmp_path):
    """Версия на Mac: подставной claude вместо Claude Code — через 2 секунды пишет ответ сбора и запоминает каждый запуск."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "result.txt").write_text(COUPANG_RESULT)
    claude = bin_dir / "claude"
    claude.write_text(f"#!/bin/sh\necho run >> {tmp_path}/starts\nsleep 2\ncp {tmp_path}/result.txt agent_run/coupang/pack_1.txt\n")
    claude.chmod(0o755)
    work = tmp_path / "app"
    work.mkdir()
    proc, url = serve(work, f"{bin_dir}:")
    yield url, tmp_path / "starts"
    proc.terminate()
    proc.wait(10)


def metric(page, label: str):
    return page.get_by_test_id("stMetric").filter(has_text=label).get_by_test_id("stMetricValue")


def test_online_flow(page, app_url, discovery_csv, result_txt):
    page.goto(app_url)
    page.locator("input[type=file]").first.set_input_files(discovery_csv)

    # Оценка по таблице: исключены отзывы > 170 и цена > 60 000, повтор не считается
    expect(page.get_by_text("В файле 9 строк. Слова берутся из колонки «키워드».")).to_be_visible(timeout=20000)
    expect(metric(page, "Проанализировано")).to_have_text("6")
    expect(metric(page, "Рекомендуем")).to_have_text("1")
    expect(metric(page, "Рассмотреть")).to_have_text("1")
    expect(metric(page, "Избегать")).to_have_text("1")
    expect(metric(page, "Бренды (исключены)")).to_have_text("3")
    expect(page.get_by_text('["요가매트", "캠핑의자"]', exact=True)).to_be_visible()

    # Ручная проверка: закладка и ссылки на поиск по каждому слову, лучшие слова — первыми
    expect(page.get_by_test_id("stMainBlockContainer").get_by_role("heading", name="Проверка на Coupang")).to_be_visible()
    bookmark = page.frame_locator("iframe").first.get_by_role("link", name="🔖 Coupang")
    assert bookmark.get_attribute("href").startswith("javascript:")
    links = page.get_by_role("link", name="요가매트")
    expect(links).to_have_attribute("href", "https://www.coupang.com/np/search?q=%EC%9A%94%EA%B0%80%EB%A7%A4%ED%8A%B8&listSize=36")
    expect(page.get_by_role("link", name="캠핑의자")).to_be_visible()

    # Автоматический сбор — запасной, в свёрнутом блоке; без Claude Code — задание для расширения, а не кнопка агента
    page.get_by_text("Автоматический сбор — может включить проверку на бота").click()
    expect(page.get_by_role("button", name="▶ Проверить на Coupang")).to_have_count(0)
    expect(page.get_by_text('kf_run(["요가매트", "캠핑의자"]);')).to_be_attached()

    # Файл результата: «캠핑의자» не подтверждён, у «요가매트» — один товар (222 дешевле 10 000 ₩, 333 — бренд)
    page.locator("input[type=file]").nth(1).set_input_files(result_txt)
    expect(metric(page, "Не подтверждено на Coupang")).to_have_text("1", timeout=20000)
    expect(page.get_by_text('["요가매트"]', exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="Лучшие товары")).to_be_visible()
    expect(page.get_by_role("button", name="Скачать CSV — лучшие товары")).to_be_visible()

    with page.expect_download() as dl:
        page.get_by_role("button", name="Скачать CSV — лучшие товары").click()
    csv = open(dl.value.path(), encoding="utf-8-sig").read().splitlines()
    assert csv[0].startswith("Ключевое слово,Товар,Просмотры,Куплено")
    assert len(csv) == 2 and "요가매트 두꺼운 10mm" in csv[1] and "100+" in csv[1] and "1.2kg" in csv[1] and "180x60cm" in csv[1]


def test_daily_limit_is_not_an_error(page, app_url, discovery_csv, tmp_path):
    limited = tmp_path / "coupang_result.txt"
    limited.write_text("ERROR|Дневной лимит 20 слов на Coupang исчерпан — продолжите завтра")
    page.goto(app_url)
    page.locator("input[type=file]").first.set_input_files(discovery_csv)
    page.locator("input[type=file]").nth(1).set_input_files(limited)
    expect(page.get_by_test_id("stAlertContentInfo").filter(has_text="Дневной лимит 20 слов")).to_be_visible(timeout=20000)


def test_error_from_result_file(page, app_url, discovery_csv, tmp_path):
    blocked = tmp_path / "coupang_result.txt"
    blocked.write_text("ERROR|Coupang включил проверку на бота — подождите 30–60 минут")
    page.goto(app_url)
    page.locator("input[type=file]").first.set_input_files(discovery_csv)
    page.locator("input[type=file]").nth(1).set_input_files(blocked)
    expect(page.get_by_text("Сбор на Coupang остановился: Coupang включил проверку на бота")).to_be_visible(timeout=20000)


def test_bad_table(page, app_url, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("키워드,что-то\n요가매트,1\n")
    page.goto(app_url)
    page.locator("input[type=file]").first.set_input_files(bad)
    expect(page.get_by_text("В таблице нет колонок для оценки")).to_be_visible(timeout=20000)


@pytest.mark.parametrize("views, kept", [(3000, True), (10000, False)])
def test_conversion_filter(page, app_url, discovery_csv, tmp_path, views, kept):
    """Просмотры и продажи из Wing: 100 продаж на 3000 просмотров (3,33%) — в таблице, на 10 000 (1%) — убран."""
    result = tmp_path / "coupang_result.txt"
    result.write_text(COUPANG_RESULT + f"V|111|{views}|100\n")
    page.goto(app_url)
    page.locator("input[type=file]").first.set_input_files(discovery_csv)
    page.locator("input[type=file]").nth(1).set_input_files(result)
    expect(page.get_by_role("heading", name="Лучшие товары")).to_be_visible(timeout=20000)
    if kept:
        with page.expect_download() as dl:
            page.get_by_role("button", name="Скачать CSV — лучшие товары").click()
        row = open(dl.value.path(), encoding="utf-8-sig").read().splitlines()[1]
        assert ",3000,100,3.33," in row
    else:
        expect(page.get_by_text("Убрано товаров с конверсией 2% и ниже: 1.")).to_be_visible()
        expect(page.get_by_text("Подходящих товаров нет.")).to_be_visible()


def test_local_check_starts_by_itself(page, local_app, discovery_csv):
    """На Mac проверка на Coupang запускается сама после загрузки: без кнопок, результаты появляются сами."""
    url, starts = local_app
    page.goto(url)
    page.locator("input[type=file]").first.set_input_files(discovery_csv)
    expect(page.get_by_text("Проанализировано").first).to_be_visible(timeout=20000)
    expect(page.get_by_role("heading", name="Лучшие товары")).to_be_visible(timeout=30000)
    expect(page.get_by_text("요가매트 두꺼운 10mm")).to_be_attached(timeout=30000)
    expect(metric(page, "Не подтверждено на Coupang")).to_have_text("1", timeout=30000)
    expect(page.get_by_role("button", name="▶ Проверить заново (2 слов)")).to_be_visible(timeout=30000)
    assert starts.read_text().count("run") == 1
    # Тот же файл ещё раз — повторно не запускается
    page.reload()
    page.locator("input[type=file]").first.set_input_files(discovery_csv)
    expect(page.get_by_role("button", name="▶ Проверить заново (2 слов)")).to_be_visible(timeout=30000)
    page.wait_for_timeout(2000)
    assert starts.read_text().count("run") == 1
