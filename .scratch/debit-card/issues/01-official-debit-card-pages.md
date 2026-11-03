# 01: 官網簽帳金融卡卡片頁

**What to build:** 使用者執行台新下載腳本時，除了信用卡，也會下載官網簽帳金融卡專區的 5 張卡片頁：Visa金融卡、元氣Visa金融卡、財富管理Visa金融卡、勞動保障卡、蝴蝶悠遊Debit卡。專區列表上的群組落地頁只有一段 JS 轉址，腳本從轉址目標找到真正的卡片頁（`card01/` 或 `card001/`），用和信用卡卡片頁相同的方式（取主內容區、Chrome 列印）轉成文件。金融卡文件的本地名稱加 `debit_` 前綴，所以和同編號的信用卡卡片頁（cg003、cg008）不撞名。更新模式（`--update`）對這個類別也有效。這張也定下金融卡新類別的命名方式，02、03 照著用（spec：`.scratch/debit-card/spec.md`「下載腳本」，盤點事實見 Further Notes）。

**Blocked by:** 增量更新（`.scratch/incremental-update/`）推上 main 之後才開工，從那時的 main 開分支（spec 外的前置條件，grill Q18）。

**Status:** resolved

- [x] 從簽帳金融卡專區列表找到 5 張卡的群組落地頁，依落地頁的轉址目標下載 `card01/` 或 `card001/` 的卡片頁；不執行 JS。
- [x] 轉址目標的相對網址以落地頁為基準解析；目標不在官網網域、或不在同一個 `payment/cgXXX/` 底下時，當成找不到轉址目標。
- [x] 落地頁找不到轉址目標或請求失敗時，那一張記成失敗並寫明原因，其他卡照常；更新模式下這次整個類別不判斷下架，已下載的那張不會被搬走。
- [x] 資料夾與本地名稱照 spec「下載腳本」的類別表：`debit_cards/`、`debit_card_cgXXX_card01`（或 `card001`）；同編號的信用卡卡片頁與金融卡卡片頁同時存在、互不覆寫。下載清單照現有欄位記錄。
- [x] 更新模式：內容沒變不重寫、主內容區變了才重新轉檔、列表上消失的卡片頁搬到 `_meta/removed/<日期>/`，和信用卡卡片頁相同；列表頁解析出 0 張而本地有檔案時，這次不判斷下架。
- [x] 測試沿用下載腳本子行程＋假 HTTP server、假 Chrome 的縫，涵蓋 `card01/` 與 `card001/` 兩種轉址、相對與絕對網址、目標不在同一個群組底下、找不到轉址目標時不判斷下架、撞名；現有測試全綠。
- [x] 下載腳本的模組說明與 README 第 2 節寫明金融卡類別，以及下載資料夾雖然叫 taishin_credit_card、裡面也有金融卡。

## 實作結果（2026-11-03）

**做了什麼**

- `scripts/fetch_taishin.py`：新增類別「金融卡卡片頁」（`DEBIT_CARDS`），排在 `CATEGORIES` 最後，也加進 `REMOVAL_CATEGORIES`。資料夾 `debit_cards/`、本地名稱 `debit_card_cgXXX_card01`（或 `card001`），格式 PDF，其餘（取 `#centercontainer`、Chrome 列印、更新模式的比對與下架）沿用卡片頁的 `web_page_producer`／`web_page_refresher`。
- 新增 `collect_debit_cards`：專區列表頁（`payment/`）找 `payment/cgXXX/` 落地頁，每個落地頁請求一次，用 `find_redirect_target` 讀 `location.replace`（不執行 JS）。轉址目標以落地頁為基準解析，協定與網域要和落地頁相同，路徑要是同一個 `payment/cgXXX/` 底下的一層，否則當成找不到轉址目標、目標不請求。
- 單一落地頁失敗的紀錄放進新的 `Run.collect_failures`（類別名稱對清單紀錄）；`main` 把它們加進清單，並在更新模式下讓該類別這次不搬任何檔案（stderr 寫明，結束碼 1）。列表頁解析出 0 張而本地有檔案時，沿用 `main` 既有的 0 筆保護。
- `scripts/test_fetch_taishin.py`：新增 20 個測試（`DebitCardPageTests` 1、`DebitCardRedirectTests` 7、`DebitCardNamingTests` 4、`DebitCardUpdateModeTests` 8）和假頁面／`serve_debit_cards`。`setUp` 預設登記一個沒有任何卡的專區列表頁，所以現有測試多了 1 個請求：8 處請求清單斷言加上 `DEBIT_LIST_PATH`，6 處請求數量斷言各加 1（13→14、15→16、16→17）。這些是請求清單與數量的預期值，沒有放寬任何判斷條件。
- 模組說明（兩個檔）與 README 第 2 節：寫明金融卡類別、資料夾雖然叫 `taishin_credit_card` 也有金融卡、`debit_` 前綴的理由、轉址規則、落地頁失敗時不判斷下架。

**紅燈輸出**

第一個測試（`DebitCardPageTests`，腳本還沒有金融卡類別時）：

```
AssertionError: Lists differ: ['_meta/manifest.jsonl'] != ['_meta/html/debit_card_cg001_card01.html', ... 'debit_cards/debit_card_cg006_card001.pdf']
Second list contains 6 additional elements.
Ran 1 test in 0.937s
FAILED (failures=1)
```

其餘 19 個測試是實作完成後才補的（沒有逐個先看紅燈）。補驗證的方式是對腳本做 5 種破壞，確認對應測試會變紅：

| 破壞 | 變紅的測試 |
|---|---|
| 不檢查「同一個 cgXXX」 | `test_redirect_target_outside_the_same_group_…`（1 個） |
| 不檢查協定與網域 | `test_redirect_target_outside_the_official_domain_…`（1 個） |
| 本地名稱前綴 `debit_card` 改成 `card` | `DebitCardNamingTests` 2 個（撞名、清單） |
| 落地頁有失敗時仍判斷下架 | `…landing_page_request_failed_is_not_moved`、`…without_a_redirect_target_blocks_removal…`（2 個） |
| 金融卡類別不在 `REMOVAL_CATEGORIES` | `DebitCardUpdateModeTests` 4 個 |

驗證中發現 `…without_a_redirect_target_blocks_removal…` 原本的情境（只有一張卡）會被 0 筆保護擋下，破壞「落地頁有失敗時仍判斷下架」時不會變紅；改成 3 張卡（一張落地頁無轉址、一張正常、一張從列表消失）後才擋得住。

**最後一次測試輸出**

- 下載腳本三個測試檔（`scripts/test_fetch_papers.py scripts/test_fetch_documents.py scripts/test_fetch_taishin.py`）：`Ran 241 tests in 359.449s`，`OK`（原 221 個加 20 個新測試）。
- 主測試套件（`python -m unittest`）：`Ran 262 tests in 1174.313s`，`OK`。這張沒有動 `rag_lab`。
- 第一次跑下載腳本測試套件有 13 個失敗，原因都是多了專區列表頁的請求（上面 14 處預期值），不是行為改變；改預期值後第二次全綠。

**沒做到或有疑慮**

- 沒有對真的官網請求，所以沒有驗證真實落地頁的轉址解析。用 2026-11-02 盤點存的真實 HTML 檢查過：`cg001`、`cg003`、`cg006`、`cg008` 落地頁各有 1 個 `location.replace`，`payment/` 列表頁有 5 個 `payment/cgXXX/` 連結。
- 不加 `--update` 而本地已有文件時，每個落地頁仍要請求一次（名稱取決於轉址目標），所以略過的卡有 1 個落地頁請求。
- 失敗紀錄的檔名是 `debit_card_cgXXX`（沒有卡片編號與副檔名），因為轉址目標不明。

**ASSUMPTION**

- `location.replace` 取整頁第一個，不限定在主內容區內。
- 落地頁失敗紀錄的 url 是落地頁網址、檔名是 `debit_card_cgXXX`。
- 轉址目標必須是 `payment/cgXXX/<一段>/`（一層），不限定是 `card01`、`card001`；本地名稱取最後一段。
- 轉址目標從 `card01/` 改成 `card001/` 時，舊名稱算下架、新名稱算新增（spec 已定）。
