# 06 Reuse vs Build Matrix

> **Reuse**＝直接用現成套件/函式庫；**Adapt**＝借架構/模式或改寫少量開源程式（注意 license）；**Build**＝自建；**Avoid**＝不要採用的做法或專案。
> 原則：凡是會被主辦方以公式重算的部分（orders、現金、權重、Active Share、NAV）一律 **Build**，因為必須逐元/逐位元對齊官方規則，沒有任何開源專案符合。

| 模組 | 判定 | 來源/參考 | 理由 |
|---|---|---|---|
| **Data Layer** | Adapt + Build | 官方 TWSE/TPEx OpenAPI 與網站端點（直接 HTTP）、FinMind（備援，注意免費額度與非商業條款）、twstock（備援）；Avoid：Goodinfo 爬蟲、yfinance 作為 VWAP 來源（無成交金額） | PIT manifest、`data/raw/YYYYMMDD/`、發布時間戳必須自建；資料抓取可用現成 client |
| **Quant Engine（特徵/分數）** | Build（Reuse pandas/numpy） | 參考 Qlib 表達式與因子定義；TradingAgents `date_window` PIT 防護模式 | 因子少（10–20 個）、需台股特有（月營收、三大法人）；導入 Qlib 成本 > 效益 |
| **LLM Research（事件/新聞抽取）** | Build（Reuse LLM SDK + pydantic/JSON schema） | TradingAgents typed schemas + REVIEW fallback；ai-hedge-fund blind mode；Glasserman & Lin 匿名化 | 輸出必須是受控 schema、可被 D-Plan 引用 |
| **Market Agent（regime / market_view）** | Build | 規則式 regime（隔夜 SOX/ADR/夜盤/大盤趨勢/波動）+ LLM 撰寫 logic/counter_evidence | C12 posture 必須由程式反推；FINSABER 顯示 LLM 擇時不可靠 |
| **Equity Agent（個股 thesis）** | Adapt | TradingAgents bull/bear → `logic` + `counter_evidence`（輕量、僅 shortlist） | 只寫文字；refs 受控 |
| **Event Agent（月營收/財報/重訊/法說）** | Build | MOPS 資料 + LLM 抽取重訊文字；數值驚奇由程式計算 | 月營收是最強台股特有訊號（`raw_notes/short_horizon_evidence.md`） |
| **Portfolio Manager（決策分類、換股邏輯）** | Adapt | ai-hedge-fund v2：view→blend→apply_limits(記錄截斷)→validate_targets；Qlib TopkDropout | 我方加入整張、費稅、檔數、現金、no-trade band |
| **Portfolio Optimizer** | Build（規則式）→ 可選 Reuse skfolio/PyPortfolioOpt/cvxpy | skfolio（cardinality + cost）、PyPortfolioOpt（DiscreteAllocation 需改 lot=1000） | MVP 先規則式（可解釋、穩定）；24 日共變異數估計雜訊大 |
| **Risk Engine** | Build | ai-hedge-fund v1 波動/相關調整上限；FinCon CVaR 觸發概念；Daniel & Moskowitz 動能崩盤條件 | 需與規則（10%/25%/現金/價格漂移 5 日寬限）整合 |
| **Memory** | Build（極簡） | TradingAgents 5 日結算 memory log；FinMem 衰減概念；tradememory-protocol audit trail | 只做決策日誌、thesis 追蹤、預測-結果、短期事件記憶；Avoid 向量資料庫/長期層 |
| **Backtest** | Build（自建 simulator）+ 可選 Reuse bt/Qlib 交叉驗證 | Qlib exchange（VWAP、lot、雙邊成本）概念；FINSABER 輸出格式 | 必須 = 主辦方結算規則；開源回測框架皆不支援除息累積、警告/DQ 規則 |
| **Competition Engine** | Build | — | 規則專屬（derive-orders.v2、C1–C14、警告計數） |
| **NAV Simulator** | Build | — | 逐元對帳；除息延後入帳；四捨五入參數化 |
| **Active Share** | Build | — | 30 檔主動 ETF 前 10 大、多解讀取最小值；無任何現成實作 |
| **Compliance** | Build | — | 時間窗、150 檔、檔數、權重、現金、主題一致性、提交次數 |
| **D-Plan** | Build（Reuse `jsonschema`） | 官方 schema v4.2；FinRobot numeric grounding 概念 | Evidence graph → export → 重新編號；schema + 語意驗證 |
| **Trade Book（orders）** | Build | 官方 derive-orders.v2 | 必須逐位元相同 |
| **Logging / Audit** | Adapt | ai-hedge-fund hash-chained ledger；FINSABER manifest；DeepFund 決策 DB | append-only JSONL + sha256 chain；每日 audit bundle；git sha 為 code_version |
| **Agent Framework** | 暫不採用（可選 LangGraph / Google ADK / pydantic-ai） | — | 流程是固定 DAG，純 Python 已足夠；框架增加版本漂移與除錯成本。若需要 checkpoint 再評估 |
| **Multi-agent debate on 150 檔** | **Avoid** | TradingAgents 全流程 | 成本與時間不可行；評等不等於權重 |
| **RL（FinRL/TensorTrade）** | **Avoid** | — | 需大量訓練、可解釋性差、與 D-Plan 證據鏈不合 |
| **Online CVRF / 長期記憶學習** | **Avoid** | FinCon、FinMem | 24 日無足夠 episode |
| **LLM 直接輸出權重或股數** | **Avoid** | — | 數值不可靠、違反 C2/C12 風險 |
| **複製無 license / 混合 license 程式碼** | **Avoid** | dexter、AI-Trader、TradingAgents-CN、AGPL/GPL 專案 | 智財與審查風險（晉級需繳程式碼） |

## 總結
- **直接 Reuse**：pandas/numpy/pyarrow、jsonschema、pydantic、HTTP client、LLM 官方 SDK、（可選）skfolio/PyPortfolioOpt/cvxpy、FinMind client。
- **Adapt（借模式）**：ai-hedge-fund v2 組合管線與 ledger、TradingAgents PIT guard/schemas/memory log/debate→counter_evidence、Qlib 成交與 TopkDropout、FINSABER 評估與 audit 輸出、FinRobot numeric grounding。
- **一定 Build**：Competition Engine、NAV Simulator、Active Share、Compliance、derive-orders、D-Plan export/validator、PIT data manifest、台股特有因子（月營收、法人）、Evidence Graph。
