"""공정 설명 마크다운 읽기 전용 미리보기용: 디스크/편집기에는 태그 없이 두고, 웹 표시 시에만 수치·단위 구간을 강조."""

from __future__ import annotations

import re
from typing import Iterable

# 원문과 동일한 톤(주황·굵게) — 표시 전용, 파일에는 저장하지 않음
_METRIC_SPAN = '<span style="color:#b45309;font-weight:700">{}</span>'

# 긴 구간부터 매칭해 짧은 부분식에 잘리지 않게 순서 유지
_HIGHLIGHT_PATTERNS: tuple[str, ...] = (
    r"정오\(12시\)\s*이전\s*오전",
    r"\d{2}시부터\s*\d{2}시",
    r"거의\s+0에\s+가까운\s+중량\(영점\)",
    r"\(\d+kg\)",
    r"\d+~\d+톤급?",
    r"합쳐\s+약\s+[\d.]+\s*시간(?:\([^)]+\))?",  # 합쳐 약 13시간(780분)
    r"합쳐\s+약\s+[\d.]+\s*분",
    r"(?:약\s+)?\d+(?:\.\d+)?(?:\s*[×x]\s*\d+(?:\.\d+)?)+\s*=\s*약\s*\d+(?:\.\d+)?\s*톤/일",
    r"(?:약\s+)?\d+(?:\.\d+)?(?:\s*[×x]\s*\d+(?:\.\d+)?)+\s*=\s*약\s*\d+(?:\.\d+)?\s*톤",
    r"약\s+\d+시간에서\s*\d+시간",
    r"약\s+[\d.]+\s*톤에서\s*[\d.]+\s*톤",
    r"\d+(?:\.\d+)?분에\s+\d+(?:\.\d+)?톤",
    r"(?:용해|산화|슬래깅|환원)\s+\d+(?:\.\d+)?(?:시간|분|초)",
    r"큐프레이크\s+\d+%,\s*SCR\s+\d+%",
    r"시간에\s+약\s+[\d.]+\s*파레트",
    r"(?:약\s+)?\d+(?:\.\d+)?(?:\s*[×x]\s*\d+(?:\.\d+)?\s*m)+쯤?",
    r"(?:약\s+)?[\d.]+\s*m\s*[×x]\s*[\d.]+\s*m",
    r"파레트\s+\d+\s*개",
    r"\d+\s*번\s*왕복",
    r"(?:약\s+)?\d+(?:\.\d+)?(?:톤|대|분|초|시간|파레트|개|기|/일|톤분)(?:짜리|까지|전후|수준|급)?",
    r"(?:약\s+)?\d+(?:\.\d+)?(?=\s*정도)",
    r"\d+(?:\.\d+)?(?:톤|대|분|초|시간|파레트|개|기|/일|톤분)(?:짜리|까지)?",
    r"약\s+[\d.]+\s*%",
    r"\d+(?:\.\d+)?\s*%가",
    r"\d+(?:\.\d+)?\s*%",
)


def _split_frontmatter(md: str) -> tuple[str, str]:
    """YAML 프론트매터가 있으면 (앞부분, 본문)으로 분리."""
    if not md.startswith("---"):
        return "", md
    m = re.match(r"^---\s*\n[\s\S]*?\n---\s*\n?", md)
    if not m:
        return "", md
    return md[: m.end()], md[m.end() :]


def _merge_intervals(intervals: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            prev_s, prev_e = merged[-1]
            merged[-1] = (prev_s, max(prev_e, end))
    return merged


def _intervals_for_patterns(text: str, patterns: tuple[str, ...]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for p in patterns:
        try:
            rx = re.compile(p)
        except re.error:
            continue
        for m in rx.finditer(text):
            spans.append((m.start(), m.end()))
    return _merge_intervals(spans)


def _apply_spans(text: str, intervals: list[tuple[int, int]]) -> str:
    if not intervals:
        return text
    out: list[str] = []
    pos = 0
    for start, end in intervals:
        if start < pos:
            continue
        out.append(text[pos:start])
        chunk = text[start:end]
        if "<span" in chunk:
            out.append(chunk)
        else:
            out.append(_METRIC_SPAN.format(chunk))
        pos = end
    out.append(text[pos:])
    return "".join(out)


def markdown_for_preview(md: str) -> str:
    """저장 형식 그대로인 마크다운에, 미리보기용 인라인 강조만 덧씌웁니다."""
    head, body = _split_frontmatter(md)
    intervals = _intervals_for_patterns(body, _HIGHLIGHT_PATTERNS)
    return head + _apply_spans(body, intervals)
