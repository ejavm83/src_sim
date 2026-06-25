"""공정 설명 문서 → S88 공정 구조 트리 (전체화면 탭).

가독성을 위해 좌→우 SVG 트리로 값까지 보여주고, 아래 표에서는 **수치(값)만** 편집한다.
표에서 값을 고치면 트리(SVG)에도 즉시 반영된다.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from process_tree import (
    ProcessTree,
    extract_process_tree_from_markdown,
    tree_to_obj,
    tree_to_svg,
)

_TREE_KEY = "process_tree_result"
_BTN_KEY = "process_tree_extract_btn"
_APPLY_KEY = "process_tree_apply_btn"
_EDITOR_KEY = "process_tree_value_editor"


def _doc_text() -> str:
    """편집 중이면 초안, 아니면 디스크 문서."""
    from views.process_description import _EDIT_MODE_KEY, _SESSION_DRAFT_KEY, _load_text

    if st.session_state.get(_EDIT_MODE_KEY):
        return str(st.session_state.get(_SESSION_DRAFT_KEY, ""))
    return _load_text()


def render_page() -> None:
    st.header("🌳 공정 트리")
    st.caption(
        "공정 설명 문서를 **배치 → 단계 → 작업 → 파라미터 / 특성** 계층으로 추출해 트리로 보여줍니다. "
        "아래 표에서 **값(수치)만** 고친 뒤 **시뮬레이션에 적용**하면 트리와 사이드바·시뮬에 반영됩니다. "
        "(LLM API 키 필요 — **⚙️ 설정** 탭에서 Gemini 또는 OpenAI(ChatGPT) 선택·등록)"
    )

    current_text = _doc_text()
    c1, _ = st.columns([1, 3])
    with c1:
        if st.button(
            "공정 트리로 추출",
            type="secondary",
            disabled=not current_text.strip(),
            key=_BTN_KEY,
            use_container_width=True,
            help="문서를 계층 구조로 분해합니다. 파라미터는 표준 설정 필드와 매핑됩니다.",
        ):
            with st.spinner("공정 구조를 트리로 추출하는 중..."):
                try:
                    tree = extract_process_tree_from_markdown(current_text)
                except Exception as e:  # noqa: BLE001
                    st.session_state.pop(_TREE_KEY, None)
                    st.error(f"트리 추출에 실패했습니다: {e}", icon="⚠️")
                else:
                    st.session_state[_TREE_KEY] = tree
                    st.session_state.pop(_EDITOR_KEY, None)  # 새 트리 → 편집 표 초기화

    if not current_text.strip():
        st.info("공정 설명 문서가 비어 있습니다. **📄 공정 설명** 탭에서 작성·저장한 뒤 추출하세요.")

    tree = st.session_state.get(_TREE_KEY)
    if isinstance(tree, ProcessTree):
        _render_tree(tree, current_text)
    elif current_text.strip():
        st.caption("아직 추출된 트리가 없습니다. 위 **공정 트리로 추출**을 누르세요.")


def _value_rows(tree: ProcessTree) -> list[dict[str, object]]:
    """편집 표 행: 필드별 1행(단계·작업·항목·값·단위·필드)."""
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for stage in tree.stages:
        for op in stage.operations:
            for p in op.parameters:
                if p.field in seen:
                    continue
                seen.add(p.field)
                rows.append(
                    {
                        "단계": stage.name,
                        "작업": op.name,
                        "항목": p.label,
                        "값": p.value,
                        "단위": p.unit,
                        "필드": p.field,
                    }
                )
    return rows


def _effective_values(rows: list[dict[str, object]]) -> dict[str, float]:
    """추출값 + 편집 표 수정분을 합친 field→값 (트리 표시·적용 공용)."""
    eff: dict[str, float] = {}
    for r in rows:
        if r["값"] is not None:
            eff[str(r["필드"])] = float(r["값"])  # type: ignore[arg-type]
    state = st.session_state.get(_EDITOR_KEY)
    if isinstance(state, dict):
        for pos, change in (state.get("edited_rows") or {}).items():
            try:
                idx = int(pos)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(rows) and "값" in change:
                field = str(rows[idx]["필드"])
                val = change["값"]
                if val is None:
                    eff.pop(field, None)
                else:
                    eff[field] = float(val)
    return eff


def _render_tree(tree: ProcessTree, md_text: str) -> None:
    n_par = sum(len(o.parameters) for s in tree.stages for o in s.operations)
    n_char = sum(
        len(o.characteristics) for s in tree.stages for o in s.operations
    ) + len(tree.batch_characteristics)

    rows = _value_rows(tree)
    eff = _effective_values(rows)

    head = st.columns([3, 1])
    with head[0]:
        st.markdown(f"### {tree.product or '배치'}")
        st.caption(f"단계 {len(tree.stages)} · 파라미터 {n_par} · 특성 {n_char}")
    with head[1]:
        apply_clicked = st.button(
            "✅ 시뮬레이션에 적용",
            type="primary",
            key=_APPLY_KEY,
            use_container_width=True,
            help="표에서 고친 값을 트리·사이드바·시뮬레이션 설정에 반영합니다.",
        )
        st.download_button(
            "트리 JSON 내려받기",
            data=json.dumps(tree_to_obj(tree), ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="process_tree.json",
            mime="application/json",
            use_container_width=True,
        )

    if apply_clicked:
        _apply_to_sim(eff, md_text)

    # ── 좌→우 트리 (가독성용, 값까지 표시) ──
    svg, _w, h = tree_to_svg(tree, eff)
    components.html(
        f'<div style="overflow:auto">{svg}</div>',
        height=min(h + 24, 1000),
        scrolling=True,
    )

    if tree.batch_characteristics:
        st.caption(
            "배치 특성(실행 시 기록): "
            + " · ".join(
                c.name + (f" ({c.unit})" if c.unit else "")
                for c in tree.batch_characteristics
            )
        )

    # ── 값(수치)만 편집하는 표 ──
    st.markdown("**📝 값(수치) 수정**")
    if rows:
        st.caption("‘값’ 칸만 고칠 수 있습니다. 고친 뒤 위 **시뮬레이션에 적용**을 누르면 트리와 시뮬에 반영됩니다.")
        df = pd.DataFrame(rows, columns=["단계", "작업", "항목", "값", "단위", "필드"])
        df["값"] = pd.to_numeric(df["값"], errors="coerce")
        st.data_editor(
            df,
            key=_EDITOR_KEY,
            hide_index=True,
            use_container_width=True,
            disabled=["단계", "작업", "항목", "단위", "필드"],
            column_config={
                "값": st.column_config.NumberColumn("값", help="문서에서 추출된 값. 이 칸만 수정할 수 있습니다."),
                "필드": None,  # 내부 매핑 키 — 숨김
            },
        )
    else:
        st.info("문서에서 매핑된 파라미터가 없습니다.")


def _apply_to_sim(data: dict[str, float], md_text: str) -> None:
    """편집된 값을 평면 머지 파이프라인에 흘려 시뮬 설정에 적용한다(추가 Gemini 호출 없음)."""
    from config import DEFAULT_CONFIG
    from llm_config import _merge_and_diff
    from ui.doc_baseline import apply_doc_extract_config, load_doc_baseline
    from views.process_description import (
        FOCUS_PARAMS_TAB_AFTER_EXTRACT,
        _LLM_EXTRACTED_KEY,
        _LLM_PROPOSED_KEY,
    )

    if not data:
        st.warning("적용할 값이 없습니다.")
        return

    baseline_cfg, _ = load_doc_baseline()
    is_initial = baseline_cfg is None
    proposed, _changes, extracted = _merge_and_diff(
        DEFAULT_CONFIG, data, diff_against=baseline_cfg, suppress_diff=is_initial
    )
    if is_initial:
        apply_doc_extract_config(proposed, [], md_text=md_text)
        st.session_state.pop(_LLM_PROPOSED_KEY, None)
        st.session_state.pop(_LLM_EXTRACTED_KEY, None)
        st.session_state["_llm_apply_toast"] = (
            f"공정 트리에서 파라미터 {len(data)}개를 사이드바에 적용했습니다."
        )
    else:
        st.session_state[_LLM_PROPOSED_KEY] = proposed
        st.session_state[_LLM_EXTRACTED_KEY] = extracted
        st.session_state[FOCUS_PARAMS_TAB_AFTER_EXTRACT] = True
    st.rerun()
