# Collaboration Workflow — Owner + Claude Code + GitHub + ChatGPT Review

> 適用於本 repository 的長期開發流程。AI 產生內容，需人工審閱。角色與禁止事項的正式版本在 `CLAUDE.md`。

## 1. 流程

```
Owner 核准 Issue / Sprint
  → Claude Code：feature branch → 實作 → tests → (必要時) local freeze regression → push → Draft PR
  → CI（secret scan / quant-freeze-check / validate / pytest）PASS
  → PR 轉為 Ready for review（Implementation Recommendation = READY_FOR_REVIEW）
  → ChatGPT Review（Blocking / Non-blocking；APPROVE / APPROVE_WITH_FOLLOW_UP / REQUEST_CHANGES / DO_NOT_MERGE）
  → Claude Code 修正 → push 同一 branch → CI → 逐項回覆 → 第二輪 Review
  → Owner：MERGE（squash，刪 branch）/ DO_NOT_MERGE
```

- Claude Code 不 merge、不開 auto-merge、不 force push、不 rewrite history，日常不直推 `master`。
- 唯一例外：2026-10-21 的 bootstrap，把既有 `master` 歷史推上空 repo。之後不再直推。

## 2. Issue 類型與 branch

| Issue type | Branch prefix | 注意 |
|---|---|---|
| FEATURE | `feat/` | 不得改投資行為 |
| BUG | `fix/` | 附重現步驟 |
| OPS | `ops/` | 排程、資料、送件、DataPack |
| RESEARCH / EXPERIMENT | `research/` | 事前登錄 gate；保留負面結果；不得直接進 production |
| DOCS | `docs/` | 不需昂貴模擬 |
| COMPETITION_RULE_CHANGE | `ops/` 或 `fix/` | Owner 核准；記錄規則來源與 DQ 風險 |
| SECURITY | `fix/` | — |
| TECH_DEBT | `fix/` / `feat/` | 不改行為 |
| PROMOTION | `feat/` | 研究升級 production；需 freeze 前後比較與 Owner 決策 |

每個 Issue 一個 branch / 一個 PR；不相關的修改不合併。並行最多 2～3 條 track（低耦合可用 worktree）。

## 3. CI

| 層級 | 何時 | 內容 |
|---|---|---|
| FAST（`ci.yml`） | 每個 PR、push master | secret scan、quant-freeze-check（策略 hash + 凍結路徑 diff，需 Owner label 才能改）、syntax / import / config / schema、完整 pytest（合成 fixtures，約 5 分鐘） |
| FULL（`full-regression.yml`） | 手動 / 每晚 | 上述全部 |
| LOCAL freeze regression | 會影響決策路徑的 PR、release、比賽期間修改 | `scripts\ci\local_freeze_regression.py`：W5 NAV、24 decision hashes、凍結路徑。需要本機 `data/history`，不上 GitHub |

CI integrity：

- 不得刪有效測試、降低標準、hard-code 結果、skip / xfail 真 bug、移除 security test。
- 測試規格要改，PR 必須說明 WHY。

## 4. Review 回覆格式

```
Review item: <comment link / summary>
Resolution: fixed | rebutted (evidence) | follow-up #<issue> | won't fix (reason)
Modified file: <path>
Commit: <sha>
Test result: <command> -> <result>
```

## 5. Sprint 回報格式

Track / Issue · Branch · PR URL · Changed files · Tests（例：560 passed, 0 failed）· CI · Quant Freeze · Experimental
Results · Known Limitations · Open Decisions · Implementation Recommendation（READY_FOR_REVIEW / NOT_READY / BLOCKED）

## 6. Evidence

- 比賽期間的 D-Plan、DataPack、receipt、submission evidence、execution logs、prompt / model 版本保留在本機（gitignored）。
- Git 只存 metadata：hash、timestamp、reference path、version（例如 `run_metadata.json` 的 hash 會寫進報告）。
