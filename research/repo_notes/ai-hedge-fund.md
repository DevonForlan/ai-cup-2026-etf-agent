# ai-hedge-fund（virattt/ai-hedge-fund）

> 存取日期：2026-10-04｜檢視版本：`main` @ `78b779c`（v2.5.0，2026-10-02）；另檢視舊架構 tag `v2026.7.10`（含 v1 `src/agents/portfolio_manager.py`、`risk_manager.py`）。方法：shallow clone 至 scratchpad 後閱讀原始碼。未安裝、未執行。

## 重要背景

此 repo 在 2026 年 7 月之後**整個重寫**：舊版（多數網路文章描述的那版，`src/agents/*` + LangGraph + 18 位名人投資人 agent + LLM portfolio manager）已從 main 移除；現行 v2 是 `hedge_fund/` 套件，「alpha model → deterministic portfolio construction → deterministic risk limits → execution → hash-chained ledger」。本筆記同時評兩版。

## Metadata

| 欄位 | 值 |
|---|---|
| URL | https://github.com/virattt/ai-hedge-fund |
| Stars / Forks / Watchers | 63,854 / 11,222 / 672（2026-10-04） |
| Created | 2024-11-29 |
| Last commit | 2026-10-02（"Bump version to 2.5.0"，co-authored by Cursor agent） |
| Latest release | v2.5.0（2026-10-02）；v2.4.1（09-25）、v2.4.0（09-24）；舊 CalVer tag v2026.5.9–v2026.7.10 |
| Maintenance | 活躍（單一作者主導、大量 AI 協作 commit、open issues 177） |
| License | MIT |
| Language | Python（^3.11）；TUI 用 Textual |
| Framework | v2：自建純 Python pipeline（無 LangGraph），LangChain 只做 LLM client；v1（舊 tag）：LangGraph |
| LLM providers | Anthropic、OpenAI、DeepSeek、Google、xAI、Kimi、TypeSafe(Jev)；Ollama 尚未移植到 v2（ROADMAP） |
| Data | 僅 Financial Datasets API（financialdatasets.ai，美股；需付費 key） |
| Paper | 無 |

### Capability flags（v2 main）

| Capability | 評等 | Evidence |
|---|---|---|
| market_data | Yes | `hedge_fund/data/client.py`（FDClient prices）、`data/cached.py` |
| fundamental | Yes | `hedge_fund/features/snapshot.py`（以 filing_date 過濾的 point-in-time FundamentalsSnapshot） |
| technical | No | v2 無技術指標 alpha（ROADMAP：Momentum/Mean reversion ⬜；v1 有 `src/agents/technicals.py`） |
| news | Partial | `data/models.py::CompanyNews` 有資料模型，但 v2 alpha 未使用；v1 有 `news_sentiment.py` |
| sentiment | No（v2）/ Partial（v1 `sentiment.py`） | — |
| portfolio_management | Yes | `hedge_fund/portfolio/construction.py::blend_signals`、`portfolio/validation.py::validate_targets` |
| multi_stock_portfolio | Yes | `pipeline/stages.py::assess_fund`（對 universe 全部 ticker 產 signal → 權重 → netted book） |
| position_sizing | Yes | 權重 ∝ conviction score，正規化到 gross_target；`pipeline/execution.py::build_orders`（`int(weight*equity/mark)` 向零取整） |
| risk_management | Partial | `risk/limits.py::apply_limits`（max_position_pct、max_gross_exposure；clamp 釋出的權重留在現金不重分配）；無波動度/相關性（v1 有） |
| memory | No | 無跨期學習記憶（有 prompt cache 與 ledger，但非 memory） |
| reflection | No | — |
| backtesting | Yes | `backtesting/fund.py::backtest_fund`（advance 迴圈、equity curve vs benchmark、Sharpe、MDD）、`backtesting/engine.py`（單一 alpha harness） |
| simulation | Yes | `brokers/sim.py`（SimBroker）、`brokers/paper.py`、`paper/ledger.py`、`paper/tick.py` |
| tool_calling | No | LLM 只接收 snapshot 文字回 JSON，無工具呼叫 |
| structured_output | Partial | `signals/llm_agent.py::_parse`（`extract_json` + 驗證 signal/confidence/reasoning；非 provider-native schema） |
| audit_log | Yes | `paper/ledger.py`（SessionRecord hash-chain、prev_hash 驗證）、`llm/cache.py`（每次 prompt+response 持久化）、`risk/limits.py::ClampEvent` |
| point_in_time_data | Partial | `features/snapshot.py`（filing_date 過濾）、`LLMAgent(blind=True)` 遮蔽 ticker/日期/金額；ROADMAP 自標 Point-in-time 🚧 |
| transaction_cost | No | `brokers/sim.py` docstring："Slippage/costs are a declared future addition"；v1 backtester 亦無手續費 |
| portfolio_constraints | Partial | 單檔上限、gross 上限、long_only/long_short/dollar_neutral；無持股數下限/上限、現金下限、整張 lot |
| rebalancing | Yes | `fund/spec.py` cadence daily/weekly/monthly；`pipeline/session.py` 決策於 T close，T+1 close 執行 |

## Architecture（v2）

```
Fund(mandate YAML) = allocator over STRATEGIES
STRATEGY = blend policy over ANALYSTS (AlphaModel)
ANALYST  = LLM persona (buffett/graham/munger/lynch/druckenmiller) 或 quant (PEAD) → Signal(value∈[-1,1], reasoning)
advance(session): reconcile → execute pending decision (T+1 close) → mark → assess (T close)
```
- `hedge_fund/fund/example.yaml`：strategies（權重、models 權重、blend mode）、`risk.max_position_pct`、`max_gross_exposure`、`capital`、`rebalance`、`benchmark`。
- `pipeline/session.py`：FundState 由 ledger fold 而得；broker 與 ledger 帳不符直接 raise `BookMismatch`；kill switch `FundHalted`。

## Data Flow

FDClient（Financial Datasets REST）→ `data/cached.py` 快取 → `features/snapshot.py` 建 point-in-time fundamentals（以 filing_date 篩選，content_hash 排除 as_of，兩次 filing 之間的日子共用同一 hash → prompt cache 命中）→ LLM persona。市場日曆由 benchmark（SPY）實際 bar 推導（`data/sessions.py`）。**無台股資料來源**；要用需實作 `data/protocol.py::DataClient`。

## Decision Flow

每檔 × 每 persona 一次 LLM 呼叫 → `{"signal": bullish|neutral|bearish, "confidence": 0-100, "reasoning"}` → value = sign×conf/100 → `blend_signals` 加權平均（abstain 排除）→ long_only 時 score=max(conviction,0) → 依 score/Σscore × gross_target 得權重 → `apply_limits` clamp → `validate_targets` 從原始 signals 重新計算比對（防止中間被竄改）→ `build_orders`（先賣後買、字母序、取整股）。LLM 對帳本的影響止於 Signal。

## Portfolio Logic

- **v2（main）**：真正的多股組合、權重、現金殘留、再平衡、T+1 執行；但 sizing 是「conviction 比例」，無風險模型、無最佳化；整股僅到 1 股（台股需改為 1000 股 lot）。
- **v1（tag v2026.7.10，`src/agents/portfolio_manager.py`）**：先以 deterministic `compute_allowed_actions` 算每檔可買/賣/放空/回補的最大股數（受 risk manager 的 `remaining_position_limit` 與現金/保證金限制），再交給 LLM「Pick one allowed action per ticker and a quantity ≤ the max」，輸出 `{action, quantity, confidence, reasoning}`。即 LLM 在硬約束內選數量——是很好的「LLM 決策 + 程式護欄」範式，但缺乏組合層面目標（總權重、持股數）。

## Risk

- v2 `risk/limits.py`：單檔 |w| ≤ max_position_pct，再 gross 等比例縮放；每次觸發記錄 `ClampEvent`（可審計）；不重分配被砍掉的權重（設計理念「Conviction requests, risk disposes」）。
- v1 `src/agents/risk_manager.py`：**波動度 × 相關性調整的單檔上限**。`calculate_volatility_adjusted_limit`：base 20%，年化波動 <15% → ×1.25（25%），15–30% 線性降到 ~12.5%，30–50% 降到 ~5%，>50% 最低；`calculate_correlation_multiplier`：平均相關 ≥0.8 → ×0.7、0.6–0.8 → ×0.85、<0.2 → ×1.1；再取 min(剩餘額度, 現金)。缺價格時用 5% 日波動 fallback。純啟發式、門檻寫死，未經驗證，但可直接改造成台股版本。

## Memory

無長期學習記憶。`llm/cache.py` PromptCache 以 (agent, model, system, user) 為 key 持久化每次 prompt/response——等於可重放的決策快取（同 snapshot 不重複付費、可重現）。

## Backtest

- `backtesting/fund.py::backtest_fund`：以 benchmark session 為格，loop `advance`，SimBroker 以收盤價完整成交；輸出 NAV、benchmark NAV、Sharpe、MDD、excess return。
- 缺點：**零手續費、零稅、零滑價**；成交價為收盤價（非 VWAP）；cash 可為負（不強制）；Point-in-time 自標未完成；LLM persona 在歷史期間仍有預訓練知識洩漏風險（作者以 `blind=True` 遮蔽 ticker/日期/金額緩解，是三個 repo 中唯一正面處理此問題者）。
- v1 backtester（`src/backtesting/engine.py`）：同一天收盤價決策並成交（同 bar 決策/成交），無成本。
- `event_study/`：市場模型 CAR 分析，可用於驗證事件型 alpha。

## Prompts

Persona 只是一段 system prompt（例 `signals/buffett.py`：checklist + Signal rules + confidence scale + Hard rules「Reason ONLY from the data provided. Treat the most recent filing date shown as the present day」+ JSON schema）。簡潔、可複製。

## Strength

1. v2 架構乾淨：LLM 只產 view，權重/風控/下單全 deterministic；`validate_targets` 重算驗證、ClampEvent、hash-chained ledger、PromptCache → 審計鏈完整。
2. 決策 T、執行 T+1 的時序設計正確，避免同 bar 偷看。
3. `blind` 模式正面處理 LLM 記憶洩漏；abstain 機制（LLM 失敗 → 0 而非亂猜）。

## Weakness

1. 資料源綁 Financial Datasets（美股），無台股；新聞/技術面 alpha 在 v2 幾乎沒有。
2. 無交易成本、無 lot size、無持股數/現金下限約束、無 VWAP 成交。
3. 每檔 × 每 persona 一次 LLM，150 檔 × 5 persona = 750 calls/日（有 cache 可降低）；名人 persona 的 alpha 未經驗證（ROADMAP 自承 Validation gate CPCV/PBO ⬜）。
4. 重寫頻繁、API 不穩定（v1→v2 破壞性變更；open issues 177，如 #702 指標不一致、#724 PEAD bug）。

## Reuse potential：4/5

值得借用（最貼近我們問題的骨架）：
- `portfolio/construction.py::blend_signals`（多 analyst 加權 → 權重正規化）＋ `risk/limits.py::apply_limits` + `ClampEvent` → 直接改寫：TSMC 25%/其他 10%、現金 <25%（gross ≥ 0.75）、20–30 檔、1000 股取整。
- `portfolio/validation.py` 的「下單前從原始 evidence 重算驗證」→ D-Plan 一致性檢查。
- `pipeline/execution.py::build_orders`（先賣後買、向零取整、差額下單）→ 改為 lot=1000 並加手續費/稅估算。
- `paper/ledger.py` hash-chain SessionRecord → 我們的每日決策 audit log。
- `signals/llm_agent.py` 的 PromptCache + abstain + blind 模式。
- v1 `risk_manager.py` 的波動度×相關性上限公式（作為 sizing 啟發式起點）。
- v1 `portfolio_manager.py` 的「deterministic allowed actions + LLM 在範圍內選擇」模式。

避免：名人 persona 當主要 alpha 來源；其 backtest 數字（無成本）。

## Competition fit：3/5

三者中唯一有真正多股組合 + 風控 clamp + 再平衡 + 模擬帳本；但台股資料、成本、整張、VWAP、Active Share 都要自建。

## Classification：B — Production-oriented（教育用途聲明）

理由：v2 有 ledger、kill switch、paper trading、決定性約束、測試；但 README 明言 "educational purposes only"、"the system does not actually make any trades"，且成本/PIT 未完成。舊 v1 屬 C（Educational-Demo）。

## README 宣稱 vs 程式碼

- VISION 描述 CIO allocator、master risk、live broker、多 alpha 模型 → 自承「Much of this is aspirational」；Momentum/Mean reversion/Value factors 皆 ⬜。
- 「point-in-time / no lookahead」ROADMAP 標 🚧，`features/snapshot.py` 只對 fundamentals 做 filing_date 過濾。
- SimBroker 宣稱 deterministic，但無成本；績效數字偏樂觀。

## Evidence（存取日期 2026-10-04）

- Repo / API：https://github.com/virattt/ai-hedge-fund ；https://api.github.com/repos/virattt/ai-hedge-fund
- v2 檔案：`hedge_fund/portfolio/construction.py`、`portfolio/validation.py`、`risk/limits.py`、`pipeline/execution.py`、`pipeline/stages.py`、`pipeline/session.py`、`brokers/sim.py`、`backtesting/engine.py`、`backtesting/fund.py`、`signals/llm_agent.py`、`signals/buffett.py`、`features/snapshot.py`、`paper/ledger.py`、`fund/example.yaml`、`data/client.py`、`models.py`、`README.md`、`VISION.md`、`ROADMAP.md`、`pyproject.toml`
- v1 檔案（tag v2026.7.10）：https://github.com/virattt/ai-hedge-fund/tree/v2026.7.10 — `src/agents/risk_manager.py`、`src/agents/portfolio_manager.py`、`src/backtesting/engine.py`、`src/backtesting/portfolio.py`
- Issues：https://github.com/virattt/ai-hedge-fund/issues
- 同作者 dexter：https://github.com/virattt/dexter（27,642 stars / 3,412 forks / 166 watchers；TypeScript/Bun + LangChain.js；last commit 2026-09-23；repo 無 LICENSE 檔、API 回傳 license=null；自主金融研究 agent（task planning、self-validation、memory with embeddings/MMR/temporal decay、evals），無組合/回測；資料同為 Financial Datasets；與本賽題關聯低，可參考其 `src/agent/scratchpad.ts`、`src/evals/` 的 agent 評測方式）
