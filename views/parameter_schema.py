"""추출 파라메터를 JSON 스키마(+ 현재값 인스턴스)로 보여주는 뷰.

`llm_config.FIELDS`(공정 설명 문서 → SimulationConfig 추출 대상)를 근거로 다음을 만든다.

- **JSON Schema**(Draft 2020-12): 공정 단계(inbound/sorting/melting/casting/outbound)별로
  중첩된 객체. 각 필드에 `type`·`title`(라벨)·`description`·`unit`·`default`를 담는다.
- **KEY_META**: 필드(json_key)별 메타 평면 사전 — `cable_schema_editor.html`의 KEY_META와
  같은 형태(desc/unit/type/required/example)이되 이 앱의 실제 추출 필드로 채운다.
- **인스턴스**: 현재 설정값(마지막 실행 / 문서 적용값 / 기본값)을 채운 JSON.

참고 문서(`기술노트_공정시뮬레이션`, `cable_schema_editor`)의 "JSON 스키마로 본다"라는
표현 방식을, 케이블 예시가 아니라 이 앱이 **실제로 추출하는** 파라메터에 적용한 것이다.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from config import DEFAULT_CONFIG, SimulationConfig
from llm_config import FIELDS, _SECTION_LABEL

# 단계 표시 순서(= SimulationConfig 하위 객체 순서).
_SECTION_ORDER: list[str] = ["inbound", "sorting", "melting", "casting", "outbound"]

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://src-sim-llm/schemas/process_logistics_params/1.0"
SCHEMA_TITLE = "공정 물류 시뮬레이션 — 추출 파라메터 스키마"
SCHEMA_DESC = (
    "공정 설명 문서(자연어)에서 LLM이 추출해 SimulationConfig에 반영하는 입력 파라메터의 구조. "
    "단위 규약: 시간=분(min), 중량=톤(t), 시각=자정 기준 분, 비율=0~1 소수."
)


# ── 빌더 ───────────────────────────────────────────────────────────────────


def _default_value(sub: str, attr: str) -> int | float | None:
    """코드·엑셀 기본 Config에서 (sub, attr)의 기본값을 읽는다."""
    try:
        return getattr(getattr(DEFAULT_CONFIG, sub), attr)
    except Exception:  # noqa: BLE001
        return None


def _describe(label: str, hint: str | None) -> str:
    return f"{label} — {hint}" if hint else label


def _field_node(
    json_key: str, sub: str, attr: str, jtype: str, label: str, unit: str, hint: str | None
) -> dict[str, Any]:
    """필드 1개의 JSON Schema 노드(타입·라벨·설명·단위·기본값)."""
    node: dict[str, Any] = {
        "type": jtype,  # "integer" | "number"
        "title": label,
        "description": _describe(label, hint),
    }
    if unit:
        node["unit"] = unit  # 커스텀 키워드(표준 JSON Schema 외 — 단위 표기용)
    dv = _default_value(sub, attr)
    if dv is not None:
        node["default"] = dv
        node["examples"] = [dv]
    node["x-json-key"] = json_key  # 평면 추출 키(llm_config 스키마와의 연결고리)
    return node


def _fields_by_section() -> dict[str, list[tuple[str, str, str, str, str, str | None]]]:
    """sub → [(json_key, attr, jtype, label, unit, hint), ...]."""
    grouped: dict[str, list[tuple[str, str, str, str, str, str | None]]] = {}
    for json_key, (sub, attr), jtype, label, unit, hint in FIELDS:
        grouped.setdefault(sub, []).append((json_key, attr, jtype, label, unit, hint))
    return grouped


def build_parameter_json_schema() -> dict[str, Any]:
    """추출 파라메터의 JSON Schema(Draft 2020-12)를 단계별 중첩 구조로 만든다."""
    grouped = _fields_by_section()
    sections: dict[str, Any] = {}
    section_required: list[str] = []
    for sub in _SECTION_ORDER:
        items = grouped.get(sub)
        if not items:
            continue
        props: dict[str, Any] = {}
        req: list[str] = []
        for json_key, attr, jtype, label, unit, hint in items:
            props[attr] = _field_node(json_key, sub, attr, jtype, label, unit, hint)
            req.append(attr)
        sections[sub] = {
            "type": "object",
            "title": _SECTION_LABEL.get(sub, sub),
            "properties": props,
            "required": req,
            "additionalProperties": False,
        }
        section_required.append(sub)
    return {
        "$schema": SCHEMA_DRAFT,
        "$id": SCHEMA_ID,
        "title": SCHEMA_TITLE,
        "description": SCHEMA_DESC,
        "type": "object",
        "properties": sections,
        "required": section_required,
        "additionalProperties": False,
    }


def build_key_meta() -> dict[str, dict[str, Any]]:
    """필드(json_key)별 메타 평면 사전 — cable_schema_editor.html의 KEY_META와 같은 형태."""
    meta: dict[str, dict[str, Any]] = {}
    for json_key, (sub, attr), jtype, label, unit, hint in FIELDS:
        dv = _default_value(sub, attr)
        meta[json_key] = {
            "desc": _describe(label, hint),
            "unit": unit,
            "type": jtype,
            "required": True,
            "section": _SECTION_LABEL.get(sub, sub),
            "default": dv,
            "example": dv,
        }
    return meta


def build_instance(cfg: SimulationConfig) -> dict[str, Any]:
    """현재 Config 값을 스키마와 같은 단계별 중첩 구조로 채운 JSON 인스턴스."""
    grouped = _fields_by_section()
    out: dict[str, Any] = {}
    for sub in _SECTION_ORDER:
        items = grouped.get(sub)
        if not items:
            continue
        values: dict[str, Any] = {}
        for _json_key, attr, _jtype, _label, _unit, _hint in items:
            try:
                values[attr] = getattr(getattr(cfg, sub), attr)
            except Exception:  # noqa: BLE001
                values[attr] = None
        out[sub] = values
    return out


def _meta_dataframe() -> pd.DataFrame:
    """필드 메타를 표(스캔용)로 — 단계·키·라벨·타입·단위·기본값·설명."""
    rows: list[dict[str, Any]] = []
    for json_key, (sub, attr), jtype, label, unit, hint in FIELDS:
        rows.append(
            {
                "단계": _SECTION_LABEL.get(sub, sub),
                "필드(json_key)": json_key,
                "라벨": label,
                "타입": jtype,
                "단위": unit,
                "기본값": _default_value(sub, attr),
                "설명": _describe(label, hint),
            }
        )
    return pd.DataFrame(rows)


# ── 현재값 출처 ─────────────────────────────────────────────────────────────


def _current_cfg_and_source() -> tuple[SimulationConfig, str]:
    """인스턴스에 채울 현재 Config와 그 출처 설명."""
    run = st.session_state.get("last_run")
    if run and run.get("cfg") is not None:
        return run["cfg"], "마지막 시뮬레이션 실행 설정"
    extracted = st.session_state.get("extracted_config")
    if extracted is not None:
        return extracted, "문서 추출 적용값"
    return DEFAULT_CONFIG, "엑셀·코드 기본값"


# ── 렌더 ───────────────────────────────────────────────────────────────────


def _json_bytes(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def render_section() -> None:
    """📊 파라메터 탭 안에서 호출되는 'JSON 스키마' 블록."""
    schema = build_parameter_json_schema()
    key_meta = build_key_meta()
    cfg, source = _current_cfg_and_source()
    instance = build_instance(cfg)

    n_fields = len(FIELDS)
    n_sections = len(schema["properties"])

    st.subheader("🧬 JSON 스키마")
    st.caption(
        "공정 설명 문서에서 **추출하는 파라메터의 구조**를 JSON 스키마로 봅니다. "
        f"추출 대상 **{n_fields}개** 필드를 **{n_sections}개** 공정 단계로 묶었고, 각 필드에는 "
        "타입·라벨·설명·단위·기본값이 담겨 있습니다. (참고: `cable_schema_editor`·`기술노트` 문서의 표현 방식)"
    )

    tab_schema, tab_instance, tab_meta = st.tabs(
        ["JSON 스키마", f"현재값 인스턴스 · {source}", "필드 메타 표"]
    )

    with tab_schema:
        st.caption(
            "JSON Schema (Draft 2020-12). 단계(▶)를 펼치면 필드별 타입·단위·기본값을 볼 수 있습니다. "
            "`unit`·`x-json-key`는 단위 표기·평면 추출 키 연결용 커스텀 키워드입니다."
        )
        st.json(schema, expanded=2)
        st.download_button(
            "스키마 JSON 내려받기",
            data=_json_bytes(schema),
            file_name="extracted_params.schema.json",
            mime="application/json",
            use_container_width=True,
            key="param_schema_dl",
        )

    with tab_instance:
        st.caption(
            f"현재 적용된 파라메터 값을 스키마와 같은 구조로 채운 인스턴스입니다. 출처: **{source}**. "
            "(우선순위: 마지막 실행 → 문서 적용값 → 기본값)"
        )
        st.json(instance, expanded=2)
        st.download_button(
            "현재값 JSON 내려받기",
            data=_json_bytes(instance),
            file_name="extracted_params.instance.json",
            mime="application/json",
            use_container_width=True,
            key="param_instance_dl",
        )

    with tab_meta:
        st.caption(
            "필드별 메타데이터를 한눈에 봅니다. 같은 내용을 평면 사전(KEY_META)으로도 내려받을 수 있습니다."
        )
        st.dataframe(_meta_dataframe(), use_container_width=True, hide_index=True)
        st.download_button(
            "KEY_META JSON 내려받기",
            data=_json_bytes(key_meta),
            file_name="extracted_params.key_meta.json",
            mime="application/json",
            use_container_width=True,
            key="param_key_meta_dl",
        )
