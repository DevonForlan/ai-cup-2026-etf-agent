# TradingAgents（TauricResearch/TradingAgents）

> 存取日期：2026-10-04｜檢視版本：`main` @ `1394a3f`（v0.6.0，2026-10-03）｜方法：shallow clone 至 scratchpad 後逐檔閱讀原始碼、CHANGELOG、README、論文 HTML、GitHub issues 頁面。未安裝、未執行程式。

## Metadata

| 欄位 | 值 |
|---|---|
| URL | https://github.com/TauricResearch/TradingAgents |
| Stars / Forks / Watchers | 109,714 / 21,096 / 823（GitHub API，2026-10-04） |
| Created | 2024-12-28 |
| Last commit | 2026-10-03（Merge PR #1478, release 0.6.0） |
| Latest release | v0.6.0（2026-10-03）；前版 v0.5.2（09-29）、v0.5.1（09-24） |
| Maintenance | 非常活躍（每週數次 release、大量測試、CHANGELOG 完整、open issues 77） |
| License | Apache-2.0 |
| Language | Python（>=3.11） |
| Framework | LangGraph（StateGraph + ToolNode + sqlite checkpointer）+ LangChain |
| LLM providers | OpenAI、Anthropic、Google、xAI、DeepSeek、Qwen、GLM、Kimi、MiniMax、Ollama、OpenRouter、Azure、Bedrock、任何 OpenAI-compatible（Groq/NVIDIA/Mistral）；quick/deep 兩層可用不同 provider |
| Paper | arXiv 2412.20138（v7, 2025-06）；同組織後續 Trading-R1（arXiv 2509.11420） |

### Capability flags

| Capability | 評等 | Evidence |
|---|---|---|
| market_data | Yes | `tradingagents/dataflows/vendors/yahoo/ohlcv.py`, `alpha_vantage/stock.py`, `agents/tools.py::get_stock_data` |
| fundamental | Yes | `vendors/sec_edgar.py`（as-filed）、`yahoo/fundamentals.py`、`tools.py::get_balance_sheet/get_cashflow/get_income_statement` |
| technical | Yes | `tools.py::get_indicators`, `vendors/alpha_vantage/indicator.py`, `agents/analysts/market_analyst.py` |
| news | Yes | `vendors/yahoo/news.py`, `alpha_vantage/news.py`, `tools.py::get_news/get_global_news` |
| sentiment | Yes | `agents/analysts/sentiment_analyst.py`, `vendors/reddit.py`, `vendors/stocktwits.py`, `agents/post_screen.py`（TypeSafe Jev 篩選） |
| portfolio_management | Partial | `tradingagents/portfolio.py`（僅把持倉/現金 render 成文字給 LLM），`agents/managers/portfolio_manager.py`（單票 5 級評等） |
| multi_stock_portfolio | No | 一次 `propagate(ticker, date)` 只處理一檔；`backtest.py` 明言 "It is not a portfolio simulator, and must not grow one" |
| position_sizing | Partial | `agents/schemas.py::TraderProposal.position_sizing`（自由文字 str，無數值計算） |
| risk_management | Partial | `agents/risk_mgmt/{aggressive,conservative,neutral}_debator.py`：LLM 辯論，無任何數值風控 |
| memory | Yes | `tradingagents/memory/log.py`（append-only markdown decision log） |
| reflection | Yes | `memory/reflection.py`, `memory/settlement.py`（持有 N 日後算 raw/alpha return → LLM 寫 2-4 句 lesson） |
| backtesting | Partial | `tradingagents/backtest.py`：ticker×date grid 逐格跑，以 rating 方向命中率/平均 alpha 評分，無資金曲線 |
| simulation | No | 無 broker/ledger；README 宣稱 "order will be sent to the simulated exchange" 但程式碼中不存在 |
| tool_calling | Yes | `agents/tools.py`（@tool）、`graph/setup.py::_analyst_graph`（ToolNode，`max_tool_rounds`=20） |
| structured_output | Yes | `agents/schemas.py`（ResearchPlan/TraderProposal/PortfolioDecision/SentimentReport Pydantic）、`agents/structured.py` |
| audit_log | Yes | `graph/trading_graph.py`（`full_states_log_{date}.json` 含 `run_settings`）、`reporting.py`、`report_html.py`、`cli/stats_handler.py` |
| point_in_time_data | Yes（盡力而為） | `dataflows/date_window.py`（as_of clamp、half-open window、withhold_live_profile）、`memory/log.py::get_past_context(as_of)`；tests `test_*_lookahead.py` |
| transaction_cost | No | 全 repo 無 fee/tax/slippage |
| portfolio_constraints | No | 無權重上限、持股數、現金比例等約束 |
| rebalancing | No | 無 |

## Architecture

LangGraph 單一 `StateGraph(AgentState)`（`graph/setup.py`）：

1. **Analyst Team（平行）**：market / sentiment(social) / news / fundamentals，每位 analyst 是一個子圖（agent ↔ ToolNode，私有 message history，超過 `max_tool_rounds` 強制 wrap-up）。同時平行跑 **Memory Log** 節點（結算過去決策）。
2. **Researcher debate**：Bull ↔ Bear 輪流（`conditional_logic.should_continue_debate`，`max_debate_rounds` 預設 1 → 各 1 次）→ **Research Manager**（deep model，structured `ResearchPlan`，5 級評等）。
3. **Trader**（quick model）：structured `TraderProposal`（Buy/Hold/Sell + entry/stop/position_sizing 文字）。
4. **Risk debate**：Aggressive → Conservative → Neutral 輪流（`max_risk_discuss_rounds` 預設 1）。
5. **Portfolio Manager**（deep model）：structured `PortfolioDecision`（Buy/Overweight/Hold/Underweight/Sell + executive_summary + investment_thesis + price_target + time_horizon），讀取 memory 的 `past_context`。

LLM 分 quick（analysts/researchers/trader/debaters）與 deep（Research Manager、Portfolio Manager）兩層（`default_config.py`）。

## Data Flow

- Vendor router（`dataflows/router.py`）依 `data_vendors` 設定串接：OHLCV/指標預設 yfinance，fundamentals 預設 `sec_edgar,yfinance`，news 預設 yfinance，macro=FRED，prediction markets=Polymarket；失敗回報 "unavailable" 而非空。
- 所有 tool 由 state 取 instrument，模型無法改查其他代號（v0.5.2）。
- Point-in-time：`date_window.as_of` 把模型要求的日期夾到 trade_date；新聞/社群依 UTC 半開區間裁切；歷史日期不給無 filing date 的 Yahoo/AV 報表與 insider；FRED 依 vintage。
- 台股：`default_config.benchmark_map` 已有 `.TW`/`.TWO` → `^TWII`；資料透過 yfinance 可取得 `2330.TW` 類代號，但無 TWSE/TPEx 官方資料、無三大法人、無月營收；Issue #1156 有人提議 Taiwan vendor（仍 open，無維護者回應）。

## Decision Flow

輸入 `(ticker, trade_date, asset_type, portfolio?)` → 4 份 analyst 報告 → Bull/Bear 辯論 → Research Manager 計畫 → Trader 提案 → 三方風險辯論 → PM 5 級評等。輸出是**單一股票的評等與文字論述**，不是下單數量。`rating.py` 只從明確的 `Rating:` 標籤解析，否則回 `REVIEW` sentinel（不默默變成 Hold）——這點對自動化很有價值。

## Portfolio Logic

- 沒有組合建構。`portfolio.py::PortfolioContext` 只是把 cash/positions 轉成 prompt 文字（"Portfolio at the analysis date: ..."），讓 Trader/風控/PM「知道」持倉；不做權重、不做現金帳、不做下單。
- `backtest.py` docstring 明確寫：「Turning a rating into a filled order needs a quantity, a fill price and a cash ledger, none of which the system has」。
- 結論：**只做 single-ticker BUY/OVERWEIGHT/HOLD/UNDERWEIGHT/SELL**，150→20-30 檔的選股、權重、整股、TSMC 25% 上限、現金 <25% 全部需要自建。

## Risk

風險管理完全是 LLM 角色扮演辯論（aggressive/conservative/neutral），無波動度、相關性、VaR、部位上限等數值計算。Trader 會被要求以技術報告中的 ATR/支撐壓力給 stop-loss 價位（`trader.py`），但沒有執行層去強制。

## Memory

- v0.2.4 起以「persistent decision log」取代舊版 per-agent BM25 `FinancialSituationMemory`（更早期是 ChromaDB embedding）。現行：`memory/log.py` append-only markdown（`~/.tradingagents/memory/trading_memory.md`），每筆 `[date | ticker | rating | pending]` + DECISION 全文。
- Settlement（`memory/settlement.py`）：持有 `holding_period_days`（預設 5 交易日）後抓收盤價計算 raw return 與相對 benchmark alpha，呼叫 LLM 產生 2-4 句 reflection，寫回並記錄 `resolution_date`。
- 只有 PM 讀 memory：同 ticker 最近 5 筆 + 跨 ticker 3 筆 lesson；歷史 run 只看 `resolved <= as_of` 的 lesson（#1251 修正 look-ahead）。
- 有檔案鎖、冪等（同 ticker+date 只記一次）。

## Backtest

- `run_backtest(tickers, dates, config)`：每個 (ticker, date) 獨立跑完整 graph，結果寫入專屬 memory log；`summarize()` 依評等統計方向命中率與平均 alpha（精度 0.1%）。
- 無資金曲線、無交易成本、無部位、無再平衡；且作者自己在 summary 註明「One model sampling per cell, and text feeds are not archived, so these figures are indicative rather than repeatable」。
- 成本：每格約十數次 LLM 呼叫 + 20+ tool calls（論文自述 11 calls & 20+ tool calls/prediction）。150 檔×每日 → 每日 ~1,650+ LLM calls，對比賽每日 19:30–08:55 窗口的成本與時間都是負擔。

## Prompts

- 在各 agent 檔案中以 f-string 撰寫（例：`agents/researchers/bull_researcher.py`、`agents/managers/portfolio_manager.py`）。PM prompt 明確要求「conflict alone is not a reason to Hold」、「Weigh the analysts on their merits, independent of speaking order」，並有 `NO_EXTERNAL_TOOLS`、`get_language_instruction()`（可輸出繁中）。
- 有 `tests/test_prompt_integrity.py`、`test_structured_agent_prompts.py` 保護 prompt 結構。

## Paper（arXiv 2412.20138）實驗設定與弱點

- 標的：AAPL、GOOGL、AMZN（主表），文中亦提 NVDA/MSFT/META；**每檔獨立評估**，非組合。
- 期間：2024-01-01 ~ 2024-03-29（約 3 個月）；deep model o1-preview，quick model gpt-4o / gpt-4o-mini。
- Baselines：Buy&Hold、MACD、KDJ+RSI、ZMR、SMA。指標 CR/ARR/SR/MDD；AAPL CR 26.62%、SR 8.21、MDD 0.91%（GOOGL CR 24.36%、AMZN 23.21%）。
- 弱點：(1) 3 個月極短窗口、單次 run、無 seed/重複；(2) 未說明部位大小與交易成本；(3) Sharpe 8.21 在 3 個月內極不穩健；(4) 只有大型美股科技股；(5) 雖宣稱無 look-ahead（只餵當日前資料），但未處理 LLM 預訓練知識洩漏（Issue #805 專門討論，無維護者回應）；(6) 論文描述的 ReAct/通訊協定與現行程式差異很大（現行 code 已大幅演進）。

## Strength

1. 工程品質高：~100 個測試檔、point-in-time 防洩漏規則集中化（`date_window.py`）、`REVIEW` sentinel、checkpoint resume、run_settings 指紋，是目前開源 LLM-trading 中可稽核性最好的之一。
2. Structured output（Pydantic schemas）+ free-text fallback 機制成熟，多 provider 支援廣，可輸出中文。
3. Memory/reflection 設計簡單可審（markdown log + 明確 resolution date），容易移植成我們的 evidence chain。

## Weakness

1. 本質是**單股票研究/評等器**，沒有組合、權重、現金、成本、約束——正是本賽題核心。
2. LLM 呼叫量大、延遲高；150 檔每日全跑不可行。
3. 決策非決定性（temperature 預設 None，多輪辯論放大變異），重現性只能靠 log，不能靠重跑。
4. 台股資料只有 yfinance；無三大法人、融資券、月營收、TWSE 官方 VWAP。
5. README 對 risk team/「simulated exchange」的描述超出程式碼。

## Reuse potential（4/5，以「模式」為主）

值得借用：
- `dataflows/date_window.py` 的 as_of clamp 與 half-open window 規則 → 我們的資料層 point-in-time 守門。
- `agents/schemas.py` + `agents/structured.py` 的 structured-output-with-fallback 模式 → D-Plan JSON 各階段（observation/inference/decision）。
- `agents/rating.py` 的「無法解析就 REVIEW，不默認 Hold」原則 → 我們應改為「無法解析就沿用前日持倉/規則化 fallback」。
- `memory/log.py` + `settlement.py` 的「決策→N 日後結算→反思→point-in-time 注入」流程。
- `run_settings` + `full_states_log` 的可追溯紀錄。
- Bull/Bear 辯論只用在**少數候選股**（例如量化初篩後 Top 40 中的邊際股），控制成本。

避免：
- 不要把整個 graph 套到 150 檔每日跑；不要讓 LLM 決定股數/權重；不要用其 backtest 當績效證據。

## Competition fit：2/5

能提供單股深度分析與審計紀錄，但比賽要求的 20-30 檔整股組合、權重上限、現金下限、成本、VWAP 成交、Active Share 全部需自建。適合作為「候選股質化審查」子模組。

## Classification：A — Research-grade（偏向 B）

理由：源自學術論文、有可重現性/look-ahead 意識與大量測試，工程化程度已接近 production；但功能定位仍是研究框架（作者明確拒絕加入組合模擬器），不是可直接上線的交易系統。

## README 宣稱 vs 程式碼

- README "Risk Management... Continuously evaluates portfolio risk by assessing market volatility, liquidity" → 程式中只有 LLM 辯論，無數值計算。
- README "If approved, the order will be sent to the simulated exchange and executed" → 無任何 exchange/broker 模組；`backtest.py` 明言非模擬器。
- 論文主表為單檔結果，非組合績效。

## Evidence（存取日期 2026-10-04）

- Repo / API：https://github.com/TauricResearch/TradingAgents ；https://api.github.com/repos/TauricResearch/TradingAgents （commits、releases）
- 程式檔：`tradingagents/graph/setup.py`、`graph/conditional_logic.py`、`graph/trading_graph.py`、`agents/state.py`、`agents/schemas.py`、`agents/rating.py`、`agents/trader/trader.py`、`agents/managers/portfolio_manager.py`、`agents/researchers/bull_researcher.py`、`agents/tools.py`、`agents/post_screen.py`、`portfolio.py`、`backtest.py`、`memory/log.py`、`memory/reflection.py`、`memory/settlement.py`、`dataflows/date_window.py`、`default_config.py`、`llm_clients/model_catalog.py`、`CHANGELOG.md`、`README.md`
- Paper：https://arxiv.org/html/2412.20138 ；Trading-R1：https://arxiv.org/abs/2509.11420
- Issues：https://github.com/TauricResearch/TradingAgents/issues ；#1156 https://github.com/TauricResearch/TradingAgents/issues/1156 ；#805 https://github.com/TauricResearch/TradingAgents/issues/805
- 衍生 fork（參考）：hsliuping/TradingAgents-CN（~30k stars，A 股/港股，FastAPI+Vue）https://ossinsight.io/analyze/hsliuping/TradingAgents-CN ；TradingAgents-astock https://www.sourcepulse.org/projects/29855634 （兩者皆未逐檔審閱，僅記錄存在）
