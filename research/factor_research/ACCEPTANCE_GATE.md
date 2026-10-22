# Candidate Acceptance Gate（研究前預先定義；2026-10-14，portfolio 結果產生前寫定）

> AI 產生內容，需人工審閱。此 gate 寫定後不得因結果修改；如需修改須另立版本並說明理由。

## 期間與資料切分（固定）
- 窗口：自 2024-07-01 起連續、不重疊的 24 交易日區塊（R01–R23，`results/windows.json`），不挑選期間。
- DISCOVERY：窗口起日 < 2025-07-01（11 窗）——**唯一**可用來決定因子方向、權重、是否入選的期間。
- VALIDATION：2025-07-01 ≤ 起日 < 2026-02-01（6 窗）；HOLDOUT：起日 ≥ 2026-02-01（6 窗）。OOS = VALIDATION + HOLDOUT（12 窗）。
- W1–W5（Round 03）另行報告作相容比較；不作入選依據（Quant v1 本身即在 W1–W5 選出，屬樣本內）。

## 篩選（只看 DISCOVERY）
因子進入候選需同時：DISCOVERY 增量 5D Rank IC（權重 0.2、方向由 DISCOVERY 決定）> 0，且 DISCOVERY 各窗 paired Δreturn 平均 > 0。
組合候選（ablation）只由通過篩選的因子族組成。

## Gate（全部以 OOS 12 窗、與 Quant v1 同窗 paired 比較；全部須通過）
| # | 條件 | 門檻 |
|---|---|---|
| 1 | OOS median return | candidate median ≥ v1 median，且 paired Δreturn 平均 > 0 |
| 2 | cost-adjusted | cost ×1.5 與 +20bp slippage 下，OOS paired Δreturn 平均 ≥ 0 |
| 3 | worst window | candidate 最差 OOS 窗報酬 ≥ v1 最差 − 1.0 pp |
| 4 | MDD | OOS 平均 MDD ≤ v1 + 1.0 pp；最大 MDD ≤ v1 + 2.0 pp |
| 5 | Rank IC | 增量 5D Rank IC 在 VALIDATION 與 HOLDOUT 皆 ≥ 0 |
| 6 | sensitivity | 權重 −20%/−10%/基準/+10%/+20% 中至少 4 個 OOS paired Δreturn 平均 ≥ 0；否則 FRAGILE |
| 7 | turnover | OOS 平均 post-day1 turnover ≤ v1 + 0.50（NAV 倍數 / 窗） |
| 8 | transaction cost | OOS 平均費稅 ≤ v1 × 1.5 |
| 9 | Active Share | 可計算之窗：官方 ≥ 15%（內部 30% 以 WARN 報告） |
| 10 | compliance | violations 不多於 v1；validation failures = 0 |
| 11 | fallback | 0 unexpected fallback |
| 12 | PIT | PIT_SAFE（PIT_CONDITIONAL 需說明；PIT_UNSAFE 直接排除） |
| 13 | 正式可得 | 比賽期間每日可合法自動取得 |

## 統計說服力（不改變 gate，但決定結論強度）
- OOS paired Δreturn 的 bootstrap 95% CI（窗為單位，10,000 次，seed 7）；若含 0 → 不得宣稱「顯著改善」。
- 記錄測試總數（因子 × 權重 × 期間），以 Harvey-Liu-Zhu 精神：新因子 t ≈ 3 才視為強證據。
- 1000 個隨機 25 檔組合（seed 7）百分位：candidate OOS 中位百分位 ≥ v1。
- 樣本不足（OOS 只有 12 窗）→ 結論標示 INSUFFICIENT_STATISTICAL_POWER 為可能結果。

## 分類
PROMISING（gate 全過）／NEUTRAL（無明顯增減）／REDUNDANT（與 v1 或其他因子高度相關，增量 ≈ 0）／FRAGILE（敏感度失敗）／
PIT_UNSAFE／DATA_BLOCKED（資料不可得）／REJECT（gate 失敗或惡化）。結論可為 KEEP_QUANT_V1。
