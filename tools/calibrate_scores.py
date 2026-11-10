#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""评分校准命令行（2026-11-10）。

两种用法：

1) **离线体检（零成本）**：统计历史场次的评分分布 / 维度 / 证据情况 /
   与回答量的相关，输出 Markdown 报告。

       python tools/calibrate_scores.py
       python tools/calibrate_scores.py --out 校准报告.md

   默认读 `cloud/data/sessions/`。建议在 `cloud/.venv` 的 Python 下跑
   （纯标准库也行，但统一环境少踩坑）。

2) **稳定性检查（花钱，默认不做）**：对同一场对话重复评分 N 次，
   看每个维度与总分的波动。

       python tools/calibrate_scores.py \
           --repeat <session_id> --n 3 --sessions cloud/data/sessions

   需要 MIMO_API_KEY（同云端服务），单次评分约十几秒，N=3 大约一分钟。

判读口径（写死在报告里）：
* 均值过高（>80）且标准差小 → 评分偏松、拉不开；
* 某维度均值明显高于其它（差距 >1 分/满分10）→ 该维度口径偏宽；
* 与回答总字数的相关 |r| > 0.7 → 分数基本被篇幅决定，提示词要收紧；
* evidence partial 比例高 → 证据核对在救场，说明模型常改写原话。
"""
import argparse
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLOUD = os.path.join(REPO, "cloud")
sys.path.insert(0, CLOUD)

import score_calibration  # noqa: E402


def offline(args):
    snapshots = score_calibration.load_snapshots(args.sessions)
    if not snapshots:
        print("没有找到会话快照：%s" % args.sessions)
        return 1
    summary = score_calibration.summarize(snapshots)
    text = score_calibration.render_markdown(summary)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("\n已写入 %s" % args.out)
    return 0


def _find_snapshot(session_id, directory):
    path = os.path.join(directory, session_id + ".json")
    if os.path.exists(path):
        return path
    import glob
    for candidate in glob.glob(os.path.join(directory, "*.json")):
        if os.path.basename(candidate).startswith(session_id):
            return candidate
    return None


def stability(args):
    path = _find_snapshot(args.repeat, args.sessions)
    if path is None:
        print("找不到会话：%s" % args.repeat)
        return 1

    import json
    import llm_service

    snapshot = json.load(open(path, encoding="utf-8"))
    history = [{"role": m["role"], "content": m.get("content", "")}
               for m in snapshot.get("messages") or []
               if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    if not history:
        print("这场没有对话内容，无法重复评分")
        return 1
    role = snapshot.get("role") or "AI 应用开发"

    runs = []
    for i in range(args.n):
        print("第 %d/%d 次评分…" % (i + 1, args.n), flush=True)
        score = llm_service.score_interview(role, list(history))
        if not score:
            print("  失败（未拿到评分）")
            continue
        dims = {d.get("name"): d.get("score")
                for d in score.get("dimensions") or [] if isinstance(d, dict)}
        runs.append({"total": score.get("total"), "dims": dims})

    if not runs:
        print("没有一次成功，检查 MIMO_API_KEY 与网络")
        return 2

    print("\n## 稳定性（同一场重复 %d 次）\n" % len(runs))
    totals = [r["total"] for r in runs if isinstance(r["total"], (int, float))]
    print("- 总分：%s" % ", ".join(str(t) for t in totals))
    if len(totals) > 1:
        print("- 总分极差：%d，标准差：%.1f"
              % (max(totals) - min(totals), statistics.pstdev(totals)))

    names = sorted({name for r in runs for name in r["dims"]})
    print("\n| 维度 | 各次得分 | 极差 |\n| --- | --- | --- |")
    for name in names:
        values = [r["dims"].get(name) for r in runs]
        clean = [v for v in values if isinstance(v, (int, float))]
        spread = (max(clean) - min(clean)) if len(clean) > 1 else 0
        print("| %s | %s | %s |"
              % (name, ", ".join(str(v) for v in values), spread))
    print("\n> 极差 <=1 视为稳定；>=3 说明该维度口径太模糊，需要给分档示例。")
    return 0


def main():
    parser = argparse.ArgumentParser(description="评分校准（离线体检 / 稳定性）")
    parser.add_argument("--sessions", default=os.path.join(CLOUD, "data", "sessions"),
                        help="会话快照目录（默认 cloud/data/sessions）")
    parser.add_argument("--out", default="", help="把离线报告写入指定 .md 文件")
    parser.add_argument("--repeat", default="", help="要重复评分的 session_id")
    parser.add_argument("--n", type=int, default=3, help="重复评分次数（默认 3）")
    args = parser.parse_args()

    if args.repeat:
        return stability(args)
    return offline(args)


if __name__ == "__main__":
    sys.exit(main())
