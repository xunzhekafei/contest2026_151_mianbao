# -*- coding: utf-8 -*-
"""流式分句 + /api/interview/live（2026-11-10，Phase 1）的单元测试。

分句器是纯函数，直接测；路由用 Flask test client + 假流式 LLM 测事件序列，
不联网、不调真实模型。
"""
import os
import unittest

# app.py 在导入期就要 key（同 test_routes.py 的处理）
os.environ.setdefault("MIMO_API_KEY", "dummy-key-for-tests-never-used")

from live_stream import SentenceAccumulator


class TestSentenceAccumulator(unittest.TestCase):
    def test_no_boundary_returns_nothing(self):
        acc = SentenceAccumulator()
        self.assertEqual(acc.feed("你好，我是"), [])
        self.assertEqual(acc.feed("面试官"), [])

    def test_boundary_completes_sentence(self):
        acc = SentenceAccumulator()
        self.assertEqual(acc.feed("你好，我是面试官。"), ["你好，我是面试官。"])

    def test_short_sentence_merges_with_next(self):
        acc = SentenceAccumulator(min_len=6)
        self.assertEqual(acc.feed("好。"), [])            # 太短，先攒着
        self.assertEqual(acc.feed("请介绍一下你自己。"),
                         ["好。请介绍一下你自己。"])

    def test_multiple_sentences_in_one_delta(self):
        acc = SentenceAccumulator()
        out = acc.feed("第一句怎么样？第二句是什么？")
        self.assertEqual(out, ["第一句怎么样？", "第二句是什么？"])

    def test_flush_returns_remainder(self):
        acc = SentenceAccumulator()
        acc.feed("没有结束标点的尾巴")
        self.assertEqual(acc.flush(), ["没有结束标点的尾巴"])
        self.assertEqual(acc.flush(), [])

    def test_long_single_sentence_splits_at_comma(self):
        acc = SentenceAccumulator(soft_max=30)
        q = "能具体讲讲这个灵感发现智能体吗，它整体的编排流程是怎么设计的，你在其中负责的评测又是怎么做的？"
        out = acc.feed(q)
        out += acc.flush()
        self.assertGreaterEqual(len(out), 2, "长问句应在软边界处切成多段")
        self.assertEqual("".join(out), q)

    def test_overlong_text_forced_cut(self):
        acc = SentenceAccumulator(min_len=6, max_len=20)
        out = acc.feed("一" * 15 + "，" + "二" * 15)      # 无句号，超长
        self.assertTrue(out)
        self.assertTrue(all(len(s) <= 20 for s in out))

    def test_newline_is_boundary(self):
        acc = SentenceAccumulator()
        self.assertEqual(acc.feed("这是第一行内容\n第二行？"),
                         ["这是第一行内容"])
        self.assertEqual(acc.flush(), ["第二行？"])


class TestLiveRoute(unittest.TestCase):
    """用假流式 LLM 验证 SSE 事件序列（不联网）。"""

    def setUp(self):
        import app as cloud_app
        self.app_mod = cloud_app
        self.client = cloud_app.app.test_client()
        self._orig_llm = cloud_app.llm_interview
        self._orig_tts = cloud_app.tts_text_to_audio

        def fake_llm(role, history, state, audio_base64="", pressure="标准",
                     target_rounds=10, stream_cb=None):
            for piece in ("您好。", "请介绍一下你自己。", "重点讲讲项目？"):
                if stream_cb:
                    stream_cb(piece)
            return {"text": "您好。请介绍一下你自己。重点讲讲项目？",
                    "next_action": "continue"}

        cloud_app.llm_interview = fake_llm
        cloud_app.tts_text_to_audio = lambda text, style=None: ""
        cloud_app.extract_note = lambda role, q, a: {}

    def tearDown(self):
        self.app_mod.llm_interview = self._orig_llm
        self.app_mod.tts_text_to_audio = self._orig_tts

    def test_stream_emits_sentences_and_done(self):
        resp = self.client.post("/api/interview/live", json={
            "state": "start", "role": "智能体开发", "pressure": "标准",
            "target_rounds": 4})
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode("utf-8")
        self.assertIn("event: meta", body)
        self.assertIn("event: sentence", body)
        self.assertIn("请介绍一下你自己。", body)
        self.assertIn("event: done", body)
        self.assertIn('"next_action": "continue"', body)

    def test_empty_answer_emits_error(self):
        resp = self.client.post("/api/interview/live", json={
            "role": "智能体开发", "pressure": "标准", "target_rounds": 4,
            "text": "   "})
        body = resp.data.decode("utf-8")
        self.assertIn("event: error", body)

    def test_session_created_and_history_recorded(self):
        import json as _json
        resp = self.client.post("/api/interview/live", json={
            "role": "智能体开发", "pressure": "标准", "target_rounds": 4,
            "text": "我是候选人，负责编排。"})
        body = resp.data.decode("utf-8")
        meta = [line for line in body.split("\n") if line.startswith("data: ")][0]
        sid = _json.loads(meta[6:])["session_id"]
        session = self.app_mod.session_manager.get_session(sid)
        self.assertIsNotNone(session)
        roles = [m["role"] for m in session.get_history()]
        self.assertEqual(roles, ["user", "assistant"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
