# FinCon — Manager-Analyst Multi-Agent with Conceptual Verbal Reinforcement (CVRF)

> 存取日期：2026-10-04。論文讀 arXiv HTML 正文；官方 repo 已 clone 檢查。

## Metadata

| 欄位 | 值 |
|---|---|
| Paper | FinCon: A Synthesized LLM Multi-Agent System with Conceptual Verbal Reinforcement for Enhanced Financial Decision Making（arXiv 2407.06567；NeurIPS 2024，vol.37 pp.137010–137045） |
| Authors | Yangyang Yu, Zhiyuan Yao, Haohang Li, ... Jordan Suchow, Zhenyu Cui, Rong Liu 等（Stevens Institute of Technology、Harvard 等；與 FinMem 同團隊） |
| Repo | https://github.com/The-FinAI/FinCon |
| Stars / Forks / Watchers | 67 / 6 / 11（GitHub 頁面 2026-10-04） |
| Last commit | 2026-02-26（"Fix typo in README regarding component anonymization"） |
| Latest release | 無 |
| **Code 狀態** | **沒有程式碼。** Repo 只有一個 `README.md`（clone 後確認整個 tree 只有這一個檔）。README 表示資料 agent 依賴商業 API，「計畫 3–4 個月內釋出」，但截至 2026-10-04（距該 commit 已 7 個月以上）仍未釋出。README 改推薦同團隊的 INVESTOR-BENCH（ACL 2025）與 Agent Market Arena（WWW 2026）。 |
| Maintenance | 只有 placeholder；無實質維護 |
| License | 無（repo 未附 LICENSE） |
| Language / Framework | N/A（論文描述：基於 FinMem 式 memory + GPT-4-Turbo；音訊用 Whisper） |
| LLM provider | 論文：GPT-4-Turbo，temperature 0.3 |

## Architecture

**Manager-Analyst 階層**（仿投資公司組織）：
- **Analyst agents（7 個）**：3 個新聞/財報/情緒 agent（daily news、10-K/10-Q）、1 個 audio agent（earnings call，Whisper 轉錄後分析）、1 個 data analysis agent（由價格序列算 momentum、CVaR 等）、1 個 stock selection agent（以相關性做風險分散選股，用於 portfolio 任務），等。每個 analyst 只負責單一模態，輸出「蒸餾後的 insight」，降低 manager context 負擔。
- **Manager agent**：唯一決策者；整合 analyst insight、risk alert、investment beliefs，輸出 buy/sell/hold（單股）或每檔方向（portfolio）。
- 通訊為**單向上報**（analyst→manager），非 peer-to-peer 辯論，作者強調可降低通訊成本；belief 更新再由 manager **選擇性下傳**給相關 analyst。

## Data Flow

價格（OHLCV）、新聞、10-K/10-Q、earnings call 音訊 → 各 analyst 的 working memory（觀察、檢索、蒸餾）→ procedural memory（insight、sentiment、建議動作）→ manager。

## Decision Flow

每日：analyst 蒸餾 → manager 整合 → within-episode risk check（CVaR）→ 決策 → 記錄到 manager procedural/episodic memory。Training 期跑多個 episode，episode 之間做 CVRF 更新 beliefs；testing 期 beliefs 凍結使用。

## Risk — 雙層風控

1. **Within-episode（逐日）**：計算 daily PnL 的 CVaR（最差 1% 的平均）。若當日 CVaR 下降或 PnL 為負 → 觸發 manager 轉為 risk-averse 姿態。Training 與 testing 都運作。
2. **Over-episode（CVRF, Conceptual Verbal Reinforcement）**：
   - 比較**相鄰兩個 training episode** 的績效（目標函數，例如 Sharpe）。
   - 從兩個 episode 中抽出獲利/虧損交易，讓 LLM 各自「概念化」成 investment insights。
   - meta-prompt 讓 LLM 對比「好 episode vs 差 episode」的 insights 差異，產出更新後的 **investment beliefs**（例如「在財報季應該更重視 earnings call 的指引而非新聞情緒」）。
   - **Learning rate**：以兩個 episode 交易決策序列的**重疊百分比**定義「text-based gradient」的步長 — 決策差異越大，beliefs 修改幅度越大。
   - 更新後 beliefs 先給 manager，再選擇性傳給相關 analyst（只更新跟該 belief 有關的 agent 的 prompt）。
   - **只在 training 期運作**（論文 limitation 明說 testing 期無法持續學習）。

## Memory

- Manager：working（整合、精煉）、procedural（交易紀錄、反思紀錄）、episodic（trajectory、PnL 序列、更新後的 beliefs）。
- Analyst：working（觀察、檢索、蒸餾）、procedural（insight、sentiment、建議），沿用 FinMem 的 recency/relevance/importance 排序，不同 analyst 用不同 decay rate（反映資訊時效）。
- 本質是 FinMem 記憶 + 「episode 級 belief 文字記憶」。

## Portfolio Logic

- Portfolio 任務：stock selection agent 先以相關性建構候選池 → manager 對每檔給方向（buy/sell/hold）→ **外部凸最佳化器做 mean-variance**：`max ⟨w,μ⟩ − ⟨w,Σw⟩`，buy 的權重 ∈[0,1]、sell ∈[−1,0]、hold = 0 → 每日 rebalance。
- 注意 sell 可為負權重（隱含放空），與比賽「不可放空」不同。
- 測試組合極小：Portfolio 1 = TSLA, MSFT, PFE；Portfolio 2 = AMZN, GM, LLY（各 3 檔）。
- 作者坦承：多資產時 LLM 會幻覺（如引用不存在的 memory index），規模擴大到「數十檔」是未來工作。

## Backtest（論文）

| 項目 | 內容 |
|---|---|
| 單股 tickers | TSLA, AMZN, NIO, MSFT, AAPL, GOOG, NFLX, COIN |
| Portfolio | 2 組 × 3 檔 |
| Train | 2022-01-03 ~ 2022-10-04 |
| Test | 2022-10-05 ~ 2023-06-10（約 8 個月） |
| LLM | GPT-4-Turbo（temp 0.3） |
| Baselines | B&H、A2C/PPO/DQN（FinRL，訓練回推到 2018）、Generative Agents、FinGPT、FinMem、FinAgent；portfolio：Markowitz MV、Equal-weight、FinRL-A2C |
| Metrics | CR%、Sharpe、MDD% |
| 結果例 | GOOG：FinCon CR 25.08%、SR 1.052 vs B&H 22.32%、1.107（Sharpe 其實低於 B&H） |
| 交易成本 | 論文未明確扣除 |
| **Look-ahead** | **高度疑慮**：GPT-4-Turbo 知識截止約 2023-04/2023-12，覆蓋整個 test 期；ticker 為知名大型股。FINSABER 指出 FinCon 未完全開源而無法獨立重現。 |

## Prompts

未公開（無程式碼）。論文附錄有 CVRF meta-prompt 的描述，但無可直接使用的模板。

## Strength

- 概念上最接近「基金經理 + 分析師」的組織，且有明確的**風控 → 行為**連結（CVaR 觸發 risk-averse）。
- CVRF 是把 Reflexion 式 verbal RL 從「單次 trial」推廣到「episode 對比 + belief 更新」，可解釋性高（beliefs 是可讀文字）。
- 有 portfolio 任務（LLM 給方向、數學最佳化器給權重）——**這種「LLM 給觀點、optimizer 給權重」的分工非常適合我們的比賽**。

## Weakness

- **無程式碼**，無法驗證或重用。
- CVRF 需多個完整 training episode（每個 episode 跑數月資料、GPT-4 成本高），比賽期間不可行。
- Portfolio 實驗只有 3 檔、允許負權重；無交易成本；測試期在 LLM 知識截止內。

## Reuse potential

- 只能借**設計概念**：(1) analyst 分模態蒸餾 → manager 決策；(2) CVaR/回撤觸發的 risk-off 規則；(3) LLM 輸出方向/信心、由 optimizer（MV 或規則）轉權重；(4) 「belief」作為可讀、可審計、版本化的文字策略參數。
- Reuse score：**1/5（程式）/ 概念 3/5**。

## Competition fit（1–5）

**2/5**。架構啟發高，但 CVRF 依賴多 episode 訓練與回測，24 交易日內無法真正「學習」。可在**賽前**用歷史資料跑少量 episode 對比，產出凍結的 beliefs 文件（需注意 LLM 知識截止造成的污染）。

## Classification

**A — Research-grade（paper-only，code 未釋出）**。

## Evidence

- https://arxiv.org/abs/2407.06567 、 https://arxiv.org/html/2407.06567 （§3 架構、§3.3 risk control/CVRF、§4 實驗、limitations）
- https://github.com/The-FinAI/FinCon （只有 README；clone 確認僅 1 檔）
- https://researchwith.stevens.edu/en/publications/fincon-a-synthesized-llm-multi-agent-system-with-conceptual-verba
- https://neurips.cc/virtual/2024/session/108395
- https://github.com/felis33/INVESTOR-BENCH 、 https://github.com/The-FinAI/Agent_Market_Arena （README 推薦的替代專案，未深入）
- https://arxiv.org/abs/2505.07078 （FINSABER：FinCon 非完全開源）
- 存取日期：2026-10-04
