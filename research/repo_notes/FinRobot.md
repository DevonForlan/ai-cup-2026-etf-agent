# FinRobot（AI4Finance-Foundation/FinRobot）

> 存取日期：2026-10-04｜檢視版本：`main` @ `2717499`（2026-09-28）｜方法：shallow clone 至 scratchpad（Windows 長路徑需 `core.longpaths`）後閱讀原始碼、README、論文 HTML、issues 頁面。未安裝、未執行。

## Metadata

| 欄位 | 值 |
|---|---|
| URL | https://github.com/AI4Finance-Foundation/FinRobot |
| Stars / Forks / Watchers | 8,139 / 1,374 / 100（2026-10-04） |
| Created | 2024-02-27 |
| Last commit | 2026-09-28（最近 5 筆皆為 docs/README 調整） |
| Latest release | desktop-v0.1.0（2026-07-07）；v1.0.0（2026-03-20）；PyPI `finrobot` 0.1.5（setup.py） |
| Maintenance | 中度活躍（V2 desktop 有大量開發；issues 回應少、含 spam 與未處理的安全回報；open issues 76） |
| License | Apache-2.0（另有 NOTICE、TRADEMARK_POLICY.md） |
| Language | Python（後端）+ TypeScript/React + Rust/Tauri（desktop） |
| Framework | V0 AutoGen（`finrobot_autogen/`）；V1 OpenAI Agents SDK（`finrobot_equity/`）；V2 PydanticAI + FastAPI + SQLite（`finrobot_desktop/`） |
| LLM providers | V2：openai-compatible（任意 base_url）+ anthropic（`finrobot_desktop/finrobot/config.py::ProviderConfig`）；V0：OAI_CONFIG_LIST（OpenAI 為主，支援 Ollama 教學） |
| Data | FMP、Finnhub、yfinance、SEC EDGAR、Adanos、NewsAggregator、FX（V2 `engine/data/providers/`）；V0 另有 Reddit、FinNLP submodule |
| Papers | arXiv 2405.14767（平台白皮書，v2 2024-05）；arXiv 2411.08804（Equity Research & Valuation） |

### Capability flags

| Capability | 評等 | Evidence |
|---|---|---|
| market_data | Yes | `finrobot_desktop/finrobot/engine/data/providers/yfinance_provider.py`, `fmp_provider.py`, `finrobot_autogen/finrobot/data_source/yfinance_utils.py` |
| fundamental | Yes | `engine/data/providers/edgar_provider.py`, `engine/compute/operators/{dcf,ddm,lbo,wacc,multiples,residual_income,sotp}.py` |
| technical | Partial | V0 `functional/charting.py`、`tutorials_advanced/lmm_agent_opt_smacross.ipynb`；V2 backtest 僅 SMA crossover |
| news | Yes | `engine/data/providers/news_aggregator.py`, `finnhub_provider.py` |
| sentiment | Partial | `engine/data/providers/adanos_provider.py`；V0 `data_source/reddit_utils.py` |
| portfolio_management | No | 無組合模組；`finrobot_autogen/experiments/portfolio_optimization.py` 實際是 AutoGen 群聊評估單一公司（PDD）並給 6 個月目標價 |
| multi_stock_portfolio | No | 所有 pipeline 以單一 ticker 為輸入（`engine/pipelines/equity_research.py` 等） |
| position_sizing | No | — |
| risk_management | Partial | `engine/compute/operators/monte_carlo.py`（估值區間）、V1 `risks_agent.py`（文字風險章節）；無部位風控 |
| memory | Partial | `finrobot_desktop/finrobot/artifact/sqlite_store.py`（研究 artifact 儲存與 `semantic_diff.py` 版本差異），非決策學習記憶 |
| reflection | Partial | `engine/backtest/strategy_agent.py`（LLM 依 IS 回測結果調參 3 次）；`compute/operators/report_drift.py` |
| backtesting | Partial | `engine/backtest/{engine,backtrader_adapter,strategy_agent}.py`：單 ticker、Backtrader、IS/OOS 70/30；V0 `functional/quantitative.py::back_test` |
| simulation | No | — |
| tool_calling | Yes | V0 `toolkits.py` + AutoGen register_function；V2 PydanticAI agents（`engine/agents/factory.py`） |
| structured_output | Yes | V2 Pydantic models（`engine/models/financial.py::ThesisResult`、`engine/backtest/engine.py::BacktestConfig/Result`、`artifact/contract.py`） |
| audit_log | Yes | `finrobot_desktop/finrobot/obs/`（middleware/formatters）、`artifact/`（provenance、field_registry）、`compute/operators/audit/*`（narrative_numeric_grounding、narrative_divergence、currency_caliber、ttm_period 等） |
| point_in_time_data | No | 研究報告以「最新」資料為主；未見 as_of 日期鎖定機制 |
| transaction_cost | No | `engine/backtest/backtrader_adapter.py:191` 明寫 "Backtest assumes zero commission and zero slippage" |
| portfolio_constraints | No | — |
| rebalancing | No | — |

## Architecture

三個並存子專案（README「Where to start」）：
- **V0 `finrobot_autogen/`**（Educational）：AutoGen 角色 agent 庫（`agents/agent_library.py`、`workflow.py`：SingleAssistant / MultiAssistant / MultiAssistantWithLeader）、資料 wrapper、`functional/`（RAG、charting、reportlab、backtrader）。論文對應版本。
- **V1 `finrobot_equity/`**（Web app）：OpenAI Agents SDK，8 個章節 agent（company_overview、competitor、investment_overview、major_takeaways、news_summary、risks、tagline、valuation_overview）→ HTML/PDF 研究報告。
- **V2 `finrobot_desktop/`**（宣稱 Production）：Lead Agent + 5 角色 pipeline agent（data/analysis/modeling/synthesis/report）+ Bull/Bear/Judge 辯論；7 pipelines（company research、DCF、comps、LBO、DDM、earnings、IC memo）；32 個純 Python compute operators（26 估值 + 6 audit）；agent 指令在 `engine/agents/instructions/*.md`。

核心原則（README）：「Numbers are code-calculated. Narratives are LLM-assisted. Every output is provenance-tracked.」

## Data Flow

DataLayer（`engine/data/layer.py`）→ 7 providers with failover → normalize（FX、TTM）→ compute operators（DCF/WACC/comps...）→ LLM narration → artifact（SQLite，含 provenance/field registry）→ audit operators 檢查（例：敘述是否引用數字、幣別一致、EV bridge、產業正負號）。ticker 驗證支援 `.T`、`.L`、`.SS/.SZ/.HK` 等後綴（`engine/data/ticker.py`），未見台股特別處理（`.TW` 可能經 yfinance 通過，但 FMP/EDGAR 覆蓋有限）。

## Decision Flow

單一 ticker → 研究報告（13 章）→ verdict + 12 個月目標價 + 信心度；`compute/operators/signal.py` 以「目標價 ±10% 或走完 50% 路程 = hit，反向 10% = failed」追蹤命中率。決策粒度是**單股研究結論**，不是可執行的部位。

## Portfolio Logic

無。repo 中帶「portfolio」字樣的程式：V0 `experiments/portfolio_optimization.py`（名不副實，見下）、`investment_group.py`（CIO 角色組織圖設定）、`multi_factor_agents.py`（AutoGen 群聊示範）、V2 `operators/sniper.py`、`primitives/industry.py` 等僅提及字詞。

## Risk

僅估值層面（Monte Carlo 估值分布、WACC 敏感度）與報告中的文字風險章節；沒有部位、波動度、相關性、集中度風控。

## Memory

V2 以 SQLite artifact store 保存每份研究與 semantic diff（`artifact/semantic_diff.py`、`compute/operators/report_drift.py`），可比較同公司不同時點報告的差異；不是從結果學習的 reflection memory。

## Backtest

- V2 `engine/backtest/`：`BacktestConfig` 單一 `ticker`，預設 `sma_crossover`；`strategy_agent.py` 讓 LLM 在 in-sample 70% 期間迭代 3 次調參，最佳參數在 out-of-sample 30% 只評估一次（有 anti-overfitting 意識）；零手續費、零滑價。
- V0 `functional/quantitative.py::back_test`：Backtrader + `yf.download`，單 ticker，FixedSize sizer。
- 皆非組合回測。

## Prompts

V2 指令在 `finrobot_desktop/finrobot/engine/agents/instructions/{data,analysis,modeling,synthesis,report,bull,bear,judge}_agent.md`；thesis prompt（`engine/pipelines/_thesis_prompt.py`）有「NARRATIVE ARGUMENT RULE」：每段必須引用白名單數字，再由 `audit/narrative_numeric_grounding.py` 程式檢查。V0 prompts 在 `finrobot_autogen/finrobot/agents/prompts.py`。

## Papers 實驗設定與弱點

- **arXiv 2405.14767（平台白皮書）**：四層架構（Financial AI Agents / Financial LLM Algorithms（FinGPT、FinRL、FinML）/ LLMOps-DataOps（Smart Scheduler 選模型）/ Foundation Models），Financial CoT。實驗只有質化 case study（NVDA、貴州茅台的短期漲跌預測敘述），**無回測、無量化指標、無 baseline、無 ablation**。
- **arXiv 2411.08804（Equity Research & Valuation）**：Data-CoT / Concept-CoT / Thesis-CoT 三 agent；評估僅單一公司（Waste Management）報告，由 7 位投行分析師與 GPT-4 以 accuracy/logicality/storytelling 0–10 評分（約 9.6/9.3/8.1）。**無目標價準確度、無推薦回測、無與券商報告實證比較**，但宣稱「comparable to major brokerage firms」。
- 共同弱點：無交易績效驗證、樣本極小、LLM 評 LLM、look-ahead 問題未討論。

## Strength

1. 「程式算數字、LLM 只敘述、輸出可溯源」原則落實得最徹底：32 個 deterministic operators + 6 個 audit operators（數字落地檢查、敘述與動能背離、幣別/TTM 期間一致性）。
2. V2 工程規模大（README 稱 ~184k 行、176 個 unit tests 檔）、PydanticAI 型別化輸出、artifact provenance。
3. 估值工具箱（DCF/DDM/LBO/comps/SOTP/residual income）完整，可作為基本面因子來源。

## Weakness

1. 完全是**單股研究報告產生器**，沒有選股、組合、權重、成本、再平衡——與本賽題核心不符。
2. 論文缺乏量化驗證；README 對 V2「production / decision-grade」的定位大於其可驗證證據。
3. 三代並存（AutoGen / Agents SDK / PydanticAI）造成碎片化；V0 有未處理安全回報（Issue #101/#102：`functional/coding.py` 的 `modify_code`/`create_file_with_code` 直接以 `default_path + filename` 開檔寫入，可路徑穿越/程式注入；`exec_python` 直接執行 LLM 產生的程式）。
4. issues 回應稀少、混入 spam（#92、#98 等），社群維護品質一般。
5. 無 point-in-time 機制，若用於歷史回測會有前視偏誤。

## Reuse potential：2/5

值得借用：
- **Audit operator 模式**：`compute/operators/audit/narrative_numeric_grounding.py`（每段推論必須引用數字，否則 warning）→ 直接對應 D-Plan「observation→inference」必須綁數據證據。
- 「deterministic compute + LLM narration」分層原則，及 `artifact/` 的 provenance/field registry 概念。
- `compute/operators/signal.py` 的 hit/watching/failed 規則化追蹤。
- `strategy_agent.py` 的 IS/OOS 切分 + LLM 調參上限（3 次）概念。

避免：V0 AutoGen 程式（教學用、不安全的 code exec）；將 13 章報告流程套到 150 檔（成本極高、無比賽價值）；以其論文作為績效依據。

## Competition fit：1/5

僅能借鑑審計/可溯源設計，對 150→20–30 檔每日組合決策幾乎無直接可用元件。

## Classification：V0 = C（Educational-Demo）；V1/V2 = B-（Production-oriented 研究工具）；整體判定 **C**

理由：作為「量化交易/組合」框架，它的可驗證成果僅限單股報告與質化評估；V2 雖工程化，但定位是 equity research workstation，而非交易系統。README 中「quantitative trading, risk analysis... high-stakes financial decisions」等宣稱遠超程式中實作（無組合、無成本回測）。

## README / 命名宣稱 vs 程式碼

- `experiments/portfolio_optimization.py`：實為 AutoGen 群聊評估 PDD 並給 6 個月目標價，無任何最佳化。
- 「end-to-end agentic workflows for ... quantitative trading, risk analysis」→ 交易相關僅單 ticker SMA 回測（零成本）。
- 論文 2411.08804「comparable to major brokerage firms」→ 無實證比較。

## Evidence（存取日期 2026-10-04）

- Repo / API：https://github.com/AI4Finance-Foundation/FinRobot ；https://api.github.com/repos/AI4Finance-Foundation/FinRobot
- 檔案：`README.md`、`setup.py`、`.gitmodules`、`finrobot_desktop/finrobot/config.py`、`engine/backtest/engine.py`、`engine/backtest/backtrader_adapter.py`、`engine/backtest/strategy_agent.py`、`engine/compute/operators/signal.py`、`engine/compute/operators/audit/narrative_numeric_grounding.py`、`engine/data/ticker.py`、`engine/agents/instructions/*.md`、`artifact/*`、`finrobot_autogen/finrobot/functional/quantitative.py`、`functional/coding.py`、`experiments/portfolio_optimization.py`、`experiments/investment_group.py`、`finrobot_equity/core/src/modules/equity_agents/*.py`
- Papers：https://arxiv.org/html/2405.14767 ；https://arxiv.org/html/2411.08804v1 ；https://arxiv.org/pdf/2411.08804
- Issues：https://github.com/AI4Finance-Foundation/FinRobot/issues （#101、#102 安全回報；#113 資料 502）
