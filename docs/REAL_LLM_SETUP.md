# 真實 LLM 啟用步驟（使用者需自行完成）

> 目前狀態：**REAL_LLM_STATUS = BLOCKED_NO_API_KEY**（2026-10-05 檢查：GEMINI_API_KEY / GOOGLE_API_KEY /
> OPENAI_API_KEY / ANTHROPIC_API_KEY 在 process / User / Machine 環境與 `.env` 皆不存在；只檢查有無，未讀取值）。
> 依指示，Agent **不會**開帳號、購買額度、建立付費資源、登入帳號或建立金鑰。以下步驟需由隊伍成員本人操作。
> 公司政策：API key 屬內部憑證，不得貼進對話、程式碼、log 或 commit。

## 1. 取得 Google Token Credit（依「玉山挑戰賽_Google Token Credit領取方式_v1.pdf」）
1. 完成文件指定的 Google Cloud Skills Boost 課程。
2. 在 **9/20–10/19** 期間，將課程完成截圖寄到 `intelligent-finance@esunbank.com`，主旨：`課程完成證明截圖-Team_XXXXX`。
3. 於比賽頁面取得序號（serial）。
4. 在 Google Cloud Console 建立 Billing Account 後，到 `console.cloud.google.com/billing/redeem` 兌換。
   **須在 11/30 前啟用，12/31 到期**；額度只能用於 Google Cloud 上的 LLM。
5. 在該帳號下自行建立 Gemini API key（或 Vertex AI 設定）。是否產生費用、額度上限，請以 Google Cloud 帳單頁面為準。

## 2. 放置金鑰（只能 `.env` 或環境變數）
在專案根目錄建立 `.env`（已在 `.gitignore`），內容一行：
```
GEMINI_API_KEY=<你的 key>
```
（`GOOGLE_API_KEY` 也可。）程式只從 `.env` / 環境變數讀取，log 會自動遮罩 key 值。

## 3. 設定模型與價格（不要讓程式猜）
編輯 `config/llm_narrative_v1.yaml`：
```yaml
provider: google
model: <確切的模型 ID，例如 Google 文件上列出的穩定版本名稱>
price_usd_per_1m_tokens:   # 依 Google 官方價目表填寫；未填則成本報告顯示 PRICE_NOT_CONFIGURED
  input: <數字>
  output: <數字>
```

## 4. 執行 10–20 日敘事重播審查（narrative only，不影響下單）
```
.venv\Scripts\python.exe agent\ops\llm_review.py --llm-config config\llm_narrative_v1.yaml --days 15
```
輸出：
- `reports/round05_llm_narrative_review.csv`：每日 provider、model、prompt_version、calls、tokens、latency、schema / grounding / numeric / source / reviewer、fallback、template vs LLM 下單是否相同，以及 A–I 決定性檢查。
- `reports/round05_llm_cost.csv`：每日實際 token（用 provider 回傳的 usage）× 設定檔價格，以及 24 日估計。
- `reports/human_review/YYYY-MM-DD_review.md`：Template vs LLM 並排、事實、來源、檢查結果、人工勾選欄。

任何一天 portfolio / orders / cash 與 Template 不同 → 指令以非 0 結束（INVARIANCE FAILURE），**不得啟用**。

## 5. 啟用標準（全部成立才可在比賽使用 LLM 敘事）
schema failure 0%｜D-Plan validation 100%｜portfolio / order invariance 100%｜numeric grounding 100%｜
hallucinated ticker 0｜hallucinated source 0｜fallback rate、p95 latency、每日 token / 成本可接受｜
**人工審閱認定文字品質明顯優於 Template**。否則比賽維持 Template 敘事。

啟用方式（通過後）：`scripts\competition_dry_run.ps1 -Mode competition -TeamId TEAM_XXX -LlmConfig config\llm_narrative_v1.yaml`。
截止前 15 分鐘內系統自動停用 LLM；任何 LLM 失敗自動回到 Template（D-Plan 仍需 PASS）。
