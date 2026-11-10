# -*- coding: utf-8 -*-
"""流式分句（2026-11-10，LLM 流式 + 分句 TTS 的基础件）。

把 LLM 的增量 token 攒成"可以送 TTS 的句子"：纯函数式、无 IO、可单测。

规则（刻意保守 —— 宁可晚半句，也不要把半句念出来）：
* 遇到 。！？!? 或换行 → 断句；
* 断出来的句子太短（< min_len，默认 6 字）先攒着，与下一句合并（避免"好。"单独合成）；
* **长句没结束标点时**：缓冲超过 soft_max（默认 36 字）→ 在最近的逗号/顿号处切一段
  （2026-11-11 实测：面试官的问句常是"逗号连成的长句"，只按句号切等于没有流式）；
* 单句超过 max_len（默认 120 字）→ 同样在软边界处强制断开。
"""

import re

_BOUNDARY = re.compile(r"[。！？!?\n]")
_SOFT = re.compile(r"[，、,;；：]")


class SentenceAccumulator:
    """增量文本 → 完整句子列表。用法见 cloud/app.py 的 /api/interview/live。"""

    def __init__(self, min_len=6, max_len=120, soft_max=36):
        self.min_len = max(1, int(min_len))
        self.max_len = max(self.min_len * 2, int(max_len))
        # 长句在软边界（逗号等）上的切分上限：超过它就切一段，保证能"边生成边合成"。
        self.soft_max = max(self.min_len * 2, int(soft_max))
        self.buf = ""

    def feed(self, delta):
        """喂一段增量文本，返回**立刻可以处理**的完整句子列表（可能为空）。"""
        if not delta:
            return []
        self.buf += delta
        out = []
        while True:
            cut = self._find_cut()
            if cut is None:
                break
            sentence = self.buf[:cut].strip()
            self.buf = self.buf[cut:]
            if sentence:
                out.append(sentence)
        return out

    def flush(self):
        """收尾：把剩余缓冲作为最后一句返回（可能没有结束标点）。"""
        rest = self.buf.strip()
        self.buf = ""
        return [rest] if rest else []

    def _find_cut(self):
        """返回可切分位置（切在边界符之后）；没有合适的边界返回 None。

        取**最早**的合法切点：短句边界（。！？等，长度够）与长句软边界（逗号等，
        超过 soft_max 时）谁先满足就用谁 —— 否则"一整句 48 字、末尾才问号"的问句
        会整段等到最后才合成（2026-11-11 实测）。
        """
        hard = None
        for match in _BOUNDARY.finditer(self.buf):
            if len(self.buf[:match.end()].strip()) >= self.min_len:
                hard = match.end()
                break

        soft = None
        if len(self.buf) > self.soft_max:
            for match in _SOFT.finditer(self.buf):
                if self.min_len <= match.end() <= self.soft_max:
                    soft = match.end()

        if hard is not None or soft is not None:
            return min(cut for cut in (hard, soft) if cut is not None)

        if len(self.buf) > self.max_len:
            best = None
            for match in _SOFT.finditer(self.buf):
                if self.min_len <= match.end() <= self.max_len:
                    best = match.end()
            return best if best is not None else self.max_len
        return None
