from __future__ import annotations

import json
from typing import Any

import streamlit as st

from config import SimulationConfig
from report import Analysis
from run_compare import flatten_config
from ui.settings import get_display_name

# UI 라벨 → Gemini 모델 ID (google-generativeai)
GEMINI_MODEL_OPTIONS: dict[str, str] = {
    "Flash (1.5)": "gemini-1.5-flash",
    "Pro (1.5)": "gemini-1.5-pro",
    "Flash (2.0)": "gemini-2.0-flash",
}

QUICK_PROMPTS: list[tuple[str, str]] = [
    (
        "시뮬레이션 파라미터 값 제시",
        "현재 시뮬레이션 설정과 관련해, 주요 파라미터(입고·선별·용해·주조·출하)의 의미와 "
        "이번 실행에 반영된 값을 표로 정리해 줘.",
    ),
    (
        "AI 분석 챗봇 사용법 설명",
        "이 챗봇으로 무엇을 물어볼 수 있는지, 시뮬레이션 결과를 해석할 때의 유의점을 짧게 설명해 줘.",
    ),
    (
        "SCR 공정 단계 설명",
        "이 시뮬레이션이 다루는 5단계 공정(입고→선별·압착→장입·용해→하이브리드 주조→출하)을 "
        "이번 KPI·병목 지표와 연결해 요약해 줘.",
    ),
]


def _load_genai():
    try:
        import google.generativeai as genai

        return genai
    except ImportError:
        return None


def _run_fingerprint(run: dict) -> str:
    cfg: SimulationConfig = run["cfg"]
    analysis: Analysis = run["analysis"]
    payload = {
        "cfg": flatten_config(cfg),
        "summary": dict(analysis.summary),
        "elapsed_s": round(float(run.get("elapsed_s", 0.0)), 3),
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _build_context_prompt(cfg: SimulationConfig, analysis: Analysis) -> str:
    return f"""
당신은 공정 시뮬레이션 결과를 분석하고 사용자의 질문에 답하는 AI 어시스턴트입니다.
현재 시뮬레이션 설정 및 결과는 다음과 같습니다.

[시뮬레이션 설정]
- 시뮬레이션 일수: {cfg.sim_days}일
- 일 트럭 수: {cfg.inbound.trucks_per_day}대
- 트럭 적재량: {cfg.inbound.truck_load_ton}t
- 반사로 대수: {cfg.melting.furnace_count}기
- 선별기: {cfg.sorting.sorters}대, 압착기: {cfg.sorting.presses}대

[시뮬레이션 결과 (요약)]
- 입고 트럭: {analysis.summary.get('inbound_trucks')}대
- 출하 트럭: {analysis.summary.get('outbound_trucks')}대
- 완료 배치: {analysis.summary.get('batches_completed')}회
- 총 생산량: {analysis.summary.get('total_ton')}t (일평균 {analysis.summary.get('daily_avg_ton')}t)
- 큐프레이크: {analysis.summary.get('flake_ton')}t, SCR: {analysis.summary.get('scr_ton')}t
- 주요 병목 구간: {analysis.bottleneck}

[인사이트]
{chr(10).join(analysis.insights)}

사용자의 질문에 위 데이터를 바탕으로 친절하고 전문적으로 답변해 주세요. 한국어로 답변해주세요.
""".strip()


def _response_text(response: Any) -> str:
    try:
        t = getattr(response, "text", None)
        if t:
            return str(t).strip()
    except Exception:
        pass
    try:
        cands = getattr(response, "candidates", None) or []
        if cands:
            parts = getattr(cands[0].content, "parts", None) or []
            texts = [getattr(p, "text", "") for p in parts if getattr(p, "text", None)]
            if texts:
                return "\n".join(texts).strip()
    except Exception:
        pass
    return "(모델이 텍스트 응답을 반환하지 않았습니다. API 키·모델명·쿼터를 확인해 주세요.)"


def _generate_reply(
    genai: Any,
    model_id: str,
    context_prompt: str,
    history: list[dict[str, str]],
    user_text: str,
) -> str:
    model = genai.GenerativeModel(model_id)
    messages: list[dict[str, Any]] = [{"role": "user", "parts": [context_prompt]}]
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        messages.append({"role": role, "parts": [msg["content"]]})
    messages.append({"role": "user", "parts": [user_text]})
    response = model.generate_content(messages)
    return _response_text(response)


def _complete_user_turn(
    genai: Any,
    model_id: str,
    context_prompt: str,
    user_text: str,
) -> None:
    text = user_text.strip()
    if not text:
        return
    hist = list(st.session_state.chat_history)
    st.session_state.chat_history.append({"role": "user", "content": text})
    try:
        reply = _generate_reply(genai, model_id, context_prompt, hist, text)
        st.session_state.chat_history.append({"role": "assistant", "content": reply})
    except Exception as e:
        st.session_state.chat_history.append(
            {"role": "assistant", "content": f"오류가 발생했습니다: {e!s}"}
        )


def _render_left_column(
    *,
    genai_ok: bool,
    api_key: str,
    run: dict | None,
) -> None:
    st.subheader("🤖 AI 시뮬레이션 결과 분석")
    st.caption(
        "우측 패널에서 카카오톡·메신저처럼 질문을 입력하고 전송할 수 있습니다. "
        "상단 빠른 질문 버튼을 누르면 해당 문장이 바로 전송됩니다."
    )
    if not genai_ok:
        st.error(
            "챗봇 패키지가 설치되지 않았습니다. 프로젝트 폴더에서 "
            "`.venv\\Scripts\\python -m pip install -r requirements.txt` 를 실행하세요."
        )
        return
    if not api_key:
        st.warning("👈 상단의 **'⚙️ 환경 설정'** 탭에서 Gemini API 키를 먼저 등록해 주세요.")
        return
    if run is None:
        st.info("👈 먼저 **시뮬레이션** 탭에서 실행을 완료한 뒤, 이 탭으로 돌아오면 우측 채팅이 활성화됩니다.")
        return
    st.success("우측 패널에서 대화를 시작할 수 있습니다.")


def _render_chat_panel_shell(genai: Any, run: dict, api_key: str) -> None:
    cfg: SimulationConfig = run["cfg"]
    analysis: Analysis = run["analysis"]
    context_prompt = _build_context_prompt(cfg, analysis)
    genai.configure(api_key=api_key)

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    fp = _run_fingerprint(run)
    if st.session_state.get("chat_bound_fp") != fp:
        st.session_state.chat_history = []
        st.session_state.chat_bound_fp = fp

    if "chat_user_message" not in st.session_state:
        st.session_state.chat_user_message = ""

    model_labels = list(GEMINI_MODEL_OPTIONS.keys())
    st.session_state.setdefault("gemini_model_label", model_labels[0])
    model_id = GEMINI_MODEL_OPTIONS[str(st.session_state["gemini_model_label"])]

    display = get_display_name()
    if display.endswith("님"):
        greet_name = display
    else:
        greet_name = f"{display}님"

    with st.container(border=True):
        st.markdown(f"**{greet_name}, 안녕하세요. 무엇을 도와드릴까요?**")

        qcols = st.columns(len(QUICK_PROMPTS), gap="small")
        for i, (label, preset) in enumerate(QUICK_PROMPTS):
            with qcols[i]:
                if st.button(label, key=f"chat_quick_{i}", use_container_width=True):
                    _complete_user_turn(genai, model_id, context_prompt, preset)
                    st.session_state.chat_user_message = ""
                    st.rerun()

        msg_box = st.container(height=420)
        with msg_box:
            if not st.session_state.chat_history:
                st.caption("아래 입력창에 질문을 적고 **전송**을 누르세요.")
            for message in st.session_state.chat_history:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        st.divider()
        c_plus, c_in, c_model, c_send = st.columns([0.55, 3.2, 1.4, 0.85])

        with c_plus:
            with st.popover("＋", help="추가 옵션"):
                if st.button("대화 기록 지우기", use_container_width=True):
                    st.session_state.chat_history = []
                    st.session_state.chat_user_message = ""
                    st.rerun()
                st.caption("API 키·이름은 **환경 설정** 탭에서 변경합니다.")

        with c_in:
            st.text_input(
                "메시지",
                placeholder="시뮬레이션 결과·탭에 대해 질문해 보세요.",
                key="chat_user_message",
                label_visibility="collapsed",
            )

        with c_model:
            st.selectbox(
                "모델",
                options=model_labels,
                key="gemini_model_label",
                label_visibility="collapsed",
            )

        model_id = GEMINI_MODEL_OPTIONS[str(st.session_state["gemini_model_label"])]

        with c_send:
            send = st.button("전송", type="primary", use_container_width=True)

        if send:
            user_text = str(st.session_state.get("chat_user_message", "") or "").strip()
            if user_text:
                _complete_user_turn(genai, model_id, context_prompt, user_text)
                st.session_state.chat_user_message = ""
                st.rerun()
            else:
                st.warning("질문 내용을 입력한 뒤 전송해 주세요.")


def render_chatbot(run: dict | None, api_key: str) -> None:
    genai = _load_genai()
    genai_ok = genai is not None

    left, right = st.columns([1.15, 1.0], gap="large")

    with left:
        _render_left_column(genai_ok=genai_ok, api_key=api_key, run=run)

    with right:
        st.markdown("##### 채팅")
        if not genai_ok:
            st.caption("패키지 설치 후 우측 패널이 활성화됩니다.")
            return
        if not api_key or run is None:
            with st.container(border=True):
                st.caption("채팅 패널")
                st.info("API 키 등록 및 시뮬레이션 실행 후 이용할 수 있습니다.")
            return

        _render_chat_panel_shell(genai, run, api_key)
