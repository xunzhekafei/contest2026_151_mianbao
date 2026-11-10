# -*- coding: utf-8 -*-
"""评分校准（2026-11-10）的单元测试 —— 纯离线，不需要 key。"""
import json
import os
import tempfile
import unittest

import score_calibration as cal


def snap(sid, total, dims, finished=True, role="智能体开发",
         version=2, evidence_status="ok", unmatched=None,
         messages=None, missing=None):
    return {
        "session_id": sid,
        "role": role,
        "is_finished": finished,
        "messages": messages or [],
        "score": {
            "total": total,
            "scoring_version": version,
            "evidence_status": evidence_status,
            "evidence_unmatched": unmatched or [],
            "missing": missing or [],
            "dimensions": [{"name": n, "score": v, "max": 10} for n, v in dims],
            "per_question": [{"index": 1, "question": "q", "suggestion": "s"}],
        },
    }


class TestSummarize(unittest.TestCase):
    def setUp(self):
        self.snapshots = [
            snap("a", 30, [("技术正确性", 3), ("深度与原理", 3),
                            ("工程与场景思考", 3), ("表达与结构", 3)]),
            snap("b", 60, [("技术正确性", 6), ("深度与原理", 6),
                            ("工程与场景思考", 6), ("表达与结构", 6)]),
            snap("c", 90, [("技术正确性", 9), ("深度与原理", 9),
                            ("工程与场景思考", 9), ("表达与结构", 9)],
                 evidence_status="partial", unmatched=["深度与原理"]),
        ]

    def test_counts_and_totals(self):
        summary = cal.summarize(self.snapshots)
        self.assertEqual(summary["counts"]["scored"], 3)
        self.assertEqual(summary["totals"]["n"], 3)
        self.assertEqual(summary["totals"]["mean"], 60.0)
        self.assertEqual(summary["totals"]["median"], 60.0)
        self.assertEqual(summary["totals"]["min"], 30.0)
        self.assertEqual(summary["totals"]["max"], 90.0)

    def test_histogram(self):
        summary = cal.summarize(self.snapshots)
        self.assertEqual(summary["histogram"]["20-39"], 1)
        self.assertEqual(summary["histogram"]["60-79"], 1)
        self.assertEqual(summary["histogram"]["80-100"], 1)

    def test_dimensions(self):
        summary = cal.summarize(self.snapshots)
        entry = summary["dimensions"]["技术正确性"]
        self.assertEqual(entry["n"], 3)
        self.assertAlmostEqual(entry["mean"], 6.0)
        self.assertAlmostEqual(entry["mean_pct"], 60.0)
        self.assertEqual(entry["min"], 3.0)
        self.assertEqual(entry["max"], 9.0)

    def test_evidence(self):
        summary = cal.summarize(self.snapshots)
        self.assertEqual(summary["evidence"]["ok"], 2)
        self.assertEqual(summary["evidence"]["partial"], 1)
        self.assertEqual(summary["evidence"]["unmatched_dims"]["深度与原理"], 1)

    def test_versions(self):
        summary = cal.summarize(self.snapshots)
        self.assertEqual(summary["versions"]["v2"]["n"], 3)

    def test_anomalies(self):
        snapshots = self.snapshots + [
            snap("d", 98, [("技术正确性", 10)]),
            snap("e", 50, [("技术正确性", 5)], missing=["深度与原理", "表达与结构"]),
        ]
        summary = cal.summarize(snapshots)
        reasons = [r for _, r in summary["anomalies"]]
        self.assertTrue(any("过松" in r for r in reasons))
        self.assertTrue(any("2 个维度未评" in r for r in reasons))

    def test_correlation_none_when_too_few(self):
        summary = cal.summarize(self.snapshots)
        self.assertIsNone(summary["correlation"]["vs_rounds"])

    def test_roles(self):
        summary = cal.summarize(self.snapshots)
        self.assertEqual(summary["roles"]["智能体开发"]["n"], 3)


class TestRender(unittest.TestCase):
    def test_markdown_sections(self):
        snapshot = snap("a", 60, [("技术正确性", 6), ("深度与原理", 6),
                                  ("工程与场景思考", 6), ("表达与结构", 6)])
        text = cal.render_markdown(cal.summarize([snapshot]))
        self.assertIn("# 评分校准报告", text)
        self.assertIn("## 总分分布", text)
        self.assertIn("## 维度均值", text)
        self.assertIn("## 证据核对", text)

    def test_empty_dataset(self):
        text = cal.render_markdown(cal.summarize([]))
        self.assertIn("会话总数：0", text)


class TestLoad(unittest.TestCase):
    def test_skips_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "good.json")
            bad = os.path.join(tmp, "bad.json")
            with open(good, "w", encoding="utf-8") as fh:
                json.dump({"session_id": "x", "score": {}}, fh)
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write("{not json")
            snapshots = cal.load_snapshots(tmp)
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0]["session_id"], "x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
