# Future Research Backlog

> 只記錄想法；**不實作到 production**，不在比賽期間改變 Quant v1。每項都需要新的預先登錄 gate 與明確核准。AI 產生內容，需人工審閱。

| # | 想法 | 來源 / 證據 | 狀態 |
|---|---|---|---|
| 1 | foreign_5 / rev_3m_yoy 在**正式比賽結束後**，用比賽期間累積的 shadow 紀錄（`data/shadow_metrics/shadow_history.csv`）重新評估：至少 40 個新的交易日，並要勝過同結構 placebo | Factor Research（INSUFFICIENT_EVIDENCE）；shadow 已上線 | 觀察中 |
| 2 | 只用「前一晚 19:30 前可見」的事前曝險訊號，例如已知事件日、前日高波動、月營收公布密集日 | Risk Overlay：07:00 才可見的隔夜訊號大多已反映在開盤跳空（10/15 案例 −4.76% / −5.65%） | 未開始 |
| 3 | 現金政策研究：v1 的 breadth regime 現金（risk_off 10–18%）本身是否有效，或應更中性；必須與 placebo 比較 | Risk Overlay 發現 v1 已在 crash 窗持有較多現金 | 未開始 |
| 4 | 比賽期間 VWAP 成交與實際官方結算差異（滑價 / 作廢）的量化，回饋到研究模擬的成本假設 | DataPack 的 `prev_day_orders` / `void_reasons` | 等待比賽資料 |
| 5 | 風險研究改用 25 檔組合本身的波動與相關性（而非 universe 指數）；預先登錄 gate | Risk Overlay | 未開始 |

## 不做

- 新一輪大規模因子挖掘或參數搜尋（避免多重檢定）。
- LLM 決定曝險 / 標的 / 權重。
