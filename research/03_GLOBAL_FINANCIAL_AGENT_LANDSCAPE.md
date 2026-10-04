# 03 國際 Financial / Trading / Portfolio Agent 技術路線

> 資料：`repo_notes/*.md`（深讀筆記）、`repo_notes/Landscape_Scan.md`（約 300 個不重複 repo、其中 119 個 ≥150 stars、48 個列入比較表）、`raw_notes/*.md`（實證文獻）。存取日 2026-10-04。
> GitHub 數據來自未登入的 GitHub REST API（部分因 rate limit 改用網頁），數字為當日快照。

## 1. 七條主要技術路線

| # | 路線 | 代表 | 本質 | 對本賽適用性 |
|---|---|---|---|---|
| R1 | **單一 LLM 訊號** | FinGPT sentiment、Lopez-Lira & Tang (ChatGPT 新聞預測)、QuantAgent | LLM 讀文字/圖 → 給方向 | 低：單一訊號、無組合；新聞訊號主要在小型股有效 |
| R2 | **多 Agent 辯論（角色扮演）** | TradingAgents、AlphaAgents(BlackRock)、TradingAgents-CN、AutoHedge | analyst 團隊 → bull/bear debate → trader → risk debate → PM | 中：**單一 ticker** 評等；成本 = tickers × agents × rounds，150 檔不可行；可用在 shortlist |
| R3 | **記憶 / 反思型** | FinMem、FinAgent、FinCon（CVRF）、CryptoTrade | 分層記憶、反思修正 belief | 低～中：需要訓練期與重複 episode；24 日內學習樣本太少；記憶可用於「稽核」而非「學習」 |
| R4 | **強化學習** | FinRL、FinRL-Meta、TensorTrade | DRL agent 在 env 中學權重 | 低：需大量歷史訓練、非 LLM Agent、可解釋性差 |
| R5 | **因子挖掘 Agent（LLM 寫量化研究）** | Microsoft RD-Agent(Q) on Qlib、Alpha-GPT、Man Group AlphaGPT | LLM 提出因子/模型 → 程式回測 → 迭代 | 中：可**賽前離線**用於發想因子；比賽中不實時使用 |
| R6 | **LLM 當分析師 + 確定性組合層（Hybrid）** | ai-hedge-fund v2（view ∈[-1,1] → blend → limits → validate → orders）、Romanko et al. 2023（LLM 選股 + 均值變異數）、FinCon portfolio task、DeepFund、MASS | LLM 產生觀點/事件；程式負責權重、限制、委託 | **高**：最符合 D-Plan 分層與硬限制 |
| R7 | **純量化平台** | Qlib、PyPortfolioOpt、skfolio、Riskfolio、vectorbt、bt | 因子 → 預測 → 優化 → 回測 | **高（作為骨幹）**：VWAP 成交、整張、成本、換手控制皆現成概念 |

## 2. 國際趨勢觀察（有證據的）

1. **嚴格回測後，LLM 交易 Agent 的 alpha 大多消失**：FINSABER（KDD 2026，2004–2024、含下市股）重測 FinMem、FinAgent → 無顯著 alpha（p>0.34）；牛市過度保守、熊市過度積極。（`repo_notes/Other_LLM_Portfolio_Papers.md`）
2. **論文實驗普遍太短、太少標的、且落在模型訓練期內**：TradingAgents 3 檔 × 3 個月；FinMem/FinCon 使用 GPT-4-Turbo，cutoff 覆蓋測試期；AlphaAgents 15 檔 × 4 個月。Lopez-Lira, Tang & Zhu (2025) 指出 cutoff 前的「能力」與「記憶」無法分辨。
3. **生產導向專案正在把 LLM 從「下單者」降級為「觀點提供者」**：ai-hedge-fund v2 完全重寫——LLM 只輸出 [-1,1] 觀點，權重/限制/驗證/委託全由程式；TradingAgents 新增 typed schema、date_window PIT 防護、無法解析時轉 `REVIEW`。
4. **可稽核性成為顯性設計目標**：ai-hedge-fund v2 hash-chained ledger；FinRobot `narrative_numeric_grounding`（敘述必須引用數字）；FINSABER 輸出 manifest/orders/rejected orders/LLM cost；DeepFund DB 決策日誌與 anti time-travel；ALTA evidence chain + reviewer。
5. **LLM 在數值任務弱**：FinanceBench（GPT-4-Turbo+檢索 81% 錯誤或拒答）、GSM-Symbolic（加一句無關文字最多掉 65%）、溫度 0 仍有最多 15% 準確度波動、LLM 對時間序列預測無幫助（Tan et al. NeurIPS 2024）。（`raw_notes/hybrid_vs_pure_llm_evidence.md`）
6. **Hybrid 實證較佳**：Romanko et al. 2023：ChatGPT 選股不錯、配權重差；LLM 選股 + 量化優化最好。Man Group AlphaGPT 讓每個訊號通過相同 gate。

## 3. 真正做「多股票組合」的專案很少

| 類型 | 專案 |
|---|---|
| 單一股票 BUY/HOLD/SELL（或評等） | TradingAgents、FinMem、FinAgent、FinRobot、QuantHarness、dexter、TradingAgents-CN、AutoHedge、多數 Landscape repo |
| 多股票但權重粗糙 | AlphaAgents（共識後等權）、ai-hedge-fund v1（每檔 20% 上限 + 波動/相關調整） |
| 真正有權重/現金/限制的組合層 | ai-hedge-fund v2（無費用、收盤成交）、Qlib（VWAP、lot、雙邊成本、TopkDropout）、FinCon portfolio task（MV 優化，可負權重，無程式碼）、DeepFund、MASS、PyPortfolioOpt/skfolio/Riskfolio |
| 同時處理整張 + 費稅 + 現金上下限 + 檔數 + 個股上限 + Active Share | **無**（必須自建） |

## 4. 對本賽的結論
- 本賽是 **cross-sectional portfolio construction**（150 → 20–30 檔，含硬限制），不是單一股票擇時。國際上最熱門的多 Agent 辯論 repo 解的是另一個問題。
- 最值得借的是 **R6 的分工**（LLM 觀點 → 確定性組合層）+ **R7 的量化骨幹** + **可稽核性模式**（ledger、PIT guard、typed output、numeric grounding）。
- R2 的辯論可作為「候選 shortlist 上的 thesis/counter-evidence 產生器」，正好對應 D-Plan 的 `logic` + `counter_evidence`。
- R3 的記憶應縮減為「決策日誌 + thesis 追蹤 + 預測-結果追蹤」。
- R5 可用於賽前離線找因子，不進入比賽中的每日流程。
