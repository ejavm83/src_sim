"""공정 설명 문서에서 추출한 시뮬레이션 파라미터 뷰."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from views.process_description import (
    _LLM_EXTRACTED_KEY,
    _LLM_PROPOSED_KEY,
    _load_text,
    _sync_llm_extract_session,
)

_BTN_APPLY_KEY = "proc_params_apply"
_BTN_CANCEL_KEY = "proc_params_cancel"


def _highlight_extracted_changes(row: pd.Series) -> list[str]:
    if row.get("변경") != "예":
        return [""] * len(row)
    base = "background-color: #fff3e0; color: #212121; font-weight: 600"
    return [
        f"{base}; color: #b45309" if col == "추출값" else base
        for col in row.index
    ]


def render() -> None:
    """문서 본문(자연어)에서 시뮬레이션 파라미터를 추출 → 변경 확인 → 적용."""
    from views import parameter_schema

    _sync_llm_extract_session()

    st.header("📊 파라메터")

    # 추출하는 파라메터의 구조를 JSON 스키마로 본다(추출 여부와 무관하게 항상 표시).
    parameter_schema.render_section()
    st.divider()

    st.subheader("📄 문서 추출값 비교")
    st.caption(
        "**📄 공정 설명** 탭에서 추출한 값을 **마지막 적용값**과 비교합니다. "
        "문서를 처음 추출할 때는 비교 없이 바로 적용되며, 문서를 수정한 뒤 추출하면 "
        "변경된 항목만 주황색으로 표시됩니다. **적용**을 누르면 사이드바·시뮬레이션에 반영됩니다."
    )

    if st.session_state.get(_LLM_PROPOSED_KEY) is None:
        st.info(
            "추출된 파라미터가 없습니다. **🌳 공정 트리** 탭에서 "
            "**공정 트리로 추출** 후 **시뮬레이션에 적용**을 실행하세요."
        )
        return

    extracted = st.session_state.get(_LLM_EXTRACTED_KEY) or []
    changes = [row for row in extracted if row.get("변경") == "예"]
    if extracted:
        n_changed = len(changes)
        if n_changed:
            st.markdown(
                f"**문서에서 {len(extracted)}개 파라미터를 추출했습니다.** "
                f"그중 **{n_changed}개**가 마지막 적용값과 다릅니다(주황색 행). 적용 전 확인하세요."
            )
        else:
            st.markdown(
                f"**문서에서 {len(extracted)}개 파라미터를 추출했습니다.** "
                "마지막 적용값과 모두 동일합니다."
            )
        df = pd.DataFrame(extracted)
        st.dataframe(
            df.style.apply(_highlight_extracted_changes, axis=1),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("문서에서 파라미터를 찾지 못했습니다.")

    c_apply, c_cancel = st.columns(2)
    with c_apply:
        if st.button(
            "적용",
            type="primary",
            disabled=not changes,
            use_container_width=True,
            key=_BTN_APPLY_KEY,
        ):
            from ui.doc_baseline import apply_doc_extract_config

            apply_doc_extract_config(
                st.session_state[_LLM_PROPOSED_KEY],
                changes,
                md_text=_load_text(),
            )
            st.session_state.pop(_LLM_PROPOSED_KEY, None)
            st.session_state.pop(_LLM_EXTRACTED_KEY, None)
            st.session_state["_llm_apply_toast"] = (
                f"문서 변경분 {len(changes)}개를 사이드바에 반영했습니다. "
                "주황색으로 표시된 항목을 확인한 뒤 🏭 시뮬레이션 탭에서 실행하세요."
            )
            st.rerun()
    with c_cancel:
        if st.button("취소", use_container_width=True, key=_BTN_CANCEL_KEY):
            st.session_state.pop(_LLM_PROPOSED_KEY, None)
            st.session_state.pop(_LLM_EXTRACTED_KEY, None)
            st.rerun()
