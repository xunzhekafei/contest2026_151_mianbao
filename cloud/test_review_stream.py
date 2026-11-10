# -*- coding: utf-8 -*-
"""逐题复盘·流式版（2026-11-10）的单元测试 —— 不需要联网。

覆盖：单题输出的收敛与证据校验、题号配对、会话存储去重、导出回退。
真正调模型的逐题生成由端到端实测覆盖（台账 §11.84）。
"""
import os
import unittest

# app.py 在导入期就要 key（同 test_routes.py 的处理），必须在 import app 之前。
os.environ["MIMO_API_KEY"] = "dummy-key-for-tests-never-used"

import llm_service                     # noqa: E402
import app as cloud_app                # noqa: E402
from session_manager import SessionManager   # noqa: E402
from report_export import to_markdown        # noqa: E402

ANSWER = "我负责整体编排、提示词和评测，评测集有 200 条人工标注。"


class TestNormalizeReview(unittest.TestCase):
    def test_clean_json_keeps_verbatim_evidence(self):
        raw = ('{"evidence": "评测集有 200 条人工标注", '
               '"suggestion": "补充一下负样本的抽样方式"}')
        item = llm_service._normalize_review(raw, ANSWER)
        self.assertEqual(item["evidence"], "评测集有 200 条人工标注")
        self.assertIn("负样本", item["suggestion"])

    def test_evidence_not_in_answer_is_dropped(self):
        raw = ('{"evidence": "我主导了三次架构重构", '
               '"suggestion": "补一个数字"}')
        item = llm_service._normalize_review(raw, ANSWER)
        self.assertEqual(item["evidence"], "")
        self.assertEqual(item["suggestion"], "补一个数字")

    def test_punctuation_insensitive_match(self):
        """原话跨标点时（压掉标点后仍是子串）证据保留。"""
        raw = ('{"evidence": "整体编排、提示词", "suggestion": "再细一点"}')
        item = llm_service._normalize_review(raw, ANSWER)
        self.assertEqual(item["evidence"], "整体编排、提示词")

    def test_missing_suggestion_is_dropped(self):
        self.assertIsNone(llm_service._normalize_review(
            '{"evidence": "评测集有 200 条人工标注", "suggestion": ""}', ANSWER))

    def test_garbage_returns_none(self):
        for raw in ("不是 JSON", "", None):
            self.assertIsNone(llm_service._normalize_review(raw, ANSWER))


class TestQuestionPairs(unittest.TestCase):
    def test_pairs_skip_report_message(self):
        manager = SessionManager()
        session = manager.get_or_create_session("p1", "智能体开发")
        session.add_ai_message("介绍一下你自己")
        session.add_user_message("我是候选人")
        session.add_ai_message("讲讲项目")
        session.add_user_message("我负责编排")
        session.add_ai_message("（报告正文）")
        pairs = cloud_app._question_pairs(session)
        self.assertEqual(pairs, [(1, "介绍一下你自己", "我是候选人"),
                                 (2, "讲讲项目", "我负责编排")])


class TestLiveReviewStorage(unittest.TestCase):
    def test_add_and_dedupe(self):
        manager = SessionManager()
        session = manager.get_or_create_session("l1", "智能体开发")
        session.add_live_review({"index": 2, "question": "q2",
                                 "evidence": "", "suggestion": "b"})
        session.add_live_review({"index": 1, "question": "q1",
                                 "evidence": "", "suggestion": "a"})
        session.add_live_review({"index": 1, "question": "q1",
                                 "evidence": "", "suggestion": "a2"})
        snap = manager.snapshot("l1")
        self.assertEqual([n["index"] for n in snap["per_question_live"]], [1, 2])
        self.assertEqual(snap["per_question_live"][0]["suggestion"], "a2")

    def test_snapshot_without_live_is_empty(self):
        manager = SessionManager()
        manager.get_or_create_session("l2", "智能体开发")
        self.assertEqual(manager.snapshot("l2")["per_question_live"], [])


class TestExportFallback(unittest.TestCase):
    def _snap(self, live):
        return {"session_id": "x", "role": "智能体开发", "question_count": 1,
                "is_finished": True, "notes": [], "per_question_live": live,
                "score": None, "messages": []}

    def test_markdown_uses_live_when_score_missing(self):
        md = to_markdown(self._snap([
            {"index": 1, "question": "讲一下项目",
             "evidence": "负责整体编排", "suggestion": "补充一个数字口径"}]))
        self.assertIn("逐题复盘", md)
        self.assertIn("负责整体编排", md)
        self.assertIn("补充一个数字口径", md)

    def test_markdown_without_any_review(self):
        self.assertNotIn("逐题复盘", to_markdown(self._snap([])))


if __name__ == "__main__":
    unittest.main(verbosity=2)
