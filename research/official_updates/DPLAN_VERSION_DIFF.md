# D-Plan v4.2 → v4.3 差異與遷移說明

> 比對：根目錄 `D-Plan.schema_v4.2.json` / `D-Plan_撰寫指南_v4.2.md` vs 官網 2026-10-12 發布的 v4.3（本資料夾）。
> 結論：**官網已發布 v4.3（NEW_DPLAN_FOUND_AS_OF_2026-10-13）**，runtime 已依官方 v4.3 升級（schema_version "4.3"、驗證用 v4.3 schema）。

## 1. Schema 結構差異（程式比對）

| 項目 | v4.2 | v4.3 | 對我們的影響 |
|---|---|---|---|
| `schema_version` | `const "4.2"` | `string`、pattern `^4\.\d+$`，指南寫 `"4.3"` | 匯出改為 `"4.3"`（設定 `config/competition.yaml dplan.schema_version`） |
| required 欄位 | 同 | 同（無增刪） | 無 |
| `additionalProperties` | false | false（不變） | 無 |
| `decisions` / `orders` maxItems | 30 | **60** | 只放寬；我們每日 ≤ 30 |
| `decision.inference_refs` maxItems | 5 | **8** | 只放寬；匯出仍取前 5（合法） |
| `observation.source_ref` maxItems | 5 | **10** | 只放寬 |
| `decision.target_weight` 說明 | 期初權重由參賽端自行記帳 | 分母 = **前日結算淨值（資料包 `account.nav_tradable`）** | 前日淨值改用 DataPack（`agent/ops/datapack.py`） |
| `orders` 說明 | C2：逐位元等於 derive-orders.v2 | 與指南 §⑥ 推導演算法一致（ticker / side / shares），輸入為資料包前日持股與淨值 + 交易所前日收盤 | 演算法不變（`floor(tw×NAV÷close÷1000)×1000 − 持有`） |
| 拒收描述 | 以 C1/C2/C6/C9/C11/C12/C14 代碼描述 | 改以文字：引用完整性（basis/premise/source/inference/decision_ref）、no_trade 覆蓋、整股 → **「未通過即整份退回」**；C12（posture / 現金區間）、C14（funding_for）只寫「系統會檢查」，未寫處置 | NC-3 部分確認；我們仍把所有 FAIL 視為拒收（保守） |
| `code_version` | 格式不限 | 說明同；指南新增：限英數與 `_ . : / -`、長度 1–64 | `git:<sha>` / `git:<sha>-dirty` 符合 |
| `model_provider` 說明 | 自報、非白名單 | 移除「非白名單」字樣，可填值清單不變 | 無（我們填 `anthropic` 或 `other`） |

## 2. 撰寫指南差異（重點）
- ⓪ 策略說明文件：改為「每隊一份」，不再寫日期（日期見辦法：10/21～10/26）。
- ⑥ 前日淨值與持股：v4.2「由你們自行記帳（競賽系統不提供）」→ v4.3「**文件繳交頁面可以下載資料包取得前日淨值與持股**」。
- 超賣：v4.2「超賣 → 整份 D-Plan 被拒收（C13）」→ v4.3「賣出股數不得超過實際持有股數」；DataPack 作廢原因含 `oversell`。
- 「若主辦方另行釋出驗證器 `verify_dplan.py`」一段刪除。

## 3. 檢查項目（C1～C14）
| 項目 | v4.3 描述 | 我們的實作 |
|---|---|---|
| C1 引用完整性 | 未通過即整份退回 | C1（FAIL → fallback / BLOCK） |
| C2 委託推導 | 須與指南 §⑥ 一致 | C2 |
| C6 時間 | `run_completed_at` / `fetched_at` ≤ server 收件戳 | C6 / C6_CUTOFF |
| C9 / C11 權重、檔數、現金 | DataPack `compliance_fail`（持股檔數 / 標的池 / 現金 / 當日加碼個股權重） | C9:R_* / C11:R_COUNT |
| C12 posture / 現金區間 | 系統檢查，處置未寫 | C12_FLOW / C12_CASH（FAIL 視為拒收，保守） |
| C13 超賣 | DataPack `oversell` 作廢 | C13 |
| C14 funding_for | 系統檢核兩項，處置未寫 | C14 |
| no_trade 覆蓋 / 整股 | 未通過即整份退回 | COVERAGE / R_LOT |
| C3/C4/C5/C7/C8/C10 | 官方仍未公開定義 | NOT_IMPLEMENTED（不猜） |

## 4. 結算 / 提交 / 重繳
- 結算：DataPack（登入後台下載，手動）；`as_of_date` = T 前一交易日；`missing: prev_settlement` → `account`、`holdings` 為 null（不是空手）。
- 提交：平台上傳（每日 25 次上限）；同日以 08:55 前最後一次**成功**提交為準（Email 2026-10-07）。
- 官方 API / CSV 下載：無公開 API；DataPack 為 JSON 檔（需登入）。

## 5. 遷移（已完成）
| 步驟 | 內容 |
|---|---|
| diff | 本文件 |
| config | `config/competition.yaml dplan.schema_path = research/official_updates/D-Plan.schema_v4.3.json`、`schema_version: "4.3"`；v4.2 路徑留作 `previous_schema_path` |
| code | `agent/dplan/exporter.py`（schema_version 由設定）、`agent/engine/validate_dplan.py`（v4.3 標籤）、`agent/ops/verify_release.py`（檢查清單加 v4.3） |
| 新增 | `agent/ops/datapack.py`（DataPack 匯入 → 既有官方結算檔 + 確認紀錄） |
| test | `tests/ops/test_rule_sync_1007.py`：官方 v4.3 正例通過 v4.3 schema；我們的 D-Plan 通過 v4.3；DataPack 解析 / 拒收 / 第一天 |
| regression | 全部測試 0 failed；W5 24/24 日 decision_core_hash 與 Round 06 baseline 相同 |
| rollback | 將 `dplan.schema_path` / `schema_version` 改回 v4.2 即可（v4.2 原檔仍在根目錄）；不建議，官方已要求更新 |
