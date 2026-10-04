# Microsoft Qlib + RD-Agent (RD-Agent(Q))

> 存取日期：2026-10-04。Qlib 以 raw GitHub 原始碼（`qlib/backtest/exchange.py`、`qlib/contrib/strategy/signal_strategy.py`、`qlib/contrib/strategy/optimizer/enhanced_indexing.py`）查核；RD-Agent 讀 README 與 arXiv 2505.15155 實驗章節。

## Metadata

| 欄位 | Qlib | RD-Agent |
|---|---|---|
| Repo | https://github.com/microsoft/qlib | https://github.com/microsoft/RD-Agent |
| Stars / Forks / Watchers | 49,127 / 7,758 / 511 | 14,840 / 1,947 / 90 |
| Last push | 2026-09-22 | 2026-10-02（最後 commit 2026-09-23 "release 1.0.0"） |
| Latest release | v0.9.7（2025-08-15） | v1.0.0（2026-09-23） |
| Maintenance | 活躍（但 release 週期慢；open issues 484） | 非常活躍 |
| License | MIT | MIT |
| Language | Python（Cython 加速） | Python；需要 Docker 執行多數 scenario |
| LLM provider | 無（Qlib 本身不是 LLM 工具） | LiteLLM（預設）→ OpenAI/Azure/DeepSeek 等；論文用 GPT-4o、o3-mini、o3、GPT-4.1、GPT-4o-mini |
| Paper | Qlib: An AI-oriented Quantitative Investment Platform（arXiv 2009.11189） | R&D-Agent-Quant（arXiv 2505.15155，NeurIPS 2025） |

## Architecture

**Qlib**：資料層（自有二進位格式 `.bin`、`dump_bin.py`、Expression engine 定義因子如 `Ref($close,1)/$close`）→ 模型層（LightGBM、GRU/LSTM/Transformer、TRA、HIST 等 model zoo，Alpha158/Alpha360 因子集）→ 策略層（`TopkDropoutStrategy`、`EnhancedIndexingStrategy`、`WeightStrategyBase`）→ 回測/執行層（`Exchange`、`Account`、nested executor）→ 分析（IC/ICIR、portfolio analysis、report）。工作流由 YAML（`qrun`）+ MLflow-like recorder 管理。

**RD-Agent(Q)**：Research（specification → synthesis：提出因子/模型假說）＋ Development（Co-STEER 寫程式實作因子或模型）→ validation（在 Qlib 上回測）→ analysis（回饋）→ multi-armed bandit 排程下一輪要改因子還是改模型。全程以 Qlib 作為執行與評估環境。

## Data Flow

- Qlib 官方資料收集器支援 CN/US/IN/BR（Yahoo），**不支援台股**；但可以自備 CSV（含 open/high/low/close/volume/vwap/factor）用 `scripts/dump_bin.py` 轉成 Qlib 格式。這是把 150 檔台股接入的可行路徑。
- RD-Agent(Q) 給 LLM 的是「schema 級資訊」（欄位名稱、資料說明），不給原始行情，論文稱以此降低 LLM 知識洩漏風險。

## Decision Flow

Qlib：signal（模型對每檔的預測分數）→ 策略取 top-k、每期最多換 n_drop 檔 → 依 `risk_degree`（預設 0.95，即 5% 現金）等權/指定權重產生 order → Exchange 撮合。

## Portfolio Logic（與比賽高度相關）

- `TopkDropoutStrategy(topk, n_drop, hold_thresh, risk_degree)`：多股票 portfolio、控制換手（每日最多汰換 n_drop 檔），天然適合「20–30 檔、低換手」。
- `EnhancedIndexingStrategy` + optimizer：`max d@r − λ(v@cov_b@v + var_u@d²)`，限制 `Σ|w−w0| ≤ δ`（換手上限）、`|d| ≤ b_dev`（相對 benchmark 偏離上限）、`|v| ≤ f_dev`（因子曝險上限）。**可直接映射**：benchmark 偏離上限 ↔ Active Share；換手上限 ↔ 交易成本控制；再加上個股權重上限（TSMC 25%、其他 10%）即可。
- `Exchange` 參數：`trade_unit`（CN 預設 100 股；台股可設 1000 = 一張）、`deal_price` 可設 `$vwap`（**正好對應比賽「以當日 VWAP 成交」**）、`open_cost`/`close_cost`/`min_cost`（台股可設 0.001425 / 0.004425 / 20 TWD）、`limit_threshold`（台股漲跌停 ±10%）、`impact_cost`。

## Risk

risk_degree（現金比例）、EnhancedIndexing 的追蹤誤差/因子曝險約束、limit up/down 不可成交處理。無 LLM 層風控。

## Memory

Qlib：無。RD-Agent：有「知識庫/trace」— 每輪假說、程式、回測結果、feedback 都存成 trace，下一輪 research 時參考（類似 experiment log memory），並有 Web UI 檢視 trace。這是**實驗管理型記憶**，可借用為「策略版本 + 結果」紀錄。

## Backtest

- Qlib：日頻/分鐘頻回測、含成本、漲跌停、整股單位、VWAP 成交、nested executor；是本清單中最貼近比賽撮合規則的回測器。
- RD-Agent(Q) 論文：CSI300，train 2008-01~2014-12、valid 2015-01~2016-12、**test 2017-01~2020-08**；另在 CSI500、NASDAQ100（test 2024~2025-06）驗證。每次 run 成本 < USD 10。結果：IC 最高 0.0532、ARR ≈14.21%、IR 最高 1.74、MDD ≈ −7.42%；ARR 約為傳統因子庫 2 倍、用 70% 更少因子。
- **Look-ahead 疑慮**：CSI300 test 期（2017–2020）完全在所有 backbone 知識截止之前；雖然 LLM 不看原始資料，但「哪些因子在 A 股 2017–2020 有效」的知識可能已存在於訓練語料（因子文獻、研報），屬間接污染。NASDAQ100 2024–2025 驗證部分在 GPT-4.1/o3 截止（約 2024 中）之後，較可信。

## Prompts

RD-Agent 的 prompt 存於 `rdagent/scenarios/qlib/...` 的 yaml（hypothesis generation、factor implementation、feedback）。未逐一閱讀。

## Strength

- Qlib：成熟、工業級、回測規則（整股單位、VWAP、成本、漲跌停、換手、benchmark 偏離）與比賽高度吻合；大量因子與模型。
- RD-Agent：自動化因子研究、trace 可審計、LiteLLM 多供應商、活躍維護。

## Weakness

- Qlib 無台股資料、學習曲線陡、release 慢；Windows 安裝偶有問題（需編譯）。
- RD-Agent 需 Docker、多輪 LLM 呼叫、適合「離線研究」而非每日 08:55 前自動決策；24 日比賽期間不適合讓 agent 自行改策略。
- 兩者都沒有新聞/文字層、沒有 evidence-chain JSON。

## Reuse potential

- **Qlib：4/5** — 建議作為回測與 portfolio 建構引擎（或至少照抄其 Exchange 規則參數化方式與 TopkDropout / EnhancedIndexing 邏輯）。
- **RD-Agent：2/5** — 賽前可用來挖掘台股因子（需自建 Qlib 台股資料）；比賽期間不建議線上使用。

## Competition fit（1–5）

- Qlib：**4/5**（回測/組合層）
- RD-Agent：**2/5**（賽前研究工具）

## Classification

- Qlib：**B — Production-oriented**
- RD-Agent：**B — Production-oriented（研究自動化）**，論文部分 A。

## Evidence

- https://github.com/microsoft/qlib （metadata via api.github.com；`qlib/backtest/exchange.py`、`qlib/contrib/strategy/signal_strategy.py`、`qlib/contrib/strategy/optimizer/enhanced_indexing.py` via raw.githubusercontent.com）
- https://github.com/microsoft/RD-Agent （README）
- https://arxiv.org/abs/2505.15155 、 https://arxiv.org/html/2505.15155 （實驗章節）
- https://rdagent.readthedocs.io/en/latest/scens/quant_agent_fin.html （README 引用，未深入）
- 存取日期：2026-10-04
