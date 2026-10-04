# 11 Source Index

> Access date：全部為 2026-10-04（除另註）。Reliability：H＝官方/同儕審查/原始程式碼；M＝preprint、官方部落格、可信媒體；L＝論壇、二手報導、未能讀取全文。
> 更細的出處（檔案路徑、行號）見 `repo_notes/*.md` 與 `raw_notes/*.md`；GitHub 搜尋查詢紀錄見 `raw_notes/gh_search_log.md`。

## A. 競賽官方檔案（本地）

| Title | Type | Path/URL | Purpose | Rel. |
|---|---|---|---|---|
| AI CUP 2026玉山人工智慧公開挑戰賽_比賽辦法 | Competition file | ./AI CUP 2026玉山人工智慧公開挑戰賽_比賽辦法.pdf | 主規則 | H |
| D-Plan.schema_v4.2.json | Competition file | ./D-Plan.schema_v4.2.json | 提交結構 | H |
| D-Plan_撰寫指南_v4.2.md | Competition file | ./D-Plan_撰寫指南_v4.2.md | 提交語意/公式 | H |
| D-Plan_TEAM_042 / TEAM_043 範例 | Competition file | ./D-Plan_TEAM_04x_2026-10-27.json | 正/反例 | H |
| 150 檔清單 | Competition file | ./玉山挑戰賽_投資組合及交易標的_150檔清單_v1.pdf | Universe | H |
| 主動型 ETF 列表 | Competition file | ./玉山挑戰賽_主動型ETF列表_v1.pdf | Active Share benchmark | H |
| ETF 投資策略說明文件 範例 / 繳交格式 | Competition file | ./玉山挑戰賽_ETF投資策略說明文件_*.pdf/.docx | 策略文件 | H |
| Google Token Credit 領取方式 | Competition file | ./玉山挑戰賽_Google Token Credit領取方式_v1.pdf | 資源 | H |
| 舊版 schema v4.0 / 指南 v4.1 | Competition file | ./D-Plan.schema.json、./D-Plan_撰寫指南.md | 差異比對 | H |
| 主辦方 Email 回覆（使用者轉述） | Correspondence | research/sources/organizer_email_reply_summary.md | 自主性規則 | M（原信未存檔） |
| 玉山 AI 競技場 | Official site | https://esun-ai-challenge.tw | 平台 | H |

## B. GitHub Repositories（深讀）

| Title | Type | URL | Purpose | Rel. |
|---|---|---|---|---|
| TradingAgents | GitHub | https://github.com/TauricResearch/TradingAgents | 多 Agent 辯論、PIT guard、memory log | H（程式） |
| ai-hedge-fund | GitHub | https://github.com/virattt/ai-hedge-fund （含 tag v2026.7.10） | 組合管線、ledger | H |
| FinRobot | GitHub | https://github.com/AI4Finance-Foundation/FinRobot | numeric grounding | H |
| dexter | GitHub | https://github.com/virattt/dexter | 單公司研究 | H |
| FinMem | GitHub | https://github.com/pipiku915/FinMem-LLM-StockTrading | 分層記憶 | H |
| FinCon | GitHub | https://github.com/The-FinAI/FinCon | 僅 README | H（確認無程式） |
| FinAgent | GitHub | https://github.com/DVampire/FinAgent ；https://github.com/effective-p/FinAgent | 反思 | H |
| FINSABER | GitHub | https://github.com/waylonli/FINSABER ；https://waylonli.github.io/FINSABER | 偏誤控制評估 | H |
| Qlib | GitHub | https://github.com/microsoft/qlib | 量化骨幹 | H |
| RD-Agent | GitHub | https://github.com/microsoft/RD-Agent | 因子挖掘 Agent | H |
| FinRL / FinRL-Meta | GitHub | https://github.com/AI4Finance-Foundation/FinRL ；/FinRL-Meta | RL 組合 | H |
| FinGPT | GitHub | https://github.com/AI4Finance-Foundation/FinGPT | 情緒 | H |
| QuantHarness (ex-QuantAgent) | GitHub | https://github.com/Y-Research-SBU/QuantHarness | 對照 | H |
| Stockagent | GitHub | https://github.com/MingyuJ666/Stockagent | 對照 | H |
| AlphaAgents 非官方實作 | GitHub | https://github.com/vedurmaliya/alpha-agents | 對照 | L |
| INVESTOR-BENCH / Agent_Market_Arena | GitHub | https://github.com/felis33/INVESTOR-BENCH ；https://github.com/The-FinAI/Agent_Market_Arena | 評測 | M |

## C. GitHub Landscape（metadata + 結構）
完整清單（約 40 個）見 `repo_notes/Landscape_Scan.md` 與 `04_GITHUB_REPO_COMPARISON.csv`。包含：HKUDS/Vibe-Trading、HKUDS/AI-Trader、hsliuping/TradingAgents-CN、ValueCell-ai/valuecell、OpenByteInc/QuantDinger、The-Swarm-Corporation/AutoHedge、TraderAlice/OpenAlice、FinStep-AI/ContestTrade、HKUSTDial/DeepFund、gta0804/MASS、Open-Finance-Lab/AgenticTrading、kyky2347/ALTA、mnemox-ai/tradememory-protocol、FreedomIntelligence/TwinMarket、xbtlin/ai-berkshire、Lumiwealth/lumibot、chrisworsey55/atlas-gic、tensortrade-org/tensortrade、Xtra-Computing/CryptoTrade、24mlight/A_Share_investment_Agent、olaxbt/ai-market-maker、flash131307/multi-agent-investment、PyPortfolio/PyPortfolioOpt、dcajasn/Riskfolio-Lib、skfolio/skfolio、cvxgrp/cvxportfolio、polakowo/vectorbt、mementum/backtrader、stefan-jansen/zipline-reloaded、pmorissette/bt、nautechsystems/nautilus_trader、openbq-org/OpenBB、FinMind/FinMind、mlouielu/twstock、Sinotrade/Shioaji、langchain-ai/langgraph、pydantic/pydantic-ai、google/adk-python。Type: GitHub；Rel.: M（未讀全部程式碼，僅頂層結構與 README）。

## D. arXiv / 論文（LLM 金融 Agent）

| Title | URL | Purpose | Rel. |
|---|---|---|---|
| TradingAgents: Multi-Agents LLM Financial Trading Framework | https://arxiv.org/abs/2412.20138 | 架構/實驗 | M |
| FinRobot | https://arxiv.org/abs/2405.14767 ；https://arxiv.org/abs/2411.08804 | 研究報告 Agent | M |
| FinMem | https://arxiv.org/abs/2311.13743 | 記憶 | M |
| FinCon (NeurIPS 2024) | https://arxiv.org/abs/2407.06567 | 階層/CVRF | H |
| FinAgent | https://arxiv.org/abs/2402.18485 | 多模態反思 | M |
| FINSABER (KDD 2026) | https://arxiv.org/abs/2505.07078 | 偏誤控制重測 | M-H |
| AlphaAgents (BlackRock) | https://arxiv.org/abs/2508.11152 | 多 Agent 選股 | M |
| QuantAgent | https://arxiv.org/abs/2402.03755 ；https://arxiv.org/abs/2509.09995 | 對照 | M |
| MarketSenseAI 2.0 | https://arxiv.org/abs/2502.00415 | 對照（僅摘要） | L |
| RD-Agent(Q) | https://arxiv.org/abs/2505.15155 | 因子挖掘 | M |
| MASS | https://arxiv.org/abs/2505.10278 | 組合建構 multi-agent | M |
| Agent Market Arena | https://arxiv.org/abs/2510.11695 | live 評測 | M |
| LiveTradeBench | https://arxiv.org/abs/2511.03628 | live 評測 | M |
| Trading-R1（README 引用，未讀） | https://arxiv.org/abs/2509.11420 | — | L |
| 其他（agent 筆記引用）| https://arxiv.org/abs/2407.18957 ；/2406.06379 ；/2501.12399 ；/2605.24564 | 對照 | L-M |

## E. 偏誤 / LLM 前視偏誤

| Title | URL | Rel. |
|---|---|---|
| Glasserman & Lin 2023, Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment | https://arxiv.org/abs/2309.17322 | M-H |
| Lopez-Lira, Tang & Zhu 2025, The Memorization Problem | https://arxiv.org/abs/2504.14765 | M-H |
| Time Machine GPT (NAACL Findings 2024) | https://arxiv.org/abs/2404.18543 | H |
| ChronoGPT / instruction-tuned | https://arxiv.org/abs/2502.21206 ；https://arxiv.org/abs/2510.11677 | M |
| DatedGPT | https://arxiv.org/abs/2603.11838 | M |
| Look-Ahead-Bench | https://arxiv.org/abs/2601.13770 | M |
| Sarkar & Vafa (ICML 2025) | https://icml.cc/virtual/2025/48685 | M |
| Bailey et al., Probability of Backtest Overfitting | https://papers.ssrn.com/abstract=2326253 | H |

## F. 實證金融（短週期訊號）

| Title | URL | Rel. |
|---|---|---|
| Jegadeesh & Titman 1993 (JF) | https://ideas.repec.org/a/bla/jfinan/v48y1993i1p65-91.html | H |
| Asness, Moskowitz & Pedersen 2013 | https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf | H |
| Du, Huang & Liao 2009 | https://ideas.repec.org/a/eee/jebusi/v61y2009i2p140-152.html | H |
| Chui, Titman & Wei 2010 (JF) | https://ideas.repec.org/a/bla/jfinan/v65y2010i1p361-392.html | H |
| Ho, Hsiao, Lo & Yang 2023 (PBFJ) | https://scholars.ntou.edu.tw/handle/123456789/24532 | H |
| Daniel & Moskowitz 2016 (JFE) | https://www.nber.org/papers/w20439 | H |
| Jegadeesh 1990 / Lehmann 1990 | https://www.nber.org/papers/w2533 | H |
| Da, Liu & Schaumburg 2014 | https://ideas.repec.org/a/inm/ormnsc/v60y2014i3p658-674.html | H |
| Moskowitz & Grinblatt 1999 | https://ideas.repec.org/a/bla/jfinan/v54y1999i4p1249-1290.html | H |
| George & Hwang 2004 (52-week high) | （書目） | H |
| Bernard & Thomas 1989 (PEAD) | （書目） | H |
| Jegadeesh & Livnat 2006 (FAJ / JAE) | https://ideas.repec.org/a/taf/ufajxx/v62y2006i2p22-34.html ；https://ideas.repec.org/a/eee/jaecon/v41y2006i1-2p147-171.html | H |
| 陳柔君、劉彥瑞、蕭朝興 2022 管理學報（月營收） | https://lawdata.com.tw/tw/detail.aspx?no=484826 | M-H |
| Lu & Xin 2024 (Int'l J. Accounting) | https://ideas.repec.org/a/wsi/tijaxx/v59y2024i01ns1094406024500021.html | H |
| Wang & Lien 2022 (RQFA) | https://ideas.repec.org/a/kap/rqfnac/v59y2022i2d10.1007_s11156-022-01051-1.html | H |
| 洪偉倫 2026 政大論文（月營收） | https://thesis.lib.nccu.edu.tw/detail/5de91a46dbc69757987d294b65a5a9cc/ | M |
| Richards 2005 (JFQA) | https://www.rba.gov.au/publications/rdp/2004/2004-05.html | H |
| Barber, Lee, Liu & Odean 2009 (RFS) | https://ideas.repec.org/a/oup/rfinst/v22y2009i2p609-632.html | H |
| 徐暄皓 2021、林軒白 2016 台大論文 | https://tdr.lib.ntu.edu.tw/handle/123456789/74582 ；/19442 | M |
| Eun & Shim 1989 (JFQA) | https://ideas.repec.org/a/cup/jfinqa/v24y1989i02p241-256_01.html | H |
| Tetlock 2007 (JF) | https://www.columbia.edu/~pt2238/papers/Tetlock_Media_Sentiment_JF.pdf | H |
| Lopez-Lira & Tang 2023 | https://arxiv.org/abs/2304.07619 | M-H |
| McLean & Pontiff 2016；Hou, Xue & Zhang 2020 | https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html | H |
| MSCI index review dates | https://www.msci.com/eqb/pressreleases/archive/ir_dates.pdf | H |

## G. Hybrid vs Pure LLM

| Title | URL | Rel. |
|---|---|---|
| FinQA (EMNLP 2021) | https://aclanthology.org/2021.emnlp-main.300 | H |
| FinanceBench | https://arxiv.org/abs/2311.11944 | M-H |
| GSM-Symbolic | https://arxiv.org/abs/2410.05229 | M-H |
| Atil et al. (non-determinism) | https://arxiv.org/abs/2408.04667 | M-H |
| Tan et al. NeurIPS 2024 (LLM 對時序預測無益) | https://arxiv.org/abs/2406.16964 | H |
| Romanko, Narayan & Kwon 2023 (ChatGPT portfolio selection) | https://arxiv.org/abs/2308.06260 | M |
| Ko & Lee 2024 (FRL) | https://ideas.repec.org/a/eee/finlet/v64y2024ics154461232400463x.html | H |
| Man Group, What AI Can (and Can't Yet) Do for Alpha | https://www.man.com/insights/what-ai-can-do-for-alpha | M-H |
| Hedgeweek: Man Group AlphaGPT | https://hedgeweek.com/news/man-group-deploys-agentic-ai-for-quant-signal-discovery | M |
| Alpha Arena 媒體報導 | https://iweaver.ai/blog/alpha-arena-ai-trader-showdown | L |

## H. 台股資料源 / 官方文件

| Title | URL | Rel. |
|---|---|---|
| TWSE OpenAPI | https://openapi.twse.com.tw/v1/swagger.json | H |
| TWSE STOCK_DAY / T86 / MI_MARGN / TWT49U | https://www.twse.com.tw | H |
| TPEx OpenAPI | https://www.tpex.org.tw/openapi/ | H |
| TAIFEX 盤後交易說明 | https://www.taifex.com.tw/cht/4/aHIntroduction | M-H |
| FinMind Pricing | https://finmind.github.io/Pricing/ | H |
| twstock (PyPI) | https://pypi.org/project/twstock/ | L-M |
| Goodinfo 服務條款（403 無法讀取） | https://goodinfo.tw/tw/ServiceTerms.asp | Unknown |
| MOPS 改版（工商時報 2025） | https://www.ctee.com.tw/news/20250113700198-439901 | M |
| TWSE 主動式 ETF 列表 | https://www.twse.com.tw/zh/products/securities/etf/products/active-list.html | H |
| TWSE 主動式 ETF 揭露說明 | https://www.twse.com.tw/market_insights/zh/detail/8a8216d697fc438f0198c55cfd800334 | H |
| Stockfeel 主動式 ETF 規模排名 | https://www.stockfeel.com.tw/ | M |
| Fugle 主動 ETF 持股跟單回測 | https://blog.fugle.tw/post/active-etf-holdings-backtest | M-L |
| Taiwan News 2021 Q3 財報期限順延 | https://www.taiwannews.com.tw/zh/news/4334181 | M |
| MSCI EM rebalance study (UCT) | https://open.uct.ac.za/items/b6627141-e4e2-4ac6-b9b6-82ad43d68aeb | M |
| NYCU 美股→台股外溢論文 | https://ir.lib.nycu.edu.tw/handle/11536/43039 | L |
