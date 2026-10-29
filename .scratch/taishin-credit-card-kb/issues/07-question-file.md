# 07: 寫題目檔

**What to build:** 一份 20 題的題目檔，參考答案依下載當天的原文撰寫，涵蓋切換、權益、回饋規則、費用、約定條款、優惠活動與跨卡比較，讓使用者能判斷知識庫答得對不對。

**Blocked by:** 06（參考答案要依實際下載的原文撰寫）

**Status:** resolved

- [x] 新增題目檔並納入版本控管，欄位沿用現有格式：`id`、`question`、`reference`、`type`、`source`。
- [x] 類別寫在 `id` 前綴，題數至少為：`switch-` 4、`benefit-` 2、`rule-` 2、`fee-` 2、`terms-` 2、`offer-` 2、`cross-` 2，合計 20。
- [x] 切換的 4 題涵蓋：有哪些回饋方案、什麼時候能切換與限制、切換後當天消費怎麼算、哪些舊卡適用。
- [x] `type` 沿用現有的四個值，跨卡比較題用 `cross-paper`。`source` 填本地檔名，多份時用逗號分隔。
- [x] 參考答案依原文撰寫；原文有錯字或前後不一致時，照原文寫並加註。
- [x] 題目檔通過 `eval` 的格式驗證（用不需要模型的方式確認，例如讀檔驗證的測試路徑，或模型 server 關閉時的錯誤訊息確認不是格式錯誤）。
- [x] 文字符合使用者的寫作規則。

## 實作結果（2026-10-30）

做了什麼：
- 新增 `eval/questions.taishin.jsonl`，20 題，欄位沿用 `eval/questions.formats.jsonl`。
- 題數：`switch-` 4、`benefit-` 3、`rule-` 3、`fee-` 3、`terms-` 2、`offer-` 3、`cross-` 2。超出最低題數的 4 題（benefit、rule、fee、offer 各多 1 題）是為了湊滿 20 題。
- `type`：`text` 14、`table` 4、`cross-paper` 2、`figure` 0。`table` 用在答案來自表格查值的題目（switch-01、benefit-01、benefit-02、benefit-03）。沒有圖片題：答案都在 PDF／docx 的文字層裡。
- 參考答案依 2026-10-30 下載、匯入知識庫的那份 PDF／docx 撰寫（本地檔名見 `source`），不是原始 HTML。PDF 用 pypdfium2 抽文字，docx 讀 `word/document.xml`；分析腳本放在 `/Users/curtis/.claude/jobs/db9cfed9/tmp/t07/`。
- 驗證每題的「來源與原文片段」：`build.py` 把下表的每個片段在對應檔案的抽出文字（去掉空白後）逐一比對，36 個片段全部找得到，長度都在 30 字內。

驗證輸出：
- 讀檔驗證（不需要模型，直接呼叫 `rag_lab.evaluation.load_questions`，與 `eval` 命令讀檔時走同一條路徑）：
  ```
  loaded 20
  Counter({'switch': 4, 'benefit': 3, 'rule': 3, 'fee': 3, 'offer': 3, 'terms': 2, 'cross': 2})
  Counter({'text': 14, 'table': 4, 'cross-paper': 2})
  ```
  對照組（type 寫成 `bogus`）：`QuestionFileError 第 1 行：欄位 type：'bogus' 不合法（可用值：text, figure, table, cross-paper）`，所以驗證確實會擋格式錯誤。
- 沒有執行 `python -m rag_lab eval`：它通過讀檔驗證後會呼叫 `get_settings()` 並連模型端點，而主 repo 正在匯入、有 server 在跑，不能讓查詢打到它。
- `python -m unittest tests.test_cli`：`Ran 8 tests ... OK`。沒有改程式碼，所以沒有跑完整測試套件。

來源與原文片段（題號、來源檔名、原文片段）：

| 題號 | 來源檔名 | 原文片段 |
|---|---|---|
| switch-01 | card_cg047_card001.pdf | 新核卡預設「天天刷」 |
| switch-02 | card_cg047_card001.pdf | 每日23:59前轉換，每日限轉換一次 |
| switch-03 | card_cg047_card001.pdf | 計算當日零時起之逐筆交易回饋 |
| switch-04 | card_cg047_card001.pdf | 皆已更名為台新Richart卡 |
| switch-04 | card_cg012_card0001.pdf | 如欲查看/申辦太陽卡切換刷權益 |
| benefit-01 | rights_road-rescue_right0401.docx | 每卡每年最多使用6次 |
| benefit-02 | rights_insurance_right0202.docx | 適用卡別：卓富無限卡 |
| benefit-02 | rights_insurance_right0202.docx | 全部票款或百分之八十以上之團費 |
| benefit-03 | rights_oversea_right0106.docx | 金額合計達NT$16,000以上 |
| rule-01 | rights_notice_restricteditems.docx | 仍享有台新Point(信用卡)回饋，其他方式不回饋 |
| rule-01 | card_cg047_card001.pdf | 不符合指定交易 |
| rule-02 | card_cg047_card001.pdf | 自核卡日起算60天內 |
| rule-03 | card_cg047_card001.pdf | 以持卡人之永久信用額度加計NT$30萬為限 |
| rule-03 | card_cg047_card001.pdf | 將於2030/1/31清除該筆點數 |
| fee-01 | rights_notice_right0908.docx | 當期繳款發生延滯時，計付違約金NT$300 |
| fee-01 | download__115_001final.pdf | 計付違約金新臺幣 300 元 |
| fee-02 | download__115_001final.pdf | 百分之三點五加上新臺幣壹佰伍拾元計算之手續費 |
| fee-02 | download__115_001final.pdf | 交易金額百分之○．五計算之國外交易服務費 |
| fee-02 | card_cg047_card001.pdf | 免1.5%國外交易手續費 |
| fee-03 | card_cg014_card0001.pdf | 正卡NT$4,500，附卡NT$4,500 |
| fee-03 | card_cg014_card0001.pdf | 正卡、附卡依卡號分開累計累消 |
| terms-01 | download__115_001final.pdf | 自負額以新臺幣 3,000 元為上限 |
| terms-01 | download__115_001final.pdf | 並繳交掛失手續費新臺幣 200 元 |
| terms-02 | download_115001.pdf | 預計條款生效日為 2026 年 4 月 10 日 |
| terms-02 | download__115_001final.pdf | 或經 165 通報，或經其他發卡機構聯防通報者 |
| offer-01 | offer_WM_20260907090737422.pdf | 全支付綁定台新信用卡：刷滿1,300元贈全點78點 |
| offer-02 | offer_WM_20260914193622109.pdf | 單筆滿5,000元，贈500點台新Point |
| offer-02 | offer_WM_20260814165339540.pdf | 新新券10%加碼 |
| offer-03 | offer_WM_20260929134706445.pdf | 享6%台新Point(信用卡)加碼回饋(上限500點) |
| cross-01 | card_cg047_card001.pdf | 次年起使用台新電子/行動簡訊帳單且生效 |
| cross-01 | card_cg038_card001.pdf | 使用台新電子/行動帳單且生效(需開卡) |
| cross-01 | card_cg042_card001.pdf | 持卡年度累積消費滿NT$6萬 |
| cross-02 | card_cg047_card001.pdf | 海外消費(含實體及線上、歐洲國家交易) |
| cross-02 | card_cg039_card001.pdf | 國外消費享2.5%外幣回饋無上限 |
| cross-02 | card_cg009_card001.pdf | 海外消費 1.5% 總上限2,500元 |
| cross-02 | rights_notice_restricteditems.docx | 雙幣信用卡、昇恆昌無限卡 |

原文有疑問或前後不一致、已在參考答案加註的地方：
- rule-03：台新Point 效期兩年，原文範例「生日 12 月、2026/7/24 獲得 100 點，將於 2030/1/31 清除」，從 2026/7/24 起算兩年是 2028/7/24，與範例差一年半，原文沒有說明換算規則。參考答案照範例寫並加註。
- fee-01：`rights_notice_right0908.docx` 同一頁有兩段循環利息文字，一段是「年利率2.88%~15%」（13 等級），另一段是「年利率6.75%~45%」（10 等級，且未付清最低應繳金額時得調整為 15%）。約定條款寫上限 15%。原文沒有標示哪一段是舊版。
- fee-02：條款的國外交易服務費是 0.5%、國際組織費率 1%；Richart 卡頁面寫台新Pay+ 日韓交易免 1.5%。1.5% 是否為兩者相加，原文沒有寫，參考答案只註記。
- fee-03：新光三越無限卡／世界卡的免年費辦法寫「正附卡合併」，同一頁注意事項寫「正卡、附卡依卡號分開累計累消」。
- cross-02：昇恆昌御璽卡「海外消費 1.5% 總上限2,500元」，該欄表頭是「單期帳單回饋上限」，「總上限」與「單期」的關係原文沒有說明；歐洲實體商店的例外清單列「昇恆昌無限卡」而非昇恆昌御璽卡，御璽卡有沒有回饋只能由清單沒列推測。
- switch-01：頁面寫「7+1大回饋方案」並列出 8 個方案，沒有指明哪一個是「+1」。參考答案推測是 2026/7/8 才開放切換的 Chill刷，並註明原文未說明。
- 原文另有可見的錯字或不存在的日期，沒有放進題目：Richart 卡頁面的 LINE Pay 領券時間表寫「十二月：2026/11/31(一) 10:00起」（11 月沒有 31 日）、同頁「Ricahrt卡」「台新Piont(信用卡)」。

ASSUMPTION：
- 超出最低題數的 4 題分給 benefit、rule、fee、offer 各 1 題；ticket 沒有指定超出部分的分配。
- `type` 為 `table` 的 4 題是依「答案來自表格」自行歸類；`rag_lab` 只檢查值在四個之中。
- 約定條款、保險、道路救援等文件的表格在 docx／PDF 轉換後有合併儲存格（例如 `rights_oversea_right0102.docx`、`rights_oversea_right0101.docx` 的後幾列門檻欄是空白），這些題目沒有出，避免參考答案依賴合併儲存格的推斷。benefit-01 只問環球無限卡／昇恆昌無限卡那一列，benefit-02、benefit-03 的列都有完整的值。
- 參考答案只以 `source` 列出的檔案為準，沒有對照官網 HTML。
- 06 尚未結案，但下載資料已在 `data/taishin_credit_card/`，參考答案依該資料撰寫。

沒做到：
- 沒有用獨立的 agent 對參考答案做 read-back。36 個片段是程式比對過的，但答案的完整度（例如 switch-01 的各方案回饋率）只由撰寫者逐段對照原文確認。
