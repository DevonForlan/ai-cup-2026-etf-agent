# 因子文獻回顧（Factor Literature Review）— 台股大型股、24 交易日、低週轉組合

> **AI 產生內容，需人工審閱。來源皆經搜尋確認；未能確認之細節標註 unverified。**
>
> 撰寫日期：2026-10-14。本文件不構成投資建議、官方文件或財務指引。

## 0. 範圍與方法

- 目的：替目前僅用「月營收 YoY（0.7）+ MoM（0.3）橫斷面百分位」的選股分數，找出有文獻支持的候選因子，並評估與本專案條件（上市前 100 + 上櫃前 50 大型股、20–30 檔、24 個交易日、低週轉、手續費 0.1425% ×2 + 證交稅 0.3%）的相關性。
- 方法：以網路搜尋取得來源，再盡量開啟出處頁面（RePEc/IDEAS、出版社、學校典藏、NBER/SSRN）核對標題、作者、年份與摘要。下表的「發現」以摘要內容為準，**未閱讀全文**；樣本、數字若出處頁未載明，標註 unverified。
- 驗證等級：
  - **A** = 已開啟出處頁核對書目與摘要；
  - **B** = 書目由多個搜尋結果一致確認，摘要內容來自搜尋摘要／二手整理，未逐字核對。
- 學位論文（碩博士）未經同儕審查，證據力較期刊論文弱，表中另行標示。

---

## 1. 來源清單

### 1.1 月營收／營收品質（台灣特有揭露）

**[T1] Mandatory Monthly Sales Disclosure and the Information Content of Earnings**（驗證 A）
- 作者：Hsueh-Tien Lu, Hua Christine Xin
- 年份／期刊：2024, *The International Journal of Accounting*, 59(01), DOI 10.1142/S1094406024500021
- URL：https://ideas.repec.org/a/wsi/tijaxx/v59y2024i01ns1094406024500021.html
- 市場／樣本：台灣上市公司，2014–2018
- 因子：月營收揭露時點 vs. 季盈餘資訊含量
- 發現：季盈餘若在次季第一個月月營收公布「之後」才發布，其公告報酬與盈餘後漂移（PEAD）較弱；作者認為即時的月營收揭露會先行吸收盈餘的資訊含量。
- 限制：研究重點是盈餘公告資訊含量，不是建構月營收選股因子；未直接檢驗大型股或扣除成本後的可交易性。對本專案的意涵是「月營收本身就是台股資訊流的主要來源」，間接支持現有營收因子，也暗示季盈餘因子的增益可能有限。

**[T2] 台灣股市的未預期月營收：綜合分析（Unexpected Monthly Revenue in the Taiwan Stock Market: A Comprehensive Analysis）**（驗證 A）
- 作者：陳柔君、劉晏睿、蕭朝興
- 年份／期刊：2022, 《管理學報》39(4), pp. 503–545
- URL：https://lawdata.com.tw/tw/detail.aspx?no=484826
- 市場／樣本：台股；樣本期間 unverified
- 因子：未預期月營收（MSURGE）、未預期季營收（QSURGE）、季盈餘意外（QSUE）
- 發現：(1) MSURGE 可預測未來盈餘成長與股票報酬；(2) MSURGE、QSURGE、QSUE 彼此相關，但各自對橫斷面報酬有獨立解釋力；(3) 以 6 個月滾動視窗 + Fama-MacBeth 進行的樣本外預測，投資績效較好；(4) 法人在 MSURGE 為正的公告前加碼、為負的公告前減碼。
- 限制：是否以大型股為主、是否扣除成本、持有期長度均 unverified；第 (4) 點表示法人可能提前反應，公告後才進場的報酬可能被壓縮。

**[T3] 營收創新高之動能策略：台灣股市之證據（The Momentum Strategy of the Revenue Hit Record: Evidence from Taiwan Stock Market）**（驗證 A；碩士論文）
- 作者：林靜妤（指導：顧廣平），淡江大學財務金融學系碩士班，2020，DOI 10.6846/TKU.2020.00643
- URL：https://www.airitilibrary.com/Article/Detail/U0002-2207202009464900
- 市場／樣本：台灣上市櫃；期間 unverified
- 因子：營收動能（未預期營收）、營收相對歷史最高（創新高）、相對歷史最低（創新低）
- 發現：營收動能與營收創新高動能在 1–12 個月持有期均有顯著正平均報酬；創新低動能較弱。效果有季節性且受研究期間影響，但對上市／上櫃或產業不敏感。三因子與總經風險無法解釋前兩者。營收動能之後有價格反轉（與過度反應一致），營收創新高組合則沒有顯著反轉（作者推測為錨定效應）。
- 限制：碩士論文；未必限定大型股；成本處理 unverified。

**[T4] 鉅額營收宣告對台灣上市電子股股價與報酬之研究（An Investigation of the Abnormal Stock Returns of Significant Monthly Sales Announcement on Listed Electronic Firms in Taiwan）**（驗證 A；碩士論文）
- 作者：周子安（指導：古永嘉），國立臺北大學企業管理學系，2016
- URL：https://www.airitilibrary.com/Publication/Index/U0023-1303201714243478
- 市場／樣本：市值前 100 大上市電子股，2012/01–2015/06；以月營收 YoY 超過 ±20% 為事件（+20% 以上 835 件、−20% 以下 509 件）
- 因子：大幅 YoY 月營收變動事件
- 發現：大幅營收增減公告後都有異常報酬；公告前 5 日也有異常報酬，表示市場會部分提前反應。
- 限制：只看電子股，期間短（3.5 年），屬事件研究、非組合回測，未扣成本。**它的樣本是大型電子股，跟本專案宇宙最接近。**

**[T5] 上市櫃公司每月營收宣告對股價之影響（The Stock Price Effect of Company's Monthly Revenue Announcements）**（驗證 A；碩士論文）
- 作者：邱廉松，國立政治大學，2020
- URL：https://nccur.lib.nccu.edu.tw/handle/140.119/130488
- 市場／樣本：上市櫃 1,470 家公司、32 個產業，2015/01–2019/12
- 因子：未預期營收 vs. 公告期 CAR
- 發現：公告日有異常報酬與累積異常報酬；未預期營收對 CAR 的影響在 25 個產業為正、觀光業為負、6 個產業不顯著。
- 限制：只看公告視窗，沒有檢驗持有 24 天的組合報酬；產業異質性大，表示「跨產業直接比較營收成長百分位」可能需要做產業中性化。

**[T6] Mendeley Data 資料集「zmwang」— 月營收宣告與修正 MAX（漲跌停）效應**（驗證 A，但僅為資料集描述）
- 作者：Zi-May Wang，2020（DOI 10.17632/5k4ktg2r6y.1）
- URL：https://data.mendeley.com/datasets/5k4ktg2r6y
- 市場：台股
- 因子：漲跌停觸及率（類樂透性）× 月營收宣告
- 發現（資料集描述）：觸及漲停率高的股票次月報酬較低（修正 MAX 效應）；若同時遇到月營收宣告，散戶的吸引力與淨下單失衡下降，效應減弱。作者認為月營收宣告是此效應的主導因素。
- 限制：只有資料集頁面描述，對應的期刊論文名稱 unverified；屬月頻率。

### 1.2 法人／外資流量（台灣）

**[T7] Does Foreign Investors Trade Predict Stock Return? Evidence from Taiwan**（驗證 A）
- 作者：Chia-jui Lai, Kuo-ren Lou（婁國仁）, Cheng-yi Shiu
- 年份／期刊：2008, *International Journal of Information and Management Sciences*, 19(3), pp. 477–494
- URL：https://teacher.tku.edu.tw/StfFdDtl.aspx?tid=9438
- 市場／樣本：台股個股日資料；期間 unverified
- 因子：外資買賣超
- 發現：外資是動能交易者（買進過去贏家、賣出輸家）；**在大型股與低淨值市價比股票上，外資買賣超可正向預測未來報酬**，作者解釋為外資在這些股票具資訊優勢（或資訊劣勢較小）。
- 限制：資料較舊（2008 年前）；預測持有期長度 unverified；外資比重與市場結構已改變。

**[T8] The Behavior and Performance of Foreign Investors in Emerging Equity Markets: Evidence from Taiwan**（驗證 A）
- 作者：Anchor Y. Lin, Peggy E. Swanson
- 年份／期刊：2003, *International Review of Finance*, 4(3–4), pp. 189–210
- URL：https://international.vlex.com/vid/the-behavior-and-performance-855672010
- 市場／樣本：TWSE 60 檔大型股；外資每日交易與持股資料 1996/12/03–2003/06/11
- 因子：外資交易行為與績效
- 發現：外資採動能策略、偏好大型、高 B/M 與高科技股，沒有羊群行為；**外資短期表現優於市場、長期則較差**，短期優勢部分來自價格動能而非承擔風險；控制規模、週轉率與產業後，短期表現在大型、高週轉、高科技股較好。
- 限制：資料止於 2003；「短期」的確切長度 unverified。注意：本文與 [T7] 在 B/M 偏好方向上不同（高 vs. 低 B/M），兩者應視為獨立證據。

**[T9] 兩篇關於國際財務管理的論文（Essays on International Financial Management: (1) Foreign Investors in Emerging Markets: The Case of Taiwan …）**（驗證 A；博士論文）
- 作者：徐政義（指導：林基煌），國立政治大學財務學系，2002
- URL：https://nccur.lib.nccu.edu.tw/handle/140.119/96311
- 市場／樣本：TWSE 外資（QFII）；頁面表格標題顯示 1991–2000
- 因子：外資淨買
- 發現：外資的資訊優勢主要出現在大型、低 B/M 及發行 ECB 的公司；外資交易會提高條件波動。搜尋摘要另指出「總體」外資淨買對未來報酬有正向影響，但個股層級結果分歧（此點出自搜尋摘要，unverified）。
- 限制：博士論文、資料很舊。

**[T10] Mutual fund herding its impact on stock returns: Evidence from the Taiwan stock market**（驗證 A）
- 作者：Weifeng Hung, Chia-Chi Lu, Cheng F. Lee
- 年份／期刊：2010, *Pacific-Basin Finance Journal*, 18(5), pp. 477–493
- URL：https://ideas.repec.org/a/eee/pacfin/v18y2010i5p477-493.html
- 市場／樣本：台灣基金（投信）季持股資料；期間 unverified
- 因子：投信（共同基金）羊群買／賣
- 發現：基金傾向延續自己的交易，而非跟隨其他基金；**羊群買進之後價格延續**（具資訊性），**羊群賣出之後報酬反轉**（非資訊性）。
- 限制：季資料，跟本專案用的每日投信買賣超頻率不同；不對稱性（買有用、賣反轉）值得在設計 trust flow 因子時檢驗。

**[T11] The dynamic analysis of investors' trading in the Taiwan stock market**（驗證 A）
- 作者：Chao-Shin Chiao, Zi-Mei Wang, Chang-Ho Huang
- 年份／期刊：2009, 《交大管理學報》(*Chiao Da Management Review*) 29(1), pp. 41–78
- URL：https://ibm.nycu.edu.tw/ibm/cmr/2009_Issue1/2009_Issue1_41-78.html
- 市場／樣本：台灣 50 成分股（TSEC 50）；期間 unverified
- 因子：法人 vs. 散戶日內／日下單失衡
- 發現：日報酬與法人淨買**同期**強烈正相關（法人追漲）、與散戶淨買負相關；日內資料顯示相當部分來自法人交易的價格壓力；**法人下單失衡並未一致地預測未來報酬**。
- 限制：屬短期（日／日內）預測檢驗，不是 24 天持有。它是重要的反向證據：大型股的法人流量可能多半是同期價格壓力，而非領先訊號。

### 1.3 動能／反轉／52 週高點（台灣）

**[T12] Momentum in Taiwan: Seasonality matters!**（驗證 A）
- 作者：Hsiao Peng Fu, Andrew Wood
- 年份／期刊：2010, *Applied Economics Letters*, 17(13), pp. 1247–1253, DOI 10.1080/00036840902917589
- URL：https://researchportal.port.ac.uk/en/publications/momentum-in-taiwan-seasonality-matters/
- 市場／樣本：「大量台股資料」；期間與股數 unverified
- 發現：動能只出現在年報申報截止後的月份；其他月份反向（contrarian）策略有顯著報酬，農曆新年與中秋前後尤其明顯。
- 限制：月頻率；未區分大型股。

**[T13] Seasonality, Monetary Supply and Taiwanese Momentum**（驗證 A）
- 作者：Hsiao-Peng Fu, Shu-Fan Hsieh
- 年份／期刊：2024, *Journal of Applied Finance & Banking*, 14(2)
- URL：https://ideas.repec.org/a/spt/apfiba/v14y2024i2f14_2_2.html
- 發現：1–2 月有顯著反轉，3–12 月在落後 M1B 成長時有強動能（只在景氣擴張期）；兩者部分可由未實現資本利得（處分效果）解釋。
- 限制：樣本期間 unverified；期刊影響力較低。

**[T14] Market dynamics and momentum in the Taiwan stock market**（驗證 A）
- 作者：Chaonan Lin, Kuan-Cheng Ko, Zhi-Xiang Feng, Nien-Tzu Yang
- 年份／期刊：2016, *Pacific-Basin Finance Journal*, 38, pp. 59–75, DOI 10.1016/j.pacfin.2016.03.009
- URL：https://ideas.repec.org/a/eee/pacfin/v38y2016icp59-75.html
- 發現：過去文獻普遍發現台股「無動能溢酬」，作者歸因於市場狀態頻繁轉換；**市場維持同一狀態時動能利潤顯著為正，轉換期則顯著反轉**；利潤集中在受投資人關注較多的股票，支持過度自信假說。
- 限制：樣本期間 unverified；月頻率動能。對本專案意涵：動能／趨勢因子應搭配市場狀態（regime）判斷。

**[T15] The 52-week high and momentum in the Taiwan stock market: Anchoring or recency biases?**（驗證 A）
- 作者：Ying Hao, Hsiang-Hui Chu, Keng-Yu Ho, Kuan-Cheng Ko
- 年份／期刊：2016, *International Review of Economics & Finance*, 43, pp. 121–138
- URL：https://ideas.repec.org/a/eee/reveco/v43y2016icp121-138.html
- 樣本：台股 1982/01–2012/12
- 發現：52 週高點策略的利潤被 1 月負報酬侵蝕；全樣本中 52 週高點策略主導動能報酬；近因（recency）策略只在 2000 年前、擴張期與多頭市場有利潤。作者結論為證據混合，錨定與近因偏誤並存。
- 限制：月頻率、全市場樣本（未限大型股）。

**[T16] 52 週高點「更新成分」對動能利潤的影響（IJBESAR 2023, vol.16(1), pp.71–86）**（驗證 B — 書目資料有衝突）
- 作者：Li-Chuan Liao, Tzu-Pu Chang, Ping-Huang Wang
- URL：https://ideas.repec.org/a/tei/journl/v16y2023i1p71-86.html ；PDF：https://ijbesar.ihu.gr/docs/volume16_issue1/16_01_07.pdf
- 註：PDF 標題為 *The Effect of the Movement in 52-Week High on Momentum Profit: The Evidence from Taiwan*，但 RePEc 頁面顯示的標題不符（疑為索引錯誤）；正式標題需以 PDF 為準。
- 發現（摘要）：將「股價／52 週高點」拆成價格變動成分與 52 週高點「更新」成分，更新成分對動能利潤影響較大；作者表示結論目前限於相對無效率的市場。
- 限制：樣本期間 unverified。

**[T17] Momentum in machine learning: Evidence from the Taiwan stock market**（驗證 A）
- 作者：Dien Giau Bui, De Rong Kong, Chih Yung Lin, Tse Chun Lin
- 年份／期刊：2023, *Pacific-Basin Finance Journal*, article 102178, DOI 10.1016/j.pacfin.2023.102178
- URL：https://scholar.nycu.edu.tw/en/publications/momentum-in-machine-learning-evidence-from-the-taiwan-stock-marke/
- 發現：重新檢驗台股 86 個異常；機器學習（神經網路、PLS）多空組合月報酬約 1.20%–1.50%；前 20 名重要預測變數中有 5 個與動能相關，雖然台股傳統上被視為動能異常的例外。
- 限制：多空、月頻率、全市場；多空報酬不等於只做多大型股組合的超額報酬；成本處理 unverified。

### 1.4 風險／低波動（台灣）

**[T18] 台灣股市低波動異常報酬實證研究（An Empirical Study on Low Volatility Abnormal Returns in Taiwan's Stock Market）**（驗證 A；碩士論文）
- 作者：劉人慈（指導：蕭明福），國立政治大學經濟學系，2025
- URL：https://thesis.lib.nccu.edu.tw/thesis/detail/ecbbb1d19b283c677ab4ed946692b359
- 樣本：台股上市公司 2007–2023
- 因子：特質波動度（idiosyncratic volatility）
- 發現：以 FF3、Carhart 4、FF5 模型做 Fama-MacBeth 回歸，低波動異常穩健存在；估計期間越長，高低波動組合報酬差越小；市場風險（台灣 VIX）上升時，低波動組合仍有正溢酬（避險效果）。低波動持股集中於紡織、水泥、食品等防禦產業；五因子下可辨識出低波動的大型科技股。
- 限制：碩士論文。對本專案而言，低波動容易造成產業偏誤（偏向傳產防禦股）。

### 1.5 獲利／價值（台灣）

**[T19] 五因子模型於台灣股票市場報酬的實證研究（An Empirical Study of the Five-factor Model in Taiwan Stock Market Returns）**（驗證 A；學位論文，學位類別 unverified）
- 作者：王芯儀，國立中央大學財務金融學系，2021
- URL：https://ir.lib.ncu.edu.tw/handle/987654321/87105
- 樣本：上市、上櫃與下市公司月資料（TEJ），1990/07–2020/12，排除金融業
- 發現：五因子模型主要降低「報酬差」組合的 alpha，獲利因子（RMW）是關鍵；但對表現好的組合反而留下更多 alpha；與 Fama-French (2015) 不同，台灣公司投資越多報酬越高。
- 限制：學位論文；資產定價檢驗，不是選股回測。搜尋中另見其他台灣學位論文對五因子的結論互相矛盾（未逐一核對），顯示台股的獲利／投資因子證據**並不一致**。

### 1.6 美股隔夜／總體連動（台灣）

**[T20] 台灣股、匯市與美國股市關聯性探討（Discussing the Linkage Between the Stock and Exchange Market of Taiwan and the Stock Market of US）**（驗證 A）
- 作者：王冠閔、黃柏農
- 年份／期刊：2004, 《臺灣經濟預測與政策》34(2), pp. 31–72, DOI 10.29629/TEFP.200403.0002
- URL：https://www.airitilibrary.com/Article/Detail/a0000040-200403-34-2-31-72-a
- 發現：美股（NASDAQ、S&P 500）報酬 Granger 領先台灣股市與匯市；台股與匯市雙向影響；危機期間有從美國到台灣的傳染效果。
- 限制：指數層級、樣本期間 unverified、資料老舊。屬「市場曝險／現金比例」層級證據，不是個股選股證據。搜尋中另見數篇交大學位論文指出美股對台股的影響主要集中在開盤（close-to-open）且開盤可能過度反應、盤中修正，但這些未逐一開啟核對，視為 unverified。

### 1.7 經典因子文獻（非台灣，供方法與基準）

**[G1] Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency**（驗證 B）
- Narasimhan Jegadeesh, Sheridan Titman, 1993, *Journal of Finance* 48(1), pp. 65–91
- URL：https://ideas.repec.org/a/bla/jfinan/v48y1993i1p65-91.html
- 市場：美國 NYSE/AMEX（樣本約 1965–1989，依二手摘要）
- 發現：買過去贏家、賣輸家的策略在 3–12 個月持有期有正報酬，非系統性風險所能解釋；第一年後部分超額報酬在之後兩年消退。
- 限制：美股、月頻率；台股證據見 [T12]–[T17]，結論明顯不同。

**[G2] The 52-Week High and Momentum Investing**（驗證 B）
- Thomas J. George, Chuan-Yang Hwang, 2004, *Journal of Finance* 59, pp. 2145–2176
- URL：https://academicnewsletter.sufe.edu.cn/info/361244
- 發現：接近 52 週高點的程度可解釋大部分動能利潤，預測力優於過去報酬，且長期不反轉。
- 限制：美股、月頻率、多空。

**[G3] The Cross-Section of Volatility and Expected Returns**（驗證 B）
- Andrew Ang, Robert J. Hodrick, Yuhang Xing, Xiaoyan Zhang, 2006, *Journal of Finance* 61(1), pp. 259–299；NBER WP 10852
- URL：https://www.nber.org/papers/w10852
- 發現：相對 Fama-French 模型的高特質波動股票平均報酬非常低；對總體波動創新敏感度高的股票報酬也低；規模、B/M、動能、流動性無法解釋。
- 限制：美股；後續研究（如 Fangjian Fu 的 EGARCH 研究，見搜尋結果 https://ink.library.smu.edu.sg/lkcsb_research/771）指出結果可能主要來自少數小型高波動股的反轉。

**[G4] Betting Against Beta**（驗證 B）
- Andrea Frazzini, Lasse Heje Pedersen, 2014, *Journal of Financial Economics* 111(1), pp. 1–25
- URL：https://ideas.repec.org/a/eee/jfinec/v111y2014i1p1-25.html
- 發現：在槓桿限制下，高 beta 資產被高估；做多（槓桿化）低 beta、做空高 beta 的 BAB 因子在美股與 20 個國際市場等有顯著風險調整報酬。
- 限制：需要槓桿與做空；Novy-Marx & Velikov (2022) "Betting Against Betting Against Beta" 指出其建構方式實際上接近等權重，且報酬來自偏向獲利與投資因子（見 https://pure.psu.edu/en/publications/betting-against-betting-against-beta/）。

**[G5] Illiquidity and Stock Returns: Cross-Section and Time-Series Effects**（驗證 B）
- Yakov Amihud, 2002, *Journal of Financial Markets* 5, pp. 31–56
- URL：https://archive.nyu.edu/handle/2451/27420
- 發現：以「每日 |報酬| / 成交金額」衡量非流動性；預期市場非流動性提高預期超額報酬；非預期非流動性與同期報酬負相關；效應在小型股較強。
- 限制：美股；搜尋結果顯示 Harris & Amato (2019, *Critical Finance Review*) 的複製在樣本外顯著性大幅減弱。對前 150 大股票，非流動性溢酬預期很小，較適合當風控／可交易性篩選。

**[G6] The Other Side of Value: The Gross Profitability Premium**（驗證 B）
- Robert Novy-Marx, 2013, *Journal of Financial Economics* 108, pp. 1–28（NBER WP 15940）
- URL：https://nber.org/papers/w15940
- 發現：毛利／總資產對橫斷面報酬的預測力與 B/M 相近；控制獲利後價值策略表現大幅改善，**尤其在最大、最具流動性的股票**。
- 限制：美股、需季報資料（本專案目前沒有）。

**[G7] Quality Minus Junk**（驗證 B）
- Clifford S. Asness, Andrea Frazzini, Lasse Heje Pedersen, 2019, *Review of Accounting Studies* 24(1), pp. 34–112
- URL：https://papers.ssrn.com/abstract=2312432
- 發現：安全、獲利、成長、管理良好的「品質」股價格只略高，但有顯著風險調整報酬；QMJ 多空因子在美國與 24 國顯著。
- 限制：多空、月頻率、需財報資料。

**[G8] Revenue Surprises and Stock Returns**（驗證 B）
- Narasimhan Jegadeesh, Joshua Livnat, 2006, *Journal of Accounting and Economics* 41(1–2), pp. 147–171
- URL：https://ideas.repec.org/a/eee/jaecon/v41y2006i1-2p147-171.html ；工作論文：https://archive.nyu.edu/handle/2451/27572
- 發現（工作論文摘要）：盈餘公告日的股價反應與當期及過去的營收意外顯著相關；控制盈餘意外後，大幅營收意外的股票公告後仍有顯著異常報酬；分析師對營收意外的修正偏慢。
- 限制：美國季營收，非月營收；但支持「營收意外」相對於「營收成長水準」的觀念，與 [T2] 一致。

**[G9] Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium?**（驗證 B）
- Victor L. Bernard, Jacob K. Thomas, 1989, *Journal of Accounting Research* 27
- URL：https://en.wikipedia.org/wiki/Post%E2%80%93earnings-announcement_drift（書目確認來源；原文未開啟）
- 發現：盈餘公告後股價沿意外方向持續漂移，作者認為是延遲反應而非風險溢酬。
- 限制：美股季盈餘；樣本期間在二手資料中不一致（1974–1985 或 1974–1986，unverified）。

**[G10] The High-Volume Return Premium**（驗證 B）
- Simon Gervais, Ron Kaniel, Dan Mingelgrin, 2001, *Journal of Finance*
- URL：https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/04/9901.pdf
- 發現：單日或單週異常高（低）成交量的股票，接下來一個月傾向上漲（下跌），作者以「能見度」解釋。
- 限制：美股；持有期約一個月，**與 24 交易日視窗相近**；搜尋結果提到中國市場的研究得到不同結論。

**[G11] ... and the Cross-Section of Expected Returns**（驗證 B）
- Campbell R. Harvey, Yan Liu, Heqing Zhu, 2016, *Review of Financial Studies* 29(1), pp. 5–68（NBER WP 20592）
- URL：https://nber.org/papers/w20592
- 發現：考量多重檢定後，新因子的 t 值門檻約 3.0（而非 2.0）；許多已發表的因子發現可能為偽陽性。
- 限制：方法論文獻；用來設定本專案的因子篩選門檻。

---

## 2. 依因子家族整理的證據強度（針對本專案）

| 因子家族 | 台灣證據 | 與 24 日／大型股／低週轉的相關性 | 現有資料是否足夠 |
|---|---|---|---|
| 月營收品質／營收意外 | T1–T6（期刊 2 篇 + 學位論文 3 篇 + 資料集） | **高**：台灣特有、更新頻率接近持有期；T4 樣本即為大型電子股 | 是（月營收 + 公布日期） |
| 外資／投信流量 | T7–T11（期刊 4 篇 + 博論） | 中：大型股外資流量有預測力（T7、T8），但 T11 顯示日頻多為同期價格壓力；投信買進有延續、賣出有反轉（T10） | 是（三大法人日資料） |
| 價格動能／52 週高 | T12–T17（期刊為主） | 中低：台股動能弱且依季節與市場狀態而定；52 週高點較穩健但 1 月表現差 | 是（日價量） |
| 低波動／風險 | T18（學位論文）、G3、G4 | 中：可作風控與降低回撤，不一定提高 24 日報酬；有產業偏誤 | 是 |
| 流動性／異常成交量 | G5、G10（皆美股） | 低至中：前 150 大非流動性溢酬應該很小；異常成交量持有期接近，但缺乏台股驗證 | 是 |
| 獲利／品質／價值 | T19（學位論文）、G6、G7 | 中（文獻）／低（可行性）：G6 指出在大型股有效，但需季報 | **否**（無季報、無 PE/PB 歷史） |
| 事件（重大訊息、財報公告） | T1、G8、G9 | 中：營收／盈餘意外後漂移有支持；重大訊息文字未找到直接台股證據 | 部分（MOPS 重大訊息有、季盈餘無） |
| 市場狀態／美股隔夜 | T20、T14 | 用於曝險／現金比例，而非選股；證據集中在開盤跳空 | 是（美股隔夜、台指期夜盤） |

---

## 3. Implications for this project（對本專案的意涵）

以下為審慎、非過度推論的觀察，需人工審閱並以本專案自己的樣本外回測驗證。

1. **月營收仍是最有台灣本地證據的訊號，但「意外」可能比「成長水準」更好。** T2（MSURGE）與 G8 都指向「相對預期的營收意外」，而不只是 YoY 百分位；T3 指出「營收創新高」動能較不反轉。可考慮的低成本擴充：(a) 未預期營收（例如本月 YoY 減去過去 N 個月 YoY 平均，或相對季節性預期的差）；(b) 營收是否創 12 個月／歷史新高；(c) 連續成長月數。需注意 T5 的產業異質性 → 建議做產業內百分位或產業中性化；T3 的反轉現象 → 單純營收動能的持有期不宜過長。
2. **法人流量：大型股的外資證據相對較多，但要防同期價格壓力與追高。** T7、T8 支持大型股外資買超有短期預測力；T11 顯示 TSEC 50 的法人下單失衡多為同期關係、無一致預測力。T2 第 (4) 點顯示法人會在營收公告前布局，因此「法人流量 × 營收意外」的交互作用或許值得測，但它也代表公告後才進場的超額報酬可能已部分被吃掉。投信方面，T10 的買／賣不對稱（買延續、賣反轉）可以作為設計假說。所有法人因子都應以成交量或市值正規化（例如 5D/20D 淨買／平均成交金額），否則會偏向大型權值股。
3. **價格動能在台股不宜當主因子。** T12–T15 一致顯示台股動能弱、受季節（1–2 月反轉）與市場狀態影響。52 週高點距離（T15、G2）較有理論支持，但 T15 顯示 1 月表現差。比較適合當作「避免選到處於明顯下跌趨勢的股票」的輔助篩選，或與市場狀態判斷（T14）搭配。
4. **低波動比較像風險控制工具而不是報酬來源。** T18 支持台股低波動異常與避險效果，但持股會偏向傳產防禦股；對 24 天評估期，可以用來控制組合波動與單一持股權重，或作為 tie-breaker，而非高權重因子。
5. **獲利／品質／價值因子目前無法直接實作。** G6、G7 的證據（含大型股）支持品質因子，但需要季報與 PE/PB 歷史；台灣的五因子證據（T19）並不一致。若要加入，需要先建立季報資料管線（並處理公布延遲，避免前視偏誤）。
6. **美股隔夜／台指期夜盤屬於曝險控制。** T20 等指出美股領先台股，而且影響集中在開盤；這比較適合用來調整現金比例或決定是否延後換股，而不是個股選擇。
7. **注意事項：**
   - **發表偏誤與多重檢定**：依 G11，新因子應要求較高的統計門檻（t ≈ 3），且同時測試的因子數量要記錄下來。
   - **大型股 vs. 小型股**：多數異常（Amihud 非流動性、特質波動）在小型股較強（G3、G5）；本宇宙為前 150 大，預期效果會打折。
   - **持有期不匹配**：大多數文獻為月頻、多空、持有 1–12 個月；本專案為只做多、24 交易日、低週轉。多空價差不能直接換算為只做多的超額報酬。
   - **成本**：來回成本約 0.585%（0.1425%×2 + 0.3%），對 24 天視窗而言，任何高週轉因子（短期反轉、日頻法人流量）都可能被成本吃掉。
   - **時效與資料老舊**：多數台灣法人文獻資料止於 2003–2010，市場結構（外資比重、ETF、當沖）已改變。
   - **學位論文證據力**：T3–T5、T9、T18、T19 為學位論文，未經同儕審查。
   - **前視偏誤**：月營收需以實際公布日期（而非所屬月份）對齊；法人資料需以盤後公布時點對齊。

### 各因子所需資料對照

| 候選因子 | 所需資料 | 目前是否已有 |
|---|---|---|
| 營收加速度、連續成長月數、YoY 穩定度、營收創新高 | 月營收 + 公布日 | 有 |
| 未預期營收（MSURGE 類） | 月營收歷史（建立預期模型） | 有 |
| 外資／投信／自營 5D、20D 淨買（正規化） | 三大法人買賣超 + 成交金額 | 有 |
| 動能 20D/60D、相對強弱、52 週高距離、均線距離 | 日收盤價（需還原權息） | 有（需配合 corporate actions 還原） |
| 波動、下行波動、beta、特質波動 | 日報酬 + 市場指數 | 有 |
| 週轉率、Amihud、異常成交量 | 日成交量／金額；週轉率另需流通股數 | 部分（流通股數 unverified） |
| 重大訊息事件 | MOPS 重大訊息 | 有（需分類／文字處理） |
| 市場廣度、美股隔夜、SOX、TSM ADR、台指期夜盤、USD/TWD | 指數與匯率資料 | 美股隔夜與夜盤有；SOX、TSM ADR、USD/TWD 是否已存 unverified |
| ROE、ROA、毛利率、EPS 成長、PE、PB、PEG、EV/EBITDA、FCF yield | 季報、股本、市值歷史 | **沒有** |

---

## 4. Search log（搜尋紀錄）

WebSearch（standard mode）：
1. Taiwan monthly sales revenue announcement stock returns drift
2. foreign investors trading Taiwan stock market returns predict
3. momentum reversal Taiwan stock market study
4. George Hwang 52-week high and momentum investing Journal of Finance
5. "Taiwan" foreign investors "positively predict future returns" large size low book-to-market momentum
6. Lin Pacific-Basin Finance Journal 2016 momentum Taiwan market states transitions overconfidence
7. Chen Jegadeesh Wermers mutual fund / Taiwan investment trust herding stock returns
8. Ang Hodrick Xing Zhang cross-section of volatility and expected returns idiosyncratic
9. Hung Lu Lee 2010 "Mutual fund herding" Taiwan Pacific-Basin Finance Journal
10. Amihud 2002 illiquidity and stock returns cross-section time-series effects
11. Novy-Marx "The other side of value" gross profitability premium
12. Jegadeesh Titman 1993 Returns to buying winners and selling losers
13. Frazzini Pedersen Betting against beta Journal of Financial Economics
14. Jegadeesh Livnat revenue surprises and stock returns
15. Gervais Kaniel Mingelgrin high-volume return premium
16. 52-week high momentum Taiwan stock market
17. US stock market overnight spillover Taiwan stock returns Nasdaq lead
18. low volatility anomaly Taiwan stock market idiosyncratic volatility returns
19. Taiwan monthly revenue momentum stock returns "monthly sales" anomaly journal
20. Bernard Thomas 1989 post-earnings-announcement drift delayed price response
21. Asness Frazzini Pedersen "Quality minus junk"
22. Harvey Liu Zhu "and the cross-section of expected returns" multiple testing
23. Taiwan institutional investors trading daily stock returns foreign investment trusts dealers predictive journal
24. Taiwan stock market value profitability factor Fama-French five-factor evidence Taiwan

WebFetch（開啟核對的出處頁）：IDEAS/RePEc（T1、T13、T14、T15、T16、T10、G8）、lawdata（T2）、airiti（T3、T4、T20）、NCCU 典藏（T5、T9、T18）、Mendeley Data（T6）、淡江教師資料（T7）、vLex（T8）、交大管理學報（T11）、Portsmouth research portal（T12）、NYCU scholar（T17）、NCU 典藏（T19）。無法開啟：scholars.ncu.edu.tw（DNS 失敗，改用淡江頁面核對 T7）、ir.lib.nycu.edu.tw/handle/11536/39065（登入頁，未採用）。

未能找到／未採用：Chen-Jegadeesh-Wermers 基金持股研究（搜尋未出現原文，未列入）；台股重大訊息（MOPS）文字事件對報酬影響的期刊研究（未找到可核對來源）；台股 TAIFEX 夜盤對日盤選股的研究（未找到）。
