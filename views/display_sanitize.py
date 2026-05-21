"""Streamlit 등 웹 UI에 보이는 문자열에서 특정 용어를 제거. (디스크 원문은 별도 편집 권장)"""

from __future__ import annotations

_REDACTED_SUBSTRINGS: tuple[str, ...] = (
    "한국미래소재",
    "군산",
)


def sanitize_display_text(text: str) -> str:
    """표시 전용: 위 용어를 빈 문자열로 치환한다."""
    out = text
    for s in _REDACTED_SUBSTRINGS:
        out = out.replace(s, "")
    return out
