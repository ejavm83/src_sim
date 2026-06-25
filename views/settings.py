"""앱 설정 — LLM 제공자(Gemini / OpenAI) 및 API 키."""

from __future__ import annotations

import streamlit as st

from llm_config import ApiKeyInfo, resolve_api_key_info
from ui.app_settings import (
    get_provider,
    session_api_key_name,
    set_provider,
    set_saved_key,
)

_ORDER = ("gemini", "openai")
_PROVIDER_META = {
    "gemini": {
        "name": "Google Gemini",
        "env": "GEMINI_API_KEY",
        "placeholder": "AIza...",
        "issuer": "Google AI Studio",
        "url": "https://aistudio.google.com/apikey",
        "steps": (
            "1. [**Google AI Studio**](https://aistudio.google.com/apikey)에 접속합니다. (Google 계정 로그인)\n"
            "2. **API 키 만들기**를 누릅니다.\n"
            "3. 표시된 키(`AIza...`로 시작)를 복사합니다.\n"
            "4. 아래 입력란에 붙여넣고 **저장**을 누릅니다.\n\n"
            "무료 할당량이 있으며, 키는 외부에 공유하지 마세요."
        ),
    },
    "openai": {
        "name": "OpenAI (ChatGPT)",
        "env": "OPENAI_API_KEY",
        "placeholder": "sk-...",
        "issuer": "OpenAI Platform",
        "url": "https://platform.openai.com/api-keys",
        "steps": (
            "1. [**OpenAI Platform**](https://platform.openai.com/api-keys)에 접속합니다. (OpenAI 계정 로그인)\n"
            "2. **Create new secret key**를 누릅니다.\n"
            "3. 표시된 키(`sk-...`로 시작)를 복사합니다. (이후 다시 볼 수 없으니 잘 보관)\n"
            "4. 아래 입력란에 붙여넣고 **저장**을 누릅니다.\n\n"
            "사용량에 따라 과금되며(결제 수단 등록 필요), 키는 외부에 공유하지 마세요."
        ),
    },
}


def _widget_key(provider: str) -> str:
    return f"settings_key_input_{provider}"


def _render_key_form(provider: str) -> None:
    meta = _PROVIDER_META[provider]
    new_key = st.text_input(
        "API 키",
        type="password",
        placeholder=meta["placeholder"],
        help=f"{meta['issuer']}에서 발급한 API 키를 입력하세요.",
        key=_widget_key(provider),
    )
    if st.button("저장", type="primary", use_container_width=True, key=f"settings_save_{provider}"):
        if not new_key.strip():
            st.error("키를 입력하세요.")
        else:
            set_saved_key(provider, new_key.strip())
            st.session_state[session_api_key_name(provider)] = new_key.strip()
            st.success("저장했습니다.")
            st.rerun()


def _render_status_card(info: ApiKeyInfo, provider_name: str) -> None:
    if info.configured:
        st.markdown(
            f"""
<div style="border: 2px solid #22c55e; border-radius: 10px; padding: 1rem 1.25rem;
background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); margin: 0.75rem 0 1rem;">
  <div style="font-size: 1.15rem; font-weight: 700; color: #166534;">
    ✅ {provider_name} 키 설정됨
  </div>
  <div style="margin-top: 0.6rem; color: #14532d; font-size: 0.95rem;">
    등록 키: <code style="background:#bbf7d0; padding: 2px 8px; border-radius: 4px;">{info.masked}</code>
    &nbsp;·&nbsp; 출처: <strong>{info.source}</strong>
  </div>
  <div style="color: #15803d; font-size: 0.88rem; margin-top: 0.5rem;">
    🌳 공정 트리 · 📊 파라메터 추출에 바로 사용됩니다.
  </div>
</div>
            """.strip(),
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
<div style="border: 2px solid #f59e0b; border-radius: 10px; padding: 1rem 1.25rem;
background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); margin: 0.75rem 0 1rem;">
  <div style="font-size: 1.15rem; font-weight: 700; color: #92400e;">
    ⚠️ {provider_name} 키 미설정
  </div>
  <div style="color: #78350f; font-size: 0.92rem; margin-top: 0.5rem;">
    <strong>🌳 공정 트리</strong>·<strong>📊 파라메터</strong> 추출을 쓰려면 아래에서 키를 등록하세요.
  </div>
</div>
        """.strip(),
        unsafe_allow_html=True,
    )


def render() -> None:
    st.header("⚙️ 설정")
    st.subheader("LLM 제공자 · API 키")

    cur = get_provider()
    labels = [_PROVIDER_META[p]["name"] for p in _ORDER]
    choice = st.radio(
        "사용할 LLM 제공자",
        labels,
        index=_ORDER.index(cur),
        horizontal=True,
        key="settings_provider_radio",
        help="공정 트리·파라미터 추출에 사용할 LLM을 선택합니다. 제공자별로 키를 따로 저장합니다.",
    )
    provider = _ORDER[labels.index(choice)]
    if provider != cur:
        set_provider(provider)

    meta = _PROVIDER_META[provider]
    info = resolve_api_key_info()  # 현재 선택된 제공자 기준

    st.caption(
        f"**{meta['name']}** 키로 공정 설명 문서에서 파라미터를 추출합니다. "
        "키는 이 PC의 `local_settings.json`에만 저장되며 Git에 올라가지 않습니다. "
        f"배포 환경에서는 환경변수 `{meta['env']}` 또는 Streamlit Secrets가 우선합니다."
    )

    _render_status_card(info, meta["name"])

    with st.expander("API 키 발급 방법", expanded=not info.configured):
        st.markdown(meta["steps"])
        st.link_button(f"{meta['issuer']}에서 키 발급", meta["url"], use_container_width=True)

    if info.configured:
        if info.is_local:
            if st.button("키 삭제", use_container_width=True, key=f"settings_del_{provider}"):
                set_saved_key(provider, None)
                st.session_state.pop(session_api_key_name(provider), None)
                st.session_state.pop(_widget_key(provider), None)
                st.success("삭제했습니다.")
                st.rerun()
            with st.expander("API 키 변경"):
                _render_key_form(provider)
        else:
            st.info(
                f"현재 키는 **{info.source}**에서 불러옵니다. "
                "이 화면에서는 삭제·변경할 수 없습니다."
            )
    else:
        _render_key_form(provider)
