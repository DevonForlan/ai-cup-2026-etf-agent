# 主辦方 Email 回覆摘要（使用者轉述）

> 來源：使用者於 2026-10-04 研究任務說明中轉述「主辦單位已透過 Email 正式回覆」。原始信件**未存入專案目錄**。
> 建議：將原始信件另存為 PDF/EML 至 `research/sources/`，作為資格審查時的合規依據（見 01 NC-14）。

| 代號 | 內容 |
|---|---|
| A | 允許透過 API 呼叫外部大型語言模型 |
| B | 可以使用 Agent Framework |
| C | 可以使用其他合法開發工具 |
| D | 目前未限制特定模型或 API |
| E | 無須事先申報 |
| F | 投資決策內容應由 Agent 自主產生 |
| G | 參賽者不得透過提示指令干預投資決策 |
| H | Agent 執行後不得人工修改股票、買賣方向、配置權重、交易數量、其他實質投資決策 |
| I | 純錯字等不影響投資決策的修正原則上可接受 |
| J | 初賽每日不用同步提交 source code、prompt、log、full conversation，但官方建議保留以利資格審查 |
| K | Prompt-based / No-code Agent 可以；若無傳統 source code，可提供 Prompt、Instructions、Workflow、Tool descriptions、Execution logs |

設計含意：Reproducibility、Auditability、Prompt versioning、Git versioning、Execution logging、Data snapshot、Input/Output trace 為一級需求。
