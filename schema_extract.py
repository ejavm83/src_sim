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
    from standard_schema_bridge import ensure_logistics_section

    data = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return ensure_logistics_section(data)


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
        "당신은 제조·물류 공정의 '표준 JSON'을 완성하는 전문가입니다.\n"
        "아래 '표준 JSON' 구조 전체를 검토하고, 두 가지 방식으로 updates 배열을 채우세요.\n\n"
        "【1】 문서 기반 갱신 — 공정 설명 문서가 명시하거나 수치로 분명히 함의하는 값\n"
        "【2】 자동 추론 갱신 — 문서 맥락에서 업계 표준·물리 관계·설계 공식으로 합리적으로 결정 가능한 값\n\n"
        "영역별 우선 매핑:\n"
        "■ logistics_process.* — 5단계 하이브리드 물류 시뮬(입고·선별·용해·주조·출하). "
        "공정 설명 MD의 트럭·계근·하역·압착·용해·주조·출하 수치는 이 영역을 우선 갱신하세요.\n"
        "  예) logistics_process.inbound.trucks_per_day, logistics_process.inbound.unload_min\n"
        "  예) logistics_process.sorting.press_min_per_block, logistics_process.melting.melting_min\n"
        "  예) logistics_process.casting.flake_ratio, logistics_process.outbound.truck_capacity_ton\n"
        "  단위: 시간=분(min), 중량=톤(t), 시각=자정 기준 분(10시→600), 비율=0~1(80%→0.8, 3:7→0.3)\n"
        "■ product_master / bom / process_routing / recipe 등 — 제품·BOM·케이블 공정(신선·연선·압출) 관련\n"
        "  예) product_master.cable_design.conductor.cross_section, process_routing.steps[0].std_speed\n\n"
        "규칙:\n"
        "- path는 표준 JSON의 실제 경로를 점/대괄호로 표기합니다.\n"
        '- value는 항상 문자열로 반환합니다(숫자도 "2.5", 불리언도 "true"). '
        "표준값 단위에 맞춰 환산하세요.\n"
        "- 표준 JSON에 이미 있는 경로만 업데이트합니다. 없는 새 항목은 updates에 넣지 말고 "
        "ambiguous_items에 설명으로 남기세요.\n"
        "- 파생값(왕복 횟수·시간당 산출량 등)은 추출하지 말고, 입력 파라미터만 갱신하세요.\n"
        "- 추론 근거가 불확실하거나 가정이 많이 필요한 항목은 updates가 아닌 ambiguous_items에 기재하세요.\n"
        "- evidence 필드에는 ① 문서 발췌 또는 ② 추론 근거(공식·업계 기준)를 간략히 적습니다.\n"
        "- 문서가 다뤘어야 하는데 빠진 핵심 항목은 missing_fields에, 모호하거나 확인이 필요한 사항은 "
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


# ── 도메인 독립적 JSON 생성 ──────────────────────────────────────────────────────

def _domain_wrapper_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "json_content": {"type": "string"},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
            "ambiguous_items": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["domain", "json_content", "missing_fields", "ambiguous_items"],
        "additionalProperties": False,
    }


def _domain_system_prompt() -> str:
    return (
        "당신은 어떤 도메인의 문서든 읽고 그 내용에 최적화된 표준 JSON을 처음부터 설계·완성하는 전문가입니다.\n\n"
        "주어진 문서의 도메인·업종·공정을 파악하고, 해당 분야에 맞는 구조화된 JSON을 설계·완성하세요.\n\n"
        "설계 원칙:\n"
        "1. 문서의 도메인을 파악하고 그에 맞는 최상위 섹션을 결정하세요.\n"
        "2. 문서에서 언급된 모든 공정 단계·설비·파라미터·품질 기준·수치를 포함하세요.\n"
        "3. 문서에 명시된 값은 정확히 채우고, 해당 업계 표준으로 추론 가능한 값도 포함하세요.\n"
        "4. 값이 없거나 불확실한 항목은 null로 두세요.\n"
        "5. JSON 키는 영문 snake_case, 값은 한국어·영어 혼용 가능합니다.\n\n"
        "반드시 포함할 최상위 섹션 (도메인에 맞게 구성):\n"
        "- _meta: domain명, doc_summary, version\n"
        "- process_overview: 공정/서비스 개요, 목적, 산출물\n"
        "- process_steps: 단계별 상세 배열 (name, description, duration_min, equipment, parameters)\n"
        "- materials_or_inputs: 원자재·입력물 (spec, unit, quantity)\n"
        "- equipment_or_resources: 설비·도구·인력 (count, capacity, unit)\n"
        "- quality_standards: 품질 기준·검사 항목·합격 기준\n"
        "- production_parameters: 처리량·효율 관련 핵심 수치\n"
        "- simulation_parameters: 시뮬레이션에 활용할 정량적 파라미터\n\n"
        "json_content 필드에 완성된 JSON을 유효한 JSON 문자열로 반환하세요.\n"
        "domain 필드에 도메인명을 한 줄로 적어주세요 (예: '자동차 전선 제조').\n"
        "문서에서 파악이 어렵거나 모호한 항목은 ambiguous_items에 한국어로 적어주세요.\n"
        "중요하지만 문서에 누락된 항목은 missing_fields에 한국어로 적어주세요.\n"
    )


def generate_domain_json(md_text: str) -> dict[str, Any]:
    """MD 내용으로부터 도메인에 맞는 표준 JSON을 처음부터 생성한다.

    반환값은 std_schema_result와 동일한 구조:
    {updated, diffs, skipped, missing, ambiguous, domain}
    """
    from llm_config import generate_structured_json

    if not md_text.strip():
        raise RuntimeError("문서가 비어 있습니다.")

    text = generate_structured_json(_domain_system_prompt(), _domain_wrapper_schema(), md_text)
    try:
        wrapper = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"모델 응답을 JSON으로 해석하지 못했습니다: {e}") from e

    json_str = wrapper.get("json_content") or "{}"
    try:
        domain_json = json.loads(json_str)
    except json.JSONDecodeError:
        domain_json = {"_meta": {"domain": wrapper.get("domain", ""), "parse_error": True}, "_raw": json_str[:800]}

    return {
        "updated": domain_json,
        "diffs": [],
        "skipped": [],
        "missing": wrapper.get("missing_fields") or [],
        "ambiguous": wrapper.get("ambiguous_items") or [],
        "domain": wrapper.get("domain", ""),
    }
