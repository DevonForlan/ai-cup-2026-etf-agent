# Daily Prediction — 2026-10-16（PRECOMPETITION_PAPER_RUN）

> **PRECOMPETITION_PAPER_RUN** — 賽前紙上交易，**不是正式比賽成績，也不是正式 D-Plan**。不上傳、不提交。AI 產生內容，需人工審閱。

| 項目 | 值 |
|---|---|
| Date（產生日） | 2026-10-15 |
| Run time | 2026-10-15T22:42:32.185317+08:00 |
| Trade date | 2026-10-16 |
| Run ID | 20261015_224232_git23f2428-dirty |
| Starting point | official (replay:C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽\data\paper_ledger) + internal state |

## Portfolio

| 項目 | 值 |
|---|---|
| Total holdings | 24 |
| Cash weight (est.) | 6.71% |
| Active Share (official, top-15, NAV) | PASS (44.69%) |
| Regime / posture | neutral / hold |
| Compliance | Universe 150: PASS / Holdings 20-30: PASS / 2330 <= 25%: PASS / Other stocks <= 10%: PASS / Cash < 25%: PASS / Active Share official >= 15%: PASS (44.69%) / Active Share internal safety target: PASS (target 30%) / Strategy consistency: PASS / D-Plan validation: PASS / Manual override: NO |

## Holdings

| Ticker | Name | Target weight | Current weight | Action | Rank |
|---|---|---|---|---|---|
| 3702 | 大聯大 | 5.48% | 5.48% | HOLD | 4 |
| 2451 | 創見 | 5.41% | 5.41% | HOLD | 1 |
| 2360 | 致茂 | 4.95% | 4.95% | HOLD | 2 |
| 7734 | 印能科技 | 4.91% | 4.91% | HOLD | 6 |
| 3661 | 世芯-KY | 4.73% | 4.73% | HOLD | 3 |
| 2347 | 聯強 | 4.26% | 4.26% | HOLD | 7 |
| 2615 | 萬海 | 4.09% | 4.09% | HOLD | 15 |
| 2376 | 技嘉 | 4.06% | 4.06% | HOLD | 5 |
| 2344 | 華邦電 | 4.00% | 4.00% | HOLD | 14 |
| 4938 | 和碩 | 4.00% | 4.00% | HOLD | 11 |
| 8299 | 群聯 | 3.89% | 3.89% | HOLD | 8 |
| 2383 | 台光電 | 3.81% | 3.81% | HOLD | 12 |
| 4979 | 華星光 | 3.52% | 3.52% | HOLD | 23 |
| 2883 | 凱基金 | 3.45% | 3.45% | HOLD | 78 |
| 6669 | 緯穎 | 3.44% | 3.44% | HOLD | 9 |
| 6770 | 力積電 | 3.41% | 3.41% | HOLD | 20 |
| 2337 | 旺宏 | 3.41% | 3.41% | HOLD | 19 |
| 3081 | 聯亞 | 3.37% | 3.37% | HOLD | 17 |
| 7769 | 鴻勁 | 3.33% | 3.33% | HOLD | 13 |
| 3443 | 創意 | 3.26% | 3.26% | HOLD | 10 |
| 3680 | 家登 | 3.22% | 3.22% | HOLD | 21 |
| 5289 | 宜鼎 | 3.20% | 3.20% | HOLD | 18 |
| 2408 | 南亞科 | 3.13% | 3.13% | HOLD | 16 |
| 6187 | 萬潤 | 2.96% | 2.96% | HOLD | 22 |

## Orders

| Ticker | Side | Shares |
|---|---|---|
| - | - | - |

## Quant

- Primary signals (frozen Quant Core v1): revenue_yoy 0.7, revenue_mom 0.3（百分位排名）
- Ranking: 147 eligible；前 5 名：2451 創見（score 0.965）、2360 致茂（score 0.944）、3661 世芯-KY（score 0.942）、3702 大聯大（score 0.928）、2376 技嘉（score 0.918）

## Claude（敘事；不影響決策）

- Runtime: Claude CLI used（calls 3, failed 0, research inferences 4）
- **Market view**: 隔夜美股普遍走弱：S&P500 為 -1.11%，Nasdaq100 為 -2.02%，費城半導體 SOX 為 -4.30%，TSM ADR 為 -3.40%。台指期夜盤相對前日結算為 -1.75%，USD/TWD 為 -0.04%，匯率變動有限。台股前日偏弱，上漲家數 22、下跌家數 124，1 日報酬中位數 -4.32%，5 日報酬中位數 -4.91%，顯示短線賣壓集中、跌勢普遍。不過 20 日報酬中位數仍為 +2.04%，150 檔中站上 20 日均線的比例為 40.7%，介於量化門檻之間，因此模型判定市場狀態為 neutral，曝險意圖為 hold，估計現金比率 6.71%，淨流量 +0 元，延續既有配置（O1、O2）。
- **Counter evidence / major risk**: 短線與中期訊號方向不一致。看空的一方：隔夜 SOX -4.30% 與 TSM ADR -3.40% 對半導體權值股不利，台指期夜盤 -1.75%，加上前日下跌家數 124 遠多於上漲家數 22，短線可能延續弱勢。看多的一方：20 日報酬中位數 +2.04% 仍為正值，站上 20 日均線比例 40.7% 尚未落入偏空區間，中期結構未明確轉弱。
- **Portfolio thesis (前 3 筆決策)**:

## D-Plan

- Version: 4.3
- Validation: PASS（{'PASS': 26, 'NOT_APPLICABLE': 1, 'NOT_IMPLEMENTED': 6}）
- Final candidate: `submissions\20261016\FINAL\D-Plan_TEAM_TEST_2026-10-16.json`（sha256 sha256:53040c245219ace9…）
- Decision fingerprint: sha256:61052bd698c4c386c35a2e092434842762214251a067374f13eaf470c84a2619

## Overall: **READY**
