# 05 Top Repositories 深度分析

> 各專案完整筆記（含檔案路徑證據）在 `repo_notes/`：`TradingAgents.md`、`ai-hedge-fund.md`、`FinRobot.md`、`FinMem.md`、`FinCon.md`、`FinAgent.md`、`Qlib_RDAgent.md`、`FinRL_FinGPT.md`、`Other_LLM_Portfolio_Papers.md`（FINSABER、AlphaAgents、QuantAgent、StockAgent…）、`Memory_Reflection_Synthesis.md`、`Landscape_Scan.md`。
> 本檔為摘要，挑 9 個（含 1 個無程式碼但架構重要的 FinCon）。Fit/Reuse 為 1–5。

## 排名總覽

| 排名 | Repo | 類型 | Competition fit | Reuse | 一句話 |
|---|---|---|---|---|---|
| 1 | virattt/ai-hedge-fund (v2) | B | 3 | 4 | 最接近我們的骨架：LLM 觀點 → 程式化權重/限制/驗證/委託 + ledger |
| 2 | microsoft/qlib | B | 4 | 4 | 量化骨幹概念最完整：VWAP 成交、lot size、雙邊成本、TopkDropout |
| 3 | TauricResearch/TradingAgents | A(近 B) | 2 | 4 | 角色/辯論/PIT guard/typed schema/memory log 值得借；單股評等不適合直接用 |
| 4 | waylonli/FINSABER | A | 3 | 3 | 評估方法論與 audit 輸出格式；提醒 LLM alpha 易被偏誤放大 |
| 5 | HKUSTDial/DeepFund | A | 3 | 3 | 少數真正多股票 fund + anti time-travel + 決策 DB |
| 6 | skfolio / PyPortfolioOpt | B | 4 | 4 | Optimizer 元件（cardinality、成本、離散配置） |
| 7 | FinMem | A | 2 | 2 | 分層記憶概念；單股、無成本、有訓練期洩漏 |
| 8 | FinAgent | A | 2 | 2 | 雙層反思、工具增強；env 結構性未來資料風險 |
| 9 | FinCon（paper only） | A | 2 | 1 | manager-analyst 階層 + CVaR + CVRF；**無程式碼** |
| 10 | AI4Finance/FinRobot | C | 1 | 2 | 只借 numeric grounding 稽核模式 |

---

## 1. virattt/ai-hedge-fund（63.9k★，MIT，v2.5.0，2026-10-02）
- **Architecture**：v2 重寫為純 Python；LLM personas（Buffett、Munger 等投資風格）各自輸出 view ∈ [-1,1]。v1（tag `v2026.7.10`）為 LangGraph。
- **Data Flow**：Financial Datasets API（僅美股）→ analysts → `blend_signals` → `apply_limits` → `validate_targets` → orders → `brokers/sim.py`。
- **Decision Flow**：T 日收盤決策、T+1 收盤成交；賣先於買；整股。
- **Portfolio Logic**：觀點加權成目標權重；每檔上限與總曝險上限，**每次截斷都記錄**；`validate_targets` 從原始訊號重算一遍再下單。
- **Risk**：v1 `risk_manager`：基礎上限 20%，依年化波動（<15% ×1.25，以上遞減）與相關性（×0.7–1.1）調整，再受可用現金限制；v1 PM 由程式算出允許動作與最大數量，LLM 只能在範圍內選。
- **Memory**：無。**Backtest**：有，但零費用、零滑價、收盤成交。
- **Prompt**：persona prompts；v2 有 **blind mode**（隱藏 ticker、日期、金額，降低預訓練記憶影響）。
- **Strength**：LLM/程式分工清楚；限制截斷可稽核；hash-chained ledger。
- **Weakness**：無費稅、無整張(1000)、無檔數/現金下限、資料僅美股；persona 觀點不等於台股短週期 alpha。
- **Reuse**：**Adapt 架構模式**（不搬程式碼）：view→blend→limits→validate→orders、截斷記錄、ledger、blind mode。
- **Fit**：3/5。

## 2. microsoft/qlib（49.1k★，MIT，v0.9.7）
- **Architecture**：資料層（bin 格式）→ 特徵表達式 → 模型 → 策略 → executor → 回測/分析。
- **Data Flow**：需 `dump_bin.py` 轉入台股資料（無台股 loader）。
- **Portfolio Logic**：`TopkDropoutStrategy`（每期只換掉最差 n 檔，天然控制 turnover）；`EnhancedIndexingOptimizer`（相對 benchmark 偏離上限）。
- **Backtest**：`exchange.py` 支援 `deal_price="vwap"`、`trade_unit`（台股可設 1000）、`open_cost`/`close_cost` 分開（台股 0.001425 / 0.004425）、漲跌停處理。
- **Risk**：風險模型 + 優化器約束；無 Active Share 多基準。
- **Memory/Prompt**：無（非 LLM）。
- **Strength**：成交模型與本賽最接近；工業級。
- **Weakness**：安裝/資料轉換成本高；學習曲線陡；3 週內導入有風險。
- **Reuse**：**Adapt 概念**（VWAP 成交、TopkDropout、成本參數）；完整導入列為可選。也可作為我方 simulator 的交叉驗證。
- **Fit**：4/5。

## 3. TauricResearch/TradingAgents（109.7k★，Apache-2.0，v0.6.0，2026-10-03）
- **Architecture**：LangGraph：Market/Fundamentals/News/Social analysts → Bull/Bear researcher debate → Research manager → Trader → Risk debate（aggressive/neutral/conservative）→ Portfolio manager。
- **Data Flow**：yfinance/Alpha Vantage 等；`dataflows/date_window.py` 統一限制 tools 不得取得分析日之後的資料。
- **Decision Flow**：**一次一檔**，輸出 5 級評等（Buy…Sell）；`agents/rating.py` 無法解析 → `REVIEW`（不默默轉 Hold）。
- **Portfolio Logic**：**無**（無權重、現金帳、成本、限制）；`backtest.py` 明寫「不是組合模擬器，也不應長成組合模擬器」；README 所述「送到模擬交易所」無對應程式。
- **Memory**：新版改為 markdown 決策日誌：5 日後對 benchmark 結算，只回饋「執行日當時已知」的教訓（取代舊 BM25/ChromaDB）。
- **Backtest/Paper**：AAPL/GOOGL/AMZN 各自 2024/1–3 月，單次執行，無成本與部位大小；Sharpe 8.21 不具穩健性；Issue #805 提出預訓練記憶洩漏未回應；Issue #1156 提議 TWSE/TPEx 資料源（open）。
- **Strength**：角色分工清楚、PIT guard、typed schemas、可多 provider；維護非常活躍。
- **Weakness**：成本 ∝ 檔數 × 角色 × 回合；150 檔不可行；不處理組合。
- **Reuse**：**Adapt 模式**：date_window PIT、schemas + fallback、REVIEW 狀態、5 日結算 memory log、bull/bear → `counter_evidence`。只在 ≤10 檔 shortlist 上用輕量 debate。
- **Fit**：2/5。

## 4. waylonli/FINSABER（147★，Apache-2.0，v2.0.1，KDD 2026）
- **Architecture**：backtrader 為底的評估框架；重測 LLM 交易策略 2004–2024，使用歷史 S&P 500 成分（含下市股）。
- **發現**：FinMem、FinAgent 無顯著 alpha；牛市太保守（FinAgent Sharpe 0.12 vs 買進持有 0.61）、熊市太激進；建議 regime-aware 趨勢偵測與風控。
- **Audit**：輸出 config、manifest、orders、rejected orders、LLM costs → 我方 audit bundle 範本。
- **Reuse**：**方法論**（survivorship-free universe、長期多視窗、成本記錄）。**Fit** 3/5。

## 5. HKUSTDial/DeepFund（299★，MIT，NeurIPS 2025）
- 多股票 fund 競技場、live 評估以避免 time travel、DB 決策日誌。程式成熟度未完整驗證（僅頂層結構與 README）。
- **Reuse**：Pattern（live 評估、決策紀錄 schema）。**Fit** 3/5。

## 6. skfolio / PyPortfolioOpt / Riskfolio-Lib（Optimizer 元件）
- skfolio（BSD-3，v1.4.11）：cardinality、交易成本、walk-forward CV、sklearn API。
- PyPortfolioOpt（MIT，v1.6.0）：MV/Black-Litterman、`DiscreteAllocation`（需改成 1000 股一張）。BL 可以把 LLM 觀點當 views —— 但 24 日內共變異數估計雜訊大。
- Riskfolio（BSD-3）：大量風險量測、MIP cardinality。
- **Reuse**：Reuse/Adapt 作為 optimizer 的可選後端；MVP 先用規則式分層權重 + 投影，再評估是否值得引入。

## 7. FinMem（962★，MIT，最後 commit 2024-08）
- **Memory**：短/中/深三層；分數 = 相似度 + exp(−δ/Q) + importance/100，Q = 14/90/365 日（設定檔中短層實為 3.0）；importance 初值隨機；唯一學習訊號為持有部位 7 日 PnL（±1），提升被引用記憶的 importance；importance 60/80 時跨層移動。
- **問題**：單股、每日 1 股、無成本；train 模式 prompt 含次日價差；最佳結果（TSLA +61.78%）用 GPT-4-Turbo，cutoff 覆蓋測試期。
- **Reuse**：只借「記憶有時間衰減與被引用強化」概念。**Fit** 2/5。

## 8. FinAgent（DVampire/FinAgent，75★，MIT）
- 多模態（K 線圖）；low-level（市場訊號→價格）與 high-level（決策→結果）兩層反思；多 query 檢索；規則策略（MACD、KDJ+RSI、均值回歸）作為工具；XML 輸出；成本 0.1%。
- **問題**：單資產全進全出；env 載入 14 日未來資料再於各 prompt 模組過濾（結構性洩漏風險）。測試期 2023/6–2024/1 在模型 cutoff 之後（優點）。
- **Reuse**：「規則策略作為工具給 LLM 參考」與「決策→結果反思」概念。**Fit** 2/5。

## 9. FinCon（論文 NeurIPS 2024；repo 僅 README）
- 7 個 analyst → 1 manager；每日 CVaR 觸發風險趨避；CVRF 比較連續訓練 episode，將差異轉成文字「投資信念」，以決策重疊度作學習率（**只在訓練時**）。Portfolio 任務：LLM 給每檔方向，均值變異數決定權重（可負）。3 檔、GPT-4-Turbo cutoff 重疊。
- **無程式碼**（承諾 2026/2 起 3–4 個月釋出，至今未見）。
- **Reuse**：概念：「LLM 給方向、優化器給權重」與 CVaR 觸發的風險姿態。**Fit** 2/5。

## 10. FinRobot（8.1k★，Apache-2.0）
- 單一公司研究報告；`experiments/portfolio_optimization.py` 實為評估單一公司（PDD）的 AutoGen 對話；回測為單股 SMA 交叉、零成本。兩篇論文皆無交易績效驗證。V0 `functional/coding.py` 有 code-injection issue。
- **唯一借用**：`audit/narrative_numeric_grounding.py`（敘述段落必須引用數字）→ 對應 D-Plan「推論必須引用 observation」。**Fit** 1/5。

---

## 「README 很厲害但程式不完整 / 高星但只適合 Demo」直接點名
- **FinCon**：只有 README，無程式碼。
- **TradingAgents**：README 描述模擬交易所下單，無對應程式；論文績效樣本極小。
- **FinRobot**：檔名「portfolio_optimization」實為單公司對話。
- **HKUDS/AI-Trader（22.6k★）**：無 license，已轉為線上平台。
- **xbtlin/ai-berkshire（16.6k★）**：只有 prompts 與報告。
- **AutoHedge（6.2k★）**：少數檔案、無回測。
- **atlas-gic（2.3k★）**：績效宣稱與程式量不相稱。
- **backtrader（23k★）**：2023/4 後無 commit。
- **TradingAgents-CN（32k★）/ dexter（27.6k★）**：程式真實，但 license 混雜/缺失 → 不可複製程式碼。
