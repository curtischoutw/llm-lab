# 01: 用語改名，匯入的單位改叫「文件」

**What to build:** 依 `GLOSSARY.md`，把程式、CLI 說明、CLI 輸出、匯入報告、Python API 與測試名稱裡指「匯入單位」的「PDF」改成「文件」（document）。這張不改任何行為：仍然只接受 PDF，只有名稱和文字改變。之後的 tickets 才能在統一的用語上加新格式，不會把改名和新功能混在同一個 diff 裡。

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Python API：`Session.ingest`、模組函式 `ingest` 的參數改名為 `documents`；匯入報告的欄位 `pdf` 改名為 `document`。不保留舊名稱，也不加相容層。
- [ ] CLI 的說明文字與輸出裡，指匯入單位的「PDF」改成「文件」。「只接受 PDF」這類描述格式的句子維持原意，等 ticket 02 改行為時再改。
- [ ] 程式與測試裡指匯入單位的變數名、函式名、測試名稱一併改名；只指 PDF 這一種格式的地方保留「PDF」。
- [ ] 既有測試只改用語，不改斷言的意思；主測試套件與下載腳本的測試全綠，貼出實際輸出。
- [ ] README、架構文件、範例裡出現的 Python API 名稱（例如 `ingest(pdfs)`、`report.pdf`）跟著改。
- [ ] 文字符合使用者的寫作規則。
