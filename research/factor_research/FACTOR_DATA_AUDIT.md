# Factor Data / PIT Audit（候選因子資料與前視偏誤稽核）

> AI 產生內容，需人工審閱。研究用；正式 Quant v1 不變。實作：`agent/research/factor_lab.py`（只在研究流程使用）。

## 決策時點與 PIT 規則
凍結 pipeline 在交易日 **T 07:00** 決策，只讀 `available_at ≤ T 07:00` 的資料（`PITView`）。研究面板採完全相同規則：
價量 / 法人用 **< T** 的交易日（T-1 收盤後即可得）；月營收、估值、MOPS 依各列 `available_at` / 發布時間 ≤ T 07:00。

**一致性驗證（parity）**：4 個抽樣日（2025-03-24、2025-11-03、2026-05-04、2026-09-15）研究面板與凍結 pipeline 在 T 07:00 計算的特徵比較：
`rev_yoy`、`rev_mom`、`mom_20`、`mom_60`、`dist_52w_high` 數值差 **0**、rank 相關 **1.0000**；`lowvol_20` 僅年化常數不同（rank 相關 1.0000）。

## 資料表涵蓋
| 資料 | 來源（合法公開） | 期間（store） | 發布 / 可得時點 | 修正（revision） | 比賽期間每日自動取得 |
|---|---|---|---|---|---|
| 日價量 | TWSE / TPEx 盤後 | 2024-03-01 ～ 2026-10-14 | T 日 15:00 後 | 無 | 是（現行 refresh） |
| 三大法人買賣超（外資 / 投信 / 自營） | TWSE / TPEx | 同上 | T 日 17:00 後 | 無 | 是 |
| 月營收（含公布日） | MOPS / TWSE 公開資料 | 2023 起（YoY 自 2024 起完整） | 公布日 23:59（法定次月 10 日前） | 偶有更正（以首次公布值為準；現行 first-seen 機制） | 是 |
| PE / PB / 殖利率（含「財報年/季」） | TWSE BWIBBU_d、TPEx peQryDate（盤後） | 研究抓取中：2024-03 起 | T 日盤後（設為 18:00，T+1 使用） | 歷史查詢為當日公布值；EPS 隨新財報更新（財報季欄位可追蹤） | 是（新增 fetcher，未上線） |
| MOPS 重大訊息 | MOPS t05st02 | **2025-02 起** | 公布時間戳 | 無（以公告時間為準） | 是 |
| 美股隔夜 / TSM ADR / 台指期夜盤 / 匯率 | 公開行情、TAIFEX、央行 | 2024-03 起 | T 日 05:05～07:00 前 | 無 | 是 |
| 主動 ETF 持股 | 各投信官網 | 2025-01 起（多數僅近期） | 約 16:00 後 | 無 | 是（Active Share 用，不作選股因子） |

## 因子 PIT 分類
| 因子 | 家族 | 原始資料 | 可得時點 | 前視風險 | 分類 |
|---|---|---|---|---|---|
| rev_yoy / rev_mom（v1 基準） | 營收 | 月營收 | 公布日 | 無（parity 驗證） | PIT_SAFE |
| rev_yoy_accel、rev_mom_accel、rev_consec_yoy_pos、rev_yoy_slope6、rev_yoy_stab6、rev_3m_yoy、rev_ttm_yoy、rev_yoy_vs_trend | 營收品質 | 月營收（僅用已公布月份） | 最新月份公布日 | 假設較早月份先於最新月公布（法定如此）；延遲申報以「可見中最新期別」處理 | PIT_SAFE |
| foreign_5 / foreign_20 / trust_5 / trust_20 / dealer_20 / inst_total_20 / foreign_accel | 法人 | 三大法人日資料 ÷ 20 日成交量 | T-1 17:00 | 無 | PIT_SAFE |
| mom_20 / mom_60 / mom_60_skip5 / reversal_5 / dist_52w_high / ma60_dist / trend_consistency | 價格趨勢 | 收盤價 | T-1 收盤 | 無 | PIT_SAFE |
| lowvol_20 / low_downside_vol / low_beta_60 / low_idio_vol_60 / low_mdd_60 | 風險 | 收盤價、等權宇宙報酬 | T-1 | 無 | PIT_SAFE |
| size_value_20 / illiquidity（Amihud）/ abnormal_volume | 流動性 | 成交量、成交金額 | T-1 | 無 | PIT_SAFE |
| earnings_yield / book_to_price / div_yield | 估值 | BWIBBU_d / peQryDate | T-1 盤後 | 歷史日表為當日公布值；PE 虧損時不提供（設 NaN） | PIT_SAFE |
| roe_proxy（PB/PE）/ eps_ttm_growth（財報季變更時 TTM EPS 變動） | 品質 | 同上推導 | T-1 盤後 | 依「財報年/季」欄位，僅用已反映之財報 | PIT_SAFE（代理指標，非完整財報） |
| mops_count_5 | 事件 | MOPS 重大訊息 | 公告時間 < T 07:00 | 2025-02 以前無資料 → 設 NaN（非 0） | PIT_CONDITIONAL（涵蓋期不足） |
| 市場廣度 / EW 趨勢 / EW 回撤 / EW 波動 | 情境（風險 / 現金） | 價量 | T-1 | 無 | PIT_SAFE（時間序列，非選股） |
| SOX / NDX / SPX / TSM ADR / TXF 夜盤 / USD-TWD 隔夜 | 情境 | 外部行情 | T 07:00 前 | 依 available_at merge_asof | PIT_SAFE（時間序列，非選股） |

## DATA_UNAVAILABLE（不補值、不用未來資料）
| 因子 | 原因 |
|---|---|
| 毛利率、營業利益率、淨利率、ROA、營業利益成長、品質一致性 | 季財報未收錄（MOPS XBRL 公開但本專案未建置抓取） |
| PEG、EV/EBITDA、FCF yield | 需盈餘預估 / 負債 / 現金流量表 |
| 營收驚喜、盈餘驚喜（vs 市場共識） | 無合法免費的 PIT 共識預估來源（`rev_yoy_vs_trend` 為「相對自身趨勢」代理） |
| 股本週轉率（成交量 / 流通股數） | 流通股數歷史未收錄 |
| 法說會、財報公告日事件 | MOPS 有公告但未結構化分類；本輪僅計數 `mops_count_5` |

## PIT_UNSAFE
本輪無被列為 PIT_UNSAFE 的候選（所有面板經 parity / 可得時點檢查）。若改用「修正後營收」或「事後財報」即屬 PIT_UNSAFE，已避免。
