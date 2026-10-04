# FinAgent — Multimodal Foundation Agent for Financial Trading

> 存取日期：2026-10-04。論文讀 arXiv HTML v3 正文；程式碼 shallow clone（HEAD 2024-08-31 "add requirements"）實際閱讀。

## Metadata

| 欄位 | 值 |
|---|---|
| Paper | A Multimodal Foundation Agent for Financial Trading: Tool-Augmented, Diversified, and Generalist（arXiv 2402.18485；KDD 2024） |
| Authors | Wentao Zhang, Lingxuan Zhao, Haochong Xia, Shuo Sun, ... Xinrun Wang, Bo An（NTU、NUS、ZJU、SMU、Skywork AI） |
| Repo（作者帳號，非論文內連結） | https://github.com/DVampire/FinAgent （DVampire = 第一作者 Wentao Zhang；README 只有安裝/執行說明，論文 HTML 未附 GitHub 連結） |
| Stars / Forks / Watchers | 75 / 27 / 1（GitHub 頁面，2026-10-04） |
| Last commit | 2024-08-31 |
| Latest release | 無 |
| Maintenance | 停止維護 |
| License | MIT（"Copyright (c) 2024 FinAgent Authors"） |
| Language / Framework | Python 3.10；mmengine 風格 config + registry；faiss-cpu；playwright；pyecharts/matplotlib 畫 K 線；XML 結構化輸出 |
| LLM provider | OpenAI：`gpt-4-1106-preview`（文字模組）、`gpt-4-vision-preview`（K 線/交易圖）；embedding `text-embedding-ada-002`/`-3-small` |
| 資料 API | FMP（價格/新聞/經濟/情緒）、Polygon、Yahoo/Finnhub、RapidAPI Seeking Alpha、Alpha Vantage |
| 其他 | `effective-p/FinAgent`（4★，2026-06，用 pykrx 的韓股改寫）為第三方 fork，非官方；FINSABER repo 內 `llm_traders/finagent` 有重構版。 |

## Architecture

五大模組（`finagent/prompt/trading/*.py` + `res/prompts/module/trading/*.html`）：
1. **Market Intelligence（MI）**：latest MI（當日新聞+價格，摘要 bullish/bearish、短中長期影響）與 past MI（以 diversified query 檢索歷史 MI 再摘要）。
2. **Low-level reflection**：連結「市場情報 + K 線圖 + 價格變化」與價格走勢，輸出 short/medium/long-term reasoning（預設 1/7/14 日）與檢索 query。
3. **High-level reflection**：檢視過去交易決策 + 交易圖（標出買賣點），輸出 reasoning / improvement / summary / query。
4. **Memory**：三個向量記憶庫（MI memory、low-level reflection memory、high-level reflection memory），faiss。
5. **Decision-making（tool-augmented）**：整合 MI、兩層 reflection、專家指引（Seeking Alpha）、規則策略工具（MACD Crossover、KDJ+RSI filter、Mean Reversion，`finagent/tools/strategy_agents.py`）、trader preference（aggressive/conservative），輸出 XML：`analysis / action(BUY|SELL|HOLD) / reasoning`。

## Data Flow

downloader（FMP/Polygon/Yahoo）→ `tools/data_process.py` → dataset（price/news/guidance/sentiment/economic parquet）→ `EnvironmentTrading.get_state()` → 各 prompt module 依 `current_date` 過濾後組 prompt。

**注意（look-ahead 結構風險）**：`get_state()` 回傳的 price/news 是截到 `day + look_forward_days(=14)` 的資料；各模組再以 `index == current_date` / `<= current_date` 過濾。`low_level_reflection.py` 也會計算 `*_next_price_movement`（未來 1/7/14 日報酬）；這些欄位只在 **train** 模板（`low_level_reflection_prompt_with_next_trading`）使用，`valid` 模板未引用（grep 確認）。因此測試期理論上無洩漏，但架構上「先拿未來再過濾」非常脆弱，任何新模組都可能誤用。

## Decision Flow

每日：latest MI → diversified retrieval past MI → low-level reflection（含 K 線圖，vision model）→ high-level reflection（含交易圖）→ decision（含工具策略訊號與 trader preference）→ env.step。每一步輸出都會寫入對應記憶庫。

## Portfolio Logic

- `finagent/environment/trading.py`：單一資產；cash + position；BUY 時 `floor(cash / price / (1+cost))` 全倉買入（乘以 `amount/action_radius`），SELL 時全賣；`transaction_cost_pct = 1e-3`；初始資金 1e4。
- **單股、全進全出**，無多股票配置。

## Risk

- 只有 prompt 層面：trader preference（aggressive / conservative）、high-level reflection 的 "improvement"。
- 無 stop-loss、無曝險上限。交易成本 0.1% 有計入。

## Memory / Reflection（重點）

- **Diversified retrieval**：每個模組輸出一個或多個「query」文字（例如針對短/中/長期、bullish/bearish 各一條），用來從向量庫檢索相似的歷史情報/反思 — 比 FinMem 固定用角色字串當 query 更合理。
- **Dual-level reflection**：
  - Low-level = 「市場訊號 → 價格」的因果解讀（偏 prediction/解釋）。
  - High-level = 「我的決策 → 結果」的自我檢討（偏 decision quality），並提出 improvement。
- 這兩層反思正好對應我們需要的 **prediction-outcome tracking** 與 **decision log review**。
- Train 期 low-level reflection 會看到未來 1/7/14 日價格變化（用於學因果）；記憶庫沿用到 test 期。

## Backtest（論文）

| 項目 | 內容 |
|---|---|
| Assets | AAPL, AMZN, GOOGL, MSFT, TSLA, ETHUSD（6 個資料集） |
| Train | 2022-06-01 ~ 2023-06-01 |
| Test | 2023-06-01 ~ 2024-01-01（約 7 個月） |
| LLM | gpt-4-1106-preview + gpt-4-vision-preview（config 確認） |
| Baselines | B&H、MACD、KDJ&RSI、ZMR、LGBM、LSTM、Transformer、DQN、SAC、PPO、FinGPT、FinMem（共 12） |
| Metrics | ARR、Sharpe、Calmar、Sortino、MDD、Volatility |
| 結果 | TSLA ARR 92.27%；平均獲利改善 36%；6 資料集中 5 個勝出 |
| **Look-ahead** | GPT-4-Turbo/Vision 知識截止約 2023-04，test 期**大致在截止之後**（相對 FinMem/FinCon 較乾淨），但 test 只有 7 個月、ticker 為事後贏家。FINSABER 長期重測：FinAgent 在 NFLX Sharpe −0.511（B&H 0.622）；momentum 組合 Sharpe 0.104 vs B&H 0.384；bull market Sharpe 0.12 vs B&H 0.61（過度保守），bear market −0.38（過度積極）。 |

## Prompts

- 以 HTML 片段模組化（task description / state description / output format / guidance / effects），由 `$$var$$` 變數替換組合。
- 輸出格式為 XML（`<output><string name="action">BUY</string>...`），可改為 JSON schema。
- 有 `trader_preference`、`decision_strategy_trading_with_record`（帶交易紀錄）、`only_strategy`（只看工具策略）等 ablation 變體（configs/exp/*）。

## Strength

- 反思分層清楚（market→price vs decision→outcome），且 query 多樣化檢索。
- Tool augmentation：把傳統技術指標策略的訊號當成 LLM 的「顧問意見」— 適合我們把量化因子分數作為 evidence 餵給 LLM。
- 交易成本有計入；ablation config 完整；MIT 授權。

## Weakness

- 單一資產、全倉進出；依賴多個付費 API；GPT-4V 成本高。
- 未來資料先載入再過濾的設計有洩漏風險。
- 長期重測顯示無穩定 alpha。
- 停止維護（2024-08 後無 commit）。

## Reuse potential

- **可借**：prompt 模組化方式、dual-level reflection 的輸出 schema、diversified query、「規則策略訊號 → LLM 顧問」的 tool augmentation。
- **不建議**：environment/backtest（單資產）、vision K 線（成本高、對 150 檔×每日不划算）。
- Reuse score：**2/5**。

## Competition fit（1–5）

**2/5**。Reflection 設計可用於每日 post-mortem，但單股架構與 150 檔 universe、整張、權重上限等限制差距大。

## Classification

**A — Research-grade**。

## Evidence

- https://arxiv.org/abs/2402.18485 、 https://arxiv.org/html/2402.18485v3 （架構 §3、實驗 §5）
- https://github.com/DVampire/FinAgent （`finagent/environment/trading.py`、`finagent/prompt/trading/low_level_reflection.py`、`finagent/prompt/trading/latest_market_intelligence_summary.py`、`res/prompts/module/trading/*.html`、`configs/exp/trading/AAPL.py`、LICENSE）
- https://github.com/effective-p/FinAgent （第三方 fork）
- https://github.com/waylonli/FINSABER （`llm_traders/finagent`）
- https://astro.paperswithcode.com/paper/finagent-a-multimodal-foundation-agent-for
- https://arxiv.org/abs/2505.07078 （FINSABER 重測）
- 存取日期：2026-10-04
