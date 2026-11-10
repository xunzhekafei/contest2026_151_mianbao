# -*- coding: utf-8 -*-
"""结构化面试笔记（2026-11-10）的单元测试 —— 不需要联网。

只测"不调模型"的部分：模型输出的收敛（_normalize_note）、会话存储、
导出渲染。真正调模型的路径由端到端实测覆盖（见台账 §11.83）。
"""
import unittest

import llm_service
from session_manager import SessionManager
from report_export import to_markdown


class TestNormalizeNote(unittest.TestCase):
    def test_clean_json(self):
        raw = ('{"summary": "介绍了灵感发现智能体", '
               '"points": [{"kind": "项目", "text": "从评论区找需求"}, '
               '{"kind": "数字", "text": "20~30 个候选"}], '
               '"doubt": "没说评测集多大"}')
        note = llm_service._normalize_note(raw)
        self.assertEqual(note["summary"], "介绍了灵感发现智能体")
        self.assertEqual(len(note["points"]), 2)
        self.assertEqual(note["doubt"], "没说评测集多大")

    def test_fenced_json(self):
        raw = ('```json\n{"summary": "打招呼", "points": [], '
               '"doubt": "建议重问"}\n```')
        note = llm_service._normalize_note(raw)
        self.assertEqual(note["summary"], "打招呼")
        self.assertEqual(note["points"], [])

    def test_garbage_returns_empty(self):
        for raw in ("这不是 JSON", "", None, '{"points": []}'):
            self.assertEqual(llm_service._normalize_note(raw), {})

    def test_points_capped_and_trimmed(self):
        raw = ('{"summary": "%s", "points": [%s], "doubt": ""}'
               % ("长" * 200,
                  ",".join(['{"kind": "数字", "text": "要点%d"}' % i
                            for i in range(10)])))
        note = llm_service._normalize_note(raw)
        self.assertLessEqual(len(note["summary"]), 80)
        self.assertEqual(len(note["points"]), 4)

    def test_title_whitespace_is_squashed(self):
        note = llm_service._normalize_note(
            '{"summary": "第一行\\n第二行", "points": [], "doubt": ""}')
        self.assertEqual(note["summary"], "第一行 第二行")

    def test_empty_answer_skips_llm(self):
        """空回答直接返回 {}，不加载技能、不调模型。"""
        self.assertEqual(llm_service.extract_note("智能体开发", "问题", "   "), {})


class TestSessionNotes(unittest.TestCase):
    def test_add_note_and_snapshot_sorted(self):
        manager = SessionManager()
        session = manager.get_or_create_session("s1", "智能体开发")
        session.add_note({"round": 2, "question": "q2",
                          "note": {"summary": "b"}})
        session.add_note({"round": 1, "question": "q1",
                          "note": {"summary": "a"}})
        snap = manager.snapshot("s1")
        self.assertEqual([n["round"] for n in snap["notes"]], [1, 2])

    def test_snapshot_without_notes_is_empty_list(self):
        manager = SessionManager()
        manager.get_or_create_session("s2", "智能体开发")
        self.assertEqual(manager.snapshot("s2")["notes"], [])

    def test_notes_do_not_touch_history(self):
        """笔记绝不进 messages（否则会被当成对话发给模型）。"""
        manager = SessionManager()
        session = manager.get_or_create_session("s3", "智能体开发")
        session.add_user_message("你好")
        session.add_note({"round": 1, "question": "q", "note": {"summary": "s"}})
        snap = manager.snapshot("s3")
        self.assertEqual(len(snap["messages"]), 1)
        for message in snap["messages"]:
            self.assertNotIn("note", message)


class TestExportNotes(unittest.TestCase):
    def _snap(self, notes):
        return {"session_id": "x", "role": "智能体开发", "question_count": 1,
                "is_finished": True, "notes": notes, "messages": []}

    def test_markdown_has_notes_section(self):
        snap = self._snap([{
            "round": 1, "question": "讲一下项目",
            "note": {"summary": "介绍了灵感发现智能体",
                     "points": [{"kind": "数字", "text": "20~30 个候选"}],
                     "doubt": "没说评测集"}}])
        md = to_markdown(snap)
        self.assertIn("## 面试笔记", md)
        self.assertIn("介绍了灵感发现智能体", md)
        self.assertIn("【数字】20~30 个候选", md)
        self.assertIn("待追问：没说评测集", md)

    def test_markdown_without_notes_has_no_section(self):
        self.assertNotIn("## 面试笔记", to_markdown(self._snap([])))

    def test_malformed_entries_are_skipped(self):
        snap = self._snap([None, "坏数据", {"round": 2}])   # 只有第三条是 dict
        md = to_markdown(snap)
        self.assertIn("## 面试笔记", md)
        self.assertIn("第 2 题", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
