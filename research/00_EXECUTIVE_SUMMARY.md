# 00 Executive Summary — AI CUP 2026 玉山 Agent 基金經理人（研究輪 v1，2026-10-04）

> 本文件為 AI 產生之研究摘要，依公司政策須經人工審閱後使用。細節見 01–11 與 `repo_notes/`、`raw_notes/`。

## 1. 這場競賽真正的技術難點
1. **合規與提交可靠度比選股更先決定生死**：D-Plan 的 orders 必須逐位元等於官方公式（derive-orders.v2）；posture（C12）與 funding_for（C14）會被數學重算；超賣即拒收；漏交容忍實際只有 2 次（≥22/24 日 + 3 次警告即取消）；**Active Share 連續 2 日 <20% 可直接取消資格**，且 Wi 定義未明。
2. **150 檔橫斷面組合建構**（不是單股擇時）：20–30 檔、整張、2330 ≤25%/其他 ≤10%、現金 0–25%、T-1 收盤估算 vs T 日均價成交的漂移、價格漂移 5 日寬限。
3. **24 交易日極短期**：結果高度受大盤曝險影響；來回成本 0.585%，換手是主要可控損耗；長期 DCF/價值在一個月內幾乎沒有預測力。
4. **Point-in-time 與 LLM 記憶污染**：只能用 08:55 前資料；LLM 預訓練記得歷史行情，賽前回測會高估 LLM 能力。
5. **可稽核、可重現的自主 Agent**：evidence chain、model/code version、prompt 版控、資料快照，以備 12/2 黑箱重現審查。

## 2–4. 值得參考的專案（Top 10 / Top 3）
共檢視約 300 個 repo，48 個進入比較表（`04_GITHUB_REPO_COMPARISON.csv`），10 個深讀程式碼與論文。

**Top 10**：① virattt/ai-hedge-fund（v2）② microsoft/qlib ③ TauricResearch/TradingAgents ④ waylonli/FINSABER ⑤ HKUSTDial/DeepFund ⑥ skfolio / PyPortfolioOpt ⑦ FinMem ⑧ FinAgent ⑨ FinCon（僅論文）⑩ FinRobot（僅借稽核模式）。

**Top 3（最推薦參考）**
1. **ai-hedge-fund v2**：LLM 只給 [-1,1] 觀點 → 程式 blend → apply_limits（截斷皆記錄）→ validate_targets → 整股委託 + hash-chained ledger。最接近我們需要的骨架（但無費稅、無整張 1000、美股資料）。
2. **Qlib**：VWAP 成交、lot size、雙邊成本、TopkDropout 換手控制 —— 成交/換手模型最貼近本賽。
3. **TradingAgents**：PIT 日期防護（date_window）、typed schemas + REVIEW fallback、5 日結算 memory log、bull/bear → counter_evidence。**但它一次只評一檔、沒有組合層**，不適合直接處理 150→20–30。

**直接點名**：FinCon 無程式碼；FinRobot 的「portfolio_optimization」是單公司對話；TradingAgents 論文僅 3 檔×3 月；AI-Trader、ai-berkshire、AutoHedge、atlas-gic 屬 Demo/行銷；FINSABER 顯示 FinMem/FinAgent 在嚴格測試下無顯著 alpha。

## 5. 可重用（Reuse / Adapt）
- Reuse：pandas/numpy/pyarrow、jsonschema/pydantic、LLM 官方 SDK、FinMind client（備援資料）、可選 skfolio/PyPortfolioOpt/cvxpy。
- Adapt（借模式不搬碼）：ai-hedge-fund v2 組合管線與 ledger、TradingAgents PIT guard/schemas/memory log、Qlib 成交與 TopkDropout、FINSABER 評估方法與 audit 輸出、FinRobot numeric grounding。

## 6. 一定自己做
Competition Engine（規則、derive-orders.v2、C1–C14 validator）、NAV Simulator（VWAP、費稅、除息延後入帳、警告/DQ）、Active Share（30 檔 ETF、多解讀取最小值）、Compliance gate、PIT 資料管線與快照、台股特有因子（月營收驚奇、三大法人）、Evidence Graph 與 D-Plan exporter、提交與 fallback。

## 7. 最推薦架構
**Hybrid Quant + LLM，Evidence-Graph-first**：
資料快照 → 程式產生 Facts（150 檔特徵）→ LLM 抽取事件（結構化）→ 分數融合（LLM 有界調整）→ 規則式 regime → 組合建構（24–27 檔、緩衝上限、no-trade band）→ 硬限制/Active Share gate → derive-orders → posture/funding_for 反推 → LLM 撰寫 logic/counter_evidence（只能引用給定 ID）→ 匯出重編號 → 驗證 → 兩段式提交（05:30 保守版、07:00 增強版）。
D-Plan v4.2 的分層幾乎就是這個 graph 的投影：L0/L1/L4 deterministic，L2 文字由 LLM，L3 權重由 optimizer。**不建議**「先決策、最後叫 LLM 補寫 D-Plan」（可靠性、稽核、C 檢查風險、token 成本皆較差，見 02 §5）。

## 8. 是否推薦 Multi-Agent？
**不推薦大規模 multi-agent。** 只用 3 個固定 LLM 角色（Event Extractor、Market Narrator、Thesis Writer，可選 Reviewer），作為 pipeline 函式呼叫。理由：150 檔 × 多角色 × 多回合成本與時間不可行；角色辯論產出的是評等不是權重；FINSABER/TradingAgents 證據顯示其 alpha 不穩健。

## 9. 是否推薦 Hybrid Quant + LLM？
**強烈推薦。** 證據：LLM 數值能力與非決定性弱點（FinanceBench、GSM-Symbolic、溫度 0 仍波動）、LLM 對時序預測無益（NeurIPS 2024）、Romanko 2023（LLM 選股 + 量化配權最佳）、ai-hedge-fund v2 重寫方向、Man Group AlphaGPT；加上本賽 C2/C12/C14 本身就是數學檢核。

## 10. 最重要的開發順序
P1 Competition Engine → P2 NAV Simulator → P3 PIT 資料管線（可平行）→ P4 Quant 特徵 → P7 組合建構 → P8 合規 gate → P9 D-Plan/提交（= MVP-0 quant-only，目標 10/18）→ P5/P6 LLM 事件與融合 → P10 記憶 → P11 多視窗 walk-forward 與 dry run（10/25 凍結版本）。
訊號優先序（24 日）：①大盤曝險與現金管理 ②月營收/財報驚奇 ③產業動能 + 52 週高 ④日內型動能（防崩盤）⑤MSCI 公告後漂移 ⑥LLM 新聞作為過濾器 ⑦法人買賣超 ⑧反轉 ⑨價值。

## 11. 最大風險
1. Active Share 定義不明 → 取消資格（R1）。
2. 前日結算持股取得方式（v4.2 移除 API）與超賣拒收；拒收/警告層級不一致（R2/R3）。
3. 漏交（實際容忍 2 次）（R4）。
4. LLM 幻覺與預訓練記憶污染回測（R12/R14）。
5. 比賽期間改版的自主性界線（R7）。
6. **新發現**：10/26–11/27 平日 25 天但辦法寫 24 交易日 → 10/26 可能為光復節補假，首日可能是 10/27（官方範例日期即 10/27）（NC-15）。

## 12. 下一輪最先做什麼
1. **送主辦方確認**：NC-1（持股取得/提交方式）、NC-2（Active Share 定義）、NC-3（檢查碼處置）、NC-15（首個交易日）、NC-9（改版界線）。
2. **開始 Phase 1 Competition Engine + Phase 2 Simulator**（不依賴任何外部資料或 LLM 決定，且是所有後續驗證的基準），同時 Phase 3 開始下載歷史資料（W1、W5 視窗）。
3. 環境：Python 3.13 已安裝但未加入 PATH；建立 venv 並安裝最小套件集（需你同意）。
