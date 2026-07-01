"""📐 표준 JSON — 표준 공정 JSON을 베이스로 입력 MD에서 관련 영역/파라미터를 추출·업데이트."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from schema_extract import apply_updates, extract_schema_updates, generate_domain_json, load_base_schema
from config_sanitize import sanitize_for_simulation
from standard_schema_bridge import logistics_to_config

_RESULT_KEY = "std_schema_result"
_BTN_KEY = "std_schema_extract_btn"
_MD_CHANGED_PATHS_KEY = "_md_extract_changed_paths"


def _doc_text() -> str:
    from views.process_description import _EDIT_MODE_KEY, _SESSION_DRAFT_KEY, _load_text

    if st.session_state.get(_EDIT_MODE_KEY):
        return str(st.session_state.get(_SESSION_DRAFT_KEY, ""))
    return _load_text()


def render_page() -> None:
    st.header("📐 표준 JSON 추출")
    st.caption(
        "범용 제조 **표준 JSON**(L1 Core + 케이블·물류 확장)을 베이스로, **📄 공정 설명** MD에서 "
        "관련 영역·파라미터를 추출해 갱신합니다. `logistics_process` 변경은 **사이드바 시뮬 파라미터**에 자동 반영됩니다. "
        "표 형태 편집은 **📋 공정 데이터** 탭을 사용하세요. (LLM API 키 필요 — **⚙️ 설정** 탭)"
    )

    base = load_base_schema()
    current_text = _doc_text()

    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        if st.button(
            "MD에서 JSON 생성",
            type="primary",
            disabled=not current_text.strip(),
            key=_BTN_KEY,
            use_container_width=True,
            help="MD 내용을 분석해 도메인에 맞는 표준 JSON을 처음부터 생성합니다.",
        ):
            with st.spinner("도메인 JSON을 생성하는 중..."):
                try:
                    result = generate_domain_json(current_text)
                except Exception as e:  # noqa: BLE001
                    st.session_state.pop(_RESULT_KEY, None)
                    st.error(f"생성에 실패했습니다: {e}")
                else:
                    st.session_state[_MD_CHANGED_PATHS_KEY] = set()
                    st.session_state[_RESULT_KEY] = result
                    if result.get("domain"):
                        st.session_state["_domain_name"] = result["domain"]
    with c2:
        if st.button(
            "기존 스키마 업데이트",
            disabled=not current_text.strip(),
            key=f"{_BTN_KEY}_legacy",
            use_container_width=True,
            help="고정된 표준 스키마를 베이스로 MD에서 값만 추출해 업데이트합니다.",
        ):
            with st.spinner("표준 JSON을 문서로 업데이트하는 중..."):
                try:
                    out = extract_schema_updates(current_text)
                except Exception as e:  # noqa: BLE001
                    st.session_state.pop(_RESULT_KEY, None)
                    st.error(f"추출에 실패했습니다: {e}")
                else:
                    updated, diffs, skipped = apply_updates(base, out.get("updates"))
                    logistics_diffs = [
                        d for d in diffs if str(d.get("경로", "")).startswith("logistics_process.")
                    ]
                    if logistics_diffs:
                        st.session_state["extracted_config"] = sanitize_for_simulation(
                            logistics_to_config(updated.get("logistics_process"))
                        )
                        st.session_state["config_nonce"] = (
                            st.session_state.get("config_nonce", 0) + 1
                        )
                    st.session_state[_MD_CHANGED_PATHS_KEY] = {
                        d["경로"] for d in diffs if d.get("경로")
                    }
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
        st.markdown("##### 📄 전체 JSON 구조")
        c_toggle, _ = st.columns([1, 4])
        with c_toggle:
            json_expanded = st.toggle("모두 펼치기", value=True, key="std_schema_json_expand")
        st.json(base, expanded=json_expanded)


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
        key_part = (
            f'<span class="jk jk-chg">"{_esc(key)}"</span>: ' if key is not None else ""
        )
        content = (
            f'{key_part}<span class="jv-chg">{_val_html(obj)}</span>'
            f'<span class="jold"> ← 표준 {_esc(old)}</span>'
        )
        out.append(f'{indent}<span class="jchg-line">{content}</span>{comma}')
    else:
        out.append(f"{indent}{prefix}{_val_html(obj)}{comma}")


def _render_changed_banner(diffs: list) -> None:
    """MD 추출로 바뀐 항목을 상단에 크게 요약."""
    if not diffs:
        return
    lines: list[str] = []
    for d in diffs[:12]:
        path = d.get("경로", "")
        old = d.get("표준값", "?")
        new = d.get("추출값", "?")
        short = path.split(".")[-1] if path else path
        lines.append(
            f'<div class="mdchg-item">'
            f'<span class="mdchg-dot">●</span>'
            f'<code class="mdchg-path" title="{_esc(path)}">{_esc(short)}</code>'
            f'<span class="mdchg-old">{_esc(old)}</span>'
            f'<span class="mdchg-arrow">→</span>'
            f'<strong class="mdchg-new">{_esc(new)}</strong>'
            f"</div>"
        )
    more = ""
    if len(diffs) > 12:
        more = f'<div class="mdchg-more">… 외 {len(diffs) - 12}건 (아래 표·JSON 참고)</div>'
    st.markdown(
        f"""
<style>
.mdchg-banner {{
  border: 2px solid #22c55e; border-radius: 10px; padding: 0.85rem 1rem;
  background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
  margin-bottom: 0.85rem;
}}
.mdchg-title {{
  font-weight: 800; font-size: 1.05rem; color: #14532d; margin-bottom: 0.55rem;
}}
.mdchg-sub {{ font-size: 0.82rem; color: #166534; margin-bottom: 0.65rem; }}
.mdchg-grid {{ display: flex; flex-direction: column; gap: 0.35rem; }}
.mdchg-item {{
  display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.35rem 0.5rem;
  padding: 0.35rem 0.55rem; background: rgba(255,255,255,0.72);
  border-left: 4px solid #22c55e; border-radius: 6px; font-size: 0.88rem;
}}
.mdchg-dot {{ color: #16a34a; font-size: 0.75rem; }}
.mdchg-path {{
  font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem;
  background: #e8f5e9; color: #1b5e20; padding: 1px 6px; border-radius: 4px;
}}
.mdchg-old {{ color: #9a3412; text-decoration: line-through; opacity: 0.85; }}
.mdchg-arrow {{ color: #15803d; font-weight: 700; }}
.mdchg-new {{ color: #14532d; font-size: 0.95rem; }}
.mdchg-more {{ margin-top: 0.45rem; font-size: 0.8rem; color: #166534; }}
</style>
<div class="mdchg-banner">
  <div class="mdchg-title">🟢 MD에서 추출·갱신된 항목 {len(diffs)}건</div>
  <div class="mdchg-sub">표준값 대비 문서에서 읽어온 값입니다. 아래 JSON·📋 공정 데이터 탭에도 반영됩니다.</div>
  <div class="mdchg-grid">{"".join(lines)}{more}</div>
</div>
        """.strip(),
        unsafe_allow_html=True,
    )


def _style_diff_dataframe(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    def _row_style(row: pd.Series) -> list[str]:
        base = (
            "background: linear-gradient(90deg, #dcfce7 0%, #f0fdf4 100%); "
            "border-left: 4px solid #22c55e; font-weight: 600; color: #14532d"
        )
        val_emph = "color: #15803d; font-weight: 800; font-size: 1.02em"
        return [
            f"{base}; {val_emph}" if col == "추출값" else base
            for col in row.index
        ]

    return df.style.apply(_row_style, axis=1)


def _assign_path(root: dict[str, Any], toks: list[str | int], value: object) -> None:
    """경로 토큰으로 중첩 dict/list에 값을 넣는다."""
    if not toks:
        return
    cur: Any = root
    for i, tok in enumerate(toks[:-1]):
        nxt = toks[i + 1]
        if isinstance(tok, int):
            while len(cur) <= tok:
                cur.append({} if isinstance(nxt, str) else [])
            if cur[tok] is None:
                cur[tok] = {} if isinstance(nxt, str) else []
            cur = cur[tok]
        else:
            if tok not in cur or not isinstance(cur[tok], (dict, list)):
                cur[tok] = {} if isinstance(nxt, str) else []
            cur = cur[tok]
    last = toks[-1]
    if isinstance(last, int):
        while len(cur) <= last:
            cur.append(None)
        cur[last] = value
    else:
        cur[last] = value


def _build_changed_subtree(updated: dict, diffs: list) -> dict[str, Any]:
    """변경된 경로만 모아 중첩 JSON으로 만든다."""
    from schema_extract import _navigate, _parse_path

    tree: dict[str, Any] = {}
    for d in diffs:
        path = d.get("경로")
        if not path:
            continue
        toks = _parse_path(str(path))
        ok, val = _navigate(updated, toks)
        if ok:
            _assign_path(tree, toks, val)
    return tree


def _json_box_css(*, variant: str, max_h: int) -> str:
    if variant == "changed":
        return (
            "<style>"
            ".jbox-chg{background:#0f1923;padding:14px 16px;border-radius:8px;"
            "border:2px solid #22c55e;max-height:"
            f"{max_h}px;overflow:auto;"
            "font-family:'IBM Plex Mono',monospace;font-size:12.5px;line-height:1.75;"
            "color:#c8d8e8;white-space:pre;}"
            ".jk{color:#86efac;font-weight:700;}.jv-str{color:#86efac;}"
            ".jv-num{color:#bef264;font-weight:700;}.jv-bool{color:#fde68a;}"
            ".jv-null{color:#7a8fa0;}"
            "</style>"
        )
    return (
        "<style>"
        ".jbox{background:#0f1923;color:#c8d8e8;font-family:'IBM Plex Mono',monospace;"
        "font-size:12.5px;line-height:1.75;padding:16px 18px;border-radius:8px;"
        "border:2px solid #1e3a2f;"
        f"white-space:pre;overflow:auto;max-height:{max_h}px;"
        "}"
        ".jk{color:#7ec8e3;}.jk-chg{color:#86efac;font-weight:800;}"
        ".jv-str{color:#a8d9a0;}.jv-num{color:#e8c878;}"
        ".jv-bool{color:#ff9f6b;}.jv-null{color:#7a8fa0;}"
        ".jv-chg .jv-str,.jv-chg .jv-num,.jv-chg .jv-bool{color:#86efac !important;"
        "font-weight:800;text-shadow:0 0 8px rgba(74,222,128,.45);}"
        ".jchg-line{display:inline-block;width:calc(100% - 1rem);"
        "background:linear-gradient(90deg,rgba(34,197,94,.32),rgba(34,197,94,.08));"
        "border-left:4px solid #4ade80;border-radius:4px;padding:0 6px 0 4px;"
        "box-shadow:0 0 12px rgba(74,222,128,.15);}"
        ".jold{color:#fdba74;font-size:11px;font-weight:500;margin-left:6px;}"
        "</style>"
    )


def _render_json_tree_html(
    data: dict,
    *,
    changed: dict[str, tuple[object, object]] | None = None,
    variant: str = "full",
    max_h: int = 520,
) -> None:
    changed = changed or {}
    out: list[str] = []
    _emit_json(None, data, "", 0, True, changed, out)
    css = _json_box_css(variant=variant, max_h=max_h)
    box_cls = "jbox-chg" if variant == "changed" else "jbox"
    st.html(f"{css}<div class='{box_cls}'>{chr(10).join(out)}</div>", width="stretch")


def _render_changed_diff_list(diffs: list) -> None:
    """변경 항목을 경로·전후 값 리스트로 표시."""
    changed = {d["경로"]: (d["표준값"], d["추출값"]) for d in diffs}
    out: list[str] = []
    for path in sorted(changed):
        old, new = changed[path]
        out.append(
            f'<div class="jchg-only">'
            f'<code class="jchg-only-path">{_esc(path)}</code>'
            f'<span class="jold">{_esc(old)}</span>'
            f'<span class="jchg-only-arrow">→</span>'
            f'<span class="jv-chg">{_esc(new)}</span>'
            f"</div>"
        )
    css = (
        "<style>"
        ".jbox-list{background:#0f1923;padding:12px 14px;border-radius:8px;"
        "border:2px solid #22c55e;max-height:280px;overflow:auto;}"
        ".jchg-only{display:flex;flex-wrap:wrap;gap:0.35rem 0.55rem;align-items:baseline;"
        "padding:0.4rem 0.5rem;margin-bottom:0.3rem;"
        "background:rgba(34,197,94,.14);border-left:4px solid #4ade80;border-radius:6px;}"
        ".jchg-only-path{color:#7ec8e3;font-size:11px;}"
        ".jold{color:#e8a87a;text-decoration:line-through;font-size:11px;}"
        ".jchg-only-arrow{color:#4ade80;font-weight:700;}"
        ".jv-chg{color:#86efac;font-weight:800;font-size:12px;}"
        "</style>"
    )
    st.html(f"{css}<div class='jbox-list'>{''.join(out)}</div>", width="stretch")


def _render_json_panels(updated: dict, diffs: list) -> None:
    """좌: 변경 JSON / 우: 전체 JSON 구조."""
    changed_map = {d["경로"]: (d["표준값"], d["추출값"]) for d in diffs}
    col_chg, col_full = st.columns([2, 3], gap="large")

    with col_chg:
        st.markdown("##### 🟢 변경된 JSON")
        st.caption("MD에서 읽어 표준값을 바꾼 항목만 모았습니다.")
        if not diffs:
            st.info("변경된 항목이 없습니다.")
        else:
            view = st.radio(
                "표시 형식",
                ["중첩 JSON", "경로 목록"],
                horizontal=True,
                key="std_schema_chg_view",
                label_visibility="collapsed",
            )
            if view == "중첩 JSON":
                subtree = _build_changed_subtree(updated, diffs)
                _render_json_tree_html(subtree, variant="changed", max_h=480)
            else:
                _render_changed_diff_list(diffs)
            with st.expander(f"변경 상세 표 ({len(diffs)}건)", expanded=False):
                df = pd.DataFrame(diffs, columns=["경로", "표준값", "추출값", "근거"])
                st.dataframe(
                    _style_diff_dataframe(df),
                    use_container_width=True,
                    hide_index=True,
                )

    with col_full:
        st.markdown("##### 📄 전체 JSON 구조")
        st.caption("갱신된 전체 표준 JSON입니다. 변경된 줄은 🟢 녹색으로 표시됩니다.")
        json_expanded = st.toggle(
            "모두 펼치기",
            value=True,
            key="std_schema_full_json_expand",
        )
        if json_expanded:
            _render_json_tree_html(
                updated,
                changed=changed_map,
                variant="full",
                max_h=560,
            )
        else:
            st.json(updated, expanded=False)


def _render_updated_json_html(updated: dict, diffs: list, *, changed_only: bool) -> None:
    """하위 호환 — changed_only면 변경 패널만, 아니면 전체."""
    if changed_only:
        if diffs:
            subtree = _build_changed_subtree(updated, diffs)
            _render_json_tree_html(subtree, variant="changed", max_h=420)
        return
    changed_map = {d["경로"]: (d["표준값"], d["추출값"]) for d in diffs}
    _render_json_tree_html(updated, changed=changed_map, variant="full", max_h=680)


def _render_result(res: dict) -> None:
    diffs = res["diffs"]
    logistics_n = sum(1 for d in diffs if str(d.get("경로", "")).startswith("logistics_process."))
    domain = res.get("domain", "")
    domain_badge = f" — 도메인: **{domain}**" if domain else ""
    st.subheader(f"업데이트 결과 — 변경 {len(diffs)}건{domain_badge}")
    if diffs:
        _render_changed_banner(diffs)
    if logistics_n:
        st.success(
            f"물류 시뮬레이션(`logistics_process`) {logistics_n}건이 **사이드바 시뮬 파라미터**에 자동 반영되었습니다."
        )
    elif not diffs:
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

    dl_col, _ = st.columns([1, 3])
    with dl_col:
        st.download_button(
            "업데이트된 JSON 내려받기",
            data=json.dumps(res["updated"], ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="process_standard_updated.json",
            mime="application/json",
            use_container_width=True,
        )

    st.divider()
    _render_json_panels(res["updated"], diffs)
