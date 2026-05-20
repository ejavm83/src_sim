"""AI 챗봇 관련 UI를 '관리자 메뉴'처럼 숨기고 Shift+F12로 표시합니다.

표시 여부는 URL 쿼리 ``scr_admin_ai=1`` 로 유지됩니다(브라우저 새로고침 후에도 동일).
Shift+F12 시 쿼리를 토글한 뒤 페이지를 다시 로드합니다.
"""

from __future__ import annotations

import streamlit as st

# Streamlit·프록시와 충돌을 피하기 위해 전용 쿼리 키 사용
ADMIN_AI_QUERY_KEY = "scr_admin_ai"

# 부모 창에 한 번만 리스너 등록 (iframe srcdoc 내 스크립트)
def _hotkey_html() -> str:
    k = ADMIN_AI_QUERY_KEY
    return f"""
<!DOCTYPE html><html><head><meta charset="utf-8"/></head><body>
<script>
(function () {{
  var p = window.parent;
  if (p.__scr_sim_admin_ai_hotkey) return;
  p.__scr_sim_admin_ai_hotkey = true;
  p.document.addEventListener(
    "keydown",
    function (e) {{
      if (e.shiftKey && (e.key === "F12" || e.keyCode === 123)) {{
        e.preventDefault();
        try {{
          var u = new URL(p.location.href);
          if (u.searchParams.get("{k}") === "1") {{
            u.searchParams.delete("{k}");
          }} else {{
            u.searchParams.set("{k}", "1");
          }}
          p.location.href = u.toString();
        }} catch (err) {{}}
      }}
    }},
    true
  );
}})();
</script>
</body></html>
"""


def admin_ai_menus_visible() -> bool:
    raw = st.query_params.get(ADMIN_AI_QUERY_KEY)
    if raw is None:
        return False
    if isinstance(raw, list):
        return bool(raw) and str(raw[0]) == "1"
    return str(raw) == "1"


def render_admin_ai_hotkey_listener() -> None:
    """Shift+F12 리스너를 삽입합니다. Streamlit은 height=0을 허용하지 않아 1px로 둡니다."""
    st.iframe(_hotkey_html(), height=1, width="stretch")
