# 純 LLM 交易 Agent vs. 量化與 LLM 混合架構：證據整理

> 撰寫日：2026-10-04。可信度：H／M／L／Unknown。

## 1. 結論摘要

現有證據相當一致：**LLM 擅長讀文字、抽取資訊、提出假設與寫程式；不擅長精確的數值計算、穩定重現的決策，以及風險控制。** 學術界與業界（Man Group、BlackRock）的實際做法都是把 LLM 放在「研究與特徵生成」這一層，最後的權重、限制條件檢查與下單則交給確定性的程式或最佳化器，並保留人工審核或規則閘門。純 LLM agent 在嚴格、長期、無偏誤的評估下，相對於簡單基準的優勢大多消失。

## 2. LLM 在數值、推理與穩定性上的限制

- **FinQA**：Chen et al. (2021)〈FinQA: A Dataset of Numerical Reasoning over Financial Data〉, EMNLP 2021. https://aclanthology.org/2021.emnlp-main.300 〔H〕
  預訓練模型在多步數值推理上遠不如專家。這是早期模型的結果，但「多步計算容易出錯」的性質至今仍然存在。
- **FinanceBench**：Islam et al. (2023)〈FinanceBench: A New Benchmark for Financial Question Answering〉, arXiv:2311.11944. https://arxiv.org/abs/2311.11944 〔M-H〕
  10,231 題公開財報的開卷問答。GPT-4-Turbo 搭配檢索系統時，**81% 的題目答錯或拒答**；所有受測模型都有幻覺問題，作者認為這限制了企業使用。此為 2023 年的模型，新模型已明顯進步，但檢索錯誤加上計算錯誤的風險仍在。
- **GSM-Symbolic**：Mirzadeh et al. (2024, Apple), arXiv:2410.05229. https://arxiv.org/abs/2410.05229 〔M-H〕
  加入一句看似相關、其實無關的子句，各家最先進模型的表現最多下降 65%。作者認為 LLM 的推理比較像機率式的樣式比對，對輸入的微小變動很敏感。
- **非確定性**：Atil et al. (2024)〈Non-Determinism of "Deterministic" LLM Settings〉, arXiv:2408.04667. https://arxiv.org/abs/2408.04667 〔M-H〕
  5 個 LLM 在 temperature=0 等「確定性」設定下各跑 10 次，準確率最多相差 15%，最好與最差可能結果的差距達 70%。**意涵：同一份輸入每天重跑可能得到不同的組合，因此需要快取、多次投票或改由程式決策。**
- **時間序列預測**：Tan et al. (2024)〈Are Language Models Actually Useful for Time Series Forecasting?〉, NeurIPS 2024 Spotlight. https://arxiv.org/abs/2406.16964 〔H〕
  把 LLM 元件移除或換成簡單的 attention 層，預測表現不會變差，通常反而更好；LLM 不能表示序列依賴，在少樣本情境也沒有幫助。**意涵：價量預測不應交給 LLM。**

## 3. 純 LLM 交易 agent 的實證

- **FINSABER**：Li, Kim, Cucuringu & Ma (2025), arXiv:2505.07078. https://arxiv.org/abs/2505.07078 〔M-H〕
  在 20 年、較廣股票池、控制偏誤的設定下，先前 LLM 策略的優勢消失；LLM 在多頭時太保守、在空頭時風控不足。
- **LiveTradeBench**（2025）, arXiv:2511.03628. https://arxiv.org/abs/2511.03628 〔M〕
  使用即時資料、不做離線回測，比較 21 個 LLM 在美股與 Polymarket 的表現：**LMArena 等通用排行榜的高分並不代表交易表現好**；各模型有明顯不同的風險偏好與配置風格。
- **Agent Market Arena**（2025）, arXiv:2510.11695. https://arxiv.org/abs/2510.11695 〔M〕
  即時、持續的多市場評估，發現 **agent 框架的設計比底層模型對結果的影響更大**。
- **Nof1 Alpha Arena Season 1**（2025/10/18–11/3，加密貨幣，每個模型 10,000 美元真錢）：Qwen3 Max 約 12,231 美元、DeepSeek 約 10,489 美元，其餘（Claude Sonnet 4.5、Gemini 2.5 Pro、Grok 4、GPT-5）虧損 40–59%。〔L：只有媒體報導，例如 https://iweaver.ai/blog/alpha-arena-ai-trader-showdown ；樣本極短、只有 6 個資產，**不能用來推論模型優劣**，但說明了純 LLM 自主交易的變異非常大〕
- **TradingAgents**：Xiao et al. (2024), arXiv:2412.20138. https://arxiv.org/abs/2412.20138 〔M〕
  多角色辯論架構（基本面、情緒、技術、多空研究員、風控、交易員），報告的報酬、Sharpe、MDD 都比基準好。但回測只有少數股票、期間很短，且落在模型的訓練期間內，有前視偏誤疑慮（見 pit_lookahead_bias.md）。

## 4. 混合架構的證據（LLM 選股或產生特徵，量化程式配置權重）

- **Romanko, Narayan & Kwon (2023)**〈ChatGPT-based Investment Portfolio Selection〉, arXiv:2308.06260. https://arxiv.org/abs/2308.06260 〔M〕（使用者原本提到「Ko & Lee 2023」，但這篇的作者是 Romanko 等人）
  ChatGPT **擅長選股、不擅長配權重**；把 ChatGPT 挑出的股票池交給量化最佳化（例如 mean-variance）的表現最好。作者明確以幻覺問題作為採用混合架構的理由。
- **Ko & Lee (2024)**〈Can ChatGPT improve investment decisions? From a portfolio management perspective〉, Finance Research Letters 64:105433. https://ideas.repec.org/a/eee/finlet/v64y2024ics154461232400463x.html 〔H〕
  ChatGPT 選出的資產在分散度指標上顯著優於隨機選擇，組成的投資組合也優於隨機組合。LLM 在這裡的角色是「助手」。
- **Chen, Kelly & Xiu (2023)**〈Expected Returns and Large Language Models〉（SSRN）〔M〕
  把 LLM **嵌入向量**當作特徵，輸入傳統的報酬預測模型，表現優於技術訊號與簡單 NLP。這是典型的「LLM 當特徵產生器」。
- **Kirtac & Germano (2024)**, Finance Research Letters 62:105227 〔M-H〕
  LLM 情緒分數加上規則化的多空組合，Sharpe 3.05（美股、未扣除前視偏誤的疑慮）。
- **Lopez-Lira & Tang (2023/2025)**, arXiv:2304.07619 〔M-H〕
  LLM 把頭條轉成 +1/0/−1 的分數，再由規則組成多空組合，同樣屬於混合架構。
- **BlackRock AlphaAgents**：Zhao, Lyu, Jones, Garber, Pasquali & Mehta（BlackRock）(2025)〈AlphaAgents: Large Language Model based Multi-Agents for Equity Portfolio Constructions〉, arXiv:2508.11152. https://arxiv.org/abs/2508.11152 〔M〕
  使用 GPT-4o 的基本面、情緒、估值三個代理人，加上辯論與**明確的風險容忍度設定**（風險中性或風險趨避），在風險中性設定下的回測風險調整報酬優於基準與單一代理人。此為研究原型，股票池小、期間短，作者也把它定位為輔助分析師。（第一作者的姓名未逐字核對 → M）
- **Man Group／Man Numeric 的 AlphaGPT**（業界）：
  - Hedgeweek 2025-07-11：https://hedgeweek.com/news/man-group-deploys-agentic-ai-for-quant-signal-discovery 〔M〕。AlphaGPT 會自動提出訊號、寫程式、回測，之後再進入標準的研究與投資委員會流程，已有數十個訊號核准上線；有「大量檢查點與護欄」。
  - Man Group〈What AI Can (and Can't Yet) Do for Alpha〉, Ziang Fang & Jason Moore, 2025-11-13. https://www.man.com/insights/what-ai-can-do-for-alpha 〔M-H，業者自述〕。重點包括：LLM 能勝任「實習生等級」的寫程式與研究摘要；風險在於大量測試會增加找到統計假象的機率，以及「構想 A、實作成 B」的幻覺；目前仍是 human-in-the-loop；每個上線策略都必須通過相同門檻。
  - Man Group 與 Anthropic 的合作新聞：https://www.man.com/news-centre/man-group-anthropic-partnership 〔M〕
- Two Sigma 的公開立場：沒有找到可驗證的一手來源 → **Unknown**。

## 5. 分工建議：LLM 與確定性程式各自負責什麼

| 任務 | 負責者 | 理由 |
|---|---|---|
| 抓取資料、時間戳、快照 | 確定性程式 | 必須可重現、可稽核（PIT） |
| VWAP、報酬、因子、z-score、營收 YoY／MoM 驚奇 | 確定性程式 | 算術不能出錯（FinQA、FinanceBench、GSM-Symbolic） |
| 價量預測、波動與共變異數估計 | 確定性程式（統計或機器學習） | LLM 在時間序列上沒有優勢（Tan et al. 2024） |
| 權重最佳化、整股取整、TSMC 25% 與其他 10% 上限、現金低於 25%、20–30 檔、Active Share 檢查 | 確定性程式加上 assert | 違反規則的代價很大；LLM 的輸出不穩定（Atil et al. 2024） |
| 成本與換手控制 | 確定性程式 | 0.585% 往返成本需要精算 |
| 重大訊息、新聞、法說會的事件分類與情緒（匿名化） | **LLM** → 結構化分數（JSON，含信心度） | LLM 的優勢所在（Lopez-Lira & Tang；Chen-Kelly-Xiu） |
| 營收或財報備註的文字解讀（例如一次性因素） | **LLM** | 把文字轉成特徵 |
| 產業與主題標籤（例如 AI 伺服器、CoWoS 供應鏈） | **LLM** 產生，人工核對後固定 | 這些標籤變動很少，適合預先產生並快取 |
| 對量化結果做常識審查（sanity check）、異常說明、產生報告 | **LLM** | 屬於輔助、可以否決但不負責最終決策 |
| 市場狀態判斷（風險開或關） | 程式規則為主，LLM 的意見只做微調並設上限 | 避免 LLM 的保守或過度反應（FINSABER） |
| 最終下單檔案 | 確定性程式產生，並通過規則驗證器 | 必須 100% 符合規則 |

**設計原則：**
1. LLM 的輸出一律使用 schema（JSON）、快取、記錄模型版本；同一輸入可以跑 3 次取多數或中位數。
2. LLM 對權重的影響要設上限，例如 LLM 分數只能讓個股權重在 ±2% 之內調整，或者只能把股票從候選名單中剔除。
3. 開發期間的評估：LLM 部分評估「抽取與分類的準確度」，報酬只在知識截止日之後的期間評估（見 pit 檔）。
4. 成本：每天只對有新事件（重訊、營收、新聞）的股票呼叫 LLM，150 檔股票池的成本可以控制。
5. 準備降級方案：LLM 服務失敗時，純量化策略要能單獨產生合法的組合。
