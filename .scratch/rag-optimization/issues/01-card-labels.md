# 01: 產生卡片標籤並交使用者抽查

**What to build:** 寫一支腳本，替 `data/taishin_credit_card/` 底下每份文件產生卡片標籤（卡別＋適用卡片），輸出標籤檔，交使用者抽查（spec：`.scratch/rag-optimization/spec.md`「卡片標籤」；GLOSSARY「卡片標籤」）。

**Blocked by:** 無

**Status:** ready-for-agent

- [ ] 腳本放在 `scripts/`，檔頭照 code standards 寫清楚規則。輸入是 manifest（`_meta/manifest.jsonl`）、類別資料夾、`_meta/html` 的頁面快照，不連網。
- [ ] 卡片頁（`cards/`、`debit_cards/`、`richart/`）：網址的 `cgXXX` 或頁面標題對應卡名，建立已知卡名清單（信用卡、金融卡分開）。
- [ ] 其他有頁面快照的文件：在頁面內文比對已知卡名清單。
- [ ] 沒有頁面快照的 52 份（下載、權益附件、活動圖片、金融卡約定條款 PDF）：查 manifest 與 `scripts/fetch_taishin.py` 有沒有記錄它從哪個頁面連過去，有就沿用那個頁面的標籤，沒有就列進待人工確認清單。比對到全部同卡別的卡時標「全部信用卡」／「全部金融卡」。比對不到時不猜，列進待人工確認清單。
- [ ] 每份文件輸出：卡別、適用卡片清單、簡短卡名（檔名用：一張卡寫卡名，多張寫「多卡」，全部寫「全部」）、標頭文字（卡別＋適用卡片；超過 150 token 時照 spec 改寫）。
- [ ] 標籤檔寫到 `data/taishin_credit_card/_meta/document_labels.json`，key 是相對於 `data/taishin_credit_card/` 的路徑。manifest 每一筆有實體檔的文件都要有一筆。
- [ ] 產生抽查報告（`output/rag_opt/labels_review.md`）：各類別資料夾的文件數、每種卡別與「多卡／全部」的數量、待人工確認清單，再從每個類別資料夾各抽 3 份列出檔名、頁面標題與標籤。
- [ ] 停下來交使用者抽查。使用者修正的項目直接改標籤檔，修正規則要回寫腳本，讓重跑時得到相同結果。
