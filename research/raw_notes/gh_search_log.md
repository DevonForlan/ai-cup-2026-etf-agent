# GitHub 搜尋紀錄（Landscape Scan）

- 執行日期：2026-10-04（Asia/Taipei 約 22:30–23:00）
- 執行者：research subagent（Claude）
- 環境限制：`gh` CLI 未登入（`gh auth status` → not logged in），因此改用**未認證** GitHub REST API（`Invoke-RestMethod`）。未認證額度為 core 60 次/小時、search 10 次/分鐘；core 額度在過程中用完，所以：
  - repo 基本資料（stars/forks/license/language/pushed_at/created_at/archived）改用 Search API 的 `repo:OWNER/NAME` 合併查詢取得；
  - last_commit 取自 `https://github.com/OWNER/REPO/commits.atom` 最新一筆 `<updated>`（預設分支）；
  - latest_release 取自 `https://github.com/OWNER/REPO/releases/latest` 的 302 轉址目標（沒有轉址就記為 none；有些專案只發到 PyPI，所以 none 不等於沒有版本）；
  - 原始碼樹沒有用 `git/trees?recursive=1`（core 額度不足），改從 GitHub HTML 頁面內嵌的 JSON 解析第一、二層目錄，再加上 README 關鍵字計數。
- 星數以 2026-10-04 查詢時為準。

## 主要查詢（`/search/repositories?q=<query>&sort=stars&order=desc&per_page=30`）

| # | Query | total_count | 取回筆數 |
|---|---|---|---|
| 1 | `AI trading agent` | 6,767 | 30 |
| 2 | `LLM trading agent` | 1,405 | 30 |
| 3 | `financial agent` | 13,444 | 30 |
| 4 | `portfolio agent` | 10,404 | 30 |
| 5 | `autonomous fund manager` | 12 | 12 |
| 6 | `multi-agent trading` | 2,275 | 30 |
| 7 | `AI hedge fund` | 741 | 30 |
| 8 | `quant agent` | 2,575 | 30 |
| 9 | `investment agent` | 4,427 | 30 |
| 10 | `portfolio management LLM` | 116 | 30 |
| 11 | `agentic trading` | 11,765 | 30 |
| 12 | `agentic investment` | 3,124 | 30 |
| 13 | `financial multi-agent` | 2,944 | 30 |

合計取回 372 筆，去重後約 300 個 repo，其中 ≥150 stars 的有 119 個，再人工挑出與本賽題相關者。

## 補充查詢（per_page=8）

| Query | total_count | 備註 |
|---|---|---|
| `LLM portfolio optimization` | 155 | 前 8 筆都 <20 stars，沒有可用的高品質專案 |
| `alpha factor mining LLM` | 17 | 前 8 筆都 <20 stars（WorldQuant Brain 因子挖掘玩具居多） |
| `taiwan stock` | 1,425 | twstock (1.5k) 居首，其餘多為爬蟲/舊專案（tsrtc、grs、tsec 都已多年未更新） |
| `QuantAgent` | 124 | 前 8 筆都 <40 stars |

## Metadata 批次查詢（Search API，`repo:` 合併，每批 6 個）

共 48 個 repo，每批 6 個，共 8 次查詢。有 3 個 repo 因改名查不到，以 `curl -I https://github.com/...` 追蹤轉址後補查：
- `robertmartin8/PyPortfolioOpt` → `PyPortfolio/PyPortfolioOpt`
- `OpenBB-finance/OpenBB` → `openbq-org/OpenBB`
- `stefan-jansen/zipline-reloaded`：Search index 查不到（只回傳 fork/feedstock），stars/forks 改從 repo HTML 頁面讀取（1,951 / 331）

## Web search

- `github LLM multi-agent portfolio construction stock selection open source 2026` → 確認 MASS（gta0804/MASS，arXiv 2505.10278）與 phanhpp/Multi-Agent-Stock-Analysis-System（AlphaAgents 概念實作，低星，沒有列入主表）。

## 原始資料（暫存，不在專案目錄）
- scratchpad `search_items.csv`（13 個主查詢的全部結果）、`search_counts.tsv`、`meta.csv`（48 個 repo 的 metadata）。
