# Portal Validation Checklist（官方競賽後台人工確認）

> 由操作者**人工登入**後逐項確認。Agent 不登入、不上傳、不讀 cookie / token / 密碼、不猜網址。AI 產生內容，需人工審閱。
> 確認結果請回傳：後台 URL、截圖（存 `data\official_test_receipts\<YYYYMMDD>\`）、官方訊息原文。**不要貼密碼、cookie、session token。**

## 0. 公開資料可確認的部分（2026-10-21，未登入）

只讀官方首頁與公開的前端 JS 靜態檔，未呼叫任何 API：

- `https://esun-ai-challenge.tw/` 是單頁應用。公開路由包含：
  - `/login`
  - `/my-registrations`（「我的活動」）
  - `/events/:slug`
  - `/sso`
  - `/profile`
- 「我的活動」卡片上的 **「進入活動」** 按鈕會開啟每筆報名資料裡的 `portalUrl`。這個網址由**登入後**的 API 提供，公開程式碼看不到。
- `/sso` 頁面是單一登入交接：登入狀態下向 `/sso/authorize/` 取得 `redirect_url`，再轉址到**另一個競賽活動後台系統**。
- 主站公開程式碼中**沒有**「文件繳交」「資料包」「D-Plan」「上傳」功能。這些都在登入後的獨立後台。

結論：

- `LOGIN_REQUIRED_FOR_PORTAL_VALIDATION`
- 後台網址未知，不猜
- `config/ops.yaml submission.ui_status = LOGIN_REQUIRED`

## 1. 後台入口

| # | 項目 | 確認方式 | 結果 |
|---|---|---|---|
| 1 | portal URL | 「進入活動」後瀏覽器網址列的**後台首頁**網址（只抄網域與路徑；**去掉**任何 `?code=` / `token=` / `state=` 參數） | [ ] __________ |
| 2 | 是否每次都經 SSO 轉址 | 直接開上一列網址是否需重新登入 | [ ] |
| 3 | MFA / CAPTCHA | 登入是否有驗證碼、簡訊、圖形驗證 | [ ] |

## 2. D-Plan 上傳

| # | 項目 | 結果 |
|---|---|---|
| 4 | D-Plan upload exists（頁面名稱，例如「文件繳交」→「Agent 決策報告及交易書」） | [ ] |
| 5 | accepted file extension（.json？大小上限？） | [ ] |
| 6 | expected filename（是否要求 `D-Plan_<TEAM>_<YYYY-MM-DD>.json`？是否重新命名？） | [ ] |
| 7 | trade date shown（頁面顯示哪個交易日？可否選日期？） | [ ] |
| 8 | team ID shown（**正式 Team ID** 長相，例如 `TEAM_042`） | [ ] __________ |
| 9 | upload button（選檔後是否還要按「送出 / 確認」？） | [ ] |
| 10 | validation response（上傳後是否立即顯示格式 / 驗證結果？逐字抄錄） | [ ] |
| 11 | success receipt（成功訊息原文、是否有回執編號 / 時間戳） | [ ] |
| 12 | submission ID（欄位名稱與格式） | [ ] |
| 13 | latest successful submission（頁面是否標示「目前生效」那一份） | [ ] |
| 14 | multiple submission history（是否列出當日所有上傳、狀態、時間；是否顯示剩餘次數 / 25 次上限） | [ ] |
| 15 | rejected upload behavior（故意上傳**本機測試用**錯誤檔：顯示什麼？是否影響先前成功的那一份？） | [ ] |
| 16 | server timestamp（回執上的時間是伺服器時間？時區？） | [ ] |

## 3. DataPack / 結算

| # | 項目 | 結果 |
|---|---|---|
| 17 | DataPack download（哪一頁、按鈕名稱） | [ ] |
| 18 | DataPack date（檔內 `as_of_date` / `trade_date` 與頁面顯示是否一致） | [ ] |
| 19 | 檔名格式 | [ ] |
| 20 | schema_version（規格書範例為 "3.0"、規格書版本 4.3；實際值？） | [ ] |
| 21 | 同一交易日是否可能有多個版本（`generated_at` 是否會變；頁面是否顯示更新時間） | [ ] |
| 22 | settlement status（結算是否完成的標示；未完成時 `missing` 是否含 `prev_settlement`） | [ ] |
| 23 | 下載時間（官方約 19:00 後更新？封測實際時間） | [ ] |

下載後請執行（只做唯讀驗證與欄位盤點，不匯入比賽鏈）：

```
.venv\Scripts\python.exe -m agent.submission.official_test datapack --file <下載的檔案> --date <T> --team-id <Team ID>
```

## 4. 回傳給 Agent 的資訊

- 後台 URL（去掉 token 參數）→ 填入 `config/ops.yaml submission.portal_url`。之後 `python -m agent.submission.portal --open` 只會開這個網址。
- 正式 / 測試 Team ID → `config/ops.yaml team.competition_team_id`（需另行確認是否就是正式比賽用 ID）。
- 上傳畫面、成功 / 失敗訊息原文 → 決定 `OFFICIAL_RECEIPT_FORMAT` 與狀態對應（`reports/OFFICIAL_TEST_E2E_RUNBOOK.md` §3）。
- DataPack 檔案（測試）→ `data\official_test_datapack\`。
