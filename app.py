"""
台鐵人潮流動分析儀表板
Streamlit app — run with: streamlit run app.py
"""
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

from data_loader import (
    get_annual_stats,
    get_daily_national,
    get_holiday_dates,
    load_all_passenger_data,
    load_holidays,
    load_stations,
    net_flow_to_rgba,
    radius_scale,
)

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="台鐵人潮流動儀表板",
    page_icon="🚂",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* hide default streamlit header */
    [data-testid="stHeader"] { background: transparent; }
    /* section titles */
    .section-title {
        font-size: 1.8rem; font-weight: 700;
        background: linear-gradient(90deg, #2196F3, #00BCD4);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .section-sub { font-size: 0.9rem; color: #888; margin-bottom: 1.5rem; }
    /* metric cards */
    div[data-testid="metric-container"] {
        background: #1a1a2e; border-radius: 12px;
        padding: 0.8rem 1rem; border: 1px solid #2d2d4e;
    }
    /* legend row */
    .legend-row {
        display: flex; gap: 2rem; align-items: center;
        font-size: 0.85rem; padding: 0.4rem 0; color: #ccc;
    }
    .legend-dot {
        width: 14px; height: 14px; border-radius: 50%;
        display: inline-block; margin-right: 5px; vertical-align: middle;
    }
</style>
""", unsafe_allow_html=True)


# ── Load all data once ─────────────────────────────────────────────────────────

df = load_all_passenger_data()
holidays = load_holidays()
stations = load_stations()
df_annual = get_annual_stats(df)
df_national = get_daily_national(df)


# ── Sidebar navigation ─────────────────────────────────────────────────────────

st.sidebar.markdown("## 🚂 台鐵人潮分析")
st.sidebar.markdown("---")
page = st.sidebar.radio(
    "選擇分析主題",
    [
        "🗺  節假日流動地圖",
        "📈  車站 20 年趨勢",
        "🏙  區域流量比較",
        "🦠  COVID 衝擊觀察",
    ],
    label_visibility="collapsed",
)
st.sidebar.markdown("---")
st.sidebar.caption("資料來源：台灣鐵路管理局 每日各站進出站人次 2005–2026")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 ── 節假日流動地圖
# ══════════════════════════════════════════════════════════════════════════════

if page == "🗺  節假日流動地圖":
    st.markdown('<div class="section-title">🗺 節假日人潮流動地圖</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">探索三節連假期間，哪些車站人潮湧出、哪些車站迎接歸鄉人</div>', unsafe_allow_html=True)

    # Controls
    c1, c2, c3, c4 = st.columns([1.2, 1, 1.5, 1])
    with c1:
        holiday_type = st.selectbox("假期類型", ["春節", "端午", "中秋"])
    with c2:
        avail_years = sorted(holidays["year"].unique(), reverse=True)
        year = st.selectbox("年份", avail_years)
    with c3:
        view_mode = st.radio("顯示模式", ["單日地圖", "假期累計"], horizontal=True)
    with c4:
        # tkt_type 欄位儲存「對號/非對號」（由 supp_info 第 2 欄確認）
        show_tkt_only = st.checkbox("僅對號車站（大站）", value=False)

    holiday_dates = get_holiday_dates(holidays, year, holiday_type)
    if not holiday_dates:
        st.warning(f"找不到 {year} 年 {holiday_type} 假期資料")
        st.stop()

    # Date slider (single-day mode)
    selected_date = holiday_dates[len(holiday_dates) // 2]
    if view_mode == "單日地圖":
        date_options = [d.strftime("%m/%d") for d in holiday_dates]
        idx = st.select_slider(
            "滑動選擇假期日期",
            options=list(range(len(holiday_dates))),
            value=len(holiday_dates) // 2,
            format_func=lambda i: date_options[i],
        )
        selected_date = holiday_dates[idx]
        filter_dates = [pd.Timestamp(selected_date)]
    else:
        filter_dates = [pd.Timestamp(d) for d in holiday_dates]

    # Filter passenger data — aggregate on staCode only (avoids NaN-city groupby drop)
    mask = df["date"].isin(filter_dates)
    if show_tkt_only:
        mask &= df["tkt_type"] == "對號"

    agg = (
        df[mask]
        .groupby("staCode")[["in_count", "out_count", "net_flow"]]
        .sum()
        .reset_index()
    )
    sta_meta = stations[["staCode", "stationName", "lat", "lon", "city"]].drop_duplicates("staCode")
    day_data = agg.merge(sta_meta, on="staCode", how="left").dropna(subset=["lat", "lon"])

    if day_data.empty:
        st.warning("此日期無資料")
        st.stop()

    # Color = net flow ratio (淨流量 / 總人次)；radius = 總人次大小
    total_vol = day_data["in_count"] + day_data["out_count"]
    day_data["flow_ratio"] = (
        day_data["net_flow"] / total_vol.replace(0, np.nan)
    ).fillna(0)
    day_data["flow_ratio_pct"] = (day_data["flow_ratio"] * 100).round(1)
    day_data["color"] = net_flow_to_rgba(day_data["flow_ratio"])
    day_data["radius"] = radius_scale(total_vol, min_r=500, max_r=8000).values

    # Summary metrics
    # net_flow = 進站 - 出站：正值 → 進多出少 → 人在此出發（流出地）
    #                         負值 → 出多進少 → 人抵達此地（流入地/目的地）
    total_in = int(day_data["in_count"].sum())
    total_out = int(day_data["out_count"].sum())
    top_out_sta = day_data.loc[day_data["net_flow"].idxmax(), "stationName"]  # 最大正值 = 最多人離開
    top_in_sta = day_data.loc[day_data["net_flow"].idxmin(), "stationName"]   # 最大負值 = 最多人抵達

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("總進站人次", f"{total_in:,}")
    m2.metric("總出站人次", f"{total_out:,}")
    m3.metric("🔴 最大流出站（出發地）", top_out_sta)
    m4.metric("🔵 最大流入站（目的地）", top_in_sta)

    # PyDeck map
    layer = pdk.Layer(
        "ScatterplotLayer",
        data=day_data,
        get_position=["lon", "lat"],
        get_color="color",
        get_radius="radius",
        pickable=True,
        opacity=0.85,
        stroked=True,
        get_line_color=[255, 255, 255, 80],
        line_width_min_pixels=1,
    )

    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=23.7, longitude=121.0, zoom=7, pitch=0),
        tooltip={
            "html": (
                "<b style='font-size:1.1em'>{stationName}</b>"
                " <span style='color:#aaa'>({city})</span><br/>"
                "進站：<b>{in_count}</b> &nbsp; 出站：<b>{out_count}</b><br/>"
                "淨流量：<b>{net_flow}</b> &nbsp; 佔比：<b>{flow_ratio_pct}%</b>"
            ),
            "style": {
                "background": "rgba(10,10,30,0.9)",
                "color": "white",
                "padding": "10px",
                "border-radius": "8px",
                "font-size": "0.85rem",
            },
        },
        map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
    )

    st.pydeck_chart(deck, width="stretch")

    # Legend
    period_label = selected_date.strftime("%Y/%m/%d") if view_mode == "單日地圖" else f"{year} {holiday_type}全程"
    st.markdown(f"""
    <div class="legend-row">
        <span><span class="legend-dot" style="background:#DC3C3C"></span>🔴 淨流出（進站多，人從此出發）</span>
        <span><span class="legend-dot" style="background:#DCDCDC"></span>⚪ 接近平衡</span>
        <span><span class="legend-dot" style="background:#3C3CDC"></span>🔵 淨流入（出站多，人抵達此地）</span>
        <span style="margin-left:auto;color:#666">泡泡大小 = 總人次 ｜ 顏色深淺 = 淨流量佔比（%） ｜ 期間：{period_label}</span>
    </div>
    """, unsafe_allow_html=True)

    # Top stations table
    st.divider()
    col_out, col_in = st.columns(2)
    tbl_cols = ["stationName", "city", "in_count", "out_count", "net_flow"]
    tbl_rename = {"stationName": "車站", "city": "縣市", "in_count": "進站", "out_count": "出站", "net_flow": "淨流量(進-出)"}

    with col_out:
        st.markdown("#### 🔴 淨流出前 10（出發地：進多出少）")
        top_out = day_data.nlargest(10, "net_flow")[tbl_cols].rename(columns=tbl_rename)
        st.dataframe(top_out, hide_index=True, width="stretch")
        st.download_button(
            "⬇ 下載 CSV",
            top_out.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"{year}{holiday_type}_淨流出前10.csv",
            mime="text/csv",
            key="dl_out",
        )

    with col_in:
        st.markdown("#### 🔵 淨流入前 10（目的地：出多進少）")
        top_in = day_data.nsmallest(10, "net_flow")[tbl_cols].rename(columns=tbl_rename)
        st.dataframe(top_in, hide_index=True, width="stretch")
        st.download_button(
            "⬇ 下載 CSV",
            top_in.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"{year}{holiday_type}_淨流入前10.csv",
            mime="text/csv",
            key="dl_in",
        )

    # Flow balance bar chart
    st.divider()
    st.markdown("#### 各縣市淨流量總覽")
    city_flow = (
        day_data.dropna(subset=["city"])
        .groupby("city")["net_flow"]
        .sum()
        .reset_index()
        .sort_values("net_flow")
    )
    city_flow["color"] = city_flow["net_flow"].apply(
        lambda v: "#DC3C3C" if v < 0 else "#3C3CDC"
    )
    fig_bar = px.bar(
        city_flow,
        x="net_flow",
        y="city",
        orientation="h",
        color="net_flow",
        color_continuous_scale=["#DC3C3C", "#DCDCDC", "#3C3CDC"],
        color_continuous_midpoint=0,
        labels={"net_flow": "淨流量（進站－出站）", "city": "縣市"},
        template="plotly_dark",
    )
    fig_bar.update_layout(
        height=500,
        coloraxis_showscale=False,
        margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig_bar, width="stretch")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 ── 車站 20 年趨勢
# ══════════════════════════════════════════════════════════════════════════════

elif page == "📈  車站 20 年趨勢":
    st.markdown('<div class="section-title">📈 車站 20 年旅運趨勢</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">觀察單一車站從 2005 到 2026 的進出站人次變化，見證 COVID 的衝擊與復甦</div>', unsafe_allow_html=True)

    # ── 分層選站：先選縣市，再選車站 ──────────────────────────────────────
    city_list = sorted(stations["city"].dropna().unique())
    city_list_all = ["（全部縣市）"] + city_list
    sel_city = st.selectbox("選擇縣市", city_list_all, index=city_list_all.index("台北") if "台北" in city_list_all else 0)

    if sel_city == "（全部縣市）":
        sta_pool = sorted(stations["stationName"].dropna().unique())
    else:
        sta_pool = sorted(stations[stations["city"] == sel_city]["stationName"].dropna().unique())

    default_sta = "台北" if "台北" in sta_pool else (sta_pool[0] if sta_pool else None)
    if not sta_pool:
        st.warning("此縣市無車站資料")
        st.stop()
    default_idx = sta_pool.index(default_sta) if default_sta in sta_pool else 0
    selected_sta = st.selectbox("選擇車站", sta_pool, index=default_idx)

    sta_annual = df_annual[df_annual["stationName"] == selected_sta].sort_values("year")

    if sta_annual.empty:
        st.warning(f"找不到「{selected_sta}」的年度資料")
        st.stop()

    # KPIs — 排除 2026（年度未完整）再計算低谷年
    peak_row = sta_annual.loc[sta_annual["in_count"].idxmax()]
    sta_complete = sta_annual[sta_annual["year"] < 2026]
    low_row = sta_complete.loc[sta_complete["in_count"].idxmin()] if not sta_complete.empty else peak_row
    val_2026 = int(sta_annual[sta_annual["year"] == 2026]["in_count"].sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("歷史高峰年", str(int(peak_row["year"])), f"{int(peak_row['in_count']):,} 人進站")
    m2.metric("歷史低谷年（完整年）", str(int(low_row["year"])), f"{int(low_row['in_count']):,} 人進站")
    m3.metric("2026 進站（至 5 月）", f"{val_2026:,}")

    # Line chart: in / out per year
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=sta_annual["year"], y=sta_annual["in_count"],
        name="進站人次", mode="lines+markers",
        line=dict(color="#2196F3", width=2.5),
        marker=dict(size=6),
    ))
    fig.add_trace(go.Scatter(
        x=sta_annual["year"], y=sta_annual["out_count"],
        name="出站人次", mode="lines+markers",
        line=dict(color="#FF7043", width=2.5, dash="dot"),
        marker=dict(size=6),
    ))

    # COVID band
    fig.add_vrect(x0=2020, x1=2022.5, fillcolor="#FF5722", opacity=0.1,
                  annotation_text="COVID-19", annotation_position="top left",
                  line_width=0)

    fig.update_layout(
        template="plotly_dark",
        height=420,
        xaxis=dict(title="年份", dtick=1, tickangle=-30),
        yaxis=dict(title="年度人次"),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch")

    # Net flow trend
    fig2 = px.bar(
        sta_annual, x="year", y="net_flow",
        color="net_flow",
        color_continuous_scale=["#DC3C3C", "#DCDCDC", "#3C3CDC"],
        color_continuous_midpoint=0,
        labels={"net_flow": "年度淨流量", "year": "年份"},
        title=f"{selected_sta} — 年度淨流量（進站 − 出站）",
        template="plotly_dark",
    )
    fig2.update_layout(height=300, coloraxis_showscale=False, margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig2, width="stretch")

    with st.expander("查看年度明細資料"):
        show = sta_annual[["year", "in_count", "out_count", "net_flow"]].copy()
        show.columns = ["年份", "進站", "出站", "淨流量"]
        st.dataframe(show.set_index("年份"), width="stretch")
        st.download_button(
            "⬇ 下載 CSV",
            show.to_csv(index=False, encoding="utf-8-sig"),
            file_name=f"{selected_sta}_年度趨勢.csv",
            mime="text/csv",
        )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3 ── 區域流量比較
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🏙  區域流量比較":
    st.markdown('<div class="section-title">🏙 區域旅運流量比較</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">將車站依縣市分組，比較各地區在不同假期的人流走向</div>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns([1.3, 1.6, 1.1, 1.1])
    with c1:
        holiday_type_r = st.selectbox("假期類型", ["春節", "端午", "中秋"], key="r_htype")
    with c2:
        compare_years = st.multiselect(
            "比較年份（最多 5 年）",
            sorted(holidays["year"].unique(), reverse=True),
            default=[2024, 2019, 2020],
        )
        compare_years = compare_years[:5]
    with c3:
        agg_metric = st.radio("指標", ["淨流量", "進站人次", "出站人次"], horizontal=False, key="r_metric")
    with c4:
        period = st.radio("分析時段", ["整個假期", "假期首日", "假期末日"], horizontal=False, key="r_period")

    metric_col = {"淨流量": "net_flow", "進站人次": "in_count", "出站人次": "out_count"}[agg_metric]

    if not compare_years:
        st.info("請選擇至少一個年份")
        st.stop()

    # Build per-year, per-city aggregates for holiday period
    rows = []
    for yr in compare_years:
        dates = get_holiday_dates(holidays, yr, holiday_type_r)
        if not dates:
            continue
        if period == "假期首日":
            ts_dates = [pd.Timestamp(dates[0])]
        elif period == "假期末日":
            ts_dates = [pd.Timestamp(dates[-1])]
        else:
            ts_dates = [pd.Timestamp(d) for d in dates]
        sub = df[df["date"].isin(ts_dates)].dropna(subset=["city"])
        city_agg = sub.groupby("city")[["in_count", "out_count", "net_flow"]].sum().reset_index()
        city_agg["year"] = yr
        rows.append(city_agg)

    if not rows:
        st.warning("所選年份均無假期資料")
        st.stop()

    region_df = pd.concat(rows, ignore_index=True)
    region_df["year"] = region_df["year"].astype(str)

    # Grouped bar
    fig = px.bar(
        region_df,
        x="city",
        y=metric_col,
        color="year",
        barmode="group",
        color_discrete_sequence=px.colors.qualitative.Set2,
        labels={"city": "縣市", metric_col: agg_metric, "year": "年份"},
        title=f"{holiday_type_r} 假期 ─ 各縣市 {agg_metric} 年份比較",
        template="plotly_dark",
    )
    fig.update_layout(height=500, margin=dict(l=0, r=0, t=50, b=0),
                      xaxis_tickangle=-30, legend_title="年份")

    # Add zero line for net flow
    if metric_col == "net_flow":
        fig.add_hline(y=0, line_color="white", line_width=1, opacity=0.4)

    st.plotly_chart(fig, width="stretch")

    # Heatmap: city × year — follows selected metric
    heatmap_mid = 0 if metric_col == "net_flow" else None
    heatmap_scale = (
        ["#DC3C3C", "#111111", "#3C3CDC"] if metric_col == "net_flow"
        else "Blues"
    )
    st.markdown(f"#### 縣市 × 年份 {agg_metric} 熱力圖")
    pivot = region_df.pivot_table(index="city", columns="year", values=metric_col, aggfunc="sum")

    fig_heat = px.imshow(
        pivot,
        color_continuous_scale=heatmap_scale,
        color_continuous_midpoint=heatmap_mid,
        aspect="auto",
        labels={"color": agg_metric},
        template="plotly_dark",
    )
    fig_heat.update_layout(height=500, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig_heat, width="stretch")

    # Small-multiple top stations per region
    with st.expander("各縣市前 5 大淨流出／流入車站"):
        sel_year_detail = st.selectbox("選擇年份", compare_years, key="r_detail_year")
        dates_d = get_holiday_dates(holidays, sel_year_detail, holiday_type_r)
        if dates_d:
            ts_d = [pd.Timestamp(d) for d in dates_d]
            detail = df[df["date"].isin(ts_d)].dropna(subset=["city"])
            detail_agg = detail.groupby(["city", "stationName"])["net_flow"].sum().reset_index()

            cities = sorted(detail_agg["city"].dropna().unique())
            for city in cities:
                sub = detail_agg[detail_agg["city"] == city].sort_values("net_flow")
                if sub.empty:
                    continue
                st.markdown(f"**{city}**")
                col_l, col_r = st.columns(2)
                with col_l:
                    st.caption("淨流出前 5")
                    st.dataframe(sub.head(5)[["stationName", "net_flow"]].rename(
                        columns={"stationName": "車站", "net_flow": "淨流量"}), hide_index=True)
                with col_r:
                    st.caption("淨流入前 5")
                    st.dataframe(sub.tail(5).iloc[::-1][["stationName", "net_flow"]].rename(
                        columns={"stationName": "車站", "net_flow": "淨流量"}), hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4 ── COVID 衝擊觀察
# ══════════════════════════════════════════════════════════════════════════════

elif page == "🦠  COVID 衝擊觀察":
    st.markdown('<div class="section-title">🦠 COVID-19 衝擊與復甦</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">2020–2023 年間台鐵旅運量的斷崖式下跌，以及疫後的逐步回升</div>', unsafe_allow_html=True)

    # ── Full timeline ──────────────────────────────────────────────────────
    st.markdown("#### 全台每日旅運總量（2005–2026）")

    # Monthly average for clarity
    df_nat = df_national.copy()
    df_nat["year_month"] = df_nat["date"].dt.to_period("M").dt.to_timestamp()
    df_monthly = df_nat.groupby("year_month")["total"].mean().reset_index()
    df_monthly.columns = ["month", "avg_daily_total"]

    fig_timeline = go.Figure()
    fig_timeline.add_trace(go.Scatter(
        x=df_monthly["month"],
        y=df_monthly["avg_daily_total"],
        mode="lines",
        name="月均日旅運量",
        line=dict(color="#2196F3", width=2),
        fill="tozeroy",
        fillcolor="rgba(33,150,243,0.15)",
    ))

    # Annotate COVID period
    fig_timeline.add_vrect(
        x0="2020-01-21", x1="2023-05-01",
        fillcolor="#FF5722", opacity=0.12,
        annotation_text="COVID-19 衝擊期", annotation_position="top left",
        annotation_font_color="#FF8A65",
        line_width=0,
    )
    # 三級警戒：2021/05/19–07/26（最嚴峻的管制期）
    fig_timeline.add_vrect(
        x0="2021-05-19", x1="2021-07-26",
        fillcolor="#FF1744", opacity=0.28,
        line_width=1, line_color="#FF6D00", line_dash="dot",
        annotation_text="三級警戒", annotation_position="top right",
        annotation_font_color="#FF8A65", annotation_font_size=11,
    )

    fig_timeline.update_layout(
        template="plotly_dark",
        height=380,
        xaxis_title="月份",
        yaxis_title="日均旅客人次",
        margin=dict(l=0, r=0, t=20, b=0),
        hovermode="x unified",
    )
    st.plotly_chart(fig_timeline, width="stretch")

    # ── YoY comparison: same holiday ──────────────────────────────────────
    st.markdown("#### 同假期跨年比較（相同假日期間的全台旅運量）")

    c1, c2 = st.columns(2)
    with c1:
        holiday_type_c = st.selectbox("假期類型", ["春節", "端午", "中秋"], key="c_htype")
    with c2:
        years_range = st.slider("年份範圍", 2005, 2026, (2017, 2026))

    yoy_rows = []
    for yr in range(years_range[0], years_range[1] + 1):
        dates = get_holiday_dates(holidays, yr, holiday_type_c)
        if not dates:
            continue
        ts_dates = [pd.Timestamp(d) for d in dates]
        sub = df[df["date"].isin(ts_dates)]
        if sub.empty:
            continue
        total = int((sub["in_count"].sum() + sub["out_count"].sum()) / 2)
        avg_days = total / len(ts_dates)
        yoy_rows.append({"year": yr, "total_avg_daily": avg_days, "n_days": len(ts_dates)})

    if not yoy_rows:
        st.warning("無可比對資料")
        st.stop()

    yoy_df = pd.DataFrame(yoy_rows)
    yoy_df["covid"] = yoy_df["year"].isin([2020, 2021, 2022])

    fig_yoy = px.bar(
        yoy_df,
        x="year",
        y="total_avg_daily",
        color="covid",
        color_discrete_map={True: "#FF5722", False: "#2196F3"},
        labels={"total_avg_daily": "假期日均旅客（進＋出）/ 2", "year": "年份", "covid": "COVID 期間"},
        title=f"{holiday_type_c} 假期歷年日均旅運量",
        template="plotly_dark",
        text_auto=".3s",
    )
    fig_yoy.update_layout(
        height=400,
        showlegend=True,
        margin=dict(l=0, r=0, t=50, b=0),
        xaxis=dict(dtick=1, tickangle=-30),
    )
    st.plotly_chart(fig_yoy, width="stretch")

    # ── Per-station COVID drop ─────────────────────────────────────────────
    st.markdown("#### 各車站 2019 vs 2020 年進站量對比")
    show_tkt_covid = st.checkbox("僅對號車站（大站）", value=False, key="covid_tkt")
    _annual = df_annual[df_annual["tkt_type"] == "對號"] if show_tkt_covid else df_annual

    sta_2019 = _annual[_annual["year"] == 2019][["stationName", "city", "in_count"]].rename(
        columns={"in_count": "in_2019"}
    )
    sta_2020 = _annual[_annual["year"] == 2020][["stationName", "in_count"]].rename(
        columns={"in_count": "in_2020"}
    )
    covid_cmp = sta_2019.merge(sta_2020, on="stationName", how="inner")
    covid_cmp["drop_pct"] = (covid_cmp["in_2020"] - covid_cmp["in_2019"]) / covid_cmp["in_2019"] * 100
    # 縣市前綴，方便辨認
    covid_cmp["label"] = covid_cmp["city"].fillna("其他") + "｜" + covid_cmp["stationName"]
    covid_cmp = covid_cmp.sort_values("drop_pct")

    col_drop, col_keep = st.columns(2)

    with col_drop:
        st.markdown("##### 🔴 跌幅最大前 30 站")
        fig_drop = px.bar(
            covid_cmp.head(30),
            x="drop_pct",
            y="label",
            orientation="h",
            color="drop_pct",
            color_continuous_scale=["#B71C1C", "#EF5350", "#FFCDD2"],
            labels={"drop_pct": "人次變化 (%)", "label": "縣市｜車站"},
            template="plotly_dark",
        )
        fig_drop.update_layout(
            height=750, coloraxis_showscale=False,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_drop, width="stretch")

    with col_keep:
        st.markdown("##### 🟢 跌幅最小（最抗跌）前 30 站")
        top30_resilient = covid_cmp.nlargest(30, "drop_pct").sort_values("drop_pct", ascending=False)
        fig_keep = px.bar(
            top30_resilient,
            x="drop_pct",
            y="label",
            orientation="h",
            color="drop_pct",
            color_continuous_scale=["#E3F2FD", "#42A5F5", "#0D47A1"],
            color_continuous_midpoint=0,
            labels={"drop_pct": "人次變化 (%)", "label": "縣市｜車站"},
            template="plotly_dark",
        )
        fig_keep.update_layout(
            height=750, coloraxis_showscale=False,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_keep, width="stretch")

    dl_cols = covid_cmp[["label", "in_2019", "in_2020", "drop_pct"]].rename(
        columns={"label": "縣市｜車站", "in_2019": "2019進站", "in_2020": "2020進站", "drop_pct": "跌幅(%)"}
    )
    st.download_button(
        "⬇ 下載完整 2019 vs 2020 跌幅資料（CSV）",
        dl_cols.to_csv(index=False, encoding="utf-8-sig"),
        file_name="2019vs2020_各站跌幅.csv",
        mime="text/csv",
    )

    # Recovery tracker
    st.markdown("#### 旅運量恢復追蹤（以 2019 為基準 = 100）")
    ref_year = 2019
    annual_national = (
        df_annual.groupby("year")[["in_count", "out_count"]].sum().reset_index()
    )
    ref_val = annual_national.loc[annual_national["year"] == ref_year, "in_count"].values
    if len(ref_val) > 0:
        ref_in = ref_val[0]
        annual_national["index_val"] = annual_national["in_count"] / ref_in * 100
        fig_idx = px.line(
            annual_national[annual_national["year"] >= 2015],
            x="year",
            y="index_val",
            markers=True,
            labels={"index_val": f"旅運指數（{ref_year}=100）", "year": "年份"},
            template="plotly_dark",
        )
        fig_idx.add_hline(y=100, line_dash="dash", line_color="white", opacity=0.4,
                          annotation_text=f"{ref_year} 基準")
        fig_idx.add_vrect(x0=2020, x1=2022.5, fillcolor="#FF5722", opacity=0.1, line_width=0)
        fig_idx.add_vline(
            x=2021.39,  # ≈ 2021/05/19
            line_dash="dot", line_color="#FF6D00", line_width=1.5,
            annotation_text="三級警戒", annotation_position="top right",
            annotation_font_color="#FF8A65", annotation_font_size=10,
        )
        fig_idx.update_layout(height=360, margin=dict(l=0, r=0, t=20, b=0),
                               xaxis=dict(dtick=1))
        st.plotly_chart(fig_idx, width="stretch")

    # ── Bar Chart Race ─────────────────────────────────────────────────────────
    st.markdown("#### 歷年各站總運量排行榜動畫（Bar Chart Race）")
    st.caption("固定前 15 大車站，依年份動態排序。點擊「▶ 播放」或拖曳下方捲軸瀏覽各年度")

    bcr_df = df_annual.copy()
    bcr_df["total"] = bcr_df["in_count"] + bcr_df["out_count"]
    bcr_df = bcr_df[bcr_df["year"] < 2026]
    bcr_df["label"] = bcr_df["city"].fillna("其他") + "｜" + bcr_df["stationName"]

    # Use fixed cast: top 15 by cumulative total across all years
    top_stations = (
        bcr_df.groupby("stationName")["total"].sum()
        .nlargest(15).index.tolist()
    )
    bcr_sub = bcr_df[bcr_df["stationName"].isin(top_stations)].copy()
    years_bcr = sorted(bcr_sub["year"].unique())
    x_max = int(bcr_sub["total"].max() * 1.12)

    def _bcr_bar(yr_data):
        yr_data = yr_data.sort_values("total", ascending=True)
        return go.Bar(
            x=yr_data["total"],
            y=yr_data["label"],
            orientation="h",
            marker=dict(
                color=yr_data["total"].tolist(),
                colorscale="Blues",
                cmin=0,
                cmax=x_max,
                showscale=False,
            ),
            text=[f"{v/1e6:.2f}M" for v in yr_data["total"]],
            textposition="outside",
        )

    bcr_frames = [
        go.Frame(
            data=[_bcr_bar(bcr_sub[bcr_sub["year"] == yr])],
            name=str(yr),
            layout=go.Layout(title_text=f"台鐵各站年度總運量 Top 15 — {yr} 年"),
        )
        for yr in years_bcr
    ]

    fig_bcr = go.Figure(
        data=[_bcr_bar(bcr_sub[bcr_sub["year"] == years_bcr[0]])],
        frames=bcr_frames,
    )
    fig_bcr.update_layout(
        template="plotly_dark",
        height=600,
        title=f"台鐵各站年度總運量 Top 15 — {years_bcr[0]} 年",
        xaxis=dict(range=[0, x_max], title="年度進出站總人次"),
        yaxis=dict(title=""),
        margin=dict(l=0, r=40, t=70, b=70),
        updatemenus=[dict(
            type="buttons",
            showactive=False,
            y=1.10, x=0.0, xanchor="left",
            buttons=[
                dict(
                    label="▶ 播放",
                    method="animate",
                    args=[None, dict(
                        frame=dict(duration=800, redraw=True),
                        fromcurrent=True,
                        transition=dict(duration=300, easing="linear"),
                    )],
                ),
                dict(
                    label="⏸ 暫停",
                    method="animate",
                    args=[[None], dict(
                        frame=dict(duration=0, redraw=False),
                        mode="immediate",
                        transition=dict(duration=0),
                    )],
                ),
            ],
        )],
        sliders=[dict(
            steps=[
                dict(
                    args=[[str(yr)], dict(
                        frame=dict(duration=800, redraw=True),
                        mode="immediate",
                        transition=dict(duration=300),
                    )],
                    label=str(yr),
                    method="animate",
                )
                for yr in years_bcr
            ],
            active=0,
            currentvalue=dict(prefix="年份：", visible=True, xanchor="center"),
            transition=dict(duration=300, easing="linear"),
            x=0, y=0, len=1.0,
            pad=dict(t=10, b=10),
        )],
    )
    st.plotly_chart(fig_bcr, width="stretch")
