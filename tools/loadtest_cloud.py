#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端压测 / 并发自检（2026-11-10）。

两种模式：

1) **进程内 mock 压测（默认，零成本）** —— 不调真实模型：把 llm_interview /
   score_interview / review_one / extract_note 换成毫秒级假实现，在本地起一个
   threaded Flask，并发跑 N 个会话。验证的是**我们自己控制的部分**：并发闸、
   会话隔离、落盘、后台线程、状态页计数。不验证模型延迟（那个由真实链路决定）。

       python tools/loadtest_cloud.py --concurrency 16 --target-rounds 3

2) **健康检查并发烟测（打真实服务，不花钱）** —— 只打 /api/health：

       python tools/loadtest_cloud.py --health --target http://127.0.0.1:5000 -n 200

判读口径：
* 错误数应为 0；会话全部拿到 report；
* mock 场景 p95 应远小于 1 秒（>1s 说明有锁竞争/落盘放大）；
* 「同会话并发」应大部分被 409 拒（这是并发闸的设计），不能出现两份报告。
"""
import argparse
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CLOUD = os.path.join(REPO, "cloud")
sys.path.insert(0, CLOUD)

# 进程内跑 Flask 需要导入期就存在的 key（同 test_routes.py 的处理）
os.environ.setdefault("MIMO_API_KEY", "loadtest-dummy-key-never-used")

import app as cloud_app  # noqa: E402


# ---------------------------------------------------------------------------
# 假实现（毫秒级，签名与真实现一致）
# ---------------------------------------------------------------------------

def _fake_llm_interview(role, history, state, audio_base64="",
                        pressure="标准", target_rounds=10):
    time.sleep(0.02)
    users = sum(1 for m in history if m.get("role") == "user")
    if state != "start" and users >= target_rounds + 1:
        return {"text": "（报告正文，mock）", "next_action": "finish"}
    return {"text": "（下一个问题，mock）", "next_action": "continue"}


def _fake_score(role, history):
    time.sleep(0.05)
    return {"total": 70,
            "dimensions": [
                {"name": "技术正确性", "score": 7, "max": 10, "comment": "mock"},
                {"name": "深度与原理", "score": 7, "max": 10, "comment": "mock"},
                {"name": "工程与场景思考", "score": 7, "max": 10, "comment": "mock"},
                {"name": "表达与结构", "score": 7, "max": 10, "comment": "mock"},
            ],
            "per_question": [], "summary": "mock"}


def _fake_review(role, question, answer):
    time.sleep(0.005)
    return {"evidence": "", "suggestion": "补一个具体数字"}


def _fake_note(role, question, answer):
    time.sleep(0.005)
    return {"summary": "mock 概括", "points": [], "doubt": ""}


# ---------------------------------------------------------------------------
# HTTP 小工具
# ---------------------------------------------------------------------------

def _post(base, path, obj, timeout=30):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read(), time.time() - t0


def _delete(base, sid):
    try:
        req = urllib.request.Request(base + "/api/sessions/" + sid, method="DELETE")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _pct(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p / 100.0 * (len(ordered) - 1)))))
    return ordered[idx]


# ---------------------------------------------------------------------------
# 两个模式
# ---------------------------------------------------------------------------

def run_session(base, target_rounds, latencies, errors, results):
    try:
        status, body, dt = _post(base, "/api/interview/text", {
            "state": "start", "role": "智能体开发", "pressure": "标准",
            "target_rounds": target_rounds})
        latencies.append(dt)
        if status != 200:
            errors.append(("start", status))
            return
        sid = json.loads(body)["session_id"]
        final = "question"
        for i in range(target_rounds + 1):
            status, body, dt = _post(base, "/api/interview/text", {
                "session_id": sid, "role": "智能体开发", "pressure": "标准",
                "target_rounds": target_rounds,
                "text": "这是第 %d 个回答，带一些具体内容。" % (i + 1)})
            latencies.append(dt)
            if status != 200:
                errors.append(("answer", status))
                return
            final = json.loads(body).get("type")
            if final == "report":
                break
        results.append((sid, final))
        _delete(base, sid)
    except Exception as error:              # noqa: BLE001
        errors.append((type(error).__name__, str(error)[:80]))


def same_session_burst(base, burst, rounds):
    """同一会话同时发 burst 个请求：验证并发闸（应大部分 409，不能出两份报告）。"""
    status, body, _ = _post(base, "/api/interview/text", {
        "state": "start", "role": "智能体开发", "pressure": "标准",
        "target_rounds": rounds})
    if status != 200:
        return None
    sid = json.loads(body)["session_id"]
    codes = []
    lock = threading.Lock()

    def fire():
        try:
            status, _, _ = _post(base, "/api/interview/text", {
                "session_id": sid, "role": "智能体开发", "pressure": "标准",
                "target_rounds": rounds, "text": "同一个会话的并发回答。"})
            with lock:
                codes.append(status)
        except urllib.error.HTTPError as error:
            with lock:
                codes.append(error.code)    # 409 等非 2xx 走这里
        except Exception:                   # noqa: BLE001
            with lock:
                codes.append(0)

    threads = [threading.Thread(target=fire) for _ in range(burst)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    _delete(base, sid)
    return codes


def mock_mode(args):
    cloud_app.llm_interview = _fake_llm_interview
    cloud_app.score_interview = _fake_score
    cloud_app.review_one = _fake_review
    cloud_app.extract_note = _fake_note

    server = threading.Thread(
        target=lambda: cloud_app.app.run(host="127.0.0.1", port=args.port,
                                         threaded=True, debug=False,
                                         use_reloader=False),
        daemon=True)
    server.start()
    base = "http://127.0.0.1:%d" % args.port
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except Exception:                   # noqa: BLE001
            time.sleep(0.1)
    else:
        print("服务没起来")
        return 1

    # normalize_target() 会把轮数下限夹到 4（传 3 会变成 4），这里先对齐，
    # 否则按 3 轮发答案永远等不到报告（2026-11-10 压测踩到）。
    rounds = max(4, args.target_rounds)
    latencies, errors, results = [], [], []
    threads = [threading.Thread(target=run_session,
                                args=(base, rounds, latencies,
                                      errors, results))
               for _ in range(args.concurrency)]
    t0 = time.time()
    [t.start() for t in threads]
    [t.join() for t in threads]
    elapsed = time.time() - t0

    report_ok = sum(1 for _, final in results if final == "report")
    total_requests = len(latencies) + len(errors)
    print("== 并发会话压测（mock）==")
    print("并发会话：%d × 每场 %d 轮；请求总数：%d；耗时：%.1fs；吞吐：%.1f req/s"
          % (args.concurrency, rounds, total_requests, elapsed,
             total_requests / elapsed if elapsed else 0))
    print("延迟：p50 %.0fms / p95 %.0fms / max %.0fms"
          % (_pct(latencies, 50) * 1000, _pct(latencies, 95) * 1000,
             (max(latencies) if latencies else 0) * 1000))
    print("错误：%d | 拿到报告的会话：%d/%d"
          % (len(errors), report_ok, args.concurrency))
    if errors:
        print("  错误样例：", errors[:3])

    codes = same_session_burst(base, args.burst, rounds)
    if codes is None:
        print("同会话并发闸：无法建会话")
    else:
        print("同会话并发闸（同时 %d 个请求）：HTTP 状态 %s（409 为预期拒绝）"
              % (args.burst, sorted(codes)))
    return 0


def health_mode(args):
    base = args.target.rstrip("/")
    latencies, errors = [], []
    lock = threading.Lock()

    def worker():
        for _ in range(args.n // args.concurrency):
            try:
                t0 = time.time()
                urllib.request.urlopen(base + "/api/health", timeout=5)
                with lock:
                    latencies.append(time.time() - t0)
            except Exception as error:      # noqa: BLE001
                with lock:
                    errors.append(type(error).__name__)

    threads = [threading.Thread(target=worker) for _ in range(args.concurrency)]
    t0 = time.time()
    [t.start() for t in threads]
    [t.join() for t in threads]
    elapsed = time.time() - t0
    print("== 健康检查并发烟测（真实服务）==")
    print("请求：%d；耗时：%.1fs；吞吐：%.0f req/s"
          % (len(latencies) + len(errors), elapsed,
             (len(latencies) + len(errors)) / elapsed if elapsed else 0))
    print("p50 %.1fms / p95 %.1fms / 错误：%d"
          % (_pct(latencies, 50) * 1000, _pct(latencies, 95) * 1000, len(errors)))
    return 0


def main():
    parser = argparse.ArgumentParser(description="云端压测/并发自检")
    parser.add_argument("--concurrency", type=int, default=16,
                        help="并发会话数（mock 模式）/ 并发线程数（health 模式）")
    parser.add_argument("--target-rounds", type=int, default=3,
                        help="每场目标轮数（mock 模式）")
    parser.add_argument("--port", type=int, default=5099, help="mock 服务端口")
    parser.add_argument("--burst", type=int, default=8,
                        help="同会话并发请求数（并发闸检查）")
    parser.add_argument("--health", action="store_true", help="健康检查并发烟测")
    parser.add_argument("--target", default="http://127.0.0.1:5000",
                        help="health 模式的目标地址")
    parser.add_argument("-n", type=int, default=200, help="health 模式总请求数")
    args = parser.parse_args()
    if args.health:
        return health_mode(args)
    return mock_mode(args)


if __name__ == "__main__":
    sys.exit(main())
