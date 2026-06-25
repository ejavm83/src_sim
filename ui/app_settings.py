"""로컬 앱 설정(API 키 등). 프로젝트 루트 `local_settings.json`에 저장(Git 제외)."""



from __future__ import annotations



import json

from pathlib import Path

from typing import Any



_GEMINI_KEY = "gemini_api_key"

_LEGACY_ANTHROPIC_KEY = "anthropic_api_key"  # 이전 버전 호환

_SESSION_KEY = "gemini_api_key"





def settings_path() -> Path:

    return Path(__file__).resolve().parent.parent / "local_settings.json"





def load_settings() -> dict[str, Any]:

    path = settings_path()

    if not path.is_file():

        return {}

    try:

        with path.open(encoding="utf-8") as f:

            data = json.load(f)

        return data if isinstance(data, dict) else {}

    except (OSError, json.JSONDecodeError):

        return {}





def save_settings(data: dict[str, Any]) -> None:

    path = settings_path()

    with path.open("w", encoding="utf-8") as f:

        json.dump(data, f, ensure_ascii=False, indent=2)





def _read_key(data: dict[str, Any], name: str) -> str | None:

    val = data.get(name)

    if val and str(val).strip():

        return str(val).strip()

    return None





def get_gemini_api_key() -> str | None:

    data = load_settings()

    key = _read_key(data, _GEMINI_KEY)

    if key:

        return key

    return _read_key(data, _LEGACY_ANTHROPIC_KEY)





def set_gemini_api_key(key: str | None) -> None:

    data = load_settings()

    if key and key.strip():

        data[_GEMINI_KEY] = key.strip()

        data.pop(_LEGACY_ANTHROPIC_KEY, None)

    else:

        data.pop(_GEMINI_KEY, None)

        data.pop(_LEGACY_ANTHROPIC_KEY, None)

    save_settings(data)





def session_api_key_name(provider: str = "gemini") -> str:

    return f"{provider}_api_key"





def sync_gemini_api_key_session() -> str | None:
    """`local_settings.json` 등에 저장된 키를 세션에 올린다(이미 있으면 유지)."""
    try:
        import streamlit as st
    except Exception:
        return get_gemini_api_key()

    name = session_api_key_name()
    existing = st.session_state.get(name)
    if existing and str(existing).strip():
        return str(existing).strip()

    persisted = get_gemini_api_key()
    if persisted:
        st.session_state[name] = persisted
    return persisted


# ── 제공자(provider) 선택 + 제공자별 키 ──
_OPENAI_KEY = "openai_api_key"
_PROVIDER_KEY = "llm_provider"
PROVIDERS = ("gemini", "openai")
_KEY_FIELD = {"gemini": _GEMINI_KEY, "openai": _OPENAI_KEY}


def get_provider() -> str:
    """저장된 LLM 제공자(gemini/openai). 기본 gemini."""
    data = load_settings()
    p = str(data.get(_PROVIDER_KEY, "")).strip().lower()
    return p if p in PROVIDERS else "gemini"


def set_provider(provider: str) -> None:
    data = load_settings()
    data[_PROVIDER_KEY] = provider if provider in PROVIDERS else "gemini"
    save_settings(data)


def get_saved_key(provider: str) -> str | None:
    """provider의 로컬 저장 키."""
    data = load_settings()
    key = _read_key(data, _KEY_FIELD.get(provider, _GEMINI_KEY))
    if key:
        return key
    if provider == "gemini":
        return _read_key(data, _LEGACY_ANTHROPIC_KEY)
    return None


def set_saved_key(provider: str, key: str | None) -> None:
    data = load_settings()
    field = _KEY_FIELD.get(provider, _GEMINI_KEY)
    if key and key.strip():
        data[field] = key.strip()
        if provider == "gemini":
            data.pop(_LEGACY_ANTHROPIC_KEY, None)
    else:
        data.pop(field, None)
        if provider == "gemini":
            data.pop(_LEGACY_ANTHROPIC_KEY, None)
    save_settings(data)

