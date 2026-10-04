# 台股資料來源、可得時間與 VWAP 計算

> 撰寫日：2026-10-04（實際抓取驗證的日期標註在各項）。可信度：H = 官方端點已實際抓取；M = 官方說明或可靠二手；L = 論壇、部落格；Unknown = 未驗證。

## 1. 成交均價（VWAP）計算：已驗證

**TWSE（上市）**
- 端點（網站 RWD，可查歷史）：`https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=YYYYMMDD&stockNo=XXXX`，回傳**一檔股票一個月**的資料。
- 2026-10-04 實際抓取的 2330 2026/09 資料，fields 為：`["日期","成交股數","成交金額","開盤價","最高價","最低價","收盤價","漲跌價差","成交筆數","註記"]`〔H〕
- 範例：115/09/01，成交股數 31,855,287、成交金額 77,463,413,685，所以 VWAP = 77,463,413,685 ÷ 31,855,287 ≈ **2,431.73**，落在當日最低 2,390 與最高 2,440 之間，合理。〔H〕
- 一次取得全市場：`/exchangeReport/MI_INDEX?response=json&date=YYYYMMDD&type=ALLBUT0999` 是每日收盤行情，含各股成交股數與成交金額（欄位依網站慣例，本次未逐欄抓取 → M）。OpenAPI 的 `/v1/exchangeReport/STOCK_DAY_ALL`（上市個股日成交資訊）只回傳**最新一個交易日**（M），適合每日即時抓取；歷史資料要用網站 RWD 端點。
- **待確認：** STOCK_DAY 的成交股數是否只含「一般交易（整股、競價）」，而不含盤後定價、零股、鉅額交易。賽方「成交均價」的定義如果來自其他資料（例如券商報價的「均價」），可能與成交金額 ÷ 成交股數有些微差異。**請向賽方確認定義（Unknown）。**

**TPEx（上櫃）**
- OpenAPI：`https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes`（上櫃股票行情，最新交易日）。2026-10-04 實際抓取的欄位：`Date, SecuritiesCompanyCode, CompanyName, Close, Change, Open, High, Low, **Average**, TradingShares, TransactionAmount, TransactionNumber, LatestBidPrice, LatesAskPrice, Capitals, NextReferencePrice, NextLimitUp, NextLimitDown`〔H〕
- **TPEx 直接提供 `Average`（均價）欄位**，也可以用 TransactionAmount ÷ TradingShares 自行計算。範例 00411A：106,585,051 ÷ 9,948,068 ≈ 10.714，Average 欄位顯示 10.71（四捨五入）。建議自行計算，以保留精度，並與 Average 交叉核對。
- 歷史資料：TPEx 網站有個股日成交資訊（st43 系列）的 RWD 頁面，可依日期查詢（端點名稱未逐一驗證 → M）。

## 2. 官方資料端點與可得時間

| 資料 | 端點 | 已驗證欄位 | 公布時間（T 日） | 可信度 |
|---|---|---|---|---|
| 個股日成交（上市） | `twse.com.tw/exchangeReport/STOCK_DAY`、`MI_INDEX`；OpenAPI `STOCK_DAY_ALL` | 見上 | 收盤（13:30；盤後定價到 14:30）後陸續更新 | H（欄位）/ M（時間） |
| 三大法人個股（上市） | `twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALLBUT0999&response=json` | 2026/10/02 實際抓取：外陸資買進、賣出、買賣超（不含外資自營商）、外資自營商、投信、自營商（自行買賣、避險）、三大法人買賣超股數（**單位為股數**） | 業界說法「三點看總額、四點看個股」，約 15:00–16:30 | H（欄位）/ M-L（時間） |
| 三大法人（上櫃） | TPEx OpenAPI `tpex_3insti_daily_trading` | 摘要 | 盤後 | M |
| 融資融券（上市） | `twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=...&selectType=ALL&response=json` | 2026/10/02 抓取：信用交易統計，以及融資融券彙總（代號、名稱、融資買進、賣出、餘額等） | 晚間（業界常說約 21:00 → L） | H（端點）/ L（時間） |
| 融資融券（上櫃） | TPEx OpenAPI `tpex_mainboard_margin_balance` | 摘要 | 晚間 | M |
| 本益比、殖利率、淨值比 | TWSE OpenAPI `BWIBBU_ALL`；TPEx `tpex_mainboard_peratio_analysis` | 摘要 | 盤後 | M |
| 除權息結果 | `twse.com.tw/rwd/zh/exRight/TWT49U?startDate=...&endDate=...&response=json` | 2026/10/04 抓取：資料日期、代號、除權息前收盤價、參考價、權值+息值、權／息、漲跌停價、開盤競價基準、減除股利參考價等 | 除權息當日之前 | H |
| 除權息預告 | TWSE TWT48U（端點名稱依慣例，未抓取 → M）；TPEx OpenAPI `tpex_exright_prepost`、`tpex_exright_daily` | | 提前數週 | M |
| 股利分派 | TWSE OpenAPI `/opendata/t187ap45_L` | | | M |
| 月營收 | TWSE OpenAPI `/opendata/t187ap05_P`；TPEx `mopsfin_t187ap05_O`；MOPS 彙總靜態頁 `mopsov.twse.com.tw/nas/t21/sii/t21sc03_{民國年}_{月}_0.html`（上市；上櫃為 otc） | 2026/10/04 確認 115 年 8 月的頁面存在，頁首有「出表日期」，**沒有每家公司的公告時間** | 每月 10 日前（證交法第 36 條；逾期處 24 萬到 240 萬元罰鍰） | H（存在）/ M |
| 外資持股比例 | TWSE OpenAPI `/fund/MI_QFIIS_cat`、`MI_QFIIS_sort_20`；TPEx `tpex_3insti_qfii` | | 盤後 | M |
| 重大訊息、財報 | MOPS。2025-02-23 起新版在 `mops.twse.com.tw`，舊版移到 `mopsov.twse.com.tw`（工商時報 2025-01-13；TWSE 宣導 PDF） | | 即時（重訊有發言時間） | M |

**每家公司營收的公告時間：** 彙總表是會隨時間更新的快照。若需要精確的可得時間，有兩種做法：(a) 從 11/1 起每天（甚至每小時）抓取 t187ap05 或 t21sc03，記錄每家公司「第一次出現」的 fetched_at；(b) 抓 MOPS 的單一公司營收查詢頁或重訊（部分公司會另外發布重訊）。建議 (a)，作法最簡單也最穩健。

**TWSE 網站頻率限制：** 社群套件 twstock 的說明是「每 5 秒 3 個 request，超過會被封鎖 IP」（https://pypi.org/project/twstock/ ，L-M）。建議每次 request 間隔 2 秒以上、加上重試與退避，並且快取。OpenAPI（openapi.twse.com.tw）是政府開放資料，授權相對友善，但官方沒有公開頻率限制 → Unknown。

## 3. 期貨（TAIFEX）

- 盤後（夜盤）交易：臺股期貨（TX）、小型臺指（MTX）、微型臺指（TMF）、臺指選擇權（TXO）等，交易時間 **15:00 至次日 05:00**（收單從 14:50 開始）；16:15 收盤的商品則是 17:25 至 05:00。https://www.taifex.com.tw/cht/4/aHIntroduction 〔M-H，官方頁面經搜尋摘要確認〕
- 交易日歸屬：夜盤成交**歸屬於次一一般交易時段的交易日**（例如 8/17 15:00 到 8/18 05:00 歸屬 8/18；說明來自券商與 nstock 文章，與 TAIFEX 規定一致 → M）。有部落格寫成「歸屬同一天」，那是錯誤說法。
- 到期契約在最後交易日沒有夜盤。
- **用途：** 05:00 夜盤收盤價相對於前一日日盤收盤（13:45）的變動，是台股 T 日開盤缺口最好的公開領先指標之一。這個資料在 08:55 之前可以取得。資料來源：TAIFEX 網站的「期貨每日交易行情（盤後）」下載頁（具體端點未驗證 → M）。夜盤的流動性較日盤低。

## 4. 第三方資料

| 來源 | 涵蓋 | 限制、條款 | 可信度 |
|---|---|---|---|
| **FinMind** | 台股價格、三大法人、融資融券、月營收、財報、股利、新聞等 75 個以上資料集 | 官方價格頁 https://finmind.github.io/Pricing/ ：Free 每小時 300 次（註冊並驗證 email 後 600 次）、45 個資料集、**限非商業用途**；Backer NT$699/月，1,600 次/時；Sponsor NT$999/月，6,000 次/時、97 個資料集；Sponsor Pro NT$3,330/月，20,000 次/時，**唯一允許商業用途** | H |
| **TEJ** | 學術界標準資料庫：點時財報、調整股價、下市股票、法人資料 | 付費；學校通常有授權。是處理存活者偏誤與點時財報的最佳來源 | M |
| **yfinance** | `.TW`（上市）、`.TWO`（上櫃） | 非官方爬取 Yahoo，可能被限流或改版；台股的除權息與分割調整、成交量單位偶有錯誤或缺漏；**沒有成交金額欄位，所以無法計算 VWAP** | M（實務經驗與搜尋）|
| **Shioaji（永豐金）** | 即時報價、歷史 K 線與 tick | 必須是永豐客戶；歷史資料查詢只供測試，官方不鼓勵大量抓取；有每 5 秒次數上限（ithelp 文章所述的數字未能從官方文件驗證 → L）；訂閱上限約 200 檔 | L-M |
| **Goodinfo** | 彙整過的基本面與籌碼 | 服務條款頁 https://goodinfo.tw/tw/ServiceTerms.asp 回傳 403，**無法驗證條款內容**；該站以反爬聞名。另有法源控告 Lawsnote 爬取資料的判例（technews）。**建議不要爬取** | Unknown / L |
| **cnyes 鉅亨網新聞與 RSS** | 中文財經新聞 | RSS 端點與條款未驗證；時間戳需轉換時區 | Unknown |
| **美股（SOX、TSM ADR、NVDA 等）** | yfinance `^SOX`、`TSM`；或 Stooq、FRED、Nasdaq 官方 | 美股收盤為台灣 04:00（11/1 之前，夏令時間）或 05:00（11/1 之後） | M |

## 5. 主動式 ETF（計算 Active Share 用）

- 規範：投信必須在**每個營業日基金淨值結算後，於公司官網揭露當日實際投資組合**（全部持股與權重），一般在 T 日盤後到 T+1 開盤前可以看到。TWSE 市場觀察文章：https://www.twse.com.tw/market_insights/zh/detail/8a8216d697fc438f0198c55cfd800334 〔H〕。共同基金則只需要每月揭露前十大、每季揭露 1% 以上的持股（鉅亨網，M）。
- 代號規則：第 6 碼為「A」是股票型主動 ETF，「D」是債券型（TWSE 主動式 ETF 專區 https://www.twse.com.tw/zh/products/securities/etf/products/active-list.html ）。〔H〕該頁面的清單由 JavaScript 載入，抓取時沒有拿到列表。
- 規模：截至 2026 年 6 月底約 30 檔、總規模接近 9,000 億元（搜尋摘要，M-L）。2025/5/5 第一檔掛牌。
- 已知國內股票型主動 ETF（stockfeel 2026-07-21 排名，M；**清單不完整**）：00981A 主動統一台股增長、00403A 主動統一升級50、00991A 主動復華未來50、00982A 主動群益台灣精選強棒、00992A 主動群益台灣科技創新、00980A 主動野村臺灣優選；另有 00400A 主動國泰動能高息（出現在 MI_MARGN）、00411A 主動統一前沿科技（**上櫃**，出現在 TPEx 行情）。海外型（00988A、00990A、00997A）與台股 Active Share 的計算無關。
- **建議的取得流程：**
  1. 每天從 TWSE 的 ETF 清單（以及 TPEx 的 ETF 清單）篩選第 6 碼為 A、且投資國內股票的 ETF。
  2. 到各投信官網（統一、群益、復華、野村、國泰、元大等）抓取「每日持股／PCF（申購買回清單）」。各家格式不同，需要個別寫 parser。
  3. 投信投顧公會（SITCA）2024 年有建置 ETF 資訊入口專區的計畫（technews 2024-03-06），是否有集中提供主動 ETF 每日持股：Unknown。
  4. 取各 ETF 的前十大持股，與我們的組合計算 Active Share = ½ Σ|w_p − w_b|，並保存每日快照（帶 fetched_at）。
- 富果研究（https://blog.fugle.tw/post/active-etf-holdings-backtest ，M-L）用 300 多個交易日的 00981A 持股回測：隔日跟單相對 0050 的 5–20 日勝率只有約 47–49%，因為超額報酬多發生在經理人實際交易的當天、揭露之前。搭配外資同步買超與營收成長，勝率可提高到約 52–54%。**結論：主動 ETF 持股不是可靠的 alpha 來源，主要用於 Active Share 合規。**

## 6. 每日抓取時程建議（Asia/Taipei）

| 時間 | 抓取項目 |
|---|---|
| T-1 14:30–15:30 | STOCK_DAY_ALL、MI_INDEX、TPEx 行情（計算 T-1 的 VWAP 與收盤 NAV） |
| T-1 16:30–17:30 | T86、TPEx 三大法人；月營收快照（每月 1–10 日每小時抓一次） |
| T-1 17:00–19:00 | MOPS 重訊、主動 ETF 持股（若已更新）、除權息預告 |
| T-1 21:30–22:30 | 融資融券 |
| T 04:10 / 05:10 | 美股收盤、SOX、TSM ADR（11/1 前後時間不同） |
| T 05:05 | 台指期夜盤收盤 |
| T 07:30 | 重抓主動 ETF 持股與新聞，產生決策 |
| T 08:30 | 送出決策（截止 08:55） |
