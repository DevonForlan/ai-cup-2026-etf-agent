# 10 風險與未決問題（Risk Register & Open Questions）

> 等級：影響（H/M/L）× 可能性（H/M/L）。「DQ」＝取消資格。規則類未決問題詳見 `01_COMPETITION_RULES_EXTRACT.md` §12（NC-1～NC-14）。

## 1. 風險總表

| # | 類別 | 風險 | 影響 | 可能性 | 緩解措施 |
|---|---|---|---|---|---|
| R1 | Competition rule | Active Share 定義不明（Wi 正規化方式、資料日期）；集中於 2330 + 權值電子時可能 <20% → **連續 2 日即可被 DQ** | H | M | 多解讀取最小值的 validator；optimizer 內建 AS ≥30% 約束；每日抓 30 檔 ETF 持股；送 NC-2 |
| R2 | Competition rule | 拒收/警告/抽檢的處置等級不一致（schema「拒收」vs 反例「僅警示」） | H | M | 以最嚴格解讀實作所有 C 檢查；NC-3 |
| R3 | Competition rule | 前日結算持股取得方式（v4.2 移除 API）；超賣 → 拒收；人工讀後台再輸入是否構成「人為介入」 | H | H | 自記帳 + 每日與後台對帳；若需人工下載庫存檔，流程定義為「僅資料搬運、不改決策」並記錄；NC-1 |
| R4 | Competition rule | 漏交容忍度實際只有 2 次（≥22/24 日 + 每次漏交記 1 警告，3 次 DQ） | H | M | 05:00 起跑、07:30 前完成；fallback；監控告警 |
| R5 | Competition rule | 價格上漲致權重超限的 5 日寬限計算錯誤 | M | M | Compliance engine 追蹤每檔「首次超限日」；預設目標權重留 1–1.5% 緩衝（非 2330 ≤8.5%、2330 ≤23.5%） |
| R6 | Competition rule | 現金邊界：T-1 收盤估算 vs T 日均價結算偏移 → 結算現金 <0 或 >25% | H | M | 目標現金 3–15%，避免 <2%；以最壞情境（買入標的 VWAP +5%/賣出 −5%）壓測 |
| R7 | Agent autonomy | 比賽中「改程式/改參數」可能被視為人為干預；「看結果手動改方向」違規 | H | M | 事先寫好變更政策：只允許 bug fix 與資料源修復，每次換 code_version 並記錄理由；策略參數 freeze；NC-9 |
| R8 | Agent autonomy | 主題一致性：決策偏離 ETF 策略說明文件 → 可被要求改善/DQ | M | M | 策略說明文件與 optimizer 約束一致（例如主題產業占比下限）；由 Agent 產生文件 |
| R9 | Data availability | 免費資料源（TWSE/TPEx OpenAPI、MOPS）格式變更、限流、維護；海外 ADR/SOX 依賴 vendor | M | M | 多來源 fallback；本地快取；資料健康檢查 |
| R10 | Data availability | 主動 ETF 每日持股揭露分散於 20+ 家投信網站，格式各異 | M | H | 先建 parser + 允許用最近一次揭露 + 標記 stale |
| R11 | API reliability | LLM API 逾時、限流、模型版本下架；Google credit 只有 US$20 | M | M | 快取、重試、token 預算、quant-only fallback；預算監控 |
| R12 | LLM hallucination | LLM 捏造數字、錯誤引用、錯誤推論 | H | H | LLM 不產生任何數字欄位；refs 受控（只能從給定 ID 清單選）；structured output + 驗證；數字一律程式填入 |
| R13 | Look-ahead bias | 回測時使用 T 日之後資料（收盤、均價、未發布新聞、財報重編） | H | M | PITView 強制過濾 + 金絲雀測試；manifest 時間戳 |
| R14 | Look-ahead bias（LLM 記憶） | LLM 預訓練已見過測試期間行情 → 回測 LLM 元件高估 | H | H | 用 knowledge cutoff 之後的視窗評估；匿名化 ablation；quant-only 對照 |
| R15 | Data leakage | 特徵工程使用全樣本標準化、未來成分股（survivorship） | M | M | 只用 rolling/expanding 統計；PIT universe 輔測 |
| R16 | Reproducibility | LLM 非決定性，重跑結果不同；資格審查「黑箱重現」 | M | H | temperature=0（或最低）、seed（若支援）、保存所有 prompt/response 以 replay 模式重放；明確說明「重現 = 用 log replay」 |
| R17 | Version drift | Provider 端模型靜默更新 | M | M | pin 完整 model version 字串；每日記錄 response metadata |
| R18 | Prompt drift | 比賽中修改 prompt 未換版本 | M | M | prompt 模板在 git，code_version 由 git sha 自動產生；dirty tree 禁止執行 |
| R19 | Submission failure | 上傳方式（網頁/API）未知；網路、登入失效；超過 25 次 | H | M | 確認提交機制；保留提交回執；提交後讀回驗證 |
| R20 | Portfolio constraint failure | floor 取整後持股檔數不足 20（高價股小權重 → 0 張） | H | M | optimizer 對每檔設最低權重使 ≥1 張；高價股（如 3008、5274、6669、3661）需檢查 1 張金額占 NAV 比 |
| R21 | Portfolio constraint failure | floor 浮點誤差與主辦方實作差 1 張 → C2 不符 | M | M | Decimal 實作；向主辦方確認；邊界值避開（target_weight 不取使結果恰為整數的值） |
| R22 | Strategy | 24 日樣本極小，策略績效以運氣為主；過度擬合回測 | M | H | 少參數、以多視窗/隨機 baseline 評估；避免頻繁換股 |
| R23 | Strategy | Turnover 侵蝕（來回 0.585%） | M | H | no-trade band、turnover penalty、最少持有期 |
| R24 | Strategy | 集中度：2330 25% + 半導體主題 → 單一產業下跌造成大 MDD | M | M | 產業上限、波動控制 |
| R25 | Ops | 本機 Python 未加入 PATH（已安裝 3.13 於 LocalAppData） | L | H | 下一輪建立 venv（需使用者同意安裝套件） |
| R26 | Compliance/Org | 公司政策：不得把機密/憑證貼給 AI；API key 管理 | M | M | `.env` + `.gitignore`；不把 key 放入 prompt/log |
| R27 | Security | 新聞/網頁內容 prompt injection 影響 LLM 決策 | M | M | 外部文本只做事件抽取（structured），不讓其指令生效；LLM 不直接控制權重 |
| R28 | Legal/ToS | 爬取 Goodinfo/新聞站違反服務條款 | M | M | 優先官方 OpenAPI 與合法 API；保留 ToS 檢查紀錄 |

## 2. 最大五項風險（優先處理）
1. **R1 Active Share DQ**（取消資格級、定義未明）
2. **R3/R2 提交合規**（持股來源、拒收規則；C2/C12/C13/C14）
3. **R4/R19 提交失敗**（漏交容忍 2 次）
4. **R12/R14 LLM 幻覺與記憶污染**（決策錯誤與回測高估）
5. **R7 自主性界線**（比賽中改版的合規界線）

## 3. 技術開放問題（非規則）

| # | 問題 | 下一步 |
|---|---|---|
| T1 | 30 檔主動 ETF 的持股揭露網址/格式/更新頻率 | 資料管線 Phase 3 調查 |
| T2 | TPEx 個股日成交金額/股數是否可由 OpenAPI 取得歷史 | Phase 3 |
| T3 | 使用哪家 LLM（Gemini via GCP credit vs 其他）；成本估算 | 架構確認後再決定（本輪不決定） |
| T4 | Agent framework 是否必要（LangGraph / Google ADK / 純 Python） | 本輪不決定；建議先純 Python pipeline |
| T5 | 提交是否可程式化 | 向主辦方確認 |
| T6 | 盤前試撮（08:30–08:55）是否值得納入（時間極緊） | 評估後決定；預設不依賴 |

## 2026-10-13 更新：官方規則同步（主辦方 Email 2026-10-07 + 官網 2026-10-05 / 10-12 文件）

| NC | 2026-10-13 狀態 | 依據 | 摘要 |
|---|---|---|---|
| NC-1 結算 | **RESOLVED（官方文件）** | DataPack 規格書 v4.3（2026-10-12） | 前日結算持股 / 現金 / `nav_tradable` 由後台「文件繳交」→「下載資料包」取得（需登入，人工下載）；`agent/ops/datapack.py` 匯入 |
| NC-1 提交 | **OPEN（NEED_CONFIRMATION）** | 辦法 §二(八)；Email 2026-10-07 | 平台人工上傳、每日 25 次上限；上傳頁面與回執格式需登入後確認 |
| NC-2 Active Share | **RESOLVED / UPDATED**（子項 OPEN） | Email 2026-10-07 + 辦法_1005更新 §六(十三) | Wi 占 NAV、含現金、雙方前 15 大聯集、逐一比較所有官方主動 ETF、< 15% 違規、連續 2 日可取消資格。子項：benchmark ETF 現金權重未揭露 → NEED_CONFIRMATION |
| NC-3 C1～C14 處置 | **OPEN（部分已知）** | D-Plan v4.3 schema、DataPack 作廢原因；Email 2026-10-07 | 引用鏈、決策覆蓋、整股 →「整份退回」；作廢原因：資金不足 / 超賣 / 無價 / 合規 / 引用鏈 / 覆蓋 / 整股；C12、C14、時間戳之處置未寫 |
| NC-9 比賽中修改 | PARTIALLY RESOLVED | Email 2026-10-07 | 建議完整保留修改紀錄 → `docs/CODE_CHANGE_GOVERNANCE.md` |
| NC-10 重繳 | **RESOLVED** | Email 2026-10-07 | 每交易日 08:55 前最後一次**成功**提交生效（≠ 最後一次上傳） |
| NC-15 第一個交易日 | **RESOLVED** | 官網公告 2026-09-29 + Email 2026-10-07 | 10/26 休市；首個交易日 10/27；10/26 19:30～10/27 08:55 可繳交 |

其他 NC（NC-4/5/6/7/8、C12 現金估算含手續費）維持 OPEN。機器可讀版本：`config/organizer_clarifications.yaml`。
詳細：`reports/OFFICIAL_RULE_SYNC_2026-10-07.md`。
