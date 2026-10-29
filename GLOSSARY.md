# rag-anything-lab

用 RAG-Anything 把多種格式的來源檔建成本地知識庫，並對它提問與評估檢索模式的實驗環境。

## Language

**文件**（document）：
匯入知識庫的一個來源檔，格式可以是 PDF、PPT、Word、Excel 或圖片。
_Avoid_：PDF（只用來指 PDF 這一種格式）、論文（只用來指學術論文這一類內容）、檔案

**格式**（format）：
文件的檔案類型，以副檔名判定：PDF、PPT（.ppt .pptx）、Word（.doc .docx）、Excel（.xls .xlsx）、圖片（.png .jpg .jpeg .bmp .tiff .tif .gif .webp）。
_Avoid_：類型（`type` 已用來指題目的種類）

**知識庫**（knowledge base）：
由文件建成、可供提問的圖譜與向量資料，存放在一個 `WORKING_DIR`。沒有特別說明時，指主題為 RAG 的主知識庫。
_Avoid_：索引、資料庫、rag_storage（只是預設的資料夾名稱）

**格式驗證知識庫**：
只用來確認某種格式能完整匯入與被問到的暫時性知識庫，內容可以和主知識庫的主題無關；驗證完成後只保留紀錄，知識庫本身刪除。
_Avoid_：測試知識庫（「測試」指 `python -m unittest` 的快速測試）
