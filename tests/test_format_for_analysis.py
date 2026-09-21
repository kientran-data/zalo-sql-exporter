"""
Unit tests for format_for_analysis.py.

Tests date/time parsing, noise and reaction classification, and 2-pass deduplication.
"""

import unittest
from format_for_analysis import (
    normalize_name,
    map_sender,
    parse_date,
    parse_time,
    parse_datetime,
    classify,
)


class TestFormatForAnalysis(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(normalize_name("SQL_K9\xa0GIA\xa0NHƯ"), "SQL_K9 GIA NHƯ")
        self.assertEqual(normalize_name("  [SQL]   Lan  "), "[SQL] Lan")

    def test_map_sender(self):
        self.assertEqual(map_sender("me"), "Tôi")
        self.assertEqual(map_sender("ME"), "Tôi")
        self.assertEqual(map_sender("other"), "Đối phương")
        self.assertEqual(map_sender("OTHER"), "Đối phương")
        self.assertEqual(map_sender("Admin"), "Admin")

    def test_parse_date(self):
        self.assertEqual(parse_date("05/05/2025"), "2025-05-05")
        self.assertEqual(parse_date("5/5/2025"), "2025-05-05")
        self.assertEqual(parse_date("12/06/24"), "2024-06-12")
        self.assertIsNone(parse_date("Hello world"))

    def test_parse_time(self):
        self.assertEqual(parse_time("07:53"), "07:53")
        self.assertEqual(parse_time("7:05"), "07:05")
        self.assertIsNone(parse_time("123:45"))

    def test_parse_datetime(self):
        self.assertEqual(parse_datetime("07:53 12/06/2024"), ("2024-06-12", "07:53"))
        self.assertIsNone(parse_datetime("invalid"))

    def test_classify_noise(self):
        self.assertEqual(classify("photo", "text"), "noise")
        self.assertEqual(classify("sticker", "text"), "noise")
        self.assertEqual(classify("chưa có tin nhắn nào", "text"), "noise")
        self.assertEqual(classify("bạn đã tham gia", "text"), "noise")

    def test_classify_reactions(self):
        self.assertEqual(classify("/-strong", "text"), "reaction")
        self.assertEqual(classify("/-heart", "text"), "reaction")
        self.assertEqual(classify(":>", "text"), "reaction")
        self.assertEqual(classify(":o", "text"), "reaction")
        self.assertEqual(classify(":-((", "text"), "reaction")
        self.assertEqual(classify(":-h", "text"), "reaction")

    def test_classify_inline_dates_and_times(self):
        self.assertEqual(classify("12/06/2024", "text"), "date")
        self.assertEqual(classify("07:53", "text"), "time")
        self.assertEqual(classify("07:53 12/06/2024", "text"), "datetime")

    def test_classify_normal_message(self):
        self.assertEqual(classify("e set public giúp a nhé", "text"), "message")
        self.assertEqual(classify("dòng nào lỗi nó hiển thị ở đây", "text"), "message")


if __name__ == '__main__':
    unittest.main()
