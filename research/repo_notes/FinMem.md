# FinMem — Layered-Memory LLM Trading Agent

> 存取日期：2026-10-04。程式碼以 shallow clone（HEAD = 2024-08-18 commit "Update reflection.py"）實際閱讀；論文讀 arXiv HTML 正文（非只摘要）。

## Metadata

| 欄位 | 值 |
|---|---|
| Paper | FinMem: A Performance-Enhanced LLM Trading Agent with Layered Memory and Character Design（arXiv 2311.13743；ICLR 2024 Workshop LLM Agents、AAAI Spring Symposium extended abstract） |
| Authors | Yangyang Yu, Haohang Li, ... Jordan W. Suchow, Khaldoun Khashanah（Stevens Institute of Technology） |
| Repo | https://github.com/pipiku915/FinMem-LLM-StockTrading |
| Stars / Forks / Watchers | 962 / 195 / 24 |
| Last commit | 2024-08-18（之後兩年多無更新） |
| Latest release | 無 release |
| Maintenance | 停止維護（dormant） |
| License | MIT |
| Language / Framework | Python 3.10；poetry；faiss（向量記憶）、guardrails-ai + pydantic（輸出驗證）、polars、typer CLI；Docker/devcontainer |
| LLM provider | OpenAI（gpt-3.5-turbo-0125、GPT-4 系列）、Google Gemini Pro、HuggingFace TGI（Llama2-70b 等）；embedding 固定 `text-embedding-ada-002`（一定要 OpenAI key） |
| 注意 | Repo 內 commit 了一個 `.env` 檔（範本），重用時切勿把實際金鑰提交 |

## Architecture

三大模組：
1. **Profiling（角色設定）**：`character_string` 描述交易員專長（例如 TSLA 的產業背景）＋風險偏好（risk-seeking / risk-averse / self-adaptive）。程式中 character_string 同時被拿來當作記憶檢索的 query text（`query_short(query_text=self.character_string)`），也就是說每天的檢索 query 幾乎固定。
2. **Memory（分層記憶）**：`puppy/memorydb.py` 的 `BrainDB` 含 short / mid / long / reflection 四個 `MemoryDB`，每個是 per-symbol 的 faiss `IndexFlatIP` + metadata（importance、recency、delta、access_counter）。
3. **Decision-making**：`puppy/reflection.py` 用 guardrails 從 pydantic schema 產生結構化輸出（`investment_decision ∈ {buy, sell, hold}`、`summary_reason`、各層引用的 memory index）。

程式碼規模小（puppy/ 約 2,500 行），單一 agent、單一 symbol。

## Data Flow

- 資料管線 `data-pipeline/`：Alpaca News API（Benzinga）、Refinitiv（SQL）、SEC API 10-K/10-Q、yfinance 價格，前處理後 pickle 成 `env_data.pkl`（date → price, filing_k, filing_q, news）。
- `agent.step()` 每日：
  1. 10-Q 寫入 mid memory、10-K 寫入 long memory（`_handling_filings`）。
  2. 當日新聞寫入 short memory（`_handling_news`）。
  3. 更新價格到 `Portfolio`。
  4. `_reflect()`：分別向四層記憶以 top_k 檢索，加上 momentum（近 3 日價格方向）與持股數組成 prompt。
  5. 產生 action → `_portfolio_step` → `_update_access_counter` → `brain.step()`（decay、clean-up、跨層 jump）。

## Decision Flow

- **Train mode**：prompt 直接給「明日與今日的價差」（`train_investment_info_prefix` 中的 `{future_record}`），LLM 只需「解釋為什麼市場這樣動」並指出支持的 memory id；動作由 `_construct_train_actions` 依真實未來漲跌決定（漲→buy，跌→sell）。這是設計上的 label leakage，用來「養」記憶庫與 reflection 記憶（類 supervised warm-up）。
- **Test mode**：不給未來價格，LLM 依四層記憶 + momentum + 持股 輸出 buy/sell/hold；失敗或空結果→hold。
- 輸出用 guardrails `ValidChoices` 限定選項與 memory id（train 模式 on_fail="reask"）。

## Portfolio Logic

- `puppy/portfolio.py`：只追蹤**單一 symbol** 的持股數；每次 action 的 direction ∈ {−1, 0, +1}，**每天只買/賣 1 股**（論文亦明言 "one share"）。
- 沒有現金帳戶、沒有權重、沒有多股票配置、沒有交易成本。
- 結論：**單股 timing agent，非 portfolio manager**。

## Risk

- 只有 prompt 層面的「風險性格」：self-adaptive 在近 3 日累積報酬 < 0 時切換為 risk-averse。
- 無 stop-loss、無曝險上限、無 VaR/CVaR、無部位上限（因為一次只動一股，等於沒有 sizing）。

## Memory（重點）

論文公式（Eq.1–6）與程式碼對照：

- **三層 + reflection 層**：
  - Shallow（short）：每日新聞，論文 Q_shallow = 14（config 裡 recency_factor=3.0，與論文不一致），importance decay α=0.9（config 0.92）。
  - Intermediate（mid）：10-Q，Q=90，α=0.967。
  - Deep（long）：10-K，Q=365，α=0.988。
  - Reflection 層：train 期的 reflection 結果，參數同 deep。
- **Recency**：`exp(-δ/Q)`，δ 為事件距今天數（`decay.py`：每天 delta+1）。
- **Importance**：初始值以機率抽樣（short：{50,70,90} p={.5,.45,.05}；mid：{40,60,80} p={.05,.8,.15}；long：{40,60,80} p={.05,.15,.8}），每日乘以 α 衰減。注意：importance 初始是**隨機抽樣**而非由 LLM 判斷，屬啟發式。
- **Relevancy**：query embedding 與記憶 embedding 的 cosine（faiss inner product on L2-normalized）。
- **Compound score**：`similarity + recency + min(importance,100)/100`（`compound_score.py`）。檢索為兩段：faiss top-k by similarity ＋ top-k by compound score，合併後再排序取 top-k。
- **Feedback（強化）**：`Portfolio.get_feedback_response()` 以 look-back window（預設 7 日）的持倉 PnL 正負產生 ±1；被當日決策引用的 memory 之 `access_counter += feedback`，`importance += access_counter*5`。即「被引用且後來賺錢的記憶」重要性提升。
- **Jump（跨層搬移）**：importance ≥ 60 由 short 升到 mid；≥ 80 由 mid 升到 long；低於下限則降級。
- **Clean-up**：recency < 0.05 或 importance < 5 刪除。

評估：設計具可解釋性（每個決策都引用 memory id），但 importance 隨機初始化、檢索 query 固定為角色字串、短期 Q 參數論文與程式不一致，代表「記憶」主要靠時間衰減做 relevance filtering，真正的學習訊號只有 7 日 PnL 的 ±1。

## Backtest

- `run.py`（typer）逐日迭代 env_data，checkpoint 存 agent + faiss index；`data-pipeline/07-metrics.py` 計算 CR/SR/MDD/Volatility，`08-Wilcoxon-Test.py` 做顯著性。
- **無交易成本、無滑價、單股 1 股部位**，B&H 對照。

### 論文實驗

| 項目 | 內容 |
|---|---|
| Tickers | TSLA, NFLX, AMZN, MSFT, COIN（5 檔，皆為知名大型/熱門股） |
| Train | 2021-08-17 ~ 2022-10-05 |
| Test | 2022-10-06 ~ 2023-04-10（約 6 個月）；TSLA 延伸測試 2022-02-11 ~ 2023-04-25；ablation 測試 2022-06-16 ~ 2022-12-28 |
| LLM | GPT-4, GPT-4-Turbo, GPT-3.5-Turbo, davinci-003, Llama2-70b-chat |
| Baselines | Buy&Hold、PPO/DQN/A2C（FinRL）、Generative Agents、FinGPT |
| Metrics | Cumulative Return、Sharpe、Daily/Annualized Volatility、MDD |
| 主要結果 | TSLA：CR +61.78%、SR 2.68 vs B&H −18.63%；GPT-4-Turbo 最佳；self-adaptive 最佳；top-K=5 最佳 |
| Look-ahead 污染 | **有疑慮**：GPT-4-Turbo（1106）知識截止約 2023-04，完全覆蓋 test 期；GPT-3.5-0125 截止 2021-09 則不覆蓋。最好成績正是來自 GPT-4-Turbo。FINSABER（arXiv 2505.07078）以 2004–2024 長期回測重測 FinMem，Sharpe 在 NFLX/AMZN/MSFT 皆明顯低於 B&H（例如 AMZN 0.188 vs 0.551），momentum 選股組合 Sharpe 0.025 vs B&H 0.384，alpha 不顯著（p>0.34）。 |

## Prompts

- `puppy/prompts.py`：`train_prompt`（解釋次日漲跌原因＋引用 memory id）、`test_prompt`（"consider only the available short-term ... reflection-term information"、momentum、持股、"When cumulative return is positive or zero, you are a risk-seeking investor"）、情緒分數與 momentum 的解釋段落。
- 結構化輸出：guardrails `Guard.from_pydantic`，欄位 `investment_decision`、`summary_reason`、`short_memory_index` 等。

## Strength

- 最早、最清楚的「分層記憶 + 衰減 + 重要性 + 回饋強化」金融 agent 實作；程式短小易讀。
- 每個決策附「引用的 memory id + summary_reason」→ 天然的 evidence chain 雛形（source→observation→decision）。
- guardrails 結構化輸出、ValidChoices 限制 memory id 防幻覺的做法可借鏡。

## Weakness

- 單一股票、每日 1 股、無資金/成本/限制，與比賽的 20–30 檔整張 portfolio 差距極大。
- Train 模式依賴未來價格標籤；長期 warm-up（一年以上）才能讓記憶生效。
- Test 期短（6 個月）、ticker 為事後贏家、LLM 知識截止覆蓋測試期 → 結果高估（FINSABER 已實證）。
- importance 隨機初始化；論文/程式參數不一致；停止維護；依賴 OpenAI embedding。

## Reuse potential

- **可借**：(1) memory record schema（text、date、source layer、importance、recency、access_counter、引用 id）；(2) 「決策必須引用 evidence id」+ schema 驗證的設計；(3) 依 PnL 回饋調整證據權重的想法（可簡化為「預測-結果追蹤」）。
- **不可直接用**：portfolio、backtest、資料管線（美股 Alpaca/SEC），以及需要長 train 期的記憶演化。
- Reuse score：**2/5**（概念 > 程式碼）。

## Competition fit（1–5）

**2/5**。24 個交易日太短，三層長期記憶的衰減參數（Q=90/365）根本無從發揮；但「事件記憶 + 引用 id 的結構化輸出」可轉化為我們的 evidence chain。

## Classification

**A — Research-grade**（研究原型，單股、無成本，非生產）。

## Evidence

- https://arxiv.org/abs/2311.13743 、 https://arxiv.org/html/2311.13743 （正文：§3 memory 公式、§4 實驗設定、Table 2）
- https://github.com/pipiku915/FinMem-LLM-StockTrading （README、`puppy/memorydb.py`、`puppy/memory_functions/*.py`、`puppy/agent.py`、`puppy/portfolio.py`、`puppy/prompts.py`、`puppy/reflection.py`、`config/tsla_*_config.toml`、`run.py`）
- https://api.github.com/repos/pipiku915/FinMem-LLM-StockTrading （metadata）
- https://arxiv.org/abs/2505.07078 （FINSABER 對 FinMem 的長期重測）
- 存取日期：2026-10-04
