"""
Data loading and preprocessing for TRA passenger flow analysis.
All heavy I/O is wrapped in @st.cache_data so it runs only once per session.
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).parent / "data"
OLD_DIR = DATA_DIR / "每日各站進出站人數2005-20190422"
NEW_DIR = DATA_DIR / "每日各站進出站人數20190423-20251231"

# JSON 站名 → supp_info 站名 對照表（解決「臺」vs「台」及縮略名稱差異）
_NAME_NORM: dict[str, str] = {
    "臺北": "台北", "臺中": "台中", "臺南": "台南", "臺東": "台東",
    "臺中港": "台中港", "臺北-環島": "台北-環島",
    "五權": "五權站", "松竹": "松竹站", "林榮新光": "林榮新",
    "栗林": "栗林站", "科工館": "科工", "精武": "精武站", "長榮大學": "長榮",
}


# ── Station metadata ───────────────────────────────────────────────────────────

@st.cache_data
def load_stations() -> pd.DataFrame:
    """Return DataFrame with one row per station: staCode, name, GPS, city, region."""
    with open(DATA_DIR / "車站基本資料集.json", encoding="utf-8") as f:
        raw = json.load(f)

    rows = []
    for s in raw:
        gps = s.get("gps", "").strip()
        lat = lon = None
        if gps:
            parts = gps.split()
            if len(parts) == 2:
                try:
                    lat, lon = float(parts[0]), float(parts[1])
                except ValueError:
                    pass
        # Normalize name to match supp_info convention (台 not 臺, full names)
        raw_name = s["stationName"].strip()
        name = _NAME_NORM.get(raw_name, raw_name)
        rows.append({
            "staCode": int(s["stationCode"]),
            "stationName": name,
            "stationEName": s.get("stationEName", ""),
            "lat": lat,
            "lon": lon,
        })

    df_sta = pd.DataFrame(rows)

    supp = pd.read_csv(DATA_DIR / "supp_info.csv", encoding="utf-8-sig")
    # Actual column content (confirmed from file inspection):
    #   col0 stationName | col1 tkt_type (對號/非對號) | col2 line_type (主線/支線) | col3 city
    supp.columns = ["stationName", "tkt_type", "line_type", "city"]
    for col in supp.select_dtypes("object").columns:
        supp[col] = supp[col].str.strip()
    # Normalize supp_info stationName to 台 form so merge works regardless of whether
    # the CSV uses 臺 or 台 (df_sta stationName was already normalized to 台 form above)
    supp["stationName"] = supp["stationName"].replace(_NAME_NORM)

    df_sta = df_sta.merge(supp, on="stationName", how="left")
    # Fill missing metadata so NaN never causes silent row-drops in downstream groupby
    df_sta["city"] = df_sta["city"].fillna("—")
    df_sta["tkt_type"] = df_sta["tkt_type"].fillna("非對號")
    df_sta["line_type"] = df_sta["line_type"].fillna("主線")
    return df_sta


# ── Holiday data ───────────────────────────────────────────────────────────────

@st.cache_data
def load_holidays() -> pd.DataFrame:
    df = pd.read_csv(
        DATA_DIR / "taiwan_holidays_and_summer_vacations_2005_2026.csv",
        encoding="utf-8-sig",
    )
    df.columns = [
        "year", "spring_festival", "dragon_boat", "mid_autumn",
        "summer_start", "summer_end", "misc", "covid",
    ]
    return df


def _parse_range(year: int, date_str: str) -> list[pd.Timestamp]:
    """Parse holiday date strings like 'MM/DD-MM/DD', 'M月D日', 'MM/DD'."""
    if not isinstance(date_str, str) or not date_str.strip():
        return []
    s = date_str.strip()

    # Chinese format: M月D日
    m = re.match(r"(\d+)月(\d+)日?", s)
    if m:
        try:
            return [pd.Timestamp(year, int(m.group(1)), int(m.group(2)))]
        except Exception:
            return []

    # Range: MM/DD-MM/DD
    if "-" in s:
        parts = s.split("-")
        if len(parts) == 2:
            try:
                sm, sd = map(int, parts[0].split("/"))
                em, ed = map(int, parts[1].split("/"))
                start = pd.Timestamp(year, sm, sd)
                end = pd.Timestamp(year, em, ed)
                return pd.date_range(start, end).tolist()
            except Exception:
                return []

    # Single date: MM/DD
    try:
        mm, dd = map(int, s.split("/"))
        return [pd.Timestamp(year, mm, dd)]
    except Exception:
        return []


def _parse_summer(year: int, start_str, end_str) -> list[pd.Timestamp]:
    """Parse summer vacation dates (M月D日 format)."""
    def _parse_one(val):
        if not isinstance(val, str):
            return None
        m = re.match(r"(\d+)月(\d+)日?", val.strip())
        if m:
            try:
                return pd.Timestamp(year, int(m.group(1)), int(m.group(2)))
            except Exception:
                return None
        return None

    start = _parse_one(start_str)
    end = _parse_one(end_str)
    if start and end:
        return pd.date_range(start, end).tolist()
    return []


HOLIDAY_COLS = {
    "春節": "spring_festival",
    "端午": "dragon_boat",
    "中秋": "mid_autumn",
}


def get_holiday_dates(holidays: pd.DataFrame, year: int, holiday_type: str) -> list[pd.Timestamp]:
    row = holidays[holidays["year"] == year]
    if row.empty:
        return []
    row = row.iloc[0]

    if holiday_type == "暑假":
        return _parse_summer(year, row["summer_start"], row["summer_end"])

    col = HOLIDAY_COLS.get(holiday_type)
    if col is None:
        return []
    return _parse_range(year, row[col])


# ── Passenger data ─────────────────────────────────────────────────────────────

@st.cache_data(show_spinner="載入旅運資料（首次約需 20 秒）...")
def load_all_passenger_data() -> pd.DataFrame:
    """
    Load and unify 2005-2026 passenger data into a single DataFrame.
    Columns: date (Timestamp), staCode (int), in_count, out_count, net_flow,
             stationName, lat, lon, city, region_broad, line_type
    """
    stations = load_stations()
    name_map = dict(zip(stations["stationName"], stations["staCode"]))

    dfs: list[pd.DataFrame] = []

    # ── Old format (2005 ~ 2019/04/22) ──────────────────────────────────────
    old_files = [
        OLD_DIR / "每日各站進出站人數2005-2017.csv",
        OLD_DIR / "每日各站進出站人數2018.csv",
        OLD_DIR / "每日各站進出站人數至20190422.csv",
    ]
    for fp in old_files:
        df = pd.read_csv(fp, encoding="utf-8-sig", header=0)
        # Assign positionally to avoid encoding artifacts in Chinese column names
        df.columns = ["date", "tkt_beg", "stationName", "in_count", "out_count"]
        df["stationName"] = df["stationName"].str.strip()
        df["staCode"] = df["stationName"].map(name_map)
        df = df.dropna(subset=["staCode"]).copy()
        df["staCode"] = df["staCode"].astype(int)
        dfs.append(df[["date", "staCode", "in_count", "out_count"]])

    # ── New format CSV (2019/04/23 ~ 2025) ──────────────────────────────────
    new_files = sorted(
        fp for fp in NEW_DIR.glob("*.csv") if "每日各站進出站人數" in fp.name
    )
    for fp in new_files:
        df = pd.read_csv(fp, encoding="utf-8-sig", header=0)
        df.columns = ["date", "staCode", "in_count", "out_count"]
        dfs.append(df[["date", "staCode", "in_count", "out_count"]])

    # ── 2026 JSON ────────────────────────────────────────────────────────────
    with open(DATA_DIR / "每日各站進出站人數-2026.json", encoding="utf-8") as f:
        raw2026 = json.load(f)
    df26 = pd.DataFrame(raw2026)
    df26.columns = ["date", "staCode", "in_count", "out_count"]
    # staCode in JSON is "0900" (string with leading zero) → normalise
    df26["staCode"] = df26["staCode"].astype(str).str.lstrip("0")
    df26.loc[df26["staCode"] == "", "staCode"] = "0"
    df26["staCode"] = df26["staCode"].astype(int)
    dfs.append(df26[["date", "staCode", "in_count", "out_count"]])

    # ── Combine ──────────────────────────────────────────────────────────────
    df_all = pd.concat(dfs, ignore_index=True)
    df_all["date"] = pd.to_datetime(
        df_all["date"].astype(str).str.strip(), format="%Y%m%d", errors="coerce"
    )
    df_all = df_all.dropna(subset=["date"])
    df_all["in_count"] = pd.to_numeric(df_all["in_count"], errors="coerce").fillna(0).astype(int)
    df_all["out_count"] = pd.to_numeric(df_all["out_count"], errors="coerce").fillna(0).astype(int)
    df_all["net_flow"] = df_all["in_count"] - df_all["out_count"]

    # Merge station metadata
    meta_cols = ["staCode", "stationName", "lat", "lon", "city", "tkt_type", "line_type"]
    df_all = df_all.merge(stations[meta_cols], on="staCode", how="left")

    return df_all


# ── Pre-aggregated views (cached separately so they compute fast) ─────────────

@st.cache_data
def get_annual_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Annual totals per station."""
    df2 = df.copy()
    df2["year"] = df2["date"].dt.year
    return (
        df2.groupby(["year", "staCode", "stationName", "city", "tkt_type", "line_type"],
                    dropna=False)
        [["in_count", "out_count", "net_flow"]]
        .sum()
        .reset_index()
    )


@st.cache_data
def get_daily_national(df: pd.DataFrame) -> pd.DataFrame:
    """Daily nationwide total ridership (for trend / COVID view)."""
    return (
        df.groupby("date")[["in_count", "out_count"]]
        .sum()
        .reset_index()
        .rename(columns={"in_count": "total_in", "out_count": "total_out"})
        .assign(total=lambda x: x["total_in"] + x["total_out"])
        .sort_values("date")
    )


# ── Color helpers ──────────────────────────────────────────────────────────────

def net_flow_to_rgba(series: pd.Series, alpha: int = 200, quantile: float = 0.95,
                     max_abs_override=None) -> list[list[int]]:
    """
    Map net_flow → RGBA list.
    net_flow = 進站 - 出站
      Positive (進站 > 出站) → 人從這裡出發，城市流出 → RED
      Near zero              → 接近平衡             → WHITE
      Negative (出站 > 進站) → 人抵達此地，城市流入 → BLUE

    Pass max_abs_override=1.0 when series is already a ratio (−1…+1) to avoid
    the floor clamp suppressing colours.
    """
    if max_abs_override is not None:
        max_abs = max_abs_override
    else:
        max_abs = float(series.abs().quantile(quantile))
        max_abs = max(max_abs, 1.0)

    colors = []
    for val in series:
        ratio = float(np.clip(val / max_abs, -1.0, 1.0))
        if ratio > 0:  # 進站多 → 人離開 → 流出 → RED
            r, g, b = 220, max(0, int(220 - ratio * 160)), max(0, int(220 - ratio * 160))
        else:          # 出站多 → 人抵達 → 流入 → BLUE
            r, g, b = max(0, int(220 + ratio * 160)), max(0, int(220 + ratio * 160)), 220
        colors.append([r, g, b, alpha])
    return colors


def radius_scale(series: pd.Series, min_r: float = 600, max_r: float = 9000) -> pd.Series:
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series([min_r] * len(series), index=series.index)
    return min_r + (series - lo) / (hi - lo) * (max_r - min_r)
