"""Чтение выгрузки (Excel / CSV) и разбор чисел."""

import io

import pandas as pd


def read_table(name: str, raw: bytes) -> pd.DataFrame:
    """Читает Excel или CSV (utf-8 / cp949 / euc-kr)."""
    if name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(raw))
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось определить кодировку CSV файла")


def to_number(series: pd.Series) -> pd.Series:
    """'12,345' / '35%' / ' 7 ' -> число; всё остальное -> NaN."""
    if pd.api.types.is_numeric_dtype(series):
        return series
    cleaned = series.astype(str).str.replace(r"[,%\s]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")
