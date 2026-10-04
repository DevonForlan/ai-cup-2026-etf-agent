# 短期（約 1 個月 / 24 交易日）報酬可預測性證據整理

> 撰寫日：2026-10-04。用途：AI CUP 2026 玉山 Agent Fund Manager（台股 150 檔大型股、每日 20–30 檔、VWAP 成交、2026/10/26–11/27）。
> 可信度標記：H = 頂級期刊或官方文件且已抓取確認；M = 工作論文 / 碩士論文 / 業界文章已確認存在；L = 二手報導或未能抓取全文；Unknown = 無法驗證。

## 0. 先講結論（給決策用）

本賽局的關鍵限制是：(1) 期間極短，只有約 24 個交易日；(2) 股票池是台股市值前 150 大，全部屬於大型、流動性高、外資與投信高度覆蓋的股票，多數學術異常在大型股中都比較弱；(3) 以當日 VWAP 成交，所以「隔夜跳空」那部分報酬在 T 日開盤前就已經被定價、拿不到，能拿到的是 VWAP→收盤以及之後幾天的漂移；(4) 一次買進加賣出的成本約 0.1425%×2 + 0.3% ≈ 0.585%，若每天換手 20%，24 天累積成本大約 2.8% NAV，因此高換手的短期反轉策略很容易被成本吃光。排名以期末 NAV 為準，平手時才比 MDD，所以「市場 beta」本身就是最大的報酬來源：在這段期間，個股選擇的 alpha 大概只有正負幾個百分點，而大盤的變動可能是正負 5–10%。

建議排序（詳見第 9 節）：營收／盈餘公告後的漂移（台灣月營收）與產業動能 > 中期個股動能（需搭配崩盤保護）> 52 週新高 > 新聞／LLM 情緒（只用在事件過濾）> 法人籌碼（大型股中效果短且弱）> 短期反轉（成本高、大型股中弱）> 價值／DCF（1 個月內幾乎沒有預測力）。

## 1. 橫斷面動能（Cross-sectional momentum）

- Jegadeesh & Titman (1993)〈Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency〉, Journal of Finance 48(1):65–91. https://ideas.repec.org/a/bla/jfinan/v48y1993i1p65-91.html 〔H〕
  以過去 3–12 個月報酬排序，買進贏家、賣出輸家，在 3–12 個月的持有期有顯著正報酬，部分報酬會在之後兩年回吐。標準做法是用 t-12 到 t-2 的報酬，並跳過最近 1 個月，以避開短期反轉。
- Asness, Moskowitz & Pedersen (2013)〈Value and Momentum Everywhere〉, Journal of Finance 68(3). https://pages.stern.nyu.edu/~lpederse/papers/ValMomEverywhere.pdf 〔H〕
  八個市場與資產類別都有價值與動能溢酬，且兩者彼此負相關，合併使用可以分散風險。
- **台灣證據偏弱，而且與市場狀態有關：**
  - Du, Huang & Liao (2009)〈Why is there no momentum in the Taiwan stock market?〉, Journal of Economics and Business 61(2):140–152. https://ideas.repec.org/a/eee/jebusi/v61y2009i2p140-152.html 〔H〕
    台灣市場的 DOWN 狀態比美國更常出現，而 DOWN 市場之後的動能報酬更負，因此整體看不到動能。作者支持「狀態相依」的解釋，而不是文化解釋。
  - Chui, Titman & Wei (2010)〈Individualism and Momentum around the World〉, Journal of Finance 65(1):361–392. https://ideas.repec.org/a/bla/jfinan/v65y2010i1p361-392.html 〔H〕
    個人主義指數較低的國家（包括東亞）動能利潤較小。
  - 搜尋摘要也提到兩項延伸證據：台灣的動能只出現在年報公告截止後的月份，其他月份反而是反向策略有效；以及「持續性贏家」策略在台灣有中期利潤。兩者都來自搜尋摘要（例如 NCCU 機構庫 https://nccur.lib.nccu.edu.tw/ir/handle/140.119/149411 ），沒有抓到全文。〔L〕
  - Ho, Hsiao, Lo & Yang (2023)〈Momentum investing and a tale of intraday and overnight returns: Evidence from Taiwan〉, Pacific-Basin Finance Journal 82. https://scholars.ntou.edu.tw/handle/123456789/24532 〔H〕
    **與本賽制直接相關。** 以「過去日內報酬（開盤→收盤）」做的動能策略有顯著正報酬，而且比較不怕動能崩盤；以「過去隔夜報酬（收盤→開盤）」做的動能則是負報酬，可延續到一年。作者的解讀是投資人對日內資訊反應不足、對盤後資訊反應過度。本賽是以 VWAP 成交，因此可考慮把過去報酬拆成 intraday 與 overnight 兩部分，只用 intraday 的部分當動能訊號。
- 動能崩盤：Daniel & Moskowitz (2016)〈Momentum Crashes〉, Journal of Financial Economics 122(2):221–247. https://www.nber.org/papers/w20439 〔H〕
  崩盤集中在「市場大跌之後、波動率很高、市場急速反彈」的時候，因為此時輸家組合的 beta 可能超過 3。用動能報酬的預測均值與變異數來調整曝險的動態策略，Sharpe 約為靜態策略的兩倍。實務意涵：在大盤剛急跌、VIX 或台指 VIX 偏高時，應降低純動能部位的權重，或對 beta 中性化。
- 對 24 天的意涵：動能文獻的持有期是 3–12 個月，1 個月持有期的效果較小但仍為正（美國）；台灣整體偏弱且依賴市場狀態。**可信度：中低。** 較適合當「不要買過去 1 年最弱股」的過濾器，而不是主要的 alpha 來源。

## 2. 短期反轉（1-month / 1-week reversal）

- Jegadeesh (1990)〈Evidence of Predictable Behavior of Security Returns〉, Journal of Finance 45(3):881–898. 〔H，經 IDEAS／搜尋確認書目〕
- Lehmann (1990)〈Fads, Martingales, and Market Efficiency〉, Quarterly Journal of Economics 105(1):1–28. https://www.nber.org/papers/w2533 〔H〕
  每週贏家與輸家在下一週明顯反轉。
- Da, Liu & Schaumburg (2014)〈A Closer Look at the Short-Term Return Reversal〉, Management Science 60(3):658–674. https://ideas.repec.org/a/inm/ormnsc/v60y2014i3p658-674.html 〔H〕
  沒有基本面消息支持的價格變動比較容易反轉；有現金流消息（例如分析師修正）支持的價格變動不易反轉。用這個方式「去除基本面」後的反轉策略，風險調整報酬約為傳統反轉的 4 倍。
  **意涵：** 若要用反轉，只對「沒有營收或財報消息、純粹因流動性衝擊造成的漲跌」做反向操作。月營收公告造成的漲跌則不應反向，反而可能延續（見第 4 節）。
- 台灣：搜尋摘要指出，台灣的反向策略除非持有到 3 年，否則整體不賺錢；但另一則摘要說台灣日內反向策略有正異常報酬，而且集中在開盤與收盤時段（NCU 碩論，https://ir.lib.ncu.edu.tw/handle/987654321/12280 ，全文抓取逾時）。〔L〕台灣有 ±10% 漲跌幅限制，相關研究認為漲跌停會抑制過度反應（CGU，https://pure.lib.cgu.edu.tw/en/publications/impact-of-price-limits-on-taiwan-security-returns/ ）。〔L〕
- 成本：反轉需要高換手，每次約 0.585% 的往返成本會大幅侵蝕利潤；學術文獻中的反轉效果主要在小型、低流動性股票。**對大型股 24 天：可信度低。** 只建議作為進場時點的輔助，例如在已選定的名單中，優先買進近 1–5 日「無消息而下跌」的股票。

## 3. 產業動能與 52 週新高

- Moskowitz & Grinblatt (1999)〈Do Industries Explain Momentum?〉, Journal of Finance 54(4):1249–1290. https://ideas.repec.org/a/bla/jfinan/v54y1999i4p1249-1290.html 〔H〕
  個股動能有很大一部分來自產業動能；產業動能策略即使控制了個股動能仍然獲利，而且**在 1 個月的持有期最強**（原文的重點之一，此處依原文印象，未逐頁核對 → M）。
  台股大型股高度集中在半導體與 AI 伺服器供應鏈，產業（或主題）動能幾乎等同於「AI 供應鏈 beta」，必須搭配單一產業曝險上限。
- George & Hwang (2004)〈The 52-Week High and Momentum Investing〉, Journal of Finance 59(5). 〔H，經多個來源確認書目〕
  股價接近 52 週高點的程度，比過去報酬更能預測未來報酬，而且長期不會反轉。這是計算簡單、換手低的訊號。台灣大型股的專門證據：Unknown（未找到）。

## 4. 盈餘公告後漂移（PEAD）與台灣月營收

- Bernard & Thomas (1989)〈Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?〉, Journal of Accounting Research 27:1–48. 〔H〕
  SUE 最高與最低十分位的報酬差在 48 季中有 41 季為正；結論是延遲反應，而不是風險溢酬。
- Jegadeesh & Livnat (2006)〈Post-Earnings-Announcement Drift: The Role of Revenue Surprises〉, Financial Analysts Journal 62(2):22–34. https://ideas.repec.org/a/taf/ufajxx/v62y2006i2p22-34.html 〔H〕
  營收驚奇與盈餘驚奇同向時，漂移更強。作者另有 JAE 2006〈Revenue surprises and stock returns〉: https://ideas.repec.org/a/eee/jaecon/v41y2006i1-2p147-171.html 〔H〕
- **台灣月營收（每月 10 日前公告，證交法第 36 條）：**
  - 陳柔君、劉彥瑞、蕭朝興 (2022)〈台灣股市的未預期月營收：綜合分析〉, 管理學報 39(4). https://lawdata.com.tw/tw/detail.aspx?no=484826 〔M-H，國內 TSSCI 期刊〕
    未預期月營收可以預測未來盈餘成長與股票報酬，且提供季資料以外的獨立解釋力；結合多種資料的策略在樣本外表現較佳。另一個發現是**機構投資人會在正（負）向未預期營收公告前增加（減少）持股**，代表資訊會提前進入價格，也代表法人籌碼與營收訊號高度相關。
  - Lu & Xin (2024)〈Mandatory Monthly Sales Disclosure and the Information Content of Earnings〉, The International Journal of Accounting 59(01). https://ideas.repec.org/a/wsi/tijaxx/v59y2024i01ns1094406024500021.html 〔H〕
    2014–2018 年的台灣資料顯示，在月營收公告之後才發布的季報，公告期報酬與 PEAD 都比較弱，表示月營收已經先行透露了大部分資訊。**意涵：11 月中的 Q3 季報對已公告 7–9 月營收的公司，增量資訊有限；10 月營收（11/10 前）反而是新資訊。**
  - Wang & Lien (2022)〈Is maximum daily return a lottery? Evidence from monthly revenue announcements〉, Review of Quantitative Finance and Accounting 59(2):545–600. https://ideas.repec.org/a/kap/rqfnac/v59y2022i2d10.1007_s11156-022-01051-1.html 〔H〕
    觸及漲停頻率高（樂透型）的股票之後的報酬較低；正面營收消息會削弱這種樂透效果。
  - 洪偉倫 (2026)〈未預期營收、資產成長與樣本外預期報酬〉, 政大碩士論文. https://thesis.lib.nccu.edu.tw/detail/5de91a46dbc69757987d294b65a5a9cc/ 〔M〕
    以 2008/01–2025/10 的資料檢驗，未預期月營收在 FF5 之下仍有顯著異常報酬，多空兩邊都捕捉到市場反應不足。
  - 搜尋摘要另指出，營收驚奇與營收動能策略在 1–12 個月持有期有正報酬（來源為 airitilibrary 的碩論，未抓取全文）。〔L〕
- **對本賽的意涵（可信度：中高）：** 10 月營收會在 11/1–11/10 陸續公告（2026/11/10 為週二），全部落在比賽期間內。可行訊號包括：YoY 與 MoM 相對於過去 12 個月同月季節性的驚奇值（SUE 形式）、累計營收 YoY 的加速度。必須以「公告時間戳」對齊（見 pit_lookahead_bias.md），公告在 T 日 14:30 之後的資訊，只能用在 T+1 的決策。

## 5. 三大法人籌碼（外資、投信、自營商）

- Richards (2005)〈Big Fish in Small Ponds: The Trading Behavior and Price Impact of Foreign Investors in Asian Emerging Equity Markets〉, JFQA 40(1):1–27. https://www.rba.gov.au/publications/rdp/2004/2004-05.html 〔H〕
  樣本包括 TWSE。外資流量對全球與本地報酬都呈現正回饋交易，且價格衝擊比過去估計的大很多。
- Barber, Lee, Liu & Odean (2009)〈Just How Much Do Individual Investors Lose by Trading?〉, Review of Financial Studies 22(2):609–632. https://ideas.repec.org/a/oup/rfinst/v22y2009i2p609-632.html 〔H〕
  使用台灣全市場交易資料：散戶每年績效損失 3.8 個百分點，機構每年獲益 1.5 個百分點，其中外資是主要贏家之一。
- Huang & Shiu (2009)〈Local Effects of Foreign Ownership in an Emerging Financial Market: Evidence from QFIIs in Taiwan〉, Financial Management 38(3):567–602. 〔H〕
  外資持股高的股票表現較好，但這是**長期**的資訊優勢。
- 徐暄皓 (2021)〈外資買賣超對台股之影響與投資策略〉, 台大碩論. https://tdr.lib.ntu.edu.tw/handle/123456789/74582 〔M〕
  跟隨外資買賣超的策略只在**小型股（市值後 50%）**有效，而且**效果只維持一天**。
- 林軒白 (2016)〈外資與投信淨買超行為及其資訊價值〉, 台大碩論. https://tdr.lib.ntu.edu.tw/handle/123456789/19442 〔M〕
  外資淨買超有季度延續性；投信的投資期較短、偏好小型股、選股能力較好，且有年底作帳跡象（Q4 標的在隔年 Q1 落後）。**11 月正是投信年底作帳前期，值得留意，但可信度低。**
- 搜尋摘要：法人羊群行為無法很好地預測未來報酬（IJBFR 2009, https://ideas.repec.org/a/ibf/ijbfre/v3y2009i2p147-167.html ）。〔M〕
- **結論：** 本賽股票池全是大型股，外資流量在大型股的「隔日之後」預測力弱，主要是同期的價格壓力。籌碼資料較適合用於：(a) 風險與擁擠度監控；(b) 與營收驚奇交互作用（法人在營收公告前先行動）。可信度：低到中。

## 6. 隔夜美股、費半（SOX）、TSM ADR 對台股次日的影響

- Eun & Shim (1989)〈International Transmission of Stock Market Movements〉, JFQA 24(2):241–256. https://ideas.repec.org/a/cup/jfinqa/v24y1989i02p241-256_01.html 〔H〕
  美國市場的衝擊會快速傳遞到其他市場，其他市場對美國的影響則不顯著。
- 台灣相關：搜尋摘要提到，美國報酬對台灣「收盤到開盤」的報酬有顯著外溢，對台灣「日內」報酬則有負向外溢（交大論文〈美國對台灣股市外溢效果之分量迴歸分析〉，https://ir.lib.nycu.edu.tw/handle/11536/43039 ，頁面無法讀取）。〔L〕這與 Ho et al. (2023) 的隔夜過度反應、日內反應不足的結論一致。
- TSM ADR 溢價：長期存在，最高曾達約 25%；Bloomberg 2026-04-23〈Sinking TSMC ADR Premium Offers Trading Window, UBS Desk Says〉（付費牆，僅確認標題）。〔L〕目前找不到「ADR 溢價變動預測台積電次日 VWAP 報酬」的學術研究：Unknown。
- **對本賽的意涵：** 美股收盤（台灣時間約 04:00–05:00）與台指期夜盤（至 05:00）的資訊，會在 T 日開盤時幾乎完全反映在開盤價。決策截止時間是 08:55，雖然可以使用這些資訊，但成交價是 VWAP，所以能拿到的只是「開盤後持續的部分」加上「日內過度反應的修正」。可信度：中，用於**市場層級的曝險與現金比例決策**，以及半導體權重的微調，而不是個股 alpha。也可以用夜盤台指期相對於日盤收盤的變動，作為 T 日開盤缺口的預測，並據此判斷是否避免在大跳空日追價（VWAP 會包含跳空後的價格）。

## 7. 新聞情緒與 LLM

- Tetlock (2007)〈Giving Content to Investor Sentiment: The Role of Media in the Stock Market〉, Journal of Finance 62:1139–1168. https://www.columbia.edu/~pt2238/papers/Tetlock_Media_Sentiment_JF.pdf 〔H〕
  媒體悲觀會預測價格下壓，之後回歸基本面（屬於短期反轉型）。
- Lopez-Lira & Tang (2023, v6 2025-10-28)〈Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models〉, arXiv:2304.07619. https://arxiv.org/abs/2304.07619 〔M-H〕
  使用知識截止日之後的頭條：GPT-4 對「不可交易的初始反應」方向命中率約 90%，對後續漂移也有顯著預測力，**主要集中在小型股與負面新聞**。報酬隨 LLM 普及而下降。
- Chen, Kelly & Xiu (2023)〈Expected Returns and Large Language Models〉, SSRN. 〔M，經 Wharton 會議資料確認〕
  在 16 個市場、13 種語言中，LLM 嵌入向量對新聞的預測優於傳統 NLP 與技術訊號，價格對新聞的反應是緩慢的。
- Kirtac & Germano (2024)〈Sentiment trading with large language models〉, Finance Research Letters 62:105227. 〔M-H〕
  OPT 情緒的多空策略 Sharpe 3.05。這是美國全市場、每日換手的結果，有前視偏誤與成本疑慮（見 pit 檔）。
- **意涵：** 新聞效果在小型股最強，對大型股、隔日 VWAP 成交、0.585% 往返成本的情境，期望效果會大幅縮小。建議用途：(a) 重大負面事件的排除過濾（例如重訊中的財務疑慮、工安、訴訟）；(b) 對營收或財報公告的語意補充。可信度：中低。

## 8. 價值／DCF

價值溢酬需要多年才會實現，在 1 個月內的預測力很低，而且與動能負相關（Asness et al. 2013）。McLean & Pontiff (2016, JF) 發現異常在發表後報酬平均下降 58%；Hou, Xue & Zhang (2020, RFS 33(5)) 發現在控制微型股之後，65% 的異常無法通過 t>1.96 的門檻。https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html 〔H〕
**結論：** DCF 不適合 24 天的選股，只建議當作「避免極端高估」的弱過濾。

## 9. 2026 年 11 月的行事曆事件

| 日期（2026） | 事件 | 來源與可信度 | 對策 |
|---|---|---|---|
| 10/26（週一） | 比賽第一天。10/25 光復節為週日，依 2025 年新的紀念日補假規則可能**於 10/26 補假**，需查證證交所 2026 年休市日 | 推論，Unknown | 以 TWSE 休市公告為準；這也可能是「約 24 個交易日」的原因 |
| 11/1–11/10（11/10 週二） | 10 月營收公告截止 | 證交法第 36 條，H | 營收驚奇訊號的主要窗口 |
| 11/3（週二，美國） | 美國期中選舉 | 一般常識，M | 市場層級的波動事件 |
| 11/11（美東）→ 台灣 11/12 早上 | MSCI 2026 年 11 月指數審核公告；**生效日 2026/12/01**，即被動資金在 11/30 收盤調整，**落在比賽結束（11/27）之後** | MSCI 官方 PDF，2026-08-12，https://www.msci.com/eqb/pressreleases/archive/ir_dates.pdf ，H | 公告後到生效前通常有漂移、生效日部分反轉（https://open.uct.ac.za/items/b6627141-e4e2-4ac6-b9b6-82ad43d68aeb ，M）。11/12–11/27 可小幅順勢持有被納入或權重調升的標的，不需要承擔生效日的反轉 |
| 11/14（週六）→ 預期順延至 **11/16（週一）** | 一般上市櫃公司 Q3 財報申報期限。2021 年 11/14 遇假日時順延至次一營業日 | 台灣英文新聞 2021，https://www.taiwannews.com.tw/zh/news/4334181 ，M；2026 年的順延為推論 | 財報增量資訊因月營收而減少（Lu & Xin 2024）；毛利率與 EPS 驚奇仍有用 |
| 約 11/30 | 金控 Q3 財報期限（2025 年為 11/29 順延 12/1） | 中央社、Yahoo 2025，M；2026 年日期為推論 | 在比賽期間之外 |
| 12 月 | FTSE 季審（2026 年 12 月公告 12/2、生效 12/21），以及台灣 50 等臺灣指數公司季審 | LSEG 搜尋摘要，M | 都在比賽期間之外，影響不大 |

## 10. 適合 24 個交易日的訊號家族排序

| 排名 | 訊號家族 | 理由 | 可信度 |
|---|---|---|---|
| 1 | 市場曝險管理（現金 0–25%、beta、半導體權重），依美股、SOX、夜盤台指期、波動率調整 | 期末 NAV 排名中，beta 的貢獻遠大於選股；也直接關係 MDD | 中（高於任何個股訊號） |
| 2 | 10 月月營收驚奇／營收動能（公告後漂移），搭配 Q3 財報驚奇 | 台灣獨有、多篇國內研究支持、事件剛好落在比賽期間 | 中高 |
| 3 | 產業／主題動能（1–6 個月），搭配 52 週新高接近度 | 1 個月持有期仍有效、換手低；需限制產業集中 | 中 |
| 4 | 個股中期動能（12-1，優先使用 intraday 部分），在高波動或市場急跌後降權 | 台灣整體偏弱，但 intraday 版本有證據（Ho et al. 2023） | 中低 |
| 5 | MSCI 11 月審核（11/12 公告後順勢） | 事件確定；大型股池中受影響的檔數少 | 中低 |
| 6 | 新聞與重訊 LLM 情緒（當過濾器） | 文獻效果集中在小型股；適合拿來排雷 | 中低 |
| 7 | 三大法人淨買超 | 大型股中只有一天的效果；可作擁擠度或確認訊號 | 低 |
| 8 | 短期反轉（1 週到 1 月） | 往返成本 0.585% 加上大型股，效果弱 | 低 |
| 9 | 價值／DCF | 1 個月內沒有預測力 | 很低 |

另外，換手要控制在合理範圍：建議每日換手上限約 10–15% NAV，並只在訊號變化超過成本門檻時才換股（例如預期超額報酬大於 1%）。
