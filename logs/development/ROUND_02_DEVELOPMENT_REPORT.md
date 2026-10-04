# ROUND 02 DEVELOPMENT REPORT — MVP-0 Quant / Deterministic Agent Core

日期：2026-10-05　｜　依公司政策：本報告與程式皆為 AI 產生，需人工審閱後使用。

## 1. 建立的檔案

**程式（agent/，56 個 .py，其中 44 個有內容、12 個為空的 `__init__.py`；約 4,070 行）**
- `agent/config.py`、`agent/pipeline.py`、`agent/run_daily.py`、`agent/run_sim.py`、`agent/README.md`
- `agent/engine/`：models, rules, fees, orders, active_share, compliance, validate_dplan
- `agent/sim/`：models, settle, metrics, calendar
- `agent/data/`：http, manifest, loaders, normalizers, pit, providers, fetchers/{twse, tpex, finmind, mops(stub), taifex(stub)}
- `agent/features/`：momentum, relative_strength, volume, volatility, institutional, revenue, feature_engine
- `agent/portfolio/`：ranking, baseline, constructor, decisions
- `agent/dplan/`：graph, builder, exporter, posture, funding
- `agent/llm/`：interfaces（EventExtractor/MarketNarrator/ThesisWriter/Reviewer + Template providers）、schemas（pydantic）
- `agent/tools/`：backfill.py、make_fixture.py

**設定（config/）**：competition.yaml（僅官方規則）、strategy.yaml（策略 buffer）、unconfirmed_rules.yaml（unknown + 模擬假設分離）、data_sources.yaml、universe_150.csv、active_etf_list.csv
**測試（tests/，10 個 test 檔 + conftest，約 910 行）**＋ fixtures：ex_context_042/043.json、raw_samples（4 個真實 API 回應）、synthetic/（合成 150 檔 × 391 日）
**其他**：requirements.txt、requirements-lock.txt、pytest.ini、.gitignore、DEVELOPMENT_STATUS.md、本報告
**資料**：data/raw/（264 日 × 4 來源原始回應 + manifest，約 575 MB）、data/history/*.parquet（2.3 MB）
**模擬**：sim_runs/W5_round02_{B0,B1,B2,B3}/、out/D-Plan_TEAM_TEST_2026-10-02.json

官方原始檔與 research/ 未修改（時間戳維持 09-30 / 研究輪）。

## 2. 安裝套件
`.venv`（Python 3.13.16）：pandas 3.0.6、numpy 2.5.3、pyarrow 25.0.1、requests 2.34.2、httpx 0.28.1、jsonschema 4.26.0、pydantic 2.13.5、PyYAML 6.0.3、pytest 9.1.1、python-dateutil 2.9.0（及其相依套件，見 requirements-lock.txt）。未安裝任何 Agent framework。

## 3. Phase 1 完成度：100%（以本輪範圍）
- 官方規則與策略 buffer、未確認規則三檔分離；RuleBook 載入 150 檔（驗證必為 150）與 30 檔 ETF。
- derive-orders.v2：Decimal floor（prec 50），含浮點陷阱測試（0.29×100,000 float=28.999… → 正確 29 張）。
- Fees：exact / round_half_up / floor / ceil。
- Active Share：NAV_WEIGHT / TOP10_NORMALIZED / FULL_PORTFOLIO / UNKNOWN(取最小值)，回傳 minimum、benchmark、各模式、缺資料 ETF；不宣稱何者為官方。
- Compliance report：rule_id / status / message / actual / limit / source。
- Validator：Schema + C1、ID（從 1 連續、不補零、不重複）、COVERAGE、ACTION、C2、C6（截止/窗口/提交時間）、PIT_CONTENT、C9/C11（T-1 收盤預估）、C12（流向+現金區間）、C13、C14（缺口存在性）、FILENAME、TEAM_ID、TRADE_DATE、UNIVERSE、LOT、Active Share；C3/C4/C5/C7/C8/C10 → NOT_IMPLEMENTED。
- **EX42**：全部已知規則 PASS（範例為節錄，C11 檔數標 NOT_APPLICABLE）。**EX43**：抓到 C1（D3→I9）、C2（2330 3000≠2000）、C12_FLOW（reduce 但淨買 +2,650,000）、C12_CASH（預估現金 3.750% ∉ [8%,15%]）——數字與官方 `_NOTE` 完全一致。

## 4. Phase 2 完成度：100%（以本輪範圍）
- settle.py：VWAP=成交金額/成交股數、買賣手續費、賣出證交稅、收盤 NAV、除息累積（不入現金，final 加回）、配股、無成交 skip/reject、拒收（超賣/非整張）視為未繳交、違規→警告+當日交易無效+以前一日組合計價、價格漂移 5 日寬限、加碼超限立即警告、3 警告 DQ、Active Share 連續 2 日 DQ、MDD 兩版、turnover。
- 3 日 golden test 逐元（含小數）對帳：Day1 NAV 9,977,569.43625、Day2 10,030,809.48625、Day3 9,988,619.11125 + 累積股息 5,000。
- golden test 抓到 1 個真 bug：MDD 期初值原本固定用官方 10 億 → 已改為 Settlement 攜帶 `initial_nav`。

## 5. Phase 3 完成度：約 70%
- 完成：TWSE MI_INDEX / T86、TPEx dailyQuotes / insti（皆實測成功）、FinMind 月營收；raw 快照 + manifest（source/url/fetched_at/content_as_of/published_at/available_at/sha256/parser_version/authority）；HistoryStore；PITView（available_at ≤ as_of 且 date ≤ as_of date，+08:00 強制）；LiveProvider / ReplayProvider 同一 interface；CSV/fixture loader。
- 回補：2025-09-01 ～ 2026-10-02，264 交易日、150 檔、0 錯誤；月營收 150 檔。
- 未完成：MOPS（stub）、TAIFEX（stub）、融資券、除權息、主動 ETF 真實持股、美股/ADR。

## 6. Phase 4 完成度：100%（v1 因子集）
ret_5d/20d/60d、relative_strength_20d/60d、volume_ratio_5d、volatility_20d、distance_to_52w_high、institutional_flow_5d/20d（以 ADV 正規化）、revenue_yoy/mom；市場廣度。資料不足 → NaN。輸出 features/scores parquet。

## 7. Phase 7 / 8 / 9 完成度
- **P7**：turnover-aware 選股（hold buffer、swap margin、每日新名額上限）、分層/等權、water-fill 上限、整張可行性（0 張剔除重選）、no-trade band、現金區間重平衡、Active Share 調整、決策 ≤30 限制；永遠回傳合法 TargetPortfolio 或 FallbackToPreviousPortfolio。
- **P8**：PreTrade（目標權重）、PostTradeEstimated（T-1 收盤預估持股/現金/權重/超賣/AS）、±5% 壓力測試（現金不為負且 <25%）；任何 FAIL → fallback。
- **P9**：Evidence Graph（Source/Fact/Signal/MarketView/Inference/Decision/NoTrade/Order）、語意 key → export 時重編號、文字中的 `{{fact:*}}` 佔位符換成實際 O-ID；posture 與 funding_for 由委託反推；quant-only 模板文字（數字皆來自 Fact 值）；驗證失敗時自動改產生 fallback D-Plan。

## 8. Tests 數量
78 個 test（10 個 test 檔）：engine 28、dplan 15、sim 12、data 9、features 6、portfolio 6、e2e 2（含 1 日閉環與完整 24 日合成競賽）。

## 9. Tests Passed / Failed
**78 passed / 0 failed**（`.venv\Scripts\python.exe -m pytest`，約 70–100 秒）。

## 10. 已知 Bug / 問題
- 無已知的規則邏輯 bug（MDD 期初值 bug 已修正）。
- 策略面：換手過高（W5 第 2 天起每日 13–27%），成本約 1–2% NAV/月。
- VWAP Decimal 28 位有效數字，跨運算順序有 <0.0001 元差異（測試以容差處理）；官方均價精度未知。
- data/raw 體積大（TPEx 全市場回應）。
- replay 的 metadata 使用模擬時鐘（T 07:00）並省略 fetched_at（真實抓取時間晚於歷史交易日）。

## 11. 無法確認的規則
NC-1 結算持股來源、NC-2 Active Share 定義、NC-3 C-code 處置、NC-4 無成交處理、NC-5 手續費捨入、NC-6 現金 25%／檔數端點、NC-7 配股、NC-8 MDD 期初、NC-9 賽中修 bug、NC-10 每日最後一次提交、NC-15 首個交易日、C12 預估是否含費用。全部參數化於 `config/unconfirmed_rules.yaml`。
補充證據：回補資料顯示 2025-10-24（週五，光復節 10/25 週六之補假）TWSE 無交易 → 2026-10-26（週一，10/25 週日）很可能休市。

## 12. 使用假資料的地方
- **主動 ETF 前 10 大持股：合成**（`make_fixture.py` 模板；real store 中 `synthetic=True`，報告訊息標示「benchmark 為合成資料」）→ 所有 Active Share 數字僅為機制測試。
- tests/fixtures/synthetic：150 檔合成價量、法人、營收（seed=42），D-Plan source 以 `file:///` + `[FIXTURE/SYNTHETIC]` 標示。
- ex_context_042/043：由官方範例 derivation_detail 反推之 context；2317/2412 股數與價格為佔位值。
- 月營收可得時間為假設（次月 10 日 23:59）。

## 13. 已成功測試的 API
| API | 結果 |
|---|---|
| TWSE `rwd/zh/afterTrading/MI_INDEX` | ✅ 264 日（需關閉 Python 3.13 VERIFY_X509_STRICT；仍驗證憑證鏈） |
| TWSE `rwd/zh/fund/T86` | ✅ |
| TPEx `afterTrading/dailyQuotes` | ✅ |
| TPEx `insti/dailyTrade` | ✅ |
| FinMind `TaiwanStockMonthRevenue` | ✅ 150 檔（免費額度、非商業條款） |
| FinMind `TaiwanStockPrice` | ✅ 單次驗證（備援，未用於回補） |
| MOPS / TAIFEX / 投信 ETF 持股 / 美股 | ❌ 未實作 |

## 14. 是否可以成功 end-to-end
**是。**
- `run_daily.py --date 2026-10-02 --mode replay`（真實資料）：25 檔、25 筆委託，Schema + 語意驗證 PASS。
- 合成 24 日競賽（pytest）與 25 日 CLI：0 驗證失敗、0 違規、0 fallback、NAV rollover 正確。
- W5 真實資料 23 日 × 4 baseline：全部 0 驗證失敗、0 違規、0 fallback；持股 24–25 檔、現金 3.1%–14.2%、Active Share 最小值（合成 benchmark）≥ 41%。

| W5 | 報酬 | MDD | 累計換手 | 費稅/本金 |
|---|---|---|---|---|
| B0 tiered | −2.21% | 7.28% | 400% | 1.01% |
| B1 equal | −0.64% | 7.40% | 377% | 0.95% |
| B2 momentum | −1.50% | 9.15% | 478% | 1.23% |
| B3 institutional | +4.75% | 2.50% | 679% | 1.90% |
| EW150 買進持有 | +3.75% | – | – | – |
單一視窗、樣本極小，不能據此選策略。

## 15. 下一輪建議
1. **策略穩定化（Phase 7.1）**：降低換手（分數平滑、最短持有天數、提高 swap margin、只在排名掉出 N+buffer 時賣出），並用 W1–W5 多視窗 + 隨機 baseline 評估，避免對單一視窗過擬合。
2. **資料補齊（Phase 3b）**：主動 ETF 真實持股 parser（先做台股型前幾大檔）、除權息（TWT49U/TPEx）、MOPS 營收 first-seen、TAIFEX 夜盤與美股收盤。
3. **營運**：git init + 乾淨工作樹才可執行（code_version=git sha）；live dry run；確認提交方式（NC-1）。
4. 以上完成後再進入 Phase 5（LLM 只改寫文字／事件抽取，經既有 interface）。
