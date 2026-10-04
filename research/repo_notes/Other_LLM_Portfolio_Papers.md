# 其他 LLM 交易 / 組合論文與 Repo（FINSABER 優先、Look-ahead 批判）

> 存取日期：2026-10-04。FINSABER、QuantHarness（原 QuantAgent）、StockAgent 已 shallow clone 檢查；其他以 arXiv 頁面/正文與 GitHub 搜尋確認是否有程式碼。GitHub API 未驗證（gh 未登入），metadata 用匿名 REST API 與 GitHub 頁面取得。

---

## 1. FINSABER —「Can LLM-based Financial Investing Strategies Outperform the Market in Long Run?」（最優先）

### Metadata

| 欄位 | 值 |
|---|---|
| Paper | arXiv 2505.07078；**KDD 2026 Datasets & Benchmarks Track（oral）**；DOI 10.1145/3770854.3785702；WSJ 2026-06 報導 |
| Authors | Waylon Li 等（GitHub: waylonli；完整作者名單見論文） |
| Repo | https://github.com/waylonli/FINSABER （另有 PyPI `finsaber`、文件站 https://waylonli.github.io/FINSABER/ 、HF dataset `finsaber-team/FINSABER-V2-Data`） |
| Stars / Forks / Watchers | 147 / 17 / 1 |
| Last commit | 2026-09-17（"Fix synthetic trading days and use validated benchmark results"） |
| Latest release | v2.0.1（2026-05-24） |
| Maintenance | 活躍（FINSABER-2 於 2026-05 重構為套件） |
| License | Apache-2.0 |
| Language / Framework | Python 3.10；backtrader；parquet 資料；branch `reproduce` 重現 v1 論文、`main` 為 FINSABER-2 |
| LLM provider | OpenAI GPT-4o、GPT-4o-mini（重測 FinMem、FinAgent） |

### 核心批判（論文正文）

1. **Survivorship bias**：前人只用「今天還存在」的熱門股（TSLA、AMZN…），忽略下市/破產股 → 報酬系統性高估。FINSABER 使用歷史正確的 S&P 500 成分並納入下市股。
2. **Look-ahead bias**：依全期結果挑選特徵、參數或標的。FINSABER 要求每個回測窗只用窗起點之前的資訊（資料對齊）。
3. **Data-snooping bias**：在同一資料上反覆實驗。
4. **評估太短太窄**：Table 1 整理 — FinMem 6 個月/5 檔、FinAgent 6 個月/6 檔；多數研究 < 1 年、< 10 檔。
5. **LLM 知識截止污染**：Limitations 承認 GPT-4o 訓練語料可能涵蓋測試期；但作者指出「即使可能洩漏，LLM 仍表現不佳」更強化其負面結論。

### 框架設計

- 2004–2024（20 年）rolling window（預設 2 年窗、1 年步長、可設 training_years）。
- 選股器：Random 5（共 91 檔）、Momentum（過去 100 日、排除最近 21 日，top-5；84 檔）、Low-volatility（21 日；63 檔）、FinCon 式 LLM selector（80 檔）、FinMem selector。
- 每個 timing strategy **逐檔獨立回測**（`run_iterative_tickers`）後彙總 → 嚴格說是「多檔單股策略的平均」，不是共享資金的 portfolio optimizer。
- 成本：$0.0049/股、最低 $0.99/筆、上限 1%（Moomoo/IBKR 式）；FINSABER-2 新增 `execution_timing ∈ {same_close, next_open}`、`slippage_perc`、`liquidity_cap_pct`、**LLM API 成本計入交易成本**（`llm_cost_as_trade_cost=True`）、結構化輸出 `run_config.json / run_manifest.json / trades.csv / orders.csv / rejected_orders.csv / llm_costs.csv`。
- Baselines：Buy&Hold、SMA/WMA crossover、ATR band、Bollinger、Trend following、Turn-of-the-month、ARIMA、XGBoost、FinRL。

### 主要結果

| 設定 | B&H | FinMem | FinAgent | 其他 |
|---|---|---|---|---|
| 原 "selected 4"（2004–2024）Sharpe：TSLA / NFLX / AMZN / MSFT | 0.630 / 0.622 / 0.551 / 0.461 | 0.641 / 0.293 / 0.188 / 0.203 | 0.546 / −0.511 / 0.389 / 0.301 | |
| Momentum 選股組合 Sharpe / 年化報酬 | 0.384 / 9.92% | 0.025 / 3.65% | 0.104 / 13.95% | ARIMA 0.542 / 13.26% |
| Alpha 顯著性 | — | 負 alpha，p>0.34 | 不顯著 | |
| Regime | Bull：B&H Sharpe 0.61 vs FinAgent 0.12（太保守）；Bear：FinAgent −0.38、FinMem −0.97 vs B&H −0.28（太激進） | | | |

### 建議（作者）

1. 趨勢偵測：上漲期至少要跟上市場 beta。
2. Regime-aware 風控：波動/回撤上升時降低曝險。
3. 「平衡 risk-taking 與 risk management，而非加大模型」；NLP 的 scaling law 不轉移到市場。

### 對比賽的啟示

- 我們的評分是 24 日最終 NAV，基準實質上是「台股大盤 beta」。FINSABER 的結果說明：LLM timing 在多頭時常因過度保守落後 B&H → **比賽中不應讓 LLM 自由決定大幅現金比例**（規則也限制現金 < 25%）；應以「接近滿倉 + LLM 做選股/權重微調」為主。
- FINSABER-2 的結構化 artifact（config/manifest/orders/rejected_orders/llm_costs）是我們 audit log 的好範本。
- Capability flags：market_data Y、fundamental Partial（10-K/10-Q 文字）、technical Y、news Y、sentiment Partial（經 LLM 策略）、portfolio_management Partial、multi_stock_portfolio Partial（逐檔獨立）、position_sizing Partial、risk_management Partial（liquidity cap、slippage）、memory N（框架本身）、reflection N、backtesting **Y**、simulation N、tool_calling N、structured_output Y（結果檔）、audit_log **Y**、point_in_time_data **Y**（歷史成分、資料對齊）、transaction_cost **Y**、portfolio_constraints N、rebalancing Partial。
- Classification：**A — Research-grade（benchmark，偏 production 品質）**。Competition fit **3/5**（方法論與 audit 格式）、Reuse **3/5**（backtrader 架構不支援台股整張/VWAP 需改寫，但設計值得照抄）。

---

## 2. QuantAgent（兩篇同名論文，務必區分）

### 2a. QuantAgent: Seeking Holy Grail in Trading by Self-Improving LLM（arXiv 2402.03755）
- Authors：Saizhuo Wang, Hang Yuan, Lionel M. Ni, Jian Guo（HKUST / IDEA）。
- 兩層迴圈：inner loop（writer 依知識庫產生 alpha、judge 評審修正）；outer loop（在真實市場資料回測，把結果寫回知識庫）。宣稱「可證明效率地逼近最優」。
- 產出：alpha 因子（類 RD-Agent / Alpha-GPT 路線），非 portfolio agent。
- **程式碼：未找到官方 repo**（GitHub 搜尋 "QuantAgent" 只見同名第三方專案）。
- 分類 A（paper-only）；Competition fit 2/5（賽前因子挖掘概念）。

### 2b. QuantAgent → 現名 **QuantHarness**: Price-Driven Multi-Agent LLMs for High-Frequency Trading（arXiv 2509.09995）
- Repo：https://github.com/Y-Research-SBU/QuantHarness （原 `Y-Research-SBU/QuantAgent` 會 redirect）；2,875★ / 617 forks / 28 watchers；last commit 2026-08-18；無 release；MIT；Python（LangChain + LangGraph、TA-Lib、Flask web UI）；LLM：OpenAI / Anthropic / Qwen(DashScope) / MiniMax。
- 四個 agent：Indicator（RSI、MACD、Stochastic 等 5 指標）、Pattern（畫圖 + 視覺比對型態）、Trend（趨勢通道圖）、Decision（輸出 LONG/SHORT、進出場、停損、理由）。
- 1h/4h K 線、9 種資產（BTC、Nasdaq futures 等）；以方向預測準確率等指標勝過 baseline。純價量、無新聞、無記憶、單資產、含做空建議。
- 分類 **C — Educational/Demo**（研究 + web demo）；Competition fit **1/5**（高頻、單資產、可放空）；Reuse 1/5（只有 indicator tool 定義可參考）。

---

## 3. StockAgent —「When AI Meets Finance (StockAgent)」（arXiv 2407.18957，ACM TIST）

- Repo：https://github.com/MingyuJ666/Stockagent ；709★ / 170 forks / 10 watchers；last commit 2026-06-16（README 更新）；無 release；**無 LICENSE**；Python 3.9；依賴 PromptCoder（procoder）；LLM：GPT 系列 / Gemini-pro（預設）。
- 本質是**模擬市場**：多個 LLM 投資人 agent 在虛構股票（Stock A/B）上交易，含貸款、每日/季度事件、隨機特殊事件；研究外部因素對交易行為與價格的影響。作者強調用虛構市場避免測試集洩漏。
- 非真實資料投資 agent；與比賽無直接關係。
- 分類 **A/C**（研究模擬器）；Competition fit **1/5**；Reuse 1/5。

---

## 4. TradingGPT（arXiv 2309.03736，FinMem 同團隊前作）

- 多 agent、分層記憶（類 FinMem）、不同角色個性、agent 間辯論。
- **程式碼：未找到官方 repo**（GitHub 搜尋 "TradingGPT" 只有 2023 年零星無關玩具專案）。後續工作即 FinMem/FinCon。
- 分類 A（paper-only）；Competition fit 1/5。

---

## 5. AlphaAgents（BlackRock，arXiv 2508.11152）

- 三個 agent：Fundamental（10-K/10-Q）、Sentiment（新聞、分析師評等）、Valuation（價量）；GPT-4o + Microsoft AutoGen；**round-robin 辯論直到共識** BUY/SELL；risk-averse / risk-neutral 由 prompt 設定。
- **真正的多股票選股，但組合 = 被選中股票等權**；宇宙只有隨機 15 檔科技股；2024-02-01 起 4 個月；以 rolling Sharpe 評估。多 agent 在 risk-neutral 下勝過單 agent；risk-averse 在多頭期落後（與 FINSABER 結論一致）。
- 作者明說 portfolio optimization/分散化不在範圍內。
- Look-ahead：GPT-4o 截止 2023-10，測試期 2024-02~06 在截止之後（較乾淨），但期間短、樣本小。
- **程式碼：BlackRock 未釋出**；第三方重現 https://github.com/vedurmaliya/alpha-agents （7★，LangGraph，未驗證品質）。
- 分類 A（industry paper）；Competition fit **3/5**（「多 agent 對單檔做 buy/不 buy 共識 → 等權組合」是最簡單可落地的 portfolio 形式，且與我們 20–30 檔等權/近等權相容）；Reuse 2/5。

---

## 6. MarketSenseAI 2.0（arXiv 2502.00415）

- RAG + LLM agents：SEC filings / earnings call（chain-of-agents 處理長文件）、總經機構報告、新聞、價格。
- S&P 100（2023–2024）：累積報酬 125.9% vs 指數 73.5%；S&P 500（2024）Sortino 高 33.8%。
- **無程式碼**（FINSABER 亦標為 closed source）；組合建構細節摘要未載明（v1 的組合規則本次未查證）。
- Look-ahead：2023 年部分在 GPT-4 系列知識截止內，需保留。
- 分類 A/B（商業研究，closed）；Competition fit 2/5；Reuse 1/5。

---

## 7. 其他快速檢查

| 名稱 | 程式碼 | 備註 |
|---|---|---|
| FinVerse（arXiv 2406.06379） | 未找到公開程式碼 | 600+ 金融 API、code interpreter 的通用分析 agent；依指示不深入 |
| FinSphere（arXiv 2501.12399） | 未找到公開程式碼 | 個股分析報告 agent（AnalyScore、Stocksis 資料集）；不深入 |
| AlphaAgent（RndmVariableQ/AlphaAgent，418★，2026-07 push） | 有 | LLM alpha 因子挖掘 + 正則化探索對抗 alpha decay；未深入，可作為 RD-Agent 替代參考 |
| Alpha-GPT（arXiv 2308.00016） | 未查證 | human-in-the-loop alpha mining；與因子挖掘同類 |
| INVESTOR-BENCH（ACL 2025） | https://github.com/felis33/INVESTOR-BENCH | FinCon README 推薦的單 agent 基準 |
| Agent Market Arena（WWW 2026，arXiv 2510.11695） | https://github.com/The-FinAI/Agent_Market_Arena | **即時（live）多市場交易基準** — 用前瞻時間評估以避開 look-ahead |

---

## 8. Look-ahead / 知識截止批判文獻（方法論）

- **FINSABER**（上）：survivorship、look-ahead、data-snooping；20 年 rolling。
- **DatedGPT**（arXiv 2603.11838）：訓練 12 個 1.3B 模型，每個只用嚴格年度截止（2013–2024）的資料，用於無前視偏誤的金融回測。
- **"Summoning the Oracle to Slay It"／FinCAD**（arXiv 2605.24564）：推論時用 context-aware decoding 抑制 LLM 對歷史結果的記憶，不需重訓。
- **Agent Market Arena**：live benchmark，從源頭避免污染。

### 本清單論文的 test 期 vs LLM 知識截止

| 論文 | Test 期 | 主 LLM（約略截止） | 判定 |
|---|---|---|---|
| FinMem | 2022-10 ~ 2023-04（6 個月） | GPT-4-Turbo（2023-04） | **污染**（最佳結果來自此模型） |
| FinCon | 2022-10 ~ 2023-06（8 個月） | GPT-4-Turbo（2023-04 / 2023-12） | **污染** |
| FinAgent | 2023-06 ~ 2024-01（7 個月） | gpt-4-1106 / vision（2023-04） | 大致乾淨，但期間短、標的為贏家 |
| FINSABER | 2004 ~ 2024（20 年） | GPT-4o / mini（2023-10） | 大部分污染（作者承認；結論反而更保守） |
| AlphaAgents | 2024-02 ~ 2024-06 | GPT-4o（2023-10） | 乾淨，但 4 個月 / 15 檔 |
| MarketSenseAI 2.0 | 2023 ~ 2024 | GPT-4 系列 | 部分污染 |
| RD-Agent(Q) | CSI300 2017 ~ 2020；NASDAQ100 2024 ~ 2025-06 | GPT-4o / o3 / GPT-4.1 | CSI300 間接污染（因子知識）；NASDAQ100 部分乾淨 |

**對我們的含意**：比賽是真正的 forward test（2026 年後的交易日），不存在 look-ahead；但**賽前回測**若用目前 LLM（知識截止 2025–2026）在 2023–2025 台股資料上跑「LLM 判斷」，結果必然高估。賽前驗證應 (a) 只回測非 LLM 的量化部分；(b) LLM 部分只用模型截止日之後的資料做 paper trading；(c) 或以 prompt 遮蔽公司名稱/日期（匿名化）做壓力測試。

---

## Evidence（存取日期 2026-10-04）

- https://arxiv.org/abs/2505.07078 、 https://arxiv.org/html/2505.07078 、 https://github.com/waylonli/FINSABER （README、`backtest/toolkit/trade_config.py`、`backtest/toolkit/execution.py`、`backtest/finsaber.py`、`finsaber/strategy/*`）、 https://waylonli.github.io/FINSABER/ 、 https://dl.acm.org/doi/10.1145/3770854.3785702
- https://arxiv.org/abs/2402.03755
- https://arxiv.org/abs/2509.09995 、 https://github.com/Y-Research-SBU/QuantHarness
- https://arxiv.org/pdf/2407.18957 、 https://github.com/MingyuJ666/Stockagent
- https://arxiv.org/html/2508.11152 、 https://github.com/vedurmaliya/alpha-agents
- https://arxiv.org/abs/2502.00415
- https://arxiv.org/pdf/2406.06379 （FinVerse）、 https://arxiv.org/html/2501.12399v2 （FinSphere）
- https://github.com/RndmVariableQ/AlphaAgent
- https://github.com/felis33/INVESTOR-BENCH 、 https://github.com/The-FinAI/Agent_Market_Arena 、 https://arxiv.org/pdf/2510.11695
- https://arxiv.org/abs/2603.11838 （DatedGPT）、 https://arxiv.org/abs/2605.24564 （FinCAD）
- https://api.github.com/search/repositories?q=TradingGPT / QuantAgent / AlphaAgents / MarketSenseAI / StockAgent （程式碼存在性檢查）
