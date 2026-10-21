# Daily Prediction — 2026-10-15（PRECOMPETITION_PAPER_RUN）

> **PRECOMPETITION_PAPER_RUN** — 賽前紙上交易，**不是正式比賽成績，也不是正式 D-Plan**。不上傳、不提交。AI 產生內容，需人工審閱。

| 項目 | 值 |
|---|---|
| Date（產生日） | 2026-10-14 |
| Run time | 2026-10-14T21:26:41.240518+08:00 |
| Trade date | 2026-10-15 |
| Run ID | 20261014_212641_git23f2428 |
| Starting point | official (replay:C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽\data\paper_ledger) + internal state |

## Portfolio

| 項目 | 值 |
|---|---|
| Total holdings | 24 |
| Cash weight (est.) | 6.33% |
| Active Share (official, top-15, NAV) | PASS (41.41%) |
| Regime / posture | risk_on / hold |
| Compliance | Universe 150: PASS / Holdings 20-30: PASS / 2330 <= 25%: PASS / Other stocks <= 10%: PASS / Cash < 25%: PASS / Active Share official >= 15%: PASS (41.41%) / Active Share internal safety target: PASS (target 30%) / Strategy consistency: PASS / D-Plan validation: PASS / Manual override: NO |

## Holdings

| Ticker | Name | Target weight | Current weight | Action | Rank |
|---|---|---|---|---|---|
| 3702 | 大聯大 | 5.30% | 5.30% | HOLD | 4 |
| 2451 | 創見 | 5.28% | 5.28% | HOLD | 1 |
| 2360 | 致茂 | 5.19% | 5.19% | HOLD | 2 |
| 7734 | 印能科技 | 5.15% | 5.15% | HOLD | 5 |
| 3661 | 世芯-KY | 4.74% | 4.74% | HOLD | 3 |
| 2615 | 萬海 | 4.05% | 4.05% | HOLD | 14 |
| 2344 | 華邦電 | 4.02% | 4.02% | HOLD | 15 |
| 2347 | 聯強 | 4.02% | 4.02% | HOLD | 7 |
| 8299 | 群聯 | 3.94% | 3.94% | HOLD | 8 |
| 2376 | 技嘉 | 3.93% | 3.93% | HOLD | 6 |
| 2383 | 台光電 | 3.88% | 3.88% | HOLD | 12 |
| 4938 | 和碩 | 3.84% | 3.84% | HOLD | 10 |
| 6669 | 緯穎 | 3.61% | 3.61% | HOLD | 9 |
| 4979 | 華星光 | 3.60% | 3.60% | HOLD | 23 |
| 7769 | 鴻勁 | 3.48% | 3.48% | HOLD | 13 |
| 3081 | 聯亞 | 3.47% | 3.47% | HOLD | 17 |
| 6770 | 力積電 | 3.45% | 3.45% | HOLD | 20 |
| 2337 | 旺宏 | 3.39% | 3.39% | HOLD | 19 |
| 3443 | 創意 | 3.31% | 3.31% | HOLD | 11 |
| 2883 | 凱基金 | 3.28% | 3.28% | HOLD | 24 |
| 3680 | 家登 | 3.25% | 3.25% | HOLD | 21 |
| 2408 | 南亞科 | 3.23% | 3.23% | HOLD | 16 |
| 5289 | 宜鼎 | 3.17% | 3.17% | HOLD | 18 |
| 6187 | 萬潤 | 3.09% | 3.09% | HOLD | 22 |

## Orders

| Ticker | Side | Shares |
|---|---|---|
| - | - | - |

## Quant

- Primary signals (frozen Quant Core v1): revenue_yoy 0.7, revenue_mom 0.3（百分位排名）
- Ranking: 146 eligible；前 5 名：2451 創見（score 0.963）、2360 致茂（score 0.942）、3661 世芯-KY（score 0.939）、3702 大聯大（score 0.926）、7734 印能科技（score 0.916）

## Claude（敘事；不影響決策）

- Runtime: Claude CLI used（calls 3, failed 0, research inferences 4）
- **Market view**: 系統判定本日市場狀態為 risk_on，淨曝險意圖為 hold。依據是 150 檔中站上 20 日均線的比例為 64.7%，20 日報酬中位數為 +4.22%，符合判定規則中「站上 20 日均線比例 ≥ 60% 且 20 日中位報酬為正」的條件，代表中期趨勢仍偏多。前一交易日的市場廣度也佳：上漲 110 家、下跌 34 家，1 日報酬中位數為 +1.22%。隔夜方面，台指期夜盤相對前日結算 +0.75%，TSM ADR 隔夜 +0.17%，對開盤略為有利。本日淨資金流為 +0 元，預估現金比例為 6.33%，整體部位維持現狀（O1、O2）。
- **Counter evidence / major risk**: 短線動能和美股表現與多頭判定不完全一致。5 日報酬中位數為 -0.37%，顯示近一週個股整體略為回落，與 20 日正報酬方向相反。美股隔夜普遍小跌：Nasdaq100 -0.31%、費城半導體 SOX -0.23%、S&P500 -0.02%，與台指期夜盤及 TSM ADR 的上漲方向分歧。此外 USD/TWD 為 +0.60%，若代表新台幣走弱，可能對資金面形成壓力，須留意多頭格局能否延續。
- **Portfolio thesis (前 3 筆決策)**:

## D-Plan

- Version: 4.3
- Validation: PASS（{'PASS': 26, 'NOT_APPLICABLE': 1, 'NOT_IMPLEMENTED': 6}）
- Final candidate: `submissions\20261015\FINAL\D-Plan_TEAM_TEST_2026-10-15.json`（sha256 sha256:ff6186283070f15c…）
- Decision fingerprint: sha256:fa174bd7f84eef72eb2ac2995b09ba3447643c3696f1031282734c8f0a25a07b

## Overall: **READY**
