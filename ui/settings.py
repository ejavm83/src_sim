import os
import json
import streamlit as st

SETTINGS_FILE = "local_settings.json"


def _merge_cloud_overrides(data: dict) -> None:
    """배포 환경: 환경 변수·Streamlit Secrets가 있으면 API 키 등을 덮어쓴다(로컬 JSON보다 우선)."""
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if env_key:
        data["gemini_api_key"] = env_key
    env_name = os.environ.get("GEMINI_DISPLAY_NAME", "").strip()
    if env_name:
        data["display_name"] = env_name
    try:
        sec = st.secrets
        if "GEMINI_API_KEY" in sec:
            data["gemini_api_key"] = str(sec["GEMINI_API_KEY"]).strip()
        if "display_name" in sec:
            data["display_name"] = str(sec["display_name"]).strip()
    except Exception:
        pass


def load_settings() -> dict:
    data: dict = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
        except Exception:
            data = {}
    _merge_cloud_overrides(data)
    return data

def save_settings(settings: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        st.error(f"설정 저장 중 오류가 발생했습니다: {e}")

def get_api_key() -> str:
    return load_settings().get("gemini_api_key", "")


def get_display_name() -> str:
    """챗봇 인사에 사용할 표시 이름 (미입력 시 '사용자')."""
    name = str(load_settings().get("display_name", "") or "").strip()
    return name or "사용자"

def render_settings(*, show_ai_section: bool = True) -> None:
    st.subheader("⚙️ 환경 설정")
    st.markdown("시뮬레이션 대시보드의 전역 설정을 관리합니다.")

    if not show_ai_section:
        st.info(
            "🤖 **AI 챗봇 설정**(Gemini API 키 등)은 관리자 메뉴에서만 표시됩니다. "
            "메인 화면에서 **Shift+F12**를 눌러 활성화한 뒤 다시 이 탭을 열어 주세요."
        )
        return

    settings = load_settings()
    current_key = settings.get("gemini_api_key", "")
    current_display = settings.get("display_name", "")

    st.divider()
    st.markdown("### 🤖 AI 챗봇 설정")
    st.caption(
        "Gemini API 키를 등록하면 AI 분석 기능을 사용할 수 있습니다. "
        "키와 표시 이름은 로컬 파일(`local_settings.json`)에 저장되며, "
        "이 파일은 Git에 올리지 않는 것을 권장합니다."
    )

    with st.form("settings_form"):
        new_display = st.text_input(
            "챗봇에 표시할 이름 (선택)",
            value=current_display,
            placeholder="예: 길용",
            help="AI 분석 탭 인사말에 사용됩니다. 비워 두면 '사용자님'으로 표시됩니다.",
        )
        new_key = st.text_input(
            "Gemini API Key",
            value=current_key,
            type="password",
            help="발급받은 Gemini API 키를 입력하세요.",
        )
        submitted = st.form_submit_button("설정 저장", type="primary")

        if submitted:
            settings["display_name"] = new_display.strip()
            settings["gemini_api_key"] = new_key.strip()
            save_settings(settings)
            st.success("✅ 설정이 성공적으로 저장되었습니다.")

    with st.expander("💡 API 키 발급 방법", expanded=False):
        st.markdown(
            "1. [Google AI Studio](https://aistudio.google.com/) 접속 및 로그인\n"
            "2. 좌측 메뉴 **'Get API key'** 클릭\n"
            "3. **'Create API key'** 버튼으로 키 생성\n"
            "4. 생성된 키 복사 후 위 입력란에 붙여넣기"
        )
