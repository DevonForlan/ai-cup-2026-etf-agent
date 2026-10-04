# GitHub Landscape Scan：AI 交易/投資 Agent 與可重用的量化基礎設施

> 掃描日期：2026-10-04。數字取自 GitHub API 與頁面，查詢過程見 `research/raw_notes/gh_search_log.md`。
> 範圍：已由其他 agent 深入研究的 TradingAgents、ai-hedge-fund、FinRobot、FinMem、FinCon、FinAgent、Qlib/RD-Agent、FinRL、FinGPT，本文只列 metadata（見第 4 節）。
> 方法限制：`gh` 未登入，改用未認證 API；source tree 只看 HTML 的前兩層目錄，加上 README 關鍵字（portfolio/weight/rebalance/commission/slippage/backtest/memory/reflect/look-ahead/audit 等）。判斷屬於快速審視，**沒有逐行讀程式碼**。最終採用前請人工複核（依公司政策，AI 產出需經人工審閱）。

## 0. 分類定義

- **A Research**：論文配套程式碼，有實驗設計，但工程完整度有限。
- **B Production**：持續維護、有發版或測試、模組化，可以實際部署。
- **C Educational/Demo**：教學或示範，流程完整但簡化。
- **D Marketing/Toy**：星數高但程式碼少，或主要是 prompt/報告/宣傳。

欄位說明：Y = 有，P = 部分或簡化，N = 沒有或沒看到，? = 從結構與 README 無法確認。

## 1. 主表：Agent 類 repo（不含 deep-dive 清單）

| Repo | Stars / Forks | Last commit | Release | License | Lang | Class | Portfolio | Multi-agent | Memory | Reflection | Backtest | PIT | Tx cost | Reuse role | 備註 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | 34,585 / 5,617 | 2026-10-03 | v0.1.16 | MIT | Python | B | P | Y (swarm) | Y | P | Y | P | Y | pattern（grounding/evidence gate、backtest 正確性檢查） | 2026-04 才建立，星數成長極快。changelog 很密，大量修正資料正確性問題（除權息調整、缺值 bar、捏造價格的 grounding gate），可作為「資料陷阱清單」來源。功能面很廣（多市場、IM、券商），對本賽題太重 |
| [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | 22,649 / 3,425 | 2026-06-11 | none | 無 | Python | D | N | P | N | N | N | N | N | avoid | 已轉型為 ai4trade.ai 線上平台與 copy-trade skills。README 只有 8KB，沒有 backtest/portfolio 關鍵字，也沒有授權。**高星 demo 標記** |
| [virattt/dexter](https://github.com/virattt/dexter) | 27,642 / 3,412 | 2026-09-23 | v1.1.0 | 無 | TypeScript | B | N | N（單 agent + 規劃/自檢） | Y | P | N | N | N | pattern（task planning、self-validation） | 個股深度研究 agent，不做投組。沒有 LICENSE，程式碼不可直接複用 |
| [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | 32,145 / 6,719 | 2026-09-22 | none | NOASSERTION（混合/部分專有） | Python | B | N（單 ticker） | Y | P | P | P | N | N | pattern-only | TradingAgents 中文增強版，A 股/港股資料源與 Web UI。授權混雜，**不要複製程式碼** |
| [ValueCell-ai/valuecell](https://github.com/ValueCell-ai/valuecell) | 11,019 / 1,802 | 2026-02-11 | v0.1.20 | Apache-2.0 | Python | C/B | P | Y | P | N | N | N | N | pattern-only | 多 agent 金融應用平台（研究 + 加密貨幣自動交易），沒有回測。2026-02 之後幾乎停更 |
| [OpenByteInc/QuantDinger](https://github.com/OpenByteInc/QuantDinger) | 12,433 / 2,532 | 2026-10-01 | v5.5.2 | Apache-2.0 | Python | B | P | P | N | N | Y | P | Y | avoid（太重） | 自架「AI Trading OS」（Flask + MCP + Grafana），以單策略/加密貨幣為主。工程完整，但與本賽題距離遠 |
| [The-Swarm-Corporation/AutoHedge](https://github.com/The-Swarm-Corporation/AutoHedge) | 6,234 / 896 | 2026-03-05 | none | MIT | Python | D | N | Y（4 個 worker） | N | N | N | N | N | avoid | 核心只有 main.py/prompts.py/workers.py，沒有回測，logs 只有兩個 csv。**高星 demo 標記** |
| [TraderAlice/OpenAlice](https://github.com/TraderAlice/OpenAlice) | 7,205 / 1,134 | 2026-10-04 | v0.94.1 | AGPL-3.0 | TypeScript | B | P | P | Y | ? | N | N | ? | pattern（guardian/安全 harness、broker 抽象） | 一人華爾街型 agent 產品，多家券商的 UTA 協定。AGPL，不宜複用程式碼 |
| [FinStep-AI/ContestTrade](https://github.com/FinStep-AI/ContestTrade) | 679 / 152 | 2025-12-22 | none | Apache-2.0 | Python | A | P（選股名單） | Y | N | P（內部競賽評分） | P | ? | N | pattern（內部競賽機制選訊號/agent） | 兩段式：Data Team 產出 textual factors，Research Team 依「交易信念」競賽並輸出候選股。適合借鏡「多個 analyst 產出、用歷史績效加權」 |
| [HKUSTDial/DeepFund](https://github.com/HKUSTDial/DeepFund) | 299 / 49 | 2026-03-18 | none | MIT | Python | A | Y（多 ticker 基金、每日 portfolio 更新） | Y | N | N | P（時序重播） | **Y（論文主題：Time Travel is Cheating）** | ? | pattern（PIT 紀律、SQLite 決策紀錄） | NeurIPS'25 D&B。用 DB 記錄每日 portfolio 與 LLM reasoning，方便追溯，跟本賽題的 auditability 很接近。強調 LLM 預訓練資料會洩漏未來，所以做即時評測 |
| [gta0804/MASS](https://github.com/gta0804/MASS) | 181 / 25 | 2025-11-17 | none | 0BSD | Python | A | **Y（端到端投組建構）** | Y（大量異質 agent 模擬） | P | P（backward optimization 調整 agent 分布） | Y（實驗） | ? | ? | pattern / 可能小量複用（0BSD 很寬鬆） | 以大量 investor agent 的分歧（stock_disagreement）形成投組權重，是少數直接做「多股投組」的 LLM 研究 |
| [Open-Finance-Lab/AgenticTrading](https://github.com/Open-Finance-Lab/AgenticTrading) | 767 / 156 | 2026-10-04 | none | NOASSERTION | Python | C/A | P | Y | P | N | Y | ? | ? | pattern（決策日誌、leaderboard vs baseline） | 「Agentic Trading Lab」教學/研究平台，配合 agentic trading 綜述。有 backtest、paper、對照 baseline |
| [kyky2347/ALTA](https://github.com/kyky2347/ALTA) | 1,020 / 121 | 2026-09-13 | v0.25.0 | Apache-2.0 | Python/JS | B（早期） | P（shadow book） | Y（scouts + reviewers + strategy desk） | Y | P | N | P（historical playback 與 live 分離） | P（策略台比較成本） | **pattern（evidence chain、獨立 reviewer、audit docs）** | 2026-08 才建立。設計理念與本賽題的 JSON evidence chain 最接近：證據 → 論點 → 反方審查 → 交易計畫，並保留不可改寫的紀錄 |
| [mnemox-ai/tradememory-protocol](https://github.com/mnemox-ai/tradememory-protocol) | 1,423 / 168 | 2026-10-02 | v0.5.6 | MIT | Python | B | N | N | **Y（outcome-weighted recall）** | P | P | N | N | 元件候選（決策審計軌跡 + memory，MCP） | 專做「decision audit trail + 持久記憶」的協定與 server，可參考 schema，必要時直接用（MIT） |
| [FreedomIntelligence/TwinMarket](https://github.com/FreedomIntelligence/TwinMarket) | 221 / 41 | 2026-03-07 | none | MIT | Python | A | N（市場模擬） | Y（大量投資人 agent） | P（belief） | N | N | N | P | pattern-only（低） | 用 LLM 投資人模擬市場湧現現象，屬社會模擬，與選股競賽關係弱 |
| [xbtlin/ai-berkshire](https://github.com/xbtlin/ai-berkshire) | 16,614 / 2,477 | 2026-09-27 | v1.0.0 | MIT | HTML | D/C | P（portfolio-review prompt） | P（prompt 中的多 agent） | N | N | N | N | N | pattern-only（研究 prompt 模板） | 幾乎全是 Claude Code/Codex prompts、skills 與研究報告，沒有交易引擎。**高星 prompt 集合標記** |
| [Lumiwealth/lumibot](https://github.com/Lumiwealth/lumibot) | 2,103 / 411 | 2026-10-03 | v4.6.4 | GPL-3.0 | Python | B | Y | P | N | N | Y | P | Y | backtest 備選（GPL 注意） | 老牌回測 + 實盤框架（12 家券商），近期加上 AI agent 介面。對台股支援有限 |
| [chrisworsey55/atlas-gic](https://github.com/chrisworsey55/atlas-gic) | 2,307 / 416 | 2026-09-22 | none | NOASSERTION | Python | D | P | Y（Darwinian 加權） | N | P（prompt 自我演化） | 宣稱有 | ? | ? | pattern-only（agent 權重依績效調整的概念） | src 只有 janus.py 與一個子目錄，results 是靜態 png/csv。大量績效宣稱，沒有可重現回測。**行銷型標記** |
| [tensortrade-org/tensortrade](https://github.com/tensortrade-org/tensortrade) | 7,195 / 1,335 | 2026-02-09 | v1.0.4 | Apache-2.0 | Python | A/C | P | N | N | N | Y（RL env） | N | Y | avoid | RL 交易環境，與 LLM 證據鏈需求不合，且 24 天賽期訓練樣本太少 |
| [Xtra-Computing/CryptoTrade](https://github.com/Xtra-Computing/CryptoTrade) | 166 / 36 | 2024-12-01 | none | NOASSERTION | Python | A | N（單幣） | N | P | **Y（generate_reflections）** | Y | P | P | pattern（reflection loop） | EMNLP'24。反思式 LLM 交易的乾淨參考實作，程式碼小、易讀 |
| [24mlight/A_Share_investment_Agent](https://github.com/24mlight/A_Share_investment_Agent) | 2,482 / 621 | 2026-05-26 | none | NOASSERTION | Python | C | N（單 ticker） | Y（含 debate_room） | P | N | Y（backtester.py） | N | N | pattern-only | ai-hedge-fund 的 A 股改寫版，加上 debate room 與 FastAPI 後端 |
| [olaxbt/ai-market-maker](https://github.com/olaxbt/ai-market-maker) | 2,115 / 301 | 2026-08-20 | none | AGPL-3.0 | Python | B | P | Y | P | N | Y | P | P | pattern（`schema/agent_trace.json`、policy 設定檔、OMS） | 加密貨幣為主的「Agentic hedge fund OS」。值得看的是 agent trace JSON schema 與 policy/risk 設定分離；AGPL |
| [flash131307/multi-agent-investment](https://github.com/flash131307/multi-agent-investment) | 207 / 26 | 2026-03-26 | none | MIT | Python | C | N | Y（3 agents） | P（RAG） | N | N | N | N | pattern（deterministic signal fusion） | LLM 只做分析，最終由確定性規則融合（decision_hub），概念上接近 hybrid 路線 |
| [LLMQuant/awesome-trading-agents](https://github.com/LLMQuant/awesome-trading-agents) | 873 / 140 | 2026-07-15 | none | CC0-1.0 | — | 清單 | — | — | — | — | — | — | — | reference | 後續延伸搜尋用的 awesome list |

**高星但只是 demo 或行銷的 repo**：HKUDS/AI-Trader（22.6k）、xbtlin/ai-berkshire（16.6k）、The-Swarm-Corporation/AutoHedge（6.2k）、chrisworsey55/atlas-gic（2.3k）。另外 hsliuping/TradingAgents-CN（32k）與 dexter（27.6k）雖然是真的程式碼，但前者授權混雜、後者沒有授權，都不宜直接複用程式碼。

## 2. 主表：確定性基礎設施（優化器 / 回測 / 資料 / Agent 框架）

| Repo | Stars / Forks | Last commit | Release | License | Lang | Class | 支援的投組功能 | Reuse role | 備註 |
|---|---|---|---|---|---|---|---|---|---|
| [PyPortfolio/PyPortfolioOpt](https://github.com/PyPortfolio/PyPortfolioOpt)（原 robertmartin8） | 6,073 / 1,176 | 2026-07-07 | v1.6.0 | MIT | Python | B | MVO、HRP、Black-Litterman（可把 LLM 觀點轉成 views）、權重上下限、**DiscreteAllocation（整數股數，可把價格乘 1000 處理整張）** | **optimizer（首選之一）** | 已移到新 org，仍有維護。Black-Litterman 很適合「LLM-as-analyst → 優化器」 |
| [dcajasn/Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) | 4,533 / 718 | 2026-10-04 | （GitHub 無 release，PyPI 有） | BSD-3-Clause | C++/Python | B | 數十種風險度量（CVaR、CDaR…）、線性約束、**cardinality（持股數 20–30）需 MIP solver**、tracking error | optimizer（約束最完整） | 檔數與 tracking/active 約束可直接建模 |
| [skfolio/skfolio](https://github.com/skfolio/skfolio) | 2,458 / 265 | 2026-10-03 | v1.4.11 | BSD-3-Clause | Python | B | sklearn 介面、cardinality、group 約束、**transaction costs、management fees**、walk-forward CV、預測先驗 | **optimizer + 驗證（首選）** | 新一代、測試完整，交易成本與 cardinality 是內建功能 |
| [cvxgrp/cvxportfolio](https://github.com/cvxgrp/cvxportfolio) | 1,293 / 303 | 2026-04-27 | 1.5.1 | GPL-3.0 | Python | B/A | 多期 MPO/SPO、**交易成本與持有成本模型**、內建回測 | optimizer + backtest（GPL：內部使用 OK） | Boyd 團隊。適合「每天重平衡 vs 交易成本」的權衡 |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | 9,273 / 1,184 | 2026-09-26 | v1.1.1 | Apache-2.0 + Commons Clause | Python | B | 向量化多資產回測、fees/slippage、group/cash sharing | backtest（快速掃參數） | Commons Clause 限制商業銷售；比賽使用無虞 |
| [mementum/backtrader](https://github.com/mementum/backtrader) | 23,388 / 5,295 | **2023-04-19** | none | GPL-3.0 | Python | B（停更） | 事件驅動、commission、sizer | avoid（停更） | 星數高但已三年沒維護；cloudQuant/backtrader 是活躍 fork |
| [stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | 1,951 / 331 | 2025-11-13 | 3.1.1 | Apache-2.0 | Python | B | Pipeline、commission/slippage 模型、交易日曆（exchange_calendars 有 XTAI） | backtest（偏重） | 需要建立 data bundle，對 24 天比賽成本偏高 |
| [pmorissette/bt](https://github.com/pmorissette/bt) | 2,993 / 500 | 2026-10-03 | v1.3.0 | MIT | Python | B | **投組重平衡型回測**（algo tree：選股 → 權重 → 重平衡）、commission | **backtest（最貼合投組重平衡）** | 輕量，適合「每日目標權重 → 回測 NAV」 |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | 29,613 / 3,919 | 2026-10-04 | v1.231.0 | LGPL-3.0 | Rust/Python | B | 高效能事件驅動，回測與實盤一致 | avoid（overkill） | 針對 HFT/執行層，本賽題不需要 |
| [openbq-org/OpenBB](https://github.com/openbq-org/OpenBB)（原 OpenBB-finance） | 73,839 / 7,638 | 2026-10-02 | ODP | NOASSERTION（舊版 AGPL） | Python | B | 資料聚合平台、MCP/agent 介面 | data（輔助，台股覆蓋有限） | org 已改名。台股基本面、法人資料仍以 FinMind 為主 |
| [FinMind/FinMind](https://github.com/FinMind/FinMind) | 2,829 / 445 | 2026-10-04 | 2.0.11 | Apache-2.0 | Python（repo 標 HTML） | B | 台股價量、財報、三大法人、融資券、月營收、新聞 | **data（台股主力）** | 免費額度有限，要注意財報/月營收的公告日（PIT） |
| [mlouielu/twstock](https://github.com/mlouielu/twstock) | 1,524 / 410 | 2026-04-23 | v1.5.1 | MIT | Python | B/C | TWSE/TPEx 價量與即時報價爬取 | data（備援/交叉驗證） | 輕量，但依賴交易所網頁，可能被限流 |
| [Sinotrade/Shioaji](https://github.com/Sinotrade/Shioaji) | 522 / 40 | 2026-09-29 | v1.7.7 | 無（SDK 封閉） | （docs/Dockerfile） | B | 永豐證券 API：行情、下單、帳務 | data/執行（多半不需要） | repo 主要是文件與 issue，SDK 是閉源 wheel。比賽如果是模擬撮合就用不到 |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 42,704 / 7,250 | 2026-10-03 | cli==0.4.32.dev0 | MIT | Python | B | 有狀態圖、checkpoint、human-in-the-loop | agent 框架（候選） | TradingAgents 系列都用它，checkpoint 有助於重播與審計 |
| [pydantic/pydantic-ai](https://github.com/pydantic/pydantic-ai) | 20,398 / 2,859 | 2026-10-03 | v2.54.0 | MIT | Python | B | 型別化 structured output、驗證重試、多模型（含 Gemini） | **agent 框架 / JSON evidence schema 驗證** | 與「必須輸出合法 JSON 證據鏈」的需求最直接對應 |
| [google/adk-python](https://github.com/google/adk-python) | 21,702 / 4,097 | 2026-10-04 | v2.11.0 | Apache-2.0 | Python | B | 多 agent 編排、tool、eval、Vertex AI Agent Engine 部署 | agent 框架（如果使用 GCP credits） | Gemini 原生，可配合主辦方提供的 Google Cloud token credits |

## 3. 國際生態的技術路線

1. **單一 LLM 產生訊號（single-LLM signal）**：LLM 讀新聞或財報，對單一標的輸出 buy/sell/hold 或分數（例如 FinGPT 情緒、dexter 研究結論、早期 Polymarket/crypto bots）。優點是簡單；缺點是沒有投組概念，輸出不穩，而且容易有 look-ahead（模型預訓練知識已包含未來）。對本賽題只能當成特徵來源之一。

2. **多 agent 辯論（multi-agent debate / 角色扮演投資公司）**：analyst（基本面/技術面/情緒/新聞）→ 多空研究員辯論 → trader → risk manager → PM（TradingAgents 系列、TradingAgents-CN、A_Share_investment_Agent、ai-hedge-fund、agno investment-team、AutoHedge）。這是最主流、星數最高的路線，但**絕大多數只做單一 ticker 決策**，沒有真正處理權重、現金比例、整張與交易成本；延伸到 150 檔時 token 成本按檔數線性放大。可借鏡的是角色分工與「反方審查」，用來產出證據鏈。

3. **記憶與反思（memory-reflection）**：分層記憶、依結果加權回憶、交易後自我反思（FinMem、FinCon、CryptoTrade、tradememory-protocol、dexter memory）。對 24 個交易日的短賽期，反思樣本極少，價值主要在**審計與可追溯**（記錄「當時知道什麼、為何決策」），而不是學習。

4. **強化學習（RL-based）**：FinRL、TensorTrade、FinRL-DeepSeek（LLM 情緒 + RL）。需要大量訓練與穩定環境，可解釋性差，跟 JSON 證據鏈不合；比賽期間樣本太少，**不建議作為主幹**。

5. **因子挖掘 agent（factor-mining / R&D agents）**：LLM 提出因子假說 → 寫程式 → 回測 → 迭代（RD-Agent、Qlib、QuantGPT、EvoQuant、Loopera、ContestTrade 的 textual factor）。適合**賽前離線**研究台股因子，產出的確定性因子可直接進入評分模型；比賽期間的即時決策不宜依賴自動生成的新因子（過擬合風險）。

6. **Hybrid quant + LLM**：確定性量化管線（資料、因子、風控、下單）為主，LLM 負責質化判讀或否決，最終由規則融合（flash131307/multi-agent-investment 的 deterministic fusion、Vibe-Trading 的 grounding/evidence gate、astra-quant-agent「多 LLM 分析 + 確定性風控」、ALTA 的 reviewer gate）。這是 2026 年的明顯趨勢：「LLM 不直接碰數字，數字要經過驗證」。

7. **LLM-as-analyst 餵給優化器（LLM views → optimizer）**：LLM 對每檔產生帶證據的 view（預期超額報酬、信心），透過 Black-Litterman 或分數調整的 expected returns，餵給 PyPortfolioOpt/skfolio/Riskfolio 在 cardinality（20–30 檔）、單檔上限、現金 <25%、交易成本、Active Share 等約束下求解，最後用整數張數離散化。MASS、DeepFund 是研究端最接近的例子，但開源生態中**沒有找到現成且完整的「LLM + 約束優化 + 整張 + Active Share」實作**，需要自行組合。

**對本賽題的結論（供決策參考，需人工複核）**：最適合的組合是路線 7 加上路線 6。用 FinMind 做 PIT 資料，以確定性因子和 LLM 的質化 views 形成分數，再用 skfolio 或 Riskfolio-Lib 處理約束、PyPortfolioOpt 做 DiscreteAllocation（或自寫整張 rounding），用 bt 或 vectorbt 回測，並以 pydantic-ai（或 ADK + Pydantic schema）強制 JSON 證據鏈格式。多 agent 辯論只用在 top-N 候選股的證據審查（參考 ALTA 的 reviewer 模式與 DeepFund 的 PIT 紀律），避免 150 檔都跑辯論。

## 4. Deep-dive 清單 metadata（只列資料，不分析）

| Repo | Stars / Forks | Last commit | Release | License | Lang |
|---|---|---|---|---|---|
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | 109,715 / 21,096 | 2026-10-03 | v0.6.0 | Apache-2.0 | Python |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | 63,854 / 11,222 | 2026-10-02 | v2.5.0 | MIT | Python |
| [microsoft/qlib](https://github.com/microsoft/qlib) | 49,127 / 7,758 | 2026-09-16 | v0.9.7 | MIT | Python |
| [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | 21,347 / 3,024 | 2026-09-23 | v1.0.0 | MIT | Jupyter |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 16,548 / 3,537 | 2026-09-28 | v0.3.8 | MIT | Jupyter |
| [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) | 14,840 / 1,947 | 2026-09-23 | v1.0.0 | MIT | Python |
| [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | 8,139 / 1,374 | 2026-09-28 | desktop-v0.1.0 | Apache-2.0 | Python |
| [pipiku915/FinMem-LLM-StockTrading](https://github.com/pipiku915/FinMem-LLM-StockTrading) | 962 / 195 | 2024-08-18 | none | MIT | Python |

（FinCon、FinAgent 沒有出現在本次搜尋前 30 名中，所以沒有查詢 metadata。）

## 5. 搜尋到但未列入主表的值得一提項目

- simonlin1212/TradingAgents-astock（3.6k）、KylinMountain/TradingAgents-AShare（851）、huygiatrng/AlpacaTradingAgent（274）、Tomortec/CryptoTradingAgents（281）：都是 TradingAgents 的衍生版本。
- LLMQuant/quant-mind（3.0k）：金融知識抽取/RAG 框架。HKUSTDial/DeepEar（286）：金融訊號追蹤 deep research。
- 0xethanq/astra-quant-agent（329）：「多 LLM 分析 + 確定性風控」，hybrid 範例（加密貨幣）。
- byteseek/Mira（274）：evidence-tracked investment thesis 工作台，與證據鏈概念接近。
- agno-agi/investment-team（170）：Agno + Gemini 的 7 analyst 範例（Demo 級）。
- 台股資料：Asoul/tsrtc、toomore/grs、Asoul/tsec 都已多年停更，不建議使用。

## 6. CSV-ready

```csv
repo,url,stars,forks,last_commit,latest_release,license,language,class,portfolio_support,multi_agent,memory,reflection,backtest,point_in_time,transaction_cost,reuse_role,notes
HKUDS/Vibe-Trading,https://github.com/HKUDS/Vibe-Trading,34585,5617,2026-10-03,v0.1.16,MIT,Python,B,P,Y,Y,P,Y,P,Y,pattern,"grounding/evidence gate; data-correctness changelog; too heavy"
HKUDS/AI-Trader,https://github.com/HKUDS/AI-Trader,22649,3425,2026-06-11,none,none,Python,D,N,P,N,N,N,N,N,avoid,"now ai4trade platform+skills; no license; high-star demo"
virattt/dexter,https://github.com/virattt/dexter,27642,3412,2026-09-23,v1.1.0,none,TypeScript,B,N,N,Y,P,N,N,N,pattern,"single-company deep research agent; no license"
hsliuping/TradingAgents-CN,https://github.com/hsliuping/TradingAgents-CN,32145,6719,2026-09-22,none,NOASSERTION,Python,B,N,Y,P,P,P,N,N,pattern,"TradingAgents CN fork; mixed/proprietary license"
ValueCell-ai/valuecell,https://github.com/ValueCell-ai/valuecell,11019,1802,2026-02-11,v0.1.20,Apache-2.0,Python,C,P,Y,P,N,N,N,N,pattern,"multi-agent finance platform; no backtest; stale since Feb"
OpenByteInc/QuantDinger,https://github.com/OpenByteInc/QuantDinger,12433,2532,2026-10-01,v5.5.2,Apache-2.0,Python,B,P,P,N,N,Y,P,Y,avoid,"self-hosted AI trading OS; crypto/single-strategy"
The-Swarm-Corporation/AutoHedge,https://github.com/The-Swarm-Corporation/AutoHedge,6234,896,2026-03-05,none,MIT,Python,D,N,Y,N,N,N,N,N,avoid,"few files; no backtest; high-star demo"
TraderAlice/OpenAlice,https://github.com/TraderAlice/OpenAlice,7205,1134,2026-10-04,v0.94.1,AGPL-3.0,TypeScript,B,P,P,Y,?,N,N,?,pattern,"guardian/safety harness; broker abstraction; AGPL"
FinStep-AI/ContestTrade,https://github.com/FinStep-AI/ContestTrade,679,152,2025-12-22,none,Apache-2.0,Python,A,P,Y,N,P,P,?,N,pattern,"internal contest selects factors/agents; candidate stock lists"
HKUSTDial/DeepFund,https://github.com/HKUSTDial/DeepFund,299,49,2026-03-18,none,MIT,Python,A,Y,Y,N,N,P,Y,?,pattern,"NeurIPS25 live fund arena; anti time-travel; DB logs reasoning"
gta0804/MASS,https://github.com/gta0804/MASS,181,25,2025-11-17,none,0BSD,Python,A,Y,Y,P,P,Y,?,?,pattern,"multi-agent simulation for portfolio construction"
Open-Finance-Lab/AgenticTrading,https://github.com/Open-Finance-Lab/AgenticTrading,767,156,2026-10-04,none,NOASSERTION,Python,C,P,Y,P,N,Y,?,?,pattern,"agentic trading lab; decision logs; baseline leaderboard"
kyky2347/ALTA,https://github.com/kyky2347/ALTA,1020,121,2026-09-13,v0.25.0,Apache-2.0,Python,B,P,Y,Y,P,N,P,P,pattern,"evidence->thesis->reviewer->plan; audit docs; very new"
mnemox-ai/tradememory-protocol,https://github.com/mnemox-ai/tradememory-protocol,1423,168,2026-10-02,v0.5.6,MIT,Python,B,N,N,Y,P,P,N,N,component,"decision audit trail + memory MCP"
FreedomIntelligence/TwinMarket,https://github.com/FreedomIntelligence/TwinMarket,221,41,2026-03-07,none,MIT,Python,A,N,Y,P,N,N,N,P,pattern,"LLM investor market simulation"
xbtlin/ai-berkshire,https://github.com/xbtlin/ai-berkshire,16614,2477,2026-09-27,v1.0.0,MIT,HTML,D,P,P,N,N,N,N,N,pattern,"prompt/skill + reports collection; no engine; high-star"
Lumiwealth/lumibot,https://github.com/Lumiwealth/lumibot,2103,411,2026-10-03,v4.6.4,GPL-3.0,Python,B,Y,P,N,N,Y,P,Y,backtest,"backtest+live broker framework; GPL"
chrisworsey55/atlas-gic,https://github.com/chrisworsey55/atlas-gic,2307,416,2026-09-22,none,NOASSERTION,Python,D,P,Y,N,P,claimed,?,?,pattern,"Darwinian agent weights; thin code; performance claims"
tensortrade-org/tensortrade,https://github.com/tensortrade-org/tensortrade,7195,1335,2026-02-09,v1.0.4,Apache-2.0,Python,A,P,N,N,N,Y,N,Y,avoid,"RL env; unsuitable for 24-day evidence-chain"
Xtra-Computing/CryptoTrade,https://github.com/Xtra-Computing/CryptoTrade,166,36,2024-12-01,none,NOASSERTION,Python,A,N,N,P,Y,Y,P,P,pattern,"EMNLP24 reflection loop reference"
24mlight/A_Share_investment_Agent,https://github.com/24mlight/A_Share_investment_Agent,2482,621,2026-05-26,none,NOASSERTION,Python,C,N,Y,P,N,Y,N,N,pattern,"ai-hedge-fund A-share port; debate room"
olaxbt/ai-market-maker,https://github.com/olaxbt/ai-market-maker,2115,301,2026-08-20,none,AGPL-3.0,Python,B,P,Y,P,N,Y,P,P,pattern,"agent_trace.json schema; policy configs; crypto; AGPL"
flash131307/multi-agent-investment,https://github.com/flash131307/multi-agent-investment,207,26,2026-03-26,none,MIT,Python,C,N,Y,P,N,N,N,N,pattern,"deterministic signal fusion of LLM agents"
LLMQuant/awesome-trading-agents,https://github.com/LLMQuant/awesome-trading-agents,873,140,2026-07-15,none,CC0-1.0,,list,-,-,-,-,-,-,-,reference,"awesome list"
PyPortfolio/PyPortfolioOpt,https://github.com/PyPortfolio/PyPortfolioOpt,6073,1176,2026-07-07,v1.6.0,MIT,Python,B,Y,N,N,N,N,N,P,optimizer,"MVO/HRP/Black-Litterman; DiscreteAllocation for lots"
dcajasn/Riskfolio-Lib,https://github.com/dcajasn/Riskfolio-Lib,4533,718,2026-10-04,none(PyPI),BSD-3-Clause,C++/Python,B,Y,N,N,N,P,N,P,optimizer,"many risk measures; cardinality via MIP"
skfolio/skfolio,https://github.com/skfolio/skfolio,2458,265,2026-10-03,v1.4.11,BSD-3-Clause,Python,B,Y,N,N,N,Y,P,Y,optimizer,"sklearn API; cardinality; tx costs; walk-forward"
cvxgrp/cvxportfolio,https://github.com/cvxgrp/cvxportfolio,1293,303,2026-04-27,1.5.1,GPL-3.0,Python,B,Y,N,N,N,Y,P,Y,optimizer+backtest,"multi-period w/ tx & holding costs; GPL"
polakowo/vectorbt,https://github.com/polakowo/vectorbt,9273,1184,2026-09-26,v1.1.1,Apache-2.0+CommonsClause,Python,B,Y,N,N,N,Y,N,Y,backtest,"fast vectorized; fees/slippage"
mementum/backtrader,https://github.com/mementum/backtrader,23388,5295,2023-04-19,none,GPL-3.0,Python,B,Y,N,N,N,Y,N,Y,avoid,"unmaintained since 2023"
stefan-jansen/zipline-reloaded,https://github.com/stefan-jansen/zipline-reloaded,1951,331,2025-11-13,3.1.1,Apache-2.0,Python,B,Y,N,N,N,Y,Y,Y,backtest,"heavy data bundles; XTAI calendar"
pmorissette/bt,https://github.com/pmorissette/bt,2993,500,2026-10-03,v1.3.0,MIT,Python,B,Y,N,N,N,Y,N,Y,backtest,"rebalance-oriented portfolio backtest"
nautechsystems/nautilus_trader,https://github.com/nautechsystems/nautilus_trader,29613,3919,2026-10-04,v1.231.0,LGPL-3.0,Rust,B,Y,N,N,N,Y,Y,Y,avoid,"HFT-grade overkill"
openbq-org/OpenBB,https://github.com/openbq-org/OpenBB,73839,7638,2026-10-02,ODP,NOASSERTION,Python,B,N,N,N,N,N,N,N,data,"data platform; limited TW coverage; org renamed"
FinMind/FinMind,https://github.com/FinMind/FinMind,2829,445,2026-10-04,2.0.11,Apache-2.0,Python,B,N,N,N,N,N,P,N,data,"Taiwan market data primary; watch announce dates"
mlouielu/twstock,https://github.com/mlouielu/twstock,1524,410,2026-04-23,v1.5.1,MIT,Python,B,N,N,N,N,N,N,N,data,"TWSE/TPEx scraper backup"
Sinotrade/Shioaji,https://github.com/Sinotrade/Shioaji,522,40,2026-09-29,v1.7.7,none,closed SDK,B,N,N,N,N,N,N,N,data/exec,"broker API; closed wheel; likely unnecessary"
langchain-ai/langgraph,https://github.com/langchain-ai/langgraph,42704,7250,2026-10-03,cli==0.4.32.dev0,MIT,Python,B,-,Y,Y,-,-,-,-,agent-framework,"stateful graphs; checkpoints"
pydantic/pydantic-ai,https://github.com/pydantic/pydantic-ai,20398,2859,2026-10-03,v2.54.0,MIT,Python,B,-,Y,-,-,-,-,-,agent-framework,"typed structured output for JSON evidence"
google/adk-python,https://github.com/google/adk-python,21702,4097,2026-10-04,v2.11.0,Apache-2.0,Python,B,-,Y,Y,-,-,-,-,agent-framework,"Gemini/Vertex native; fits GCP credits"
```
