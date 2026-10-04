# 08 MVP 開發路線規劃

> 前提：採 `07_AGENT_ARCHITECTURE_RECOMMENDATION.md` 的 Hybrid Quant + LLM、Evidence-Graph-first 架構。
> 時程壓力：今天 2026-10-04，策略說明文件 10/21 起繳交，初賽 10/26 開始 → **約 3 週**。因此排序原則是「先保證每天能合法提交，再追求報酬」。
> 本輪不開發；以下為下一輪起的計畫。各 Phase 可部分平行，但 Phase 1–2 是所有後續的驗證基礎。

## 總覽與關鍵路徑

```
P1 Competition Engine ─► P2 Portfolio/NAV Simulator ─┐
P3 Market Data Pipeline ─► P4 Quant Features ────────┼─► P7 Portfolio Manager ─► P8 Risk+Compliance ─► P9 D-Plan+Trade Book ─► P11 Walk-forward
                           P5 Research Agents (LLM) ─► P6 Signal Fusion ─┘                                   ▲
                                                                          P10 Memory/Reflection ─────────────┘
```
**MVP-0（最低可提交版，目標 10/18）**：P1+P2+P3(價量/法人)+P4(少量因子)+P7(規則式)+P8+P9 —— quant-only，LLM 只寫文字欄位。
**MVP-1（目標 10/23）**：加入 P5/P6 事件與新聞、P10 決策日誌、P11 至少 2 個視窗。

---

### Phase 1 — Competition Engine（規則核心）
- **Goal**：把官方規則寫成純函式庫：derive-orders.v2、費稅、限制檢查、Active Share、D-Plan schema + 語意驗證（C1–C14）。
- **Inputs**：01/02 規則萃取、`D-Plan.schema_v4.2.json`、150 檔清單、30 檔主動 ETF 清單。
- **Outputs**：`engine/rules.py`、`engine/orders.py`、`engine/validate_dplan.py`、`engine/active_share.py`、單元測試。
- **Dependencies**：無。
- **Validation**：EX42 通過、EX43 檢出 C1 斷鏈與 C2 不符；手算案例；property-based tests（隨機組合）。
- **Done Criteria**：所有已知 C 檢查有測試；Decimal 精度；可 CLI 驗證任一 D-Plan 檔。

### Phase 2 — Portfolio / NAV Simulator
- **Goal**：重現主辦方結算：VWAP 成交、費稅、收盤 NAV、除息累積、警告/DQ、MDD、turnover。
- **Inputs**：D-Plan、前日 settlement、T 日價量。
- **Outputs**：`sim/settle.py` → `settlement_T.json`；`sim/metrics.py`。
- **Dependencies**：P1。
- **Validation**：golden 3 日案例逐元對帳；與 P1 的限制檢查一致；參數化四捨五入/無成交處理。
- **Done Criteria**：可跑任意長度序列；輸出每日 NAV、警告、指標。

### Phase 3 — Market Data Pipeline（PIT）
- **Goal**：抓取並快照 T-1 19:30～T 08:55 可得資料，建立 `data/raw/YYYYMMDD/` + manifest；歷史 backfill；PITView。
- **Inputs**：TWSE/TPEx OpenAPI（日成交、成交金額/股數、三大法人、融資券）、MOPS（月營收、重訊）、TAIFEX 夜盤、美股/SOX/ADR（vendor）、主動 ETF 持股、交易日曆、除權息表。
- **Outputs**：`data/raw/…`、`data/history/…`（Parquet）、`pit.py`。
- **Dependencies**：無（可與 P1 平行）。
- **Validation**：資料完整率、與官方網頁抽樣比對、金絲雀未來資料測試、時間戳單調。
- **Done Criteria**：W1/W5 歷史可完整 replay；live 模式每日 < 10 分鐘完成抓取；失敗有 fallback。

### Phase 4 — Quant Feature Engine
- **Goal**：150 檔 cross-sectional 特徵與分數：動能（5/20/60 日）、短期反轉、相對強弱、52 週高、成交量變化、波動、法人買賣超（外資/投信 1/5/20 日）、融資變化、月營收 YoY/MoM 與驚奇、產業動能、隔夜美股/ADR 敏感度（beta to SOX）。
- **Inputs**：P3 PITView。
- **Outputs**：`features/YYYYMMDD.parquet`（每檔 × 特徵）、每個特徵可轉成 observation（含 values）。
- **Dependencies**：P3。
- **Validation**：無 look-ahead 單元測試；歷史 IC/Rank IC（多視窗）；分位數報酬。
- **Done Criteria**：每日自動產生；特徵定義文件化；IC 報告。

### Phase 5 — Research Agents（LLM）
- **Goal**：只做 LLM 擅長的事：新聞/重訊/法說事件抽取（structured）、事件對個股方向與時效判斷、市場 regime 敘述、候選標的 thesis 與 counter-evidence 撰寫。
- **Inputs**：P3 文字資料（已 PIT 過濾）、P4 facts（以 ID 提供）。
- **Outputs**：`EventFact`（JSON schema 驗證）、`Thesis`（引用受控 fact IDs）、LLM call log（prompt、response、model、tokens、latency）。
- **Dependencies**：P3、P4。
- **Validation**：抽樣人工審閱（開發期）；引用 ID 全部有效；數字欄位 0 由 LLM 產生；prompt injection 測試。
- **Done Criteria**：每日 LLM 成本與時間在預算內；失敗時可略過（fallback）。
- **注意**：只有 2–3 個角色（Market/Event/Thesis writer），**不做 10+ 個 sub-agent**。

### Phase 6 — Signal Fusion
- **Goal**：把 quant 分數與 LLM 事件分數融合成每檔 expected-alpha 分數（規則式加權或 rank-average；LLM 事件只做有界調整，例如 ±1 個分位）。
- **Inputs**：P4、P5。
- **Outputs**：`scores/YYYYMMDD.parquet`、融合紀錄（每檔分數組成）。
- **Dependencies**：P4、P5。
- **Validation**：ablation（有/無 LLM）；IC 比較；分數穩定度（避免日日大換股）。
- **Done Criteria**：權重固定、版本化；可解釋每檔分數來源。

### Phase 7 — Portfolio Manager / Optimizer
- **Goal**：由分數產生 target weights：選 20–30 檔（建議 24–27 檔留緩衝）、2330 ≤ 23.5%、其他 ≤ 8.5–9%、現金目標 3–12%、產業上限、turnover penalty、no-trade band、Active Share ≥30%（多解讀）、整張可行性（每檔 ≥1 張）。
- **Inputs**：P6 分數、前日 settlement、T-1 收盤價、ETF 持股、regime。
- **Outputs**：`TargetPortfolio`（含約束報告）。
- **Dependencies**：P1、P6。
- **Validation**：約束 100% 滿足；與 baseline B2/B3 對照；最壞價格漂移壓測。
- **Done Criteria**：任何輸入下都能輸出可行解，否則 fallback 到「維持前日組合」。
- **實作**：先規則式（rank → 分層權重 → 投影到約束），再視時間加 cvxpy/PyPortfolioOpt 類二次規劃。

### Phase 8 — Risk + Compliance
- **Goal**：pre-trade 硬檢查（全部規則 + Active Share + 主題一致性 + 時間窗）、post-trade 預估（以 T-1 收盤與 VWAP 情境）、價格漂移 5 日寬限追蹤、警告計數。
- **Inputs**：P7 輸出、P1 規則。
- **Outputs**：`ValidationReport`；若失敗→自動修正（降權/補檔）或 fallback。
- **Dependencies**：P1、P7。
- **Validation**：故意違規的測試組合全數被擋。
- **Done Criteria**：0 違規提交（模擬 24 日 × 多視窗）。

### Phase 9 — D-Plan + Trade Book
- **Goal**：Evidence graph → 篩選被引用節點 → 重新編號 → D-Plan JSON；orders by derive-orders.v2；posture 與 funding_for 由程式反推；schema + 語意驗證；檔名規約；提交模組。
- **Inputs**：P4 facts、P5 theses、P7/P8 結果。
- **Outputs**：`out/D-Plan_<team>_<date>.json`、提交回執、本地 audit bundle（raw snapshot hash、log、config）。
- **Dependencies**：P1、P7、P8（P5 可選）。
- **Validation**：100% 通過自建 validator；人讀檢查文字品質（開發期）。
- **Done Criteria**：一鍵執行 `run_daily --date T` 產生合法 D-Plan；另支援由 Agent 產生「ETF 投資策略說明文件」（10/21–10/26）。

### Phase 10 — Memory / Reflection
- **Goal**：短期、實用的記憶：決策日誌（每檔 thesis、進場日、理由、目標/停損條件）、預測-結果追蹤（thesis 是否兌現）、事件記憶（已處理過的新聞避免重複反應）、規則化反思（例如某類訊號近期 IC 轉負 → 預先定義的降權規則）。
- **Inputs**：歷次 D-Plan、settlement、價格。
- **Outputs**：`memory/decision_log.parquet`、`memory/thesis_tracker.json`、每日反思摘要（LLM，僅作為下一日 thesis 的 context，不得改寫數值規則）。
- **Dependencies**：P9。
- **Validation**：反思不改變硬約束；記憶內容全部有時間戳且 ≤ cutoff。
- **Done Criteria**：thesis 連續性可在 D-Plan inference 中被引用（以 observation 形式，例如「持有 8 日報酬 +4.2%」）。
- **注意**：自主性 —— 反思機制必須事先設計、自動執行；不得人看結果後手改方向。

### Phase 11 — Walk-forward Simulation
- **Goal**：依 `09_PRECOMPETITION_TEST_PLAN.md` 跑多視窗 24 日完整競賽重演、baseline 比較、故障演練、dry run。
- **Inputs**：全部 Phase。
- **Outputs**：`sim_runs/…`、比較報告、凍結版本 v1.0。
- **Dependencies**：P1–P9（P10 可選）。
- **Validation**：0 違規、0 提交失敗、quant+LLM ≥ quant-only（W5）、報酬優於隨機 baseline 中位數。
- **Done Criteria**：10/25 前凍結 code_version 並完成 2 次 live dry run。

---

## 建議的程式庫結構（下一輪建立）

```
agent/
  engine/     rules, orders(derive-orders.v2), fees, active_share, validate_dplan
  sim/        settle, metrics, calendar
  data/       fetchers/, pit.py, manifest
  features/   momentum, flows, revenue, overnight, ...
  llm/        clients (provider-agnostic), prompts/ (versioned), schemas/
  research/   event_extractor, market_view_writer, thesis_writer
  portfolio/  fusion, optimizer, decisions
  dplan/      graph, export, posture, funding
  memory/     decision_log, thesis_tracker, reflection
  run_daily.py / run_sim.py
config/       strategy.yaml (frozen params), universe.csv, etf_list.csv
data/raw/YYYYMMDD/ … (gitignored, 另以 hash 清單入版控)
logs/YYYYMMDD/ … (LLM I/O, run log)
```

## 套件（最小集合，下一輪需經同意再安裝）
`pandas`, `numpy`, `pyarrow`, `requests`/`httpx`, `jsonschema`, `pydantic`, `pytest`；可選 `cvxpy` 或 `PyPortfolioOpt`（optimizer）、LLM SDK（擇一）。不安裝大型 agent framework 直到 P5 證明需要。
