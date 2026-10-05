# ROUND 06 — Release Candidate

日期：2026-10-05　｜　依公司政策：AI 產生內容，需人工審閱。**未建立 git tag**（由隊伍負責人確認後人工建立，見 `docs/COMPETITION_CODE_FREEZE.md`）。

## Recommended release SHA：`83af462`
（最後一個修改 `agent/`、`config/`、`scripts/` 的 commit；之後只有報告 / 稽核索引 commit。）

`python agent\ops\verify_release.py --sha 83af462 --smoke` → **PASS**：commit 存在、策略設定 = 凍結紀錄、官方輸入（competition.yaml / D-Plan schema / 150 檔）與 HEAD 相同、暫存 worktree smoke tests 56 passed（工作樹未被改動）。

## Hashes（sha256 前 16 碼）

| 檔案 | sha256 |
|---|---|
| `config/strategy_quant_v1.yaml`（凍結 `f4dfb66`） | `f34fa02e924011b2` |
| `config/competition.yaml`（官方規則） | `9e7bf459d419b68e` |
| `D-Plan.schema_v4.2.json`（官方 schema） | `8787f041c3acc3e9` |
| `config/universe_150.csv`（官方 150 檔） | `5ceda5c92d3606cc` |
| `config/unconfirmed_rules.yaml` | `f430f315b346390d` |
| `config/ops.yaml` | `11f1317bff3aca3f` |
| `config/llm.yaml` / `config/llm_narrative_v1.yaml`（未啟用） | `48b8db0eeb7dce27` / `77eda0cba1b7824c` |
| prompts：event_extractor_v1 / market_narrator_v1 / reviewer_v1 / thesis_writer_v1 | `ed7a8419` / `7426916e` / `89fd70c5` / `57fb84d2` |

完整 hash：`audit/configs/CONFIGS.json`、`audit/prompts/PROMPTS.json`、`reports/round06_verify_release.json`。

## Tests
`.venv\Scripts\python.exe -m pytest` → **324 passed / 0 failed**（Round 05 的 267 全數保留）。Quant v1 W5 baseline：NAV 1,014,240,575.839861741934859718，0 違規 / 0 驗證失敗 / 0 fallback。

## 營運設定
Quant-only（`config/strategy_quant_v1.yaml`）、Template 敘事、不使用 LLM 訊號、Crash Guard 關閉。

## Known blockers（不影響 dry-run，阻擋 COMPETITION_READY）
1. **NC-1** 官方結算取得方式未確認（目前人工 SOP：`docs/OFFICIAL_SETTLEMENT_ENTRY_SOP.md`）。
2. **NC-1** 正式提交方式未確認（ManualSubmissionProvider：只準備檔案，人工上傳 + 回執）。
3. **NC-15** 首個交易日 10/26 或 10/27 未確認。
4. **REAL_LLM_STATUS = BLOCKED_NO_API_KEY**（比賽使用 Template 敘事，不影響 D-Plan）。

## Known risks（非阻擋）
- 中信 3 檔主動 ETF（00983A / 00995A / 00406A）發行商端目前回空 → STALE_FALLBACK（沿用 10/01–10/02 持股）；>10 交易日未恢復 → preflight BLOCK。
- 送件窗口「前一日 19:30」以日曆日實作（週一 D-Plan 需週日晚上或週一早上產生）；是否為交易日未確認。
- `config/ops.yaml market_holidays` 為空：比賽期間若有休市，需依 TWSE 官方公告填入，否則保守 BLOCK。
- 未在真實 19:30–08:55 窗口、以主辦方真實結算跑過 competition 模式。
