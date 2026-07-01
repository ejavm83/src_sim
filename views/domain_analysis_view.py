"""🔬 프로세스 분석 — LLM이 현재 JSON·MD를 읽고 KPI·병목·개선안을 도출한다."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

_RESULT_KEY = "_domain_analysis_result"
_BTN_KEY = "_domain_analysis_btn"


def _current_json() -> dict[str, Any]:
    result = st.session_state.get("std_schema_result")
    if isinstance(result, dict) and "updated" in result:
        return result["updated"]
    try:
        from schema_extract import load_base_schema
        return load_base_schema()
    except Exception:
        return {}


def _current_md() -> str:
    try:
        from views.process_description import _EDIT_MODE_KEY, _SESSION_DRAFT_KEY, _load_text
        if st.session_state.get(_EDIT_MODE_KEY):
            return str(st.session_state.get(_SESSION_DRAFT_KEY, ""))
        return _load_text()
    except Exception:
        return ""


def _analysis_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "domain": {"type": "string"},
            "kpis": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": "string"},
                        "unit": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["name", "value"],
                    "additionalProperties": False,
                },
            },
            "process_flow": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},
                        "duration": {"type": "string"},
                        "throughput": {"type": "string"},
                        "utilization": {"type": "string"},
                    },
                    "required": ["step"],
                    "additionalProperties": False,
                },
            },
            "bottlenecks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},
                        "issue": {"type": "string"},
                        "impact": {"type": "string"},
                        "severity": {"type": "string"},
                    },
                    "required": ["step", "issue"],
                    "additionalProperties": False,
                },
            },
            "recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "priority": {"type": "string"},
                        "action": {"type": "string"},
                        "expected_effect": {"type": "string"},
                    },
                    "required": ["priority", "action"],
                    "additionalProperties": False,
                },
            },
            "simulation_insights": {"type": "string"},
        },
        "required": ["summary", "kpis", "bottlenecks", "recommendations"],
        "additionalProperties": False,
    }


def _system_prompt(domain_json: dict, md_text: str) -> str:
    json_snippet = json.dumps(domain_json, ensure_ascii=False, indent=2)[:4000]
    md_snippet = md_text[:3000]
    return (
        "당신은 공정·업무 프로세스 분석 전문가입니다.\n"
        "아래 공정 설명(MD)과 표준 JSON을 분석해 KPI·병목·개선안을 도출하세요.\n\n"
        "분석 요구사항:\n"
        "- summary: 전체 공정을 2~3문장으로 요약\n"
        "- domain: 도메인명 한 줄\n"
        "- kpis: 주요 성과지표 5~10개 (처리량, 리드타임, 효율, 불량률 등)\n"
        "  status는 good/warning/bad 중 하나\n"
        "- process_flow: 공정 단계별 소요시간·처리량·가동률 추정\n"
        "- bottlenecks: 병목 단계, 이슈, 영향도 (severity: high/medium/low)\n"
        "- recommendations: 개선 제안 (priority: high/medium/low)\n"
        "- simulation_insights: 시뮬레이션 관점에서의 핵심 통찰\n\n"
        "JSON에 수치가 있으면 그 수치를 기반으로 정량적으로 분석하세요.\n\n"
        f"표준 JSON:\n```json\n{json_snippet}\n```\n\n"
        f"공정 설명(MD):\n{md_snippet}"
    )


def _run_analysis() -> None:
    from llm_config import generate_structured_json

    cur_json = _current_json()
    cur_md = _current_md()

    if not cur_md.strip() and not cur_json:
        st.warning("공정 설명 MD 또는 표준 JSON이 없습니다. 먼저 📄 공정 설명 탭에서 문서를 작성하거나 불러오세요.")
        return

    with st.spinner("프로세스를 분석하는 중..."):
        try:
            prompt_input = cur_md or json.dumps(cur_json, ensure_ascii=False)[:2000]
            text = generate_structured_json(
                _system_prompt(cur_json, cur_md),
                _analysis_schema(),
                prompt_input,
            )
            result = json.loads(text)
            st.session_state[_RESULT_KEY] = result
            if result.get("domain"):
                st.session_state["_domain_name"] = result["domain"]
        except Exception as exc:
            st.error(f"분석 실패: {exc}")


def render_page() -> None:
    domain = st.session_state.get("_domain_name", "")
    title = f"🔬 프로세스 분석 — {domain}" if domain else "🔬 프로세스 분석"
    st.header(title)
    st.caption(
        "현재 **📄 공정 설명**과 **📐 표준 JSON**을 바탕으로 LLM이 KPI·병목·개선안을 도출합니다. "
        "먼저 공정 설명 MD를 작성하고, **📐 표준 JSON** 탭에서 「MD에서 JSON 생성」을 실행한 뒤 분석하세요."
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🚀 분석 실행", type="primary", key=_BTN_KEY, use_container_width=True):
            _run_analysis()
            st.rerun()
    with col2:
        if st.session_state.get(_RESULT_KEY):
            if st.button("🗑️ 결과 초기화", key=f"{_BTN_KEY}_clear"):
                st.session_state.pop(_RESULT_KEY, None)
                st.rerun()

    result = st.session_state.get(_RESULT_KEY)
    if not result:
        st.info(
            "「분석 실행」 버튼을 누르면 현재 MD·JSON을 기반으로 프로세스 분석을 시작합니다.\n\n"
            "**순서:** 📄 공정 설명에 문서 작성/업로드 → 📐 표준 JSON에서 「MD에서 JSON 생성」 → 여기서 「분석 실행」"
        )
        return

    # ── 요약 ──
    if result.get("summary"):
        st.info(result["summary"])

    # ── KPI ──
    kpis = result.get("kpis") or []
    if kpis:
        st.markdown("#### 📊 주요 KPI")
        n_cols = min(len(kpis), 4)
        cols = st.columns(n_cols)
        for i, kpi in enumerate(kpis[:8]):
            with cols[i % n_cols]:
                status_icon = {"good": "🟢", "warning": "🟡", "bad": "🔴"}.get(
                    str(kpi.get("status", "")).lower(), "🔵"
                )
                unit = kpi.get("unit", "")
                st.metric(
                    label=f"{status_icon} {kpi.get('name', '')}",
                    value=f"{kpi.get('value', '-')}{' ' + unit if unit else ''}",
                )

    # ── 공정 흐름 ──
    flow = result.get("process_flow") or []
    if flow:
        st.markdown("#### 🔄 공정 흐름 분석")
        import pandas as pd
        rows = [
            {
                "공정 단계": s.get("step", ""),
                "소요 시간": s.get("duration", "-"),
                "처리량": s.get("throughput", "-"),
                "가동률": s.get("utilization", "-"),
            }
            for s in flow
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── 병목 ──
    bottlenecks = result.get("bottlenecks") or []
    if bottlenecks:
        st.markdown("#### ⚠️ 병목 분석")
        severity_color = {"high": "#fee2e2", "medium": "#fef9c3", "low": "#f0fdf4"}
        for b in bottlenecks:
            sev = str(b.get("severity", "medium")).lower()
            color = severity_color.get(sev, "#f8f8f8")
            border = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}.get(sev, "#f59e0b")
            impact_html = f"<br><small style='color:#6b7280'>{b['impact']}</small>" if b.get("impact") else ""
            st.markdown(
                f'<div style="background:{color};border-radius:8px;padding:0.65rem 1rem;'
                f'margin-bottom:0.5rem;border-left:4px solid {border};">'
                f'<strong>{b.get("step", "")}</strong> — {b.get("issue", "")}'
                f'{impact_html}</div>',
                unsafe_allow_html=True,
            )

    # ── 개선 제안 ──
    recs = result.get("recommendations") or []
    if recs:
        st.markdown("#### 💡 개선 제안")
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        for r in recs:
            icon = priority_icon.get(str(r.get("priority", "")).lower(), "🔵")
            effect = f" → *{r['expected_effect']}*" if r.get("expected_effect") else ""
            st.markdown(f"- {icon} **{r.get('action', '')}**{effect}")

    # ── 시뮬레이션 인사이트 ──
    if result.get("simulation_insights"):
        with st.expander("🧠 시뮬레이션 인사이트", expanded=True):
            st.markdown(result["simulation_insights"])
