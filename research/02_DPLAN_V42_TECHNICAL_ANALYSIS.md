# 02 D-Plan v4.2 技術分析

> 依據：`D-Plan.schema_v4.2.json`、`D-Plan_撰寫指南_v4.2.md`、`D-Plan_TEAM_042_2026-10-27.json`（正例）、`D-Plan_TEAM_043_2026-10-27.json`（反例）。
> 驗證方法：以 Python 標準函式庫對兩個範例做引用鏈與公式重算（腳本未存入專案，結果列於 §6）。

---

## 1. 結構總覽（7 層 + metadata）

| 層 | 欄位 | 數量限制 | ID 格式 | 必填子欄位 | 引用 |
|---|---|---|---|---|---|
| L0 | `sources[]` | 1–50 | `S\d{1,3}` | source_id, authority, url, content_as_of | — |
| L1 | `observations[]` | 1–100 | `O\d{1,3}` | obs_id, source_ref(1–5), statement(5–500 字), values(≥1 個 **純數字**) | → S |
| L2M | `market_view{}` | 1 | — | basis_refs(1–10), logic(20–1000), regime, stance, posture{net_exposure_intent, target_cash_pct_range[2]∈[0,0.25]}, counter_evidence(str/null) | → O |
| L2 | `inferences[]` | 1–60 | `I\d{1,3}` | inf_id, premise_refs(1–10), logic(20–1000), counter_evidence | → O |
| L3 | `decisions[]` | 0–30 | `D\d{1,3}` | decision_id, ticker, action∈{BUY,ADD,TRIM,SELL_ALL}, target_weight∈[0,0.25], inference_refs(1–5) | → I；選填 funding_for → D |
| L3 | `no_trade_decisions[]` | 0–30 | (ticker) | ticker, reason_refs(1–5) | → I |
| L4 | `orders[]` | 0–30 | (ticker) | ticker, side∈{BUY,SELL}, shares(≥1000, ×1000), decision_ref | → D |
| meta | `agent_metadata{}` | 1 | — | model_provider(enum), model_version, run_started_at, run_completed_at, code_version | — |

其他：`schema_version` const "4.2"；`doc_type` const "D-Plan"；`team_id` `^[A-Za-z0-9_-]{1,32}$` 須與認證身分一致；`trade_date` YYYY-MM-DD；全文件 `additionalProperties:false`；`_NOTE` 為選填非正式欄位。

**ID 規則（指南）**：大寫前綴 + 1–3 位數，從 1 起、連續、不跳號、不補零；每日獨立編號。注意 schema 的 regex 只擋格式，「連續不跳號」屬語意層規則 → 我方 validator 必須自行檢查。

## 2. Evidence Chain（引用鏈）

```
sources(S) ──source_ref──► observations(O) ──basis_refs──► market_view
                                      └──premise_refs──► inferences(I)
inferences(I) ──inference_refs──► decisions(D) ──decision_ref──► orders
inferences(I) ──reason_refs────► no_trade_decisions(ticker)
decisions(D: TRIM/SELL_ALL) ──funding_for──► decisions(D: BUY/ADD)
```

方向是「下層引用上層」。完整性條件（C1 + 指南）：
1. 所有引用 id 必須存在（C1；孤兒決策 → 拒收，EX43 的 `D3→I9`）。
2. 每筆 order 指向一筆 decision；每筆 decision 至少一筆 inference。
3. **覆蓋完整**：昨日每一檔持股必須且只能出現在 `decisions` 或 `no_trade_decisions` 之一。
4. 新買進的標的放在 `decisions`（action=BUY）。
5. 「斷環」不只指不存在的 id；指南原則「不能有斷環」→ 我方另加：不得有未被引用的 S/O/I（孤兒來源/事實），雖非明文拒收條件，但抽檢時會降低可信度。

**上限壓力**：持股最多 30 檔，若 30 檔全部需交代 → decisions + no_trade ≤ 30+新買入；每檔至少一個 I，inferences 上限 60，observations 上限 100，sources 上限 50。→ 150 檔的完整研究不可能全部寫進 D-Plan；**D-Plan 是「被選中與被持有標的」的證據摘錄，而不是全部研究過程**。完整研究過程放在內部 log。

## 3. 各欄位語意要點

### 3.1 sources
- `authority` 決定稽核方式：`twse/tpex/taifex/mops` 主辦方會**事後重抓比值**（數字必須能被官方公開資料重現）；`fininst/media/vendor` 不 refetch，靠 `archive_url`。
- `content_as_of` = 內容描述之時點（不是抓取時間）；`fetched_at` 選填，若填則 C6 檢查 ≤ server 收件時間。
- 上市用 `twse`、上櫃用 `tpex`，不可混用。
- **設計含意**：
  - 數值型事實盡量引用 twse/tpex/taifex/mops → 可驗證、可信度最高。
  - media 來源要在抓取時同步送 web.archive.org 存檔並填 `archive_url`（需處理存檔失敗/延遲）。
  - 內部要保存原始內容（hash）以便自證。

### 3.2 observations
- 「只准可核對的事實，禁止推論性語句」；`values` 只收數字 → **天然適合由 deterministic code 產生**（價格、報酬、法人買賣超、營收 YoY）。
- LLM 若參與（例如新聞事件摘要），statement 必須是事實陳述，values 仍需數字（如「發布時間」「營收 YoY%」）。

### 3.3 market_view（C12 硬檢查）
- `posture.net_exposure_intent`：用 **T-1 收盤價**重算委託淨流向；`increase`→淨買、`reduce`→淨賣、`hold`→|淨流向| ≤ 2% NAV（server 參數）。
- `target_cash_pct_range`：以 T-1 收盤價估算委託後現金比，須落在區間內；下限 ≤ 上限；元素 ∈ [0, 0.25]。
- **含意**：market_view 不是敘述文字，而是**可被數學檢核的承諾**。必須在 orders 算完之後回填 posture（或由 posture 約束 optimizer），不能讓 LLM 自由填。

### 3.4 inferences
- logic 20–1000 字；「抽檢時對照公開說明書主題/因子審關聯性」→ 推論須以策略說明文件中宣告的因子語言撰寫。
- counter_evidence 必填（可 null）→ 鼓勵每筆推論有反方論點，這與 TradingAgents 類 bull/bear debate 的產物天然契合。

### 3.5 decisions
- `target_weight` 是**唯一的決策數值**；orders 由它機械導出。
- schema 只擋 ≤0.25；非 2330 ≤0.10 由 C9 重算。
- SELL_ALL 的 target_weight 應為 0（推定，[U]）。
- `funding_for`（C14）：①引用存在且指向同日 BUY/ADD；②**拿掉所有調度賣出後重算的現金比須低於 `target_cash_pct_range` 下限**，否則拒件。→ 需由程式判定是否標記。

### 3.6 orders（C2）
```
target_shares = floor(target_weight × NAV_{T-1} ÷ close_{T-1} ÷ 1000) × 1000
order_shares  = target_shares − current_shares      (正=BUY, 負=SELL)
```
- 「必須逐位元等於 derive-orders.v2(decisions, 主辦方前日結算持股, 交易所公開收盤價, 前日結算 NAV)」→ **完全 deterministic，LLM 不得參與數字**。
- 數值精度：floor 前的浮點誤差可能導致差 1 張（例如 0.045×102,000,000/42.5 恰為整數 108.0）。實作須用 `Decimal` 並加極小 epsilon 規則，且需向主辦方確認其實作（[NC]）。
- 若 target_shares == current_shares → 無 order，但 decision 仍存在？（例如 TRIM 但 floor 後股數不變）→ 應改列 no_trade 或調整 target_weight，否則可能出現「有決策無委託」；是否違規 [U]。
- 超賣（C13）→ 拒收：current_shares 必須以主辦方結算為準。

### 3.7 agent_metadata
- `model_version`「抽檢重跑須用同一版本」→ 必須 pin 精確的模型版本字串（不要用 `latest` alias）。
- `code_version`「改參數＝改版」→ 參數、prompt 模板、ticker universe、因子權重全部要進 git，`code_version=git:<sha>`，且執行時 working tree 必須 clean（否則 sha 不對應真實程式）。
- `run_completed_at` ≤ server 收件戳（C6）。

## 4. 正例與反例的教學訊息（EX42 / EX43）

| 項目 | EX42（正例） | EX43（反例） | 教學 |
|---|---|---|---|
| 引用鏈 | 完整（程式驗證 0 斷鏈） | `D3→I9` 不存在 | C1 孤兒決策 → 拒收 |
| 2330 委託 | SELL 2000 = 公式 | SELL 3000 ≠ 公式 2000 | C2 不一致：反例標「僅警示，蓄意不一致轉六(十四)(6)抽檢」 |
| posture | hold、現金 3–10% | reduce、現金 8–15%，實際淨買超、預估現金 3.75% | C12：「嘴上保守、手上激進」 |
| funding_for | D1 → D2（有缺口） | 無 | C14 示範 |
| market_view basis | 4 個市場級 O | 2 個 | 盡量完整 |
| 時間 | run 05:02–07:52，來源最晚 05:00 | run 08:31–08:47，引用 08:41 盤前試撮 | 08:55 前可用的盤前資料未被標為違規 → 推定允許；但 08:47 完成極接近截止 |
| 數值 | 範例 NAV 為 1.02 億（非 10 億）、行情虛構 | 同 | `_NOTE` 已說明為虛構 |

**矛盾點**：Schema 對 C12/C14 寫「拒收/拒件」，但 EX43 的 C12 類問題被標「僅警示」→ 列入 NC-3。

## 5. 能否把 D-Plan v4.2 直接當成 Agent 內部 State Graph？

### 5.1 兩種方式

**方式 A — Post-hoc 補寫**：Agent 自由研究、決策 → 最後叫 LLM 讀全部 context「寫成 D-Plan」。
**方式 B — Native Evidence Graph**：Data → Source → Observation → Market View → Inference → Decision → Order，每一步產生帶 ID 的節點，D-Plan 是內部 graph 的投影（projection/serialization）。

### 5.2 比較

| 面向 | A Post-hoc | B Native graph |
|---|---|---|
| 可靠性 | 低：LLM 會「事後合理化」，引用的數字可能與實際決策使用的數字不同（hallucinated numbers）；observation values 可能被改寫 | 高：observation values 由程式從原始資料產生，必然與決策使用者一致 |
| Auditability | 弱：D-Plan 與真實決策過程可能不一致 → 觸發 §六(十四)(6)「交易決策與交易行為不一致」抽檢風險；也違反主辦方「決策過程透明」精神 | 強：每個 O 對應原始檔 hash、每個 I 對應 prompt/response log、每個 D 對應 optimizer 輸出 |
| Debugging | 難：錯誤可能在研究或在補寫階段 | 易：可逐層重放；每層有 schema |
| Submission risk | 高：C1 斷鏈、C2 股數、C12 posture、C14 funding 都可能被 LLM 寫錯 | 低：C1/C2/C12/C14 全由程式保證，LLM 只產生文字欄位 |
| Token usage | 高：最後一步要把全部研究內容塞進 context 生成大 JSON（~10–20k output tokens），且出錯需整份重生 | 低～中：LLM 只在 inference/market_view 的 logic 欄位與事件抽取時被呼叫，可分塊、可快取；JSON 組裝由程式完成 |
| 彈性 | 高（研究流程不受限） | 中（需事先設計節點型別），但 D-Plan 已提供現成 ontology |

**結論：採用方式 B**。D-Plan v4.2 的分層（L0 事實來源 / L1 可核對事實 / L2 推論 / L3 決策 / L4 機械委託）與「Hybrid Quant + LLM」的分工幾乎一一對應：L0/L1/L4 deterministic，L2/L2M 由 LLM 撰寫 logic 但 refs 由程式控制，L3 由 optimizer 決定 target_weight、LLM 提供 thesis。

### 5.3 但不能「直接」等於 State Graph —— 需要一個超集（Internal Evidence Graph）

D-Plan 有上限（50/100/60/30）且只收錄被引用的部分，所以內部 graph 應是 D-Plan 的**超集**：

| 內部節點 | 對應 D-Plan | 額外欄位（不送出，存 log） |
|---|---|---|
| `RawSnapshot` | — | path、sha256、fetched_at、http status、原始 bytes |
| `Source` | sources[] | snapshot_id、archive 狀態 |
| `Fact` | observations[] | 計算程式版本、輸入 snapshot、ticker、feature 名稱 |
| `Signal` / `Score` | （不直接送出，透過 Fact + Inference 表達） | 150 檔完整 cross-section 分數、排名 |
| `MarketView` | market_view | regime 模型輸出、LLM prompt/response id |
| `Thesis` / `Inference` | inferences[] | LLM call id、temperature、model、cited facts |
| `TargetPortfolio` | decisions[] + no_trade_decisions[] | optimizer 輸入/輸出、約束鬆弛紀錄、Active Share 報告 |
| `Order` | orders[] | derive-orders 中間值 |
| `ValidationReport` | — | C1–C14 自檢結果 |

**ID 映射策略**：內部用穩定的 UUID/語意 key（如 `fact:2330:ret_20d:2026-10-26`），在**序列化（export）階段**才做「篩選被引用節點 → 依拓撲順序重新編號 S1..Sn、O1..On、I1..In、D1..Dn」。這樣同時滿足「從 1 起連續不跳號」與內部穩定追蹤。

### 5.4 生成流程（建議）

```
1. Snapshot  : 抓資料 → data/raw/YYYYMMDD/... (hash)            [code]
2. Facts     : 計算特徵 → Fact 節點（含 values）                 [code]
3. Events    : 新聞/重訊 → 事件抽取（LLM, structured output）→ Fact [LLM+schema]
4. Scores    : 150 檔 cross-sectional score                    [code]
5. MarketView: regime 規則 + LLM 撰寫 logic/counter_evidence     [code+LLM]
6. Theses    : 對 candidate/持股，LLM 依指定 facts 寫 inference    [LLM, refs 受控]
7. Optimizer : target_weight（含所有硬限制、Active Share、turnover）[code]
8. Decisions : action 分類（BUY/ADD/TRIM/SELL_ALL/no_trade）      [code]
9. Orders    : derive-orders.v2                               [code]
10. Posture  : 由 orders 反推 net_exposure_intent 與 cash range  [code]
11. funding_for: 依 C14 規則判定                                [code]
12. Export   : 篩選+重編號 → JSON → schema 驗證 → 語意驗證(C1–C14) [code]
13. Submit   : 上傳（若無 API，需定義合規的提交方式）            [code/人工按鈕?]
```
注意第 10 步：與其讓 LLM 宣告 posture 再強迫 orders 吻合，不如由 orders 計算 posture 並把 regime/stance 作為 optimizer 的輸入（例如 risk_off → 目標現金上調），維持「決策 → 宣告」一致。

## 6. 驗證（Validation）設計

### 6.1 結構層
- JSON Schema 2020-12 驗證（`jsonschema` 套件；需支援 `format: uri` 與 `$defs`）。

### 6.2 語意層（自建 `validate_dplan.py`，對齊已知 C 碼）
| 檢查 | 內容 |
|---|---|
| C1 | 所有 refs 存在；無孤兒 decision |
| ID | 從 1 起連續、不重複、不補零（指南） |
| 覆蓋 | 前日持股 ⊆ decisions ∪ no_trade，兩者不相交；ticker 不重複 |
| C2 | orders 逐筆 = derive-orders.v2；不存在 decision 無 order 的矛盾 |
| C6 | run_completed_at、fetched_at ≤ 預計提交時間；所有 `content_as_of`/`published_at` ≤ run_started_at（我方更嚴格的 PIT 規則） |
| C9/C11 | 以 T-1 收盤估算：檔數 20–30、2330 ≤25%、其他 ≤10%、現金 0–25%（加緩衝）、universe ⊆ 150 |
| C12 | posture 與淨流向一致；預估現金 ∈ 區間 |
| C13 | SELL shares ≤ 結算持股 |
| C14 | funding_for 指向同日 BUY/ADD；缺口存在 |
| 檔名 | `D-Plan_<team_id>_<trade_date>.json` 與內容一致 |
| Active Share | 對 30 檔 ETF 多解讀計算（見 01 §6.1） |
| 主題一致性 | 主題產業占比 ≥ 自訂門檻 |
| 時間 | trade_date 為交易日；現在時間 ∈ 繳交窗口 |

### 6.3 已執行之範例驗證結果
- EX42：0 斷鏈；無未引用 S/O/I；orders 重算 2330=15,000 目標股、2891=108,000 → 與檔案一致。
- EX43：檢出 `D3→I9` 斷鏈；2330 公式值 2,000 ≠ 檔案 3,000；最晚來源 08:41。
- 兩例 NAV 皆用 102,000,000（虛構），非 10 億。

## 7. 對 Agent 設計的關鍵約束（摘要）
1. **orders 必須純程式**（C2 位元相等）。
2. **posture/funding_for 必須由程式反推**（C12/C14 數學檢核）。
3. **observations.values 必須來自程式計算**（權威來源會被重抓比對）。
4. **LLM 的產出只進入文字欄位**（statement 的措辭、logic、counter_evidence、conclusion、risk_check、reason）以及事件抽取；refs 只能從程式提供的候選 ID 清單中選（constrained output）。
5. **前日結算持股/NAV 是單點失敗來源**（超賣即拒收）：取得方式需確認（NC-1）。
6. **可重現**：model_version 精確 pin、code_version=git sha、prompt 模板入版控、每日 raw snapshot 保存。
