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





def session_api_key_name() -> str:

    return _SESSION_KEY

