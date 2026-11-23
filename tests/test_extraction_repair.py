"""rag_lab.extraction_repair 的測試：修補 LLM 抽取輸出裡 LightRAG 會整筆丟掉的紀錄。

為什麼存在：Gemma 的抽取輸出常把分隔符號寫壞、漏掉 keywords 欄位，LightRAG 1.4.16 的嚴格解析器會把整筆紀錄丟掉
（重匯後的快取裡 1,904 筆）。修補要能不啟動任何服務就驗證，而且不能改到原本就解析得了的紀錄。

關鍵設計決策：
- 錯誤樣本都取自重匯後 LLM 快取裡真實出現的紀錄（rag_storage/kv_store_llm_response_cache.json，2026-11-23）。
- 純函式（repair_extraction_output）只看輸入輸出的文字；掛到 LightRAG 的效果另用 LightRAG 自己的
  _process_extraction_result 驗證，看最後解析出的實體與關係。

Dependencies: lightrag。
"""

import asyncio
import unittest
from importlib.metadata import version

import lightrag.operate

from rag_lab.extraction_repair import MISSING_KEYWORDS, REPAIRED_LIGHTRAG_VERSION, install, repair_extraction_output

TD = "<|#|>"


def parse(text: str) -> tuple[dict, dict]:
    """用 LightRAG 目前的 _process_extraction_result 解析一段抽取輸出。"""
    return asyncio.run(lightrag.operate._process_extraction_result(text, "chunk-test", 0))


def repaired(line: str) -> str:
    return repair_extraction_output(line + "\n<|COMPLETE|>").split("\n")[0]


class UntouchedRecordsTest(unittest.TestCase):
    def test_records_lightrag_already_accepts_are_left_exactly_as_they_are(self):
        text = "\n".join(
            [
                f"entity{TD}台新Richart卡{TD}卡片{TD}台新銀行發行的信用卡。",
                f"relation{TD}台新Richart卡{TD}台新Point{TD}回饋{TD}刷卡可獲得台新Point。",
                "<|COMPLETE|>",
            ]
        )
        self.assertEqual(repair_extraction_output(text), text)

    def test_loop_garbage_is_left_for_lightrag_to_drop(self):
        line = "entity<|luk-e-id-7e3f-placeholder-placeholder-placeholder"
        self.assertEqual(repaired(line), line)

    def test_a_line_holding_several_records_is_left_for_lightrag_to_split(self):
        line = f"entity{TD}A卡{TD}卡片{TD}一張卡。{TD}entity{TD}B卡{TD}卡片{TD}另一張卡。"
        self.assertEqual(repaired(line), line)

    def test_a_name_that_still_carries_a_broken_delimiter_is_not_repaired(self):
        line = f"relation{TD}正卡持卡人<|錯台新銀行信用卡{TD}user management{TD}正卡持卡人擁有管理權限。"
        self.assertEqual(repaired(line), line)


class BrokenHeadTest(unittest.TestCase):
    def test_a_broken_first_delimiter_followed_by_the_name_keeps_the_name(self):
        for line, name in [
            (f"entity<|換算總費用年百分率{TD}費用{TD}分期利率轉換後的成本計算標準。", "換算總費用年百分率"),
            (f"entity<|：#|>Gogoro Smart Points{TD}回饋方案{TD}本活動之點數回饋形式。", "Gogoro Smart Points"),
            (f"entity<dt_type=卡片>Gogoro Wallet{TD}支付工具{TD}可綁定聯名卡的數位支付工具。", "Gogoro Wallet"),
            (f"entity|#|Gogoro Smart Points{TD}權益{TD}正附卡持卡人獲得之點數。", "Gogoro Smart Points"),
        ]:
            with self.subTest(line=line):
                self.assertEqual(repaired(line).split(TD)[:2], ["entity", name])

    def test_an_ascii_tag_in_place_of_the_first_delimiter_is_dropped(self):
        for line in [
            f"entity<to_type_not_provided>台新銀行{TD}機構{TD}提供信用卡服務的金融機構。",
            f"relation<|hold_type{TD}正卡及附卡申請人{TD}身分證明文件{TD}申請人需提供身分證件。",
        ]:
            with self.subTest(line=line):
                fields = repaired(line).split(TD)
                self.assertNotIn("type", fields[1])
                self.assertIn(fields[0], ("entity", "relation"))

    def test_stray_characters_of_other_scripts_before_the_name_are_dropped(self):
        fields = repaired(f"relation<|도台新Richart卡{TD}新客禮遇{TD}適用卡片,新客優惠{TD}台新Richart卡用戶可享加碼贈送。").split(TD)
        self.assertEqual(fields[:3], ["relation", "台新Richart卡", "新客禮遇"])

    def test_an_ascii_label_with_a_colon_before_the_name_is_dropped(self):
        fields = repaired(f"entity<|ebb_name: 泉思雙人套房平日一泊二食{TD}回饋方案{TD}包含住宿一晚的優惠方案。").split(TD)
        self.assertEqual(fields[1], "泉思雙人套房平日一泊二食")

    def test_an_entity_whose_type_field_holds_a_long_name_is_not_repaired(self):
        # 模型把類型寫在名稱的位置：修了會得到名稱「週益/回饋方案」、類型「東南旅遊指定行程優惠」
        line = f"entity<|週益/回饋方案{TD}東南旅遊指定行程優惠{TD}包含指定團體行程最高5%回饋。"
        self.assertEqual(repaired(line), line)

    def test_a_record_with_no_head_is_typed_by_its_field_count(self):
        entity = repaired(f"{TD}高雄機場(KHH){TD}商店或通路{TD}服務範圍內的機場之一。")
        relation = repaired(f"{TD}卓富無限卡{TD}海外刷卡全攻略{TD}案例應用{TD}用於展示海外刷卡策略的卡片。")
        self.assertEqual(entity.split(TD)[0], "entity")
        self.assertEqual(relation.split(TD), ["relation", "卓富無限卡", "海外刷卡全攻略", "案例應用", "用於展示海外刷卡策略的卡片。"])


class BrokenFieldsTest(unittest.TestCase):
    def test_a_broken_delimiter_between_source_and_target_splits_them(self):
        fields = repaired(f"relation{TD}訂房優惠活動<|도>Trip.com{TD}活動對象,通路參與{TD}Trip.com 是指定平台之一。").split(TD)
        self.assertEqual(fields[:4], ["relation", "訂房優惠活動", "Trip.com", "活動對象,通路參與"])

    def test_keywords_glued_to_the_description_with_a_comma_are_split_off(self):
        fields = repaired(f"relation{TD}台新銀行{TD}台新Richart卡{TD}發行關係,台新銀行為台新Richart卡的發卡機構。").split(TD)
        self.assertEqual(fields, ["relation", "台新銀行", "台新Richart卡", "發行關係", "台新銀行為台新Richart卡的發卡機構。"])

    def test_a_relation_with_only_a_description_gets_placeholder_keywords(self):
        # LightRAG 切欄位會丟掉空欄位，所以不能補空字串
        fields = repaired(f"relation{TD}上班族{TD}財力證明文件{TD}上班族需提供薪資單或勞健保資料作為財力證明。").split(TD)
        self.assertEqual(fields, ["relation", "上班族", "財力證明文件", MISSING_KEYWORDS, "上班族需提供薪資單或勞健保資料作為財力證明。"])

    def test_a_bare_hash_delimiter_inside_a_field_is_restored(self):
        fields = repaired(f"relation{TD}翱翔鈦金卡{TD}全鋒汽車{TD}權益, 旅遊優惠|#|持卡人在全鋒汽車享有接送優惠。").split(TD)
        self.assertEqual(fields[3:], ["權益, 旅遊優惠", "持卡人在全鋒汽車享有接送優惠。"])

    def test_an_entity_with_relation_fields_becomes_a_relation(self):
        fields = repaired(f"entity{TD}台新銀行{TD}遠傳電信股份有限公司{TD}約定條款{TD}兩家機構具有協作關係。").split(TD)
        self.assertEqual(fields[0], "relation")

    def test_noise_around_the_entity_type_is_removed(self):
        for line, entity_type in [
            (f"entity{TD}Gogoro 夥伴商家{TD}(Other){TD}可享加碼回饋之商家。", "Other"),
            (f"entity{TD}捷絲旅{TD}商店或通路<block_type=商店或通路>{TD}適用加碼回饋之飯店。", "商店或通路"),
            (f"entity{TD}全程險{TD}權益<|도| much-needed-info-placeholder{TD}最高 NT$1,000 萬的保障。", "權益"),
        ]:
            with self.subTest(line=line):
                self.assertEqual(repaired(line).split(TD)[2], entity_type)


class InstalledIntoLightRAGTest(unittest.TestCase):
    def test_lightrag_parses_the_repaired_records_once_installed(self):
        install()
        install()  # 裝兩次不會包兩層
        nodes, edges = parse(
            "\n".join(
                [
                    f"entity<|換算總費用年百分率{TD}費用{TD}分期利率轉換後的成本計算標準。",
                    f"relation{TD}台新銀行{TD}台新Richart卡{TD}發行關係,台新銀行為發卡機構。",
                    "<|COMPLETE|>",
                ]
            )
        )
        self.assertIn("換算總費用年百分率", nodes)
        self.assertEqual(edges[("台新銀行", "台新Richart卡")][0]["keywords"], "發行關係")

    def test_the_hook_was_written_for_the_installed_lightrag_version(self):
        # 升級 lightrag-hku 後這個測試會失敗：確認 _process_extraction_result 的呼叫方式沒變，再更新 REPAIRED_LIGHTRAG_VERSION
        self.assertEqual(version("lightrag-hku"), REPAIRED_LIGHTRAG_VERSION)


if __name__ == "__main__":
    unittest.main()
