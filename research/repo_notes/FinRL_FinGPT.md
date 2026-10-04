# FinRL / FinRL-Meta / FinGPT（AI4Finance Foundation）— 簡要評估

> 存取日期：2026-10-04。Metadata 來自 api.github.com；FinRL portfolio env 讀 raw 原始碼 `finrl/meta/env_portfolio_allocation/env_portfolio.py`；FinGPT 讀 README。屬 brief review。

## Metadata

| 欄位 | FinRL | FinRL-Meta | FinGPT |
|---|---|---|---|
| Repo | https://github.com/AI4Finance-Foundation/FinRL | https://github.com/AI4Finance-Foundation/FinRL-Meta | https://github.com/AI4Finance-Foundation/FinGPT |
| Stars / Forks / Watchers | 16,548 / 3,537 / 237 | 1,946 / 751 / 50 | 21,347 / 3,024 / 315 |
| Last push | 2026-09-28 | 2026-09-28 | 2026-09-23 |
| Latest release | v0.3.8（2026-03-20） | v0.3.6（2022-06-26） | v1.0.0（2026-04-08） |
| Maintenance | 有更新，但 open issues 307、品質參差 | 低（release 停在 2022） | 有更新，主要是 notebook/模型 |
| License | MIT | MIT | MIT |
| Language | Jupyter/Python；stable-baselines3、ElegantRL、RLlib | Python；gym envs + data processors | Jupyter/Python；HF transformers、PEFT/LoRA |
| LLM provider | 無（DRL） | 無 | 自訓 LoRA（Llama2-7B/13B、ChatGLM2）＋ OpenAI 用於資料/比較 |

## Architecture / Data / Decision

- **FinRL**：三層 — data processors（Yahoo、Alpaca、WRDS 等）→ gym 環境（stock trading、**portfolio allocation**、crypto）→ DRL agents（A2C/PPO/DDPG/SAC/TD3）。
- **Portfolio allocation env**（`StockPortfolioEnv`）：state = 過去 252 日共變異數矩陣 + 技術指標；action = 每檔一個實數，經 **softmax normalization** 轉成權重（long-only、總和 1、無現金部位）；reward = portfolio value 變化；有 `transaction_cost_pct` 參數與 `turbulence_threshold`（市場亂流時清倉）。
- **FinRL-Meta**：更多市場的資料處理器與 env、"dynamic datasets"；release 停滯。
- **FinGPT**：開源金融 LLM（情緒分析 v3：Llama2-13B LoRA，F1 在 FPB/FiQA 等勝過 GPT-4）、FinGPT-Forecaster（DOW30 週報酬方向預測 + 分析，2023-05~2024-05 資料集）、RAG 情緒分析、Benchmark。

## Portfolio Logic / Risk

- FinRL portfolio env 是**真正的多股票配置**（連續權重），但：無整張限制、無個股上限、無現金下限、softmax 權重分散度由網路輸出決定；turbulence 規則為唯一風控。
- FinGPT 不做組合，只產生情緒/預測訊號。

## Memory

皆無 LLM 記憶機制（FinRL 的 `asset_memory/actions_memory` 只是回測紀錄）。

## Backtest

FinRL：train/trade split 回測、DRL baseline；FinMem/FinCon/FinAgent 均用 FinRL 的 A2C/PPO/DQN 當 baseline。FINSABER 也整合 FinRL baseline。DRL 需要多年訓練資料（FinCon 回推到 2018 才收斂）。

## Strength

- FinRL：portfolio allocation env、大量教學、成為 baseline 事實標準。
- FinGPT：可本地部署的金融情緒模型（成本低、無資料外洩）。

## Weakness

- FinRL：品質參差、教學取向、DRL 在 24 日比賽無法線上學習且過擬合嚴重；無台股整張/上限等規則。
- FinGPT：英文為主（雖有中文 ChatGLM2 版本但針對 A 股），模型舊（Llama2 世代），對繁中台股新聞效果未知；Forecaster 為 DOW30。

## Reuse potential

- FinRL：**2/5**（可參考 env 介面與 softmax 權重做法；不建議用 DRL 做主策略）。
- FinRL-Meta：**1/5**。
- FinGPT：**2/5**（若需本地情緒分類可參考 LoRA 流程；但直接用現代 LLM 做繁中新聞情緒更實際）。

## Competition fit（1–5）

FinRL 2/5、FinRL-Meta 1/5、FinGPT 2/5。

## Classification

- FinRL：**C — Educational/Demo**（偏教學 + 研究 baseline）
- FinRL-Meta：**C — Educational/Demo**
- FinGPT：**A/C**（模型與論文為研究級，repo 多為 notebook 示範）

## Evidence

- https://api.github.com/repos/AI4Finance-Foundation/FinRL 、 .../FinRL-Meta 、 .../FinGPT
- https://raw.githubusercontent.com/AI4Finance-Foundation/FinRL/master/finrl/meta/env_portfolio_allocation/env_portfolio.py
- https://raw.githubusercontent.com/AI4Finance-Foundation/FinGPT/master/README.md
- https://huggingface.co/FinGPT/fingpt-sentiment_llama2-13b_lora 、 https://huggingface.co/datasets/FinGPT/fingpt-forecaster-dow30-202305-202405 （README 引用）
- 存取日期：2026-10-04
