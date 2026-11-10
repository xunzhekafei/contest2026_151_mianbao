# -*- coding: utf-8 -*-
"""评分校准：把历史场次的评分拉出来做统计体检（2026-11-10）。

**离线、零模型调用**：读取 `cloud/data/sessions/*.json`（session_store 落的
快照），回答四个问题：

1. 分数分布是否合理（太松 / 太紧 / 挤在中间、拉不开）；
2. 四个维度有没有系统性偏高偏低、经常"未评"；
3. 证据核对情况（v2 才有）：partial 比例、对不上原话的维度分布；
4. 评分和"回答量"有没有异常相关（比如分数主要被篇幅决定 —— 那是提示词的病）。

另提供 `stability()`：同一场对话重复评分 N 次看方差（**要花钱**，CLI 用
`--repeat` 才触发，本模块不主动调模型）。

为什么放 cloud 而不是 tools：它要被单测覆盖、也可能被网页/脚本复用；
`tools/calibrate_scores.py` 只是它的命令行壳。
"""
import glob
import json
import os
import statistics


def load_snapshots(directory):
    """读目录下所有会话快照；坏文件跳过（不因一个脏文件让整份报告失败）。"""
    snapshots = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                data.setdefault("_file", os.path.basename(path))
                snapshots.append(data)
        except (OSError, ValueError):
            continue
    return snapshots


def _scored(snapshots):
    return [s for s in snapshots
            if isinstance(s.get("score"), dict)
            and isinstance(s["score"].get("total"), (int, float))]


def _pearson(xs, ys):
    """皮尔逊相关系数；样本不足或方差为零时返回 None（不硬算）。"""
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    try:
        mx = statistics.fmean(xs)
        my = statistics.fmean(ys)
        vx = sum((x - mx) ** 2 for x in xs)
        vy = sum((y - my) ** 2 for y in ys)
        if vx <= 0 or vy <= 0:
            return None
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        return cov / (vx ** 0.5 * vy ** 0.5)
    except (TypeError, ValueError, statistics.StatisticsError):
        return None


def summarize(snapshots):
    """把快照集合压成一份统计结构（纯函数、可单测）。"""
    scored = _scored(snapshots)
    totals = [float(s["score"]["total"]) for s in scored]

    # ---- 分数分布 ----
    total_stats = {}
    histogram = {"0-19": 0, "20-39": 0, "40-59": 0, "60-79": 0, "80-100": 0}
    if totals:
        total_stats = {
            "n": len(totals),
            "mean": round(statistics.fmean(totals), 1),
            "median": round(statistics.median(totals), 1),
            "min": min(totals),
            "max": max(totals),
            "stdev": round(statistics.pstdev(totals), 1) if len(totals) > 1 else 0.0,
        }
        for value in totals:
            if value < 20:
                histogram["0-19"] += 1
            elif value < 40:
                histogram["20-39"] += 1
            elif value < 60:
                histogram["40-59"] += 1
            elif value < 80:
                histogram["60-79"] += 1
            else:
                histogram["80-100"] += 1

    # ---- 维度 ----
    dimensions = {}
    for snap in scored:
        for dim in snap["score"].get("dimensions") or []:
            if not isinstance(dim, dict):
                continue
            name = dim.get("name") or "?"
            entry = dimensions.setdefault(
                name, {"n": 0, "sum": 0.0, "max_sum": 0.0,
                       "min": None, "max": None})
            try:
                value = float(dim.get("score"))
            except (TypeError, ValueError):
                continue
            entry["n"] += 1
            entry["sum"] += value
            entry["max_sum"] += float(dim.get("max") or 10)
            entry["min"] = value if entry["min"] is None else min(entry["min"], value)
            entry["max"] = value if entry["max"] is None else max(entry["max"], value)
    for entry in dimensions.values():
        entry["mean"] = round(entry["sum"] / entry["n"], 2) if entry["n"] else None
        entry["mean_pct"] = (round(100.0 * entry["sum"] / entry["max_sum"], 1)
                             if entry["max_sum"] else None)
        entry.pop("sum")
        entry.pop("max_sum")

    # ---- 证据核对（v2）----
    evidence = {"ok": 0, "partial": 0, "unknown": 0, "unmatched_dims": {}}
    for snap in scored:
        status = snap["score"].get("evidence_status")
        if status == "ok":
            evidence["ok"] += 1
        elif status == "partial":
            evidence["partial"] += 1
        else:
            evidence["unknown"] += 1
        for name in snap["score"].get("evidence_unmatched") or []:
            evidence["unmatched_dims"][name] = evidence["unmatched_dims"].get(name, 0) + 1

    # ---- 评分口径版本 ----
    versions = {"v2": [], "v1/未标": []}
    for snap in scored:
        if snap["score"].get("scoring_version") == 2:
            versions["v2"].append(float(snap["score"]["total"]))
        else:
            versions["v1/未标"].append(float(snap["score"]["total"]))
    version_stats = {}
    for key, values in versions.items():
        version_stats[key] = {
            "n": len(values),
            "mean": round(statistics.fmean(values), 1) if values else None,
        }

    # ---- 与回答量的相关（分数被篇幅决定 = 提示词有病）----
    pairs = []
    for snap in scored:
        answers = [m for m in (snap.get("messages") or [])
                   if isinstance(m, dict) and m.get("role") == "user"]
        if not answers:
            continue
        chars = sum(len(str(m.get("content") or "")) for m in answers)
        pairs.append((float(snap["score"]["total"]), len(answers), chars))
    corr = {
        "vs_rounds": _pearson([p[0] for p in pairs], [float(p[1]) for p in pairs]),
        "vs_answer_chars": _pearson([p[0] for p in pairs], [float(p[2]) for p in pairs]),
        "n": len(pairs),
    }

    # ---- 按岗位 ----
    roles = {}
    for snap in scored:
        role = snap.get("role") or "（未知）"
        roles.setdefault(role, []).append(float(snap["score"]["total"]))
    role_stats = {role: {"n": len(values),
                         "mean": round(statistics.fmean(values), 1)}
                  for role, values in sorted(roles.items())}

    # ---- 异常场次 ----
    anomalies = []
    for snap in scored:
        score = snap["score"]
        total = float(score["total"])
        sid = str(snap.get("session_id") or snap.get("_file") or "?")[:8]
        if total >= 95:
            anomalies.append((sid, "总分 >= 95（疑似过松）"))
        if total <= 5:
            anomalies.append((sid, "总分 <= 5（疑似过紧/空场）"))
        missing = score.get("missing") or []
        if len(missing) >= 2:
            anomalies.append((sid, "有 %d 个维度未评" % len(missing)))
        if snap.get("is_finished") and not (score.get("per_question") or []):
            anomalies.append((sid, "已结束但没有逐题复盘"))

    return {
        "counts": {
            "sessions": len(snapshots),
            "finished": sum(1 for s in snapshots if s.get("is_finished")),
            "scored": len(scored),
        },
        "totals": total_stats,
        "histogram": histogram,
        "dimensions": dimensions,
        "evidence": evidence,
        "versions": version_stats,
        "correlation": corr,
        "roles": role_stats,
        "anomalies": anomalies,
    }


def render_markdown(summary, title="评分校准报告"):
    """把 summarize 的结果渲染成 Markdown（给人看/贴台账）。"""
    counts = summary["counts"]
    lines = ["# %s" % title, ""]
    lines.append("- 会话总数：%d（已结束 %d，有评分 %d）"
                 % (counts["sessions"], counts["finished"], counts["scored"]))

    totals = summary["totals"]
    if totals:
        lines += ["", "## 总分分布", "",
                  "| 样本 | 均值 | 中位数 | 最低 | 最高 | 标准差 |",
                  "| --- | --- | --- | --- | --- | --- |",
                  "| %d | %s | %s | %s | %s | %s |"
                  % (totals["n"], totals["mean"], totals["median"],
                     totals["min"], totals["max"], totals["stdev"]), "",
                  "| 区间 | 场次 |", "| --- | --- |"]
        for bucket, count in summary["histogram"].items():
            lines.append("| %s | %d |" % (bucket, count))

    if summary["dimensions"]:
        lines += ["", "## 维度均值", "",
                  "| 维度 | 样本 | 均值 | 占满分比例 | 最低 | 最高 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for name, entry in summary["dimensions"].items():
            lines.append("| %s | %d | %s | %s%% | %s | %s |"
                         % (name, entry["n"], entry["mean"],
                            entry["mean_pct"], entry["min"], entry["max"]))

    evidence = summary["evidence"]
    if any(evidence.get(k) for k in ("ok", "partial", "unknown")):
        lines += ["", "## 证据核对（v2）", "",
                  "- ok：%d 场；partial：%d 场；无标记（v1/旧数据）：%d 场"
                  % (evidence["ok"], evidence["partial"], evidence["unknown"])]
        if evidence["unmatched_dims"]:
            lines.append("- 对不上原话的维度：%s"
                         % "、".join("%s×%d" % (k, v) for k, v
                                     in sorted(evidence["unmatched_dims"].items(),
                                               key=lambda kv: -kv[1])))

    versions = summary["versions"]
    if any(v.get("n") for v in versions.values()):
        lines += ["", "## 评分口径版本", "",
                  "| 版本 | 场次 | 均值 |", "| --- | --- | --- |"]
        for key, entry in versions.items():
            lines.append("| %s | %d | %s |"
                         % (key, entry["n"],
                            entry["mean"] if entry["mean"] is not None else "—"))

    corr = summary["correlation"]
    lines += ["", "## 分数与回答量的相关（n=%d）" % corr["n"], ""]
    for label, key in (("轮数", "vs_rounds"), ("回答总字数", "vs_answer_chars")):
        value = corr.get(key)
        lines.append("- 与%s的相关系数：%s" % (
            label, "—（样本不足/无方差）" if value is None else "%.2f" % value))
    lines.append("  > 绝对值 >0.7 说明分数基本由篇幅决定，提示词需要加「按内容质量"
                 "而非长度」的约束。")

    if summary["roles"]:
        lines += ["", "## 按岗位", "",
                  "| 岗位 | 场次 | 均值 |", "| --- | --- | --- |"]
        for role, entry in summary["roles"].items():
            lines.append("| %s | %d | %s |" % (role, entry["n"], entry["mean"]))

    if summary["anomalies"]:
        lines += ["", "## 需要人工看一眼的场次", ""]
        for sid, reason in summary["anomalies"][:20]:
            lines.append("- `%s`：%s" % (sid, reason))
    else:
        lines += ["", "## 异常场次", "", "（无）"]

    return "\n".join(lines) + "\n"
