"""앱 설정 — API 키 등."""

from __future__ import annotations

import streamlit as st

from llm_config import api_key_configured
from ui.app_settings import (
    session_api_key_name,
    set_gemini_api_key,
)

_WIDGET_KEY = "settings_gemini_api_key_input"
_GEMINI_KEY_URL = "https://aistudio.google.com/apikey"


def render() -> None:
    st.header("⚙️ 설정")

    st.subheader("Google Gemini API 키")
    st.caption(
        "공정 설명 문서에서 파라미터를 자동 추출할 때 사용합니다. "
        "키는 이 PC의 `local_settings.json`에만 저장되며 Git에 올라가지 않습니다. "
        "배포 환경에서는 환경 변수 `GEMINI_API_KEY` 또는 Streamlit Secrets가 우선합니다."
    )

    with st.expander("API 키 발급 방법", expanded=not api_key_configured()):
        st.markdown(
            f"""
1. [**Google AI Studio**]({_GEMINI_KEY_URL})에 접속합니다. (Google 계정 로그인)
2. **API 키 만들기**를 누릅니다.
3. 표시된 키(`AIza...`로 시작)를 복사합니다.
4. 아래 입력란에 붙여넣고 **저장**을 누릅니다.

무료 할당량이 있으며, 키는 외부에 공유하지 마세요.
            """.strip()
        )
        st.link_button("Google AI Studio에서 키 발급", _GEMINI_KEY_URL, use_container_width=True)

    configured = api_key_configured()
    if configured:
        st.success("API 키가 설정되어 있습니다.")
    else:
        st.warning(
            "API 키가 설정되지 않았습니다. **📊 파라메터** 탭의 파라미터 추출을 쓰려면 키를 등록하세요."
        )

    new_key = st.text_input(
        "API 키",
        type="password",
        placeholder="AIza..." if configured else "",
        help="Google AI Studio에서 발급한 API 키를 입력하세요. 저장 후에는 마스킹되어 표시되지 않습니다.",
        key=_WIDGET_KEY,
    )

    c_save, c_clear = st.columns(2)
    with c_save:
        if st.button("저장", type="primary", use_container_width=True):
            if not new_key.strip():
                st.error("키를 입력하세요.")
            else:
                set_gemini_api_key(new_key.strip())
                st.session_state[session_api_key_name()] = new_key.strip()
                st.success("저장했습니다.")
                st.rerun()
    with c_clear:
        if st.button("키 삭제", use_container_width=True, disabled=not configured):
            set_gemini_api_key(None)
            st.session_state.pop(session_api_key_name(), None)
            st.session_state.pop(_WIDGET_KEY, None)
            st.success("삭제했습니다.")
            st.rerun()

    if configured and not new_key:
        st.caption("이미 저장된 키가 있습니다. 바꾸려면 새 키를 입력한 뒤 **저장**을 누르세요.")
