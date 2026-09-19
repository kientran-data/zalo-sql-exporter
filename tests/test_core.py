"""
Unit tests for Zalo SQL Exporter.

Tests name matching, database operations, and overlap reconciliation.
"""

import os
import sys
import tempfile
import unittest

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zalo_exporter.name_matching import (
    normalize_for_match, matches_sql, is_pua_only, classify_text, is_sidebar_date,
)
from zalo_exporter.db import ExporterDB


class TestNameMatching(unittest.TestCase):
    """Validate all required name patterns match 'sql'."""

    def test_bracketed_sql(self):
        self.assertTrue(matches_sql("[SQL] Vũ Đức Thanh"))

    def test_underscore_prefix(self):
        self.assertTrue(matches_sql("SQL_Kien"))

    def test_underscore_middle(self):
        self.assertTrue(matches_sql("khach_hang_sql_1"))

    def test_bracketed_lowercase(self):
        self.assertTrue(matches_sql("[sql] Lan"))

    def test_nbsp_separated(self):
        """Zalo uses \\xa0 between name parts."""
        self.assertTrue(matches_sql("SQL_K9\xa0GIA\xa0NHƯ\xa0HÀ\xa0HÀ"))

    def test_no_match(self):
        self.assertFalse(matches_sql("Ngọc Mai"))
        self.assertFalse(matches_sql("Đức"))
        self.assertFalse(matches_sql("Tiệm Lẩu Kathy"))

    def test_normalization_preserves_vietnamese(self):
        norm = normalize_for_match("[SQL] Vũ Đức Thanh")
        self.assertIn("sql", norm)
        self.assertIn("vũ", norm)

    def test_normalization_collapses_spaces(self):
        norm = normalize_for_match("SQL_K9\xa0\xa0GIA")
        self.assertNotIn("\xa0", norm)
        self.assertNotIn("  ", norm)

    def test_pua_only(self):
        self.assertTrue(is_pua_only("\uec65"))
        self.assertTrue(is_pua_only("\uec65 \uec46"))
        self.assertFalse(is_pua_only("hello"))
        self.assertFalse(is_pua_only("\uec65 hello"))

    def test_classify_text(self):
        self.assertEqual(classify_text("24/06/24"), "date")
        self.assertEqual(classify_text("24/06/2024"), "date")
        self.assertEqual(classify_text("11:23"), "time")
        self.assertEqual(classify_text("21:40 14/06/2024"), "datetime")
        self.assertEqual(classify_text("hello"), "text")
        self.assertEqual(classify_text("ok"), "text")

    def test_sidebar_date(self):
        self.assertTrue(is_sidebar_date("24/06/24"))
        self.assertTrue(is_sidebar_date("24/06/2024"))
        self.assertFalse(is_sidebar_date("hello"))
        self.assertFalse(is_sidebar_date("SQL_K9"))


class TestDatabase(unittest.TestCase):
    """Test SQLite operations."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = ExporterDB(self.tmp.name)

    def tearDown(self):
        self.db.close()
        os.unlink(self.tmp.name)
        # Clean up WAL/SHM files
        for ext in ("-wal", "-shm"):
            p = self.tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)

    def test_create_run(self):
        run_id = self.db.create_run()
        self.assertIsNotNone(run_id)
        run = self.db.get_latest_run()
        self.assertEqual(run["run_id"], run_id)
        self.assertEqual(run["status"], "running")

    def test_add_conversation(self):
        run_id = self.db.create_run()
        conv_id = self.db.add_conversation(run_id, "SQL_Test", "sql_test")
        self.assertIsNotNone(conv_id)

        convs = self.db.get_conversations(run_id)
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["display_name"], "SQL_Test")
        self.assertEqual(convs[0]["status"], "pending")

    def test_commit_batch_and_checkpoint(self):
        run_id = self.db.create_run()
        conv_id = self.db.add_conversation(run_id, "Test", "test")

        items = [
            {"text_content": "hello", "sender": "Me", "element_type": "text"},
            {"text_content": "11:23", "sender": None, "element_type": "time"},
            {"text_content": "ok", "sender": "Other", "element_type": "text"},
        ]

        self.db.commit_batch(conv_id, 0, items)

        # Verify checkpoint
        cp = self.db.get_checkpoint(conv_id)
        self.assertEqual(cp["last_batch_number"], 0)
        self.assertEqual(cp["observation_count"], 3)

        # Verify observations
        obs = self.db.get_observations(conv_id)
        self.assertEqual(len(obs), 3)
        self.assertEqual(obs[0]["text_content"], "hello")
        self.assertEqual(obs[2]["text_content"], "ok")

    def test_commit_multiple_batches(self):
        run_id = self.db.create_run()
        conv_id = self.db.add_conversation(run_id, "Test", "test")

        self.db.commit_batch(conv_id, 0, [
            {"text_content": "msg1", "sender": "Me", "element_type": "text"},
        ])
        self.db.commit_batch(conv_id, 1, [
            {"text_content": "msg2", "sender": "Other", "element_type": "text"},
        ])

        cp = self.db.get_checkpoint(conv_id)
        self.assertEqual(cp["last_batch_number"], 1)
        self.assertEqual(cp["observation_count"], 2)

    def test_duplicate_flagging(self):
        run_id = self.db.create_run()
        conv_id = self.db.add_conversation(run_id, "Test", "test")

        self.db.commit_batch(conv_id, 0, [
            {"text_content": "hello", "sender": "Me", "element_type": "text"},
            {"text_content": "ok", "sender": "Other", "element_type": "text"},
        ])

        # Flag first item as duplicate
        self.db.flag_duplicates_in_batch(conv_id, 0, [0])

        # Excluding duplicates
        obs = self.db.get_observations(conv_id, exclude_duplicates=True)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["text_content"], "ok")

        # Including duplicates
        all_obs = self.db.get_observations(conv_id, exclude_duplicates=False)
        self.assertEqual(len(all_obs), 2)

    def test_pending_conversations(self):
        run_id = self.db.create_run()
        c1 = self.db.add_conversation(run_id, "Done", "done")
        c2 = self.db.add_conversation(run_id, "Pending", "pending")
        c3 = self.db.add_conversation(run_id, "Partial", "partial")

        self.db.update_conversation_status(c1, "completed")
        self.db.update_conversation_status(c3, "partial")

        pending = self.db.get_pending_conversations(run_id)
        self.assertEqual(len(pending), 2)  # pending + partial

    def test_crash_safety_committed_data_survives(self):
        """Verify committed batches survive a connection close/reopen."""
        run_id = self.db.create_run()
        conv_id = self.db.add_conversation(run_id, "Test", "test")

        self.db.commit_batch(conv_id, 0, [
            {"text_content": "msg1", "sender": "Me", "element_type": "text"},
        ])

        # Simulate crash: close without explicit cleanup
        self.db.close()

        # Reopen
        db2 = ExporterDB(self.tmp.name)
        obs = db2.get_observations(conv_id)
        self.assertEqual(len(obs), 1)
        self.assertEqual(obs[0]["text_content"], "msg1")

        cp = db2.get_checkpoint(conv_id)
        self.assertEqual(cp["last_batch_number"], 0)
        db2.close()


class TestOverlapReconciliation(unittest.TestCase):
    """Test the overlap detection used in extraction."""

    def _find_overlap(self, new_batch, prev_batch):
        """Replicate the overlap logic from extraction.py."""
        nf = [(m["text_content"], m["sender"]) for m in new_batch]
        pf = [(m["text_content"], m["sender"]) for m in prev_batch]
        best = 0
        limit = min(len(nf), len(pf))
        for length in range(1, limit + 1):
            if nf[-length:] == pf[:length]:
                best = length
        return best

    def _make(self, text, sender="Other"):
        return {"text_content": text, "sender": sender}

    def test_simple_overlap(self):
        prev = [self._make("a"), self._make("b"), self._make("c")]
        new = [self._make("x"), self._make("a"), self._make("b")]
        # Suffix of new [a, b] matches prefix of prev [a, b]
        self.assertEqual(self._find_overlap(new, prev), 2)

    def test_no_overlap(self):
        prev = [self._make("a"), self._make("b")]
        new = [self._make("x"), self._make("y")]
        self.assertEqual(self._find_overlap(new, prev), 0)

    def test_consecutive_ok_messages_preserved(self):
        """Two legitimate consecutive 'ok' messages must both survive."""
        prev = [self._make("ok"), self._make("ok"), self._make("c")]
        new = [self._make("x"), self._make("ok"), self._make("ok")]
        # Suffix of new [ok, ok] matches prefix of prev [ok, ok]
        overlap = self._find_overlap(new, prev)
        self.assertEqual(overlap, 2)
        # After removing overlap from new, we get [x] + prev = [x, ok, ok, c]
        result = new[:-overlap] + prev if overlap > 0 else new + prev
        texts = [m["text_content"] for m in result]
        self.assertEqual(texts, ["x", "ok", "ok", "c"])

    def test_consecutive_ok_different_senders(self):
        """ok from Me and ok from Other are distinct."""
        prev = [self._make("ok", "Other"), self._make("c")]
        new = [self._make("ok", "Me"), self._make("ok", "Other")]
        overlap = self._find_overlap(new, prev)
        self.assertEqual(overlap, 1)  # Only the last "ok Other" matches

    def test_full_overlap(self):
        """Entire new batch matches prefix of prev."""
        prev = [self._make("a"), self._make("b"), self._make("c")]
        new = [self._make("a"), self._make("b")]
        self.assertEqual(self._find_overlap(new, prev), 2)

    def test_identical_timestamps_both_ok(self):
        """Two 'ok' messages with identical timestamps in adjacent batches."""
        prev = [
            self._make("ok"), self._make("11:23"),
            self._make("ok"), self._make("11:23"),
            self._make("see you"),
        ]
        new = [
            self._make("hello"),
            self._make("ok"), self._make("11:23"),
            self._make("ok"), self._make("11:23"),
        ]
        overlap = self._find_overlap(new, prev)
        self.assertEqual(overlap, 4)  # [ok, 11:23, ok, 11:23]
        result = new[:-overlap] + prev
        texts = [m["text_content"] for m in result]
        # Should preserve both "ok" messages
        self.assertEqual(texts, ["hello", "ok", "11:23", "ok", "11:23", "see you"])
        self.assertEqual(texts.count("ok"), 2)


if __name__ == "__main__":
    unittest.main()
