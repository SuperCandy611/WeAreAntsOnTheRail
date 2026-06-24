# 🚂 台鐵人潮流動分析儀表板

互動式視覺化 Streamlit app，探索台灣鐵路 2005–2026 年的每日進出站人次。
從三節連假的城鄉遷徙，到 COVID-19 對各車站的衝擊，用圖表說故事。

**[➡ 前往 App](https://weareantsontherail.streamlit.app/)**

---

## 功能介紹

| 分頁 | 說明 |
|------|------|
| 🗺 **節假日流動地圖** | 地圖泡泡呈現各站淨流量，看春節 / 端午 / 中秋的人潮如何流動 |
| 📈 **車站 20 年趨勢** | 選一個站，觀察 2005–2026 年進出站量的長期變化 |
| 🏙 **區域流量比較** | 跨年份比較各縣市假期旅運量，含熱力圖與分析時段篩選 |
| 🦠 **COVID 衝擊觀察** | 疫情前後對比、各站跌幅排行、Bar Chart Race 動畫 |

---

## 更新紀錄

### v1.1 — 2026-06-24（期末報告後回饋修改）

根據口頭報告觀眾回饋進行以下優化：

- **🗺 節假日流動地圖**：地圖泡泡顏色改以「淨流量佔比（%）」著色（原為絕對淨流量）。泡泡大小代表總流量規模，顏色深淺代表單向性強弱，兩者資訊互補、不重疊。Tooltip 同步顯示佔比數值。
- **🦠 COVID 衝擊觀察**：在全台旅運量時間軸與恢復追蹤圖中，新增標示「三級警戒」期間（2021/05/19–07/26），呈現台灣管制最嚴峻時的旅運斷崖。
- **CSV 下載功能**：各分頁關鍵表格新增「⬇ 下載 CSV」按鈕，方便匯出資料自行分析：
  - 節假日流動地圖：淨流出 / 流入前 10 站
  - 車站 20 年趨勢：年度明細
  - COVID 衝擊觀察：2019 vs 2020 全站跌幅完整資料

---

## 資料來源

| 資料集 | 來源 | 時間範圍 |
|--------|------|----------|
| 每日各站進出站人數 | [台灣鐵路管理局 / 政府開放資料平台](https://data.gov.tw) | 2005–2026 |
| 車站基本資料集（含 GPS） | 台灣鐵路管理局 | 現況 |
| 三節連假 / 暑假日期 | 手工整理 | 2005–2026 |
| 車站縣市 / 對號分類 | 手工整理（`supp_info.csv`） | 全站 |

---

## 本機執行

### 1. 安裝相依套件

```bash
pip install -r requirements.txt
```

### 2. 啟動 app

```bash
streamlit run app.py
```

開啟瀏覽器前往 `http://localhost:8501`

> **Windows 使用者**：如果有虛擬環境，先啟動再執行：
> ```powershell
> & "path\to\your\venv\Scripts\Activate.ps1"
> streamlit run app.py
> ```

---

## 部署到 Streamlit Cloud

1. 將此 repo push 到 GitHub（含 `data/` 資料夾）
2. 前往 [share.streamlit.io](https://share.streamlit.io)，登入後點 **New app**
3. 選擇 repo、branch，Main file path 填 `app.py`
4. 點 **Deploy** — 完成！

---

## 技術棧

- [Streamlit](https://streamlit.io) — 主框架
- [Plotly](https://plotly.com/python/) — 互動圖表、Bar Chart Race 動畫
- [PyDeck](https://deckgl.readthedocs.io) — 地圖視覺化
- [pandas](https://pandas.pydata.org) — 資料處理

---

## 專案結構

```
final_project/
├── app.py                # 主程式（四個分頁）
├── data_loader.py        # 資料載入與前處理
├── requirements.txt
├── data/
│   ├── 每日各站進出站人數*/   # 台鐵原始資料
│   ├── 車站基本資料集.json
│   ├── supp_info.csv          # 車站縣市 / 對號分類（自行整理）
│   └── taiwan_holidays_*.csv  # 連假日期（自行整理）
└── 開發歷程紀錄.md
```
