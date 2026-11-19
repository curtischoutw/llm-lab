"""Settings 讀環境變數的行為：KB_LANGUAGE 與 KB_ENTITY_TYPES（缺少、空值、逗號分隔解析）。

為什麼存在：這兩個欄位是 ticket rag-optimization 03 新增的必填設定，解析規則（去空白、空項目中止）
不適合只靠 CLI 子行程測；這裡直接在行程內呼叫 get_settings，觀察回傳的 Settings 與 ConfigError。

關鍵設計決策：
- 每個測試用 patch.dict(clear=True) 換上一份完整的有效環境，並在前後清掉 get_settings 的快取；
  rag_lab.config.load_dotenv 換成空操作：get_settings 會往上找 .env（含開發者的 .env）把不存在的變數補回來，
  不換掉的話「欄位不存在」的結果取決於開發者的 .env。
- 期望值是 spec 給的字面值，不從 rag_lab 取值。

Dependencies: 標準函式庫。
"""

import os
import unittest
from unittest import mock

from rag_lab.config import ConfigError, get_settings
from tests.test_cli import KB_ENTITY_TYPES, valid_env

SPEC_ENTITY_TYPES = (
    "卡片",
    "權益",
    "回饋方案",
    "回饋規則",
    "費用",
    "約定條款",
    "活動",
    "商店或通路",
    "支付工具",
    "機構",
)


class KnowledgeBaseSettingsTest(unittest.TestCase):
    def settings(self, **overrides: str):
        """以有效基準環境加上覆蓋值呼叫 get_settings。

        Args:
            **overrides: 覆蓋的環境變數。

        Returns:
            Settings。
        """
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        with mock.patch.dict(os.environ, {**valid_env(), **overrides}, clear=True), mock.patch("rag_lab.config.load_dotenv"):
            return get_settings()

    def test_language_and_entity_types_come_from_the_environment(self):
        settings = self.settings()
        self.assertEqual(settings.kb_language, "Traditional Chinese")
        self.assertEqual(settings.kb_entity_types, SPEC_ENTITY_TYPES)
        self.assertEqual(KB_ENTITY_TYPES, ",".join(SPEC_ENTITY_TYPES))

    def test_entity_types_are_trimmed_around_each_item(self):
        settings = self.settings(KB_ENTITY_TYPES="  卡片 , 權益\t,費用  ")
        self.assertEqual(settings.kb_entity_types, ("卡片", "權益", "費用"))

    def test_a_single_entity_type_is_valid(self):
        self.assertEqual(self.settings(KB_ENTITY_TYPES="卡片").kb_entity_types, ("卡片",))

    def test_missing_or_blank_fields_abort_with_the_field_name(self):
        for field in ("KB_LANGUAGE", "KB_ENTITY_TYPES"):
            for blank in ("", "   "):
                with self.subTest(field=field, value=blank):
                    with self.assertRaises(ConfigError) as caught:
                        self.settings(**{field: blank})
                    self.assertEqual(caught.exception.field, field)
                    self.assertIn("缺少必要環境變數", str(caught.exception))

    def test_a_field_absent_from_the_environment_aborts(self):
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        for field in ("KB_LANGUAGE", "KB_ENTITY_TYPES"):
            with self.subTest(field=field):
                env = valid_env()
                del env[field]
                with (
                    mock.patch.dict(os.environ, env, clear=True),
                    mock.patch("rag_lab.config.load_dotenv"),
                    self.assertRaises(ConfigError) as caught,
                ):
                    get_settings()
                self.assertEqual(caught.exception.field, field)

    def test_empty_items_in_entity_types_abort(self):
        for bad in (",", "卡片,,權益", "卡片,", ",卡片", "卡片, ,權益"):
            with self.subTest(value=bad):
                with self.assertRaises(ConfigError) as caught:
                    self.settings(KB_ENTITY_TYPES=bad)
                self.assertEqual(caught.exception.field, "KB_ENTITY_TYPES")


if __name__ == "__main__":
    unittest.main()
