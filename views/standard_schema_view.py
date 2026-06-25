"""📐 표준 JSON — 표준 공정 JSON을 베이스로 입력 MD에서 관련 영역/파라미터를 추출·업데이트."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from schema_extract import apply_updates, extract_schema_updates, load_base_schema

_RESULT_KEY = "std_schema_result"
_BTN_KEY = "std_schema_extract_btn"


def _doc_text() -> str:
    from views.process_description import _EDIT_MODE_KEY, _SESSION_DRAFT_KEY, _load_text

    if st.session_state.get(_EDIT_MODE_KEY):
        return str(st.session_state.get(_SESSION_DRAFT_KEY, ""))
    return _load_text()


def render_page() -> None:
    st.header("📐 표준 JSON 추출")
    st.caption(
        "케이블 제조 **표준(범용) 공정 JSON**을 베이스로, **📄 공정 설명** 문서에서 "
        "관련 영역·파라미터만 추출해 표준값을 업데이트합니다. 변경(diff)·누락·모호 항목을 함께 보여주고, "
        "업데이트된 JSON을 내려받을 수 있습니다. (LLM API 키 필요 — **⚙️ 설정** 탭)"
    )

    base = load_base_schema()
    current_text = _doc_text()

    c1, _ = st.columns([1, 3])
    with c1:
        if st.button(
            "MD에서 추출·업데이트",
            type="primary",
            disabled=not current_text.strip(),
            key=_BTN_KEY,
            use_container_width=True,
            help="표준 JSON 구조에 맞춰 문서가 명시한 값만 추출해 표준값을 갱신합니다.",
        ):
            with st.spinner("표준 JSON을 문서로 업데이트하는 중..."):
                try:
                    out = extract_schema_updates(current_text)
                except Exception as e:  # noqa: BLE001
                    st.session_state.pop(_RESULT_KEY, None)
                    st.error(f"추출에 실패했습니다: {e}")
                else:
                    updated, diffs, skipped = apply_updates(base, out.get("updates"))
                    st.session_state[_RESULT_KEY] = {
                        "updated": updated,
                        "diffs": diffs,
                        "skipped": skipped,
                        "missing": out.get("missing_fields") or [],
                        "ambiguous": out.get("ambiguous_items") or [],
                    }

    if not current_text.strip():
        st.info("공정 설명 문서가 비어 있습니다. **📄 공정 설명** 탭에서 작성·저장한 뒤 추출하세요.")

    res = st.session_state.get(_RESULT_KEY)
    if isinstance(res, dict):
        _render_result(res)
    else:
        with st.expander("표준 JSON 구조 보기", expanded=False):
            st.json(base, expanded=False)


def _esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _val_html(v: object) -> str:
    if isinstance(v, bool):
        return f'<span class="jv-bool">{str(v).lower()}</span>'
    if v is None:
        return '<span class="jv-null">null</span>'
    if isinstance(v, str):
        return f'<span class="jv-str">"{_esc(v)}"</span>'
    return f'<span class="jv-num">{_esc(v)}</span>'


def _emit_json(key, obj, path, depth, last, changed, out) -> None:
    indent = "  " * depth
    prefix = f'<span class="jk">"{_esc(key)}"</span>: ' if key is not None else ""
    comma = "" if last else ","
    if isinstance(obj, dict):
        out.append(f"{indent}{prefix}{{")
        items = list(obj.items())
        for i, (k, v) in enumerate(items):
            cp = f"{path}.{k}" if path else str(k)
            _emit_json(k, v, cp, depth + 1, i == len(items) - 1, changed, out)
        out.append(f"{indent}}}{comma}")
    elif isinstance(obj, list):
        out.append(f"{indent}{prefix}[")
        for i, v in enumerate(obj):
            _emit_json(None, v, f"{path}[{i}]", depth + 1, i == len(obj) - 1, changed, out)
        out.append(f"{indent}]{comma}")
    elif path in changed:
        old, _new = changed[path]
        content = f'{prefix}{_val_html(obj)}<span class="jold"> ⟵ 표준 {_esc(old)}</span>'
        out.append(f'{indent}<span class="jchg">● {content}</span>{comma}')
    else:
        out.append(f"{indent}{prefix}{_val_html(obj)}{comma}")


def _render_updated_json_html(updated: dict, diffs: list) -> None:
    changed = {d["경로"]: (d["표준값"], d["추출값"]) for d in diffs}
    out: list[str] = []
    _emit_json(None, updated, "", 0, True, changed, out)
    html = (
        "<style>"
        ".jbox{background:#0f1923;color:#c8d8e8;font-family:'IBM Plex Mono',monospace;"
        "font-size:12.5px;line-height:1.75;padding:16px 18px;border-radius:8px;"
        "white-space:pre;overflow:auto;}"
        ".jk{color:#7ec8e3;}.jv-str{color:#a8d9a0;}.jv-num{color:#e8c878;}"
        ".jv-bool{color:#ff9f6b;}.jv-null{color:#7a8fa0;}"
        ".jchg{background:rgba(106,176,76,.28);border-radius:3px;padding:0 4px;font-weight:700;}"
        ".jold{color:#e8a87a;font-size:11px;font-weight:400;}"
        "</style>"
        f'<div class="jbox">{chr(10).join(out)}</div>'
    )
    components.html(html, height=min(len(out) * 23 + 40, 680), scrolling=True)


def _render_result(res: dict) -> None:
    diffs = res["diffs"]
    st.subheader(f"업데이트 결과 — 변경 {len(diffs)}건")
    if diffs:
        st.caption("표준값과 다르게 추출된 항목입니다. ‘근거’는 문서 발췌입니다.")
        st.dataframe(
            pd.DataFrame(diffs, columns=["경로", "표준값", "추출값", "근거"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("문서에서 표준값과 다른 항목을 찾지 못했습니다.")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**누락(미언급) 항목**")
        if res["missing"]:
            for m in res["missing"]:
                st.markdown(f"- {m}")
        else:
            st.caption("없음")
    with cols[1]:
        st.markdown("**모호 / 확인 필요**")
        if res["ambiguous"]:
            for a in res["ambiguous"]:
                st.markdown(f"- {a}")
        else:
            st.caption("없음")

    if res["skipped"]:
        with st.expander(f"표준에 없어 건너뛴 항목 {len(res['skipped'])}건"):
            for s in res["skipped"]:
                st.markdown(f"- `{s.get('path')}` — {s.get('reason')}")

    st.download_button(
        "업데이트된 JSON 내려받기",
        data=json.dumps(res["updated"], ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="process_standard_updated.json",
        mime="application/json",
    )

    st.markdown("**업데이트된 JSON** — 변경 항목은 🟢 강조 + 표준값 병기")
    _render_updated_json_html(res["updated"], res["diffs"])
