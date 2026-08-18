"""🔬 프로세스 분석 — LLM이 현재 JSON·MD를 읽고 KPI·병목·개선안을 도출한다."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

_RESULT_KEY = "_domain_analysis_result"
_SIM_BRIEF_KEY = "_domain_analysis_sim_brief"
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


def _simulation_brief() -> str:
    """CMS 시뮬레이션(SimPy) 결과를 병목 분석용 사실 묶음으로 가져온다.

    문서만 읽으면 "가장 느린 공정이 병목"이라는 뻔한 결론밖에 안 나온다.
    설비가 몇 대인지, 여러 라인이 한 설비를 두고 어떻게 다투는지, 그래서 어느
    라인이 계획을 못 채우는지는 **실제로 돌려 봐야** 알 수 있다. 이미 실행한
    결과가 있으면 그것을 쓰고, 없으면 여기서 한 번 돌린다.
    """
    try:
        from cms_report import analyze_cms, bottleneck_brief, bottleneck_report
        from ui.cms_sidebar import spec_config
        from views.cms_sim_view import RUN_KEY

        run = st.session_state.get(RUN_KEY)
        if run:
            m, a = run["metrics"], run["analysis"]
            cfg = run.get("cfg") or st.session_state.get("cms_sidebar_cfg") or spec_config()
        else:
            from cms_simulation import run_cms_simulation

            cfg = st.session_state.get("cms_sidebar_cfg") or spec_config()
            m = run_cms_simulation(cfg)
            a = analyze_cms(m, cfg)
        return bottleneck_brief(bottleneck_report(m, cfg, a))
    except Exception:
        return ""


def _analysis_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "detail": {"type": "string"},
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
                        "basis": {"type": "string"},
                    },
                    "required": ["name", "value", "basis"],
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
                        "equipment": {"type": "string"},
                        "issue": {"type": "string"},
                        "evidence": {"type": "string"},
                        "impact": {"type": "string"},
                        "severity": {"type": "string"},
                    },
                    "required": ["step", "issue", "evidence"],
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
        "required": ["summary", "detail", "kpis", "bottlenecks", "recommendations"],
        "additionalProperties": False,
    }


def _system_prompt(domain_json: dict, md_text: str, sim_brief: str = "") -> str:
    json_snippet = json.dumps(domain_json, ensure_ascii=False, indent=2)[:4000]
    md_snippet = md_text[:3000]
    return (
        "당신은 공정·업무 프로세스 분석 전문가입니다.\n"
        "아래 공정 설명(MD)과 표준 JSON을 분석해 KPI·병목·개선안을 도출하세요.\n\n"
        "분석 요구사항:\n"
        "- summary: 전체 공정을 2~3문장으로 요약 (한눈에 읽는 개요)\n"
        "- detail: 공정 상세 설명 — 원자재 입고부터 출하까지 흐름을 따라 단계별로, "
        "각 단계가 무엇을 하는 곳이고 어떤 설비·수치가 나오는지 일반인도 이해할 수 있게 "
        "마크다운(소제목·목록)으로 풀어서 설명. 문서에 있는 실제 수치를 인용\n"
        "- domain: 도메인명 한 줄\n"
        "- kpis: 주요 성과지표 5~10개 (처리량, 리드타임, 효율, 불량률 등)\n"
        "  status는 good/warning/bad 중 하나\n"
        "  basis는 그 값을 어떻게 구했는지 — 반드시 원본 문서의 실제 수치를 대입한 "
        "산술 수식(예: '13대 × 19.8t = 257.4t/월')과 출처(문서의 어느 표·문장인지)를 "
        "일반인도 이해할 수 있는 쉬운 한국어 1~3문장으로. 추정이면 '추정'이라고 명시\n"
        "  value에는 숫자만, unit에는 단위만 — value에 단위를 중복해 넣지 마세요\n"
        "- process_flow: 공정 단계별 소요시간·처리량·가동률 추정\n"
        "- bottlenecks: 병목 3~6개. **아래 [SimPy 시뮬레이션 결과]의 수치만 근거로** 쓰세요\n"
        "  step은 공정 단계, equipment는 설비명과 대수(예: '조사기 1대')\n"
        "  issue는 왜 병목인지 한 문장\n"
        "  evidence는 반드시 시뮬레이션 수치를 인용한 산술 근거 "
        "(예: '요구 824h ÷ 가용 497h = 부하 166%, 평균 대기 101h, 최대 대기열 210개')\n"
        "  impact는 이 병목이 **어느 라인의 생산을 얼마나 막았는지** 수치로 "
        "(예: 'Cu19가 이 설비 앞에서 7,200h 대기 → 달성률 47%')\n"
        "  severity는 high/medium/low\n"
        "  ⚠ '가장 느린 공정이 병목'처럼 문서만 읽어도 아는 뻔한 서술은 금지합니다. "
        "설비 대수·공유 경합·대기열처럼 **돌려 봐야 아는 것**을 쓰세요\n"
        "- recommendations: 개선 제안 (priority: high/medium/low). "
        "expected_effect에는 시뮬레이션이 계산한 효과를 수치로 "
        "(예: '1대 증설 시 부하 166% → 83%')\n"
        "- simulation_insights: 시뮬레이션 관점에서의 핵심 통찰\n\n"
        "JSON에 수치가 있으면 그 수치를 기반으로 정량적으로 분석하세요.\n\n"
        + (
            "\n[SimPy 시뮬레이션 결과] — 아래는 이 공정을 실제로 돌려 본 결과입니다. "
            "병목·개선안은 반드시 이 수치를 근거로 삼으세요.\n"
            f"{sim_brief}\n\n"
            if sim_brief
            else ""
        )
        + f"표준 JSON:\n```json\n{json_snippet}\n```\n\n"
        + f"공정 설명(MD):\n{md_snippet}"
    )


def _run_analysis() -> None:
    from llm_config import generate_structured_json

    cur_json = _current_json()
    cur_md = _current_md()

    if not cur_md.strip() and not cur_json:
        st.warning("공정 설명 MD 또는 표준 JSON이 없습니다. 먼저 📄 공정 설명 탭에서 문서를 작성하거나 불러오세요.")
        return

    with st.spinner("SimPy로 공정을 돌려 본 뒤 분석하는 중..."):
        try:
            sim_brief = _simulation_brief()
            st.session_state[_SIM_BRIEF_KEY] = sim_brief
            prompt_input = cur_md or json.dumps(cur_json, ensure_ascii=False)[:2000]
            text = generate_structured_json(
                _system_prompt(cur_json, cur_md, sim_brief),
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

    # ── 요약 · 상세 설명 ──
    if result.get("summary"):
        st.markdown("#### 📝 공정 요약")
        st.info(result["summary"])
    if result.get("detail"):
        with st.expander("📖 공정 상세 설명 — 단계별로 풀어 보기", expanded=False):
            st.markdown(result["detail"])

    # ── KPI ──
    kpis = result.get("kpis") or []
    if kpis:
        st.markdown("#### 📊 주요 KPI")
        st.caption("각 카드 아래 **🧮 근거**를 누르면 그 값을 어떻게 구했는지 나옵니다.")
        n_cols = min(len(kpis), 4)
        cols = st.columns(n_cols)
        for i, kpi in enumerate(kpis[:8]):
            with cols[i % n_cols]:
                status_icon = {"good": "🟢", "warning": "🟡", "bad": "🔴"}.get(
                    str(kpi.get("status", "")).lower(), "🔵"
                )
                value = str(kpi.get("value", "-")).strip()
                unit = str(kpi.get("unit", "")).strip()
                # LLM이 value에 단위까지 넣었으면 중복 표기하지 않는다 (예: "80t/월" + "t")
                shown = value if not unit or unit in value else f"{value} {unit}"
                st.metric(label=f"{status_icon} {kpi.get('name', '')}", value=shown)
                basis = str(kpi.get("basis", "")).strip()
                with st.popover("🧮 근거", use_container_width=True):
                    st.markdown(f"**{kpi.get('name', '')} = {shown}**")
                    if basis:
                        st.markdown(basis)
                    else:
                        st.markdown(
                            "이 결과는 근거 필드가 없던 이전 버전에서 분석된 것입니다. "
                            "**🚀 분석 실행**을 다시 누르면 산출 수식과 출처가 함께 나옵니다."
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
        st.caption(
            "문서를 읽어 짐작한 것이 아니라 **SimPy로 공정을 실제로 돌려 본 결과**입니다. "
            "설비 대수·라인 간 경합·대기열처럼 돌려 봐야 알 수 있는 것만 담았습니다."
        )
        severity_color = {"high": "#fee2e2", "medium": "#fef9c3", "low": "#f0fdf4"}
        for b in bottlenecks:
            sev = str(b.get("severity", "medium")).lower()
            color = severity_color.get(sev, "#f8f8f8")
            border = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}.get(sev, "#f59e0b")
            equip = str(b.get("equipment", "")).strip()
            head = f'{b.get("step", "")}' + (f' · {equip}' if equip else "")
            parts = [
                f'<div style="background:{color};border-radius:8px;padding:0.65rem 1rem;'
                f'margin-bottom:0.5rem;border-left:4px solid {border};">'
                f'<strong>{head}</strong> — {b.get("issue", "")}'
            ]
            if b.get("evidence"):
                parts.append(
                    "<br><span style='font-size:0.9em'>🧮 <b>근거</b> "
                    f"<code>{b['evidence']}</code></span>"
                )
            if b.get("impact"):
                parts.append(
                    f"<br><small style='color:#6b7280'>📉 영향 — {b['impact']}</small>"
                )
            parts.append("</div>")
            st.markdown("".join(parts), unsafe_allow_html=True)

        brief = st.session_state.get(_SIM_BRIEF_KEY, "")
        if brief:
            with st.expander("🔬 이 진단이 나온 SimPy 원시 결과 보기", expanded=False):
                st.caption("LLM에 근거로 넘긴 시뮬레이션 수치 그대로입니다.")
                st.code(brief, language="text")

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
