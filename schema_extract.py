"""표준 공정 JSON을 베이스로, 입력 MD에서 관련 영역/파라미터를 추출해 업데이트한다.

`llm_config.generate_structured_json`(Gemini/OpenAI 공용)으로 문서가 '명시'한 값만
경로(path)+값(value)으로 받아 표준 JSON 사본에 덮어쓴다. 표준값과의 차이(diff),
표준에 없는 경로(skipped), 모델이 표시한 누락/모호 항목을 함께 돌려준다.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "standard_process_schema.json"


def load_base_schema() -> dict[str, Any]:
    """프로젝트에 저장된 표준 공정 JSON."""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _updates_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "value": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["path", "value"],
                    "additionalProperties": False,
                },
            },
            "missing_fields": {"type": "array", "items": {"type": "string"}},
            "ambiguous_items": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["updates"],
        "additionalProperties": False,
    }


def _system_prompt(base: dict[str, Any]) -> str:
    return (
        "당신은 제조 공정의 '표준 JSON'을 한국어 공정 설명 문서로 갱신하는 추출기입니다.\n"
        "아래 '표준 JSON' 구조를 기준으로, 문서가 '명시'하거나 단일 숫자로 분명히 함의하는 값만 골라 "
        "그 경로(path)와 값(value)을 updates 배열로 반환하세요.\n\n"
        "규칙:\n"
        "- path는 표준 JSON의 실제 경로를 점/대괄호로 표기합니다 "
        "(예: product_master.cable_design.conductor.cross_section, process_routing.steps[0].std_speed).\n"
        '- value는 항상 문자열로 반환합니다(숫자도 "2.5", 불리언도 "true"). '
        "표준값 단위에 맞춰 환산하세요(시각→자정 기준 분, 비율→0~1 등).\n"
        "- 표준 JSON에 이미 있는 경로만 업데이트합니다. 없는 새 항목은 updates에 넣지 말고 "
        "ambiguous_items에 설명으로 남기세요.\n"
        "- 문서에 근거가 없으면 추정·생성 금지. 관련 영역만 갱신합니다.\n"
        "- 문서가 다뤘어야 하는데 빠진 핵심 항목은 missing_fields에, 모호하거나 확인이 필요한 발화는 "
        "ambiguous_items에 한국어로 적으세요.\n\n"
        "표준 JSON:\n```json\n"
        + json.dumps(base, ensure_ascii=False, indent=2)
        + "\n```"
    )


def extract_schema_updates(md_text: str) -> dict[str, Any]:
    """문서에서 표준 JSON 업데이트를 추출한다(LLM). 실패 시 RuntimeError."""
    from llm_config import generate_structured_json

    if not md_text.strip():
        raise RuntimeError("문서가 비어 있습니다.")
    base = load_base_schema()
    text = generate_structured_json(_system_prompt(base), _updates_schema(), md_text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:  # noqa: TRY003
        raise RuntimeError(f"모델 응답을 JSON으로 해석하지 못했습니다: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("모델 응답 형식이 올바르지 않습니다.")
    return data


_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _parse_path(path: str) -> list[str | int]:
    toks: list[str | int] = []
    for m in _TOKEN_RE.finditer(path):
        if m.group(1) is not None:
            toks.append(m.group(1))
        else:
            toks.append(int(m.group(2)))
    return toks


def _navigate(obj: Any, toks: list[str | int]) -> tuple[bool, Any]:
    cur = obj
    for t in toks:
        if isinstance(t, int):
            if isinstance(cur, list) and 0 <= t < len(cur):
                cur = cur[t]
            else:
                return False, None
        elif isinstance(cur, dict) and t in cur:
            cur = cur[t]
        else:
            return False, None
    return True, cur


def _coerce_like(raw: str, existing: Any) -> Any:
    """문자열 value를 표준값(existing)의 타입에 맞춰 변환."""
    s = str(raw).strip()
    if isinstance(existing, bool):
        return s.lower() in ("true", "1", "yes", "y", "참", "예")
    if isinstance(existing, int):  # bool은 위에서 처리됨
        try:
            return int(round(float(s)))
        except (TypeError, ValueError):
            return s
    if isinstance(existing, float):
        try:
            return float(s)
        except (TypeError, ValueError):
            return s
    return s


def apply_updates(
    base: dict[str, Any], updates: list[dict[str, Any]] | None
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """표준 JSON 사본에 업데이트를 적용. 반환 (updated, diffs, skipped)."""
    updated = copy.deepcopy(base)
    diffs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for u in updates or []:
        if not isinstance(u, dict):
            continue
        path = str(u.get("path", "")).strip()
        if not path:
            continue
        toks = _parse_path(path)
        if not toks:
            skipped.append({"path": path, "reason": "경로 파싱 실패"})
            continue
        ok, old = _navigate(updated, toks)
        if not ok:
            skipped.append({"path": path, "reason": "표준 JSON에 없는 경로"})
            continue
        if isinstance(old, (dict, list)):
            skipped.append({"path": path, "reason": "객체/배열은 직접 갱신하지 않음"})
            continue
        parent_ok, parent = (
            _navigate(updated, toks[:-1]) if len(toks) > 1 else (True, updated)
        )
        if not parent_ok:
            skipped.append({"path": path, "reason": "상위 경로 없음"})
            continue
        new = _coerce_like(str(u.get("value", "")), old)
        try:
            parent[toks[-1]] = new  # type: ignore[index]
        except Exception:  # noqa: BLE001
            skipped.append({"path": path, "reason": "값 설정 실패"})
            continue
        if old != new:
            diffs.append(
                {
                    "경로": path,
                    "표준값": old,
                    "추출값": new,
                    "근거": str(u.get("evidence", ""))[:120],
                }
            )
    return updated, diffs, skipped
