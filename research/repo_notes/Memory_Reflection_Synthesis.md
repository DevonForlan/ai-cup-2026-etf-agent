# Memory / Reflection 綜合分析與比賽取捨

> 存取日期：2026-10-04。依據 FinMem、FinCon、FinAgent 的程式碼與論文正文，以及 FINSABER 長期重測結果。各 repo 詳細內容見同目錄筆記。

## 1. 三種記憶/反思機制摘要

| | FinMem | FinCon | FinAgent |
|---|---|---|---|
| 記憶結構 | short / mid / long / reflection 四個 faiss 庫（per symbol） | Manager：working / procedural / episodic；Analyst：working / procedural（沿用 FinMem 評分） | MI memory、low-level reflection memory、high-level reflection memory |
| 寫入來源 | 新聞→short；10-Q→mid；10-K→long；train 期的反思→reflection | 各 analyst 蒸餾的 insight；manager 的交易紀錄、PnL、beliefs | 每日 MI 摘要、兩層 reflection 輸出 |
| 檢索評分 | similarity + exp(−δ/Q) + importance/100；importance 每日 ×α 衰減 | recency / relevance / importance，各 analyst 不同 decay | 向量相似度 + **diversified queries**（模組自己產生多條 query） |
| 學習訊號 | 7 日持倉 PnL 正負 ±1 → 被引用記憶的 access_counter → importance +5×counter；超門檻跨層搬移 | **CVRF**：相鄰 episode 績效比較 → LLM 概念化 beliefs → 以決策重疊率作 learning rate 更新 prompt；CVaR 逐日觸發 risk-averse | Low-level：訊號→價格的因果解讀；High-level：決策→結果的自我檢討＋improvement |
| 需要的 warm-up | Train 期約 1 年（且使用未來價格標籤） | 多個 training episode（約 9 個月資料 × N 次） | Train 期 1 年（low-level 用未來 1/7/14 日報酬） |
| Test 期是否持續學習 | 是（feedback 仍運作） | 否（beliefs 凍結，CVaR 仍運作） | 是（反思持續寫入） |

### 關鍵觀察

1. **三者的「長期記憶」都靠一段使用未來資訊的 train 期養成**（FinMem 直接給次日價差、FinAgent 給未來報酬、FinCon 用 episode 結果）。這在比賽中不可能複製 — 比賽只有 24 個交易日，且每天只能看到過去。
2. **衰減參數（Q=90/365 日）遠長於比賽期**：在 24 日內，mid/long 層的 recency 幾乎不變（exp(−24/90)≈0.77、exp(−24/365)≈0.94），等於沒有作用；short 層 Q=14 則有作用。
3. **FinMem 的 importance 是隨機初始化**，回饋訊號只有 ±1 的 7 日 PnL — 24 日內最多約 17 次有效回饋，且對 20–30 檔 portfolio 而言 portfolio 級 PnL 無法歸因到單一證據。
4. **FINSABER 證明**：這些記憶/反思機制在長期、無偏樣本上**沒有產生顯著 alpha**；失敗模式是 regime 不敏感（多頭太保守、空頭太激進），而不是「記憶不夠」。
5. 真正有價值的是三者的**副產品**：每個決策都引用 evidence id（FinMem）、分模態蒸餾再交給決策者（FinCon）、把「預測→實際」與「決策→結果」分開反思（FinAgent）。這些正好構成我們需要的 **evidence chain 與 audit log**。

## 2. 24 交易日比賽：值得做 vs 不值得做

### 值得實作（高 ROI、可審計、無需 train 期）

| 記憶類型 | 內容 | 用途 | 參考來源 |
|---|---|---|---|
| **Decision log（不可變、append-only）** | 每日 JSON：source → observation → inference → decision → order；含 prompt 版本、模型 ID、資料時間戳、輸入 hash | 比賽要求的 evidence chain；事後審計；重現 | FinMem 的 memory-id 引用、FINSABER-2 的 run_manifest / orders / rejected_orders / llm_costs |
| **Thesis tracker（持倉論點）** | 每檔持股：進場理由、預期催化劑、失效條件（invalidation）、預計持有期、目標權重；每日檢查是否失效 | 避免 LLM 每天重新「從零」判斷而造成高換手（成本 0.1425%×2 + 0.3% 稅 ≈ 0.585% 來回） | FinCon manager procedural memory；FinAgent high-level reflection |
| **Prediction–outcome tracker** | 每次對個股/因子的方向或排名預測、信心；T+1/T+5 實際報酬；滾動命中率、IC、calibration | 在比賽中唯一可用的「學習」訊號：用來調整 LLM 觀點對量化分數的混合權重（例如 LLM overlay 權重 0~30%，命中率差就自動降權） | FinAgent low-level reflection（訊號→價格）；FinMem feedback 簡化版 |
| **Short-term news/event memory（3–10 日窗）** | 個股新聞、公告（月營收、法說、除權息、重大訊息）、法人買賣超；去重、時間戳、來源；recency 衰減 Q≈5–14 交易日 | 避免重複反應同一則新聞；事件是否「已反映」 | FinMem short layer（Q=14）；FinAgent latest/past MI |
| **Constraint / risk state memory** | 前一日持股（張數）、現金比、TSMC 權重、Active Share vs 各 ETF top-10、回撤、波動 regime | 硬性約束檢查與 regime-aware 曝險（FINSABER 建議） | FinCon within-episode CVaR；FINSABER 建議 |
| **Daily post-mortem（輕量反思）** | 收盤後比較昨日決策 vs 實際（歸因：選股/權重/成本）；產出 ≤3 條「明日注意事項」，有效期限 3–5 日 | 文字化的短期修正，但**只作為 prompt 提示，不改硬規則** | FinAgent high-level reflection、Reflexion |

### 不值得實作（或僅賽前離線做）

| 類型 | 原因 |
|---|---|
| FinMem 式 mid/long layer 的 importance 演化、跨層 jump | 衰減尺度（90/365 日）遠長於 24 日；importance 隨機初始化；回饋稀疏 |
| FinCon CVRF 線上 belief 更新 | 需要多個完整 episode 對比；比賽只有一條路徑，無 episode 可比；線上改策略增加審計風險 |
| 需要 train 期的「learned memory」（用未來價格標籤養記憶） | 比賽中不可得；賽前用歷史資料養會受 LLM 知識截止污染（FINSABER/DatedGPT/FinCAD 所述） |
| 向量資料庫 + embedding 語意檢索全量新聞 | 150 檔 × 24 日的資料量小，結構化表（ticker, date, type）+ 規則篩選即可，向量檢索徒增不確定性與不可重現性 |
| 多模態 K 線圖反思（FinAgent vision） | 成本高、對 150 檔每日不划算、可由數值指標替代 |
| RL/DRL 線上學習 | 樣本不足 |

### 可在「賽前」離線做的版本

- 以 2025-後（LLM 截止後）資料做 paper trading，產出一份**凍結的 belief/playbook 文件**（類 CVRF 的產物，但人工審核、版本化），比賽期間只讀不寫。
- 用 Qlib / 自建回測器驗證量化核心（不含 LLM），因為 LLM 部分的歷史回測不可信。

## 3. 建議的最小記憶架構（JSON 檔即可，不需資料庫）

```
memory/
  decisions/YYYY-MM-DD.json        # append-only evidence chain（source→observation→inference→decision→order）
  theses/{ticker}.json             # 當前論點、失效條件、建立日、最後檢查日
  predictions/YYYY-MM-DD.json      # 預測 + 之後回填 outcome
  events/YYYY-MM-DD.json           # 短期事件（帶 expires_at）
  state/portfolio_state.json       # 持股張數、權重、現金、Active Share、約束檢查結果
  reflections/YYYY-MM-DD.json      # ≤3 條注意事項，帶 expires_at，引用 decision/prediction id
```

設計原則：
1. **每條記憶都有 id、時間戳、來源、expires_at**；決策必須引用 id（FinMem 的 ValidChoices 思路 → 用 JSON schema 驗證引用的 id 存在）。
2. **反思只能影響「軟」參數**（LLM overlay 權重、關注清單），不能改「硬」約束（權重上限、現金下限、整張、Active Share）。
3. **預測-結果追蹤是唯一的線上學習迴圈**，並以簡單統計（滾動命中率/IC）而非 LLM 自評驅動。
4. 所有 LLM 呼叫記錄 model id、prompt hash、temperature、token/cost（FINSABER-2 `llm_costs.csv` 作法）。

## 4. Capability matrix（Y / P = Partial / N）

| Capability | FinMem | FinCon* | FinAgent | FINSABER | Qlib | RD-Agent | FinRL | FinGPT | QuantHarness | StockAgent | AlphaAgents* |
|---|---|---|---|---|---|---|---|---|---|---|---|
| market_data | Y | Y | Y | Y | Y | Y | Y | P | Y | N（虛構） | Y |
| fundamental | P（10-K/Q 文字） | Y | P | P | P（需自備） | P | N | N | N | P（虛構） | Y |
| technical | P（momentum） | Y | Y | Y | Y | Y | Y | N | Y | N | Y |
| news | Y | Y | Y | Y | N | N | N | Y | N | P（虛構事件） | Y |
| sentiment | Y | Y | Y | P | N | N | N | Y | N | N | Y |
| portfolio_management | N | P | N | P | Y | P | Y | N | N | N | P |
| multi_stock_portfolio | N | P（3 檔） | N | P（逐檔獨立） | Y | Y | Y | N | N | P | Y（等權 15 檔池） |
| position_sizing | N（1 股） | P（MV） | P（全進全出） | P | Y | P | Y | N | P（建議） | P | N（等權） |
| risk_management | P（prompt） | Y（CVaR） | P | P | P | N | P（turbulence） | N | P（停損建議） | N | P（prompt） |
| memory | Y | Y | Y | N | N | P（trace） | N | N | N | P | N |
| reflection | Y | Y（CVRF） | Y（雙層） | N | N | Y（feedback） | N | N | N | N | P（辯論） |
| backtesting | P | P | Y | Y | Y | Y | Y | N | P | N | P |
| simulation | N | N | N | N | Y（執行器） | N | Y | N | N | Y | N |
| tool_calling | N | P | Y | N | N | Y | N | N | Y | N | Y（AutoGen） |
| structured_output | Y（guardrails） | ? | Y（XML） | Y（結果檔） | Y | Y | N | N | P | P | P |
| audit_log | P（memory id 引用） | ? | P | Y | P（recorder） | Y（trace UI） | N | N | N | P | N |
| point_in_time_data | P（train 用未來標籤） | ? | P（先載入未來再過濾） | Y | Y | P | P | N | P | N/A | P |
| transaction_cost | N | N | Y（0.1%） | Y | Y | Y | Y | N | N | N | N |
| portfolio_constraints | N | P | N | N | Y | P | N | N | N | N | N |
| rebalancing | N | Y（每日） | N | P | Y | Y | Y | N | N | N | P |

\* FinCon、AlphaAgents 無官方程式碼，依論文描述判斷。

## 5. 結論

- **在 24 交易日的比賽中，值得做的是「審計型記憶」而不是「學習型記憶」**：decision log、thesis tracker、prediction-outcome tracker、短期事件記憶、約束/風險狀態，加上受限的每日 post-mortem。
- FinMem 長期分層記憶、FinCon CVRF、需要 train 期的 learned memory 都不划算；其概念可在賽前離線轉成「凍結 playbook」。
- 依 FINSABER 證據，LLM 不應主導擇時/現金水位；應以量化排序（Qlib 式 TopkDropout / 帶約束最佳化）為骨幹，LLM 做事件解讀與小幅 overlay，且 overlay 權重由 prediction-outcome tracker 動態控制。

## Evidence（存取日期 2026-10-04）

- https://arxiv.org/html/2311.13743 、 https://github.com/pipiku915/FinMem-LLM-StockTrading
- https://arxiv.org/html/2407.06567 、 https://github.com/The-FinAI/FinCon
- https://arxiv.org/html/2402.18485v3 、 https://github.com/DVampire/FinAgent
- https://arxiv.org/html/2505.07078 、 https://github.com/waylonli/FINSABER
- https://github.com/microsoft/qlib 、 https://github.com/microsoft/RD-Agent 、 https://arxiv.org/html/2505.15155
- https://arxiv.org/abs/2603.11838 、 https://arxiv.org/abs/2605.24564
