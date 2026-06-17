"""`data/공정설명260521.md` 보기·편집 뷰."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from views.process_doc_highlight import markdown_for_preview

# 프로젝트 루트 기준 공정 설명 문서
PROCESS_DOC_PATH = Path(__file__).resolve().parent.parent / "data" / "공정설명260521.md"
_SESSION_DRAFT_KEY = "process_description_md_draft"
_RELOAD_FROM_DISK_FLAG = "process_description_reload_from_disk"
_EDIT_MODE_KEY = "process_description_editing"
_OPEN_EDITOR_FLAG = "process_description_open_editor"
_CLOSE_EDITOR_FLAG = "process_description_close_editor"
_UPLOAD_NONCE_KEY = "process_description_md_upload_nonce"
_LLM_PROPOSED_KEY = "process_description_llm_proposed"
_LLM_EXTRACTED_KEY = "process_description_llm_extracted"
_LLM_CHANGES_KEY = _LLM_EXTRACTED_KEY  # 이전 이름 호환
_LEGACY_LLM_CHANGES_SESSION_KEY = "process_description_llm_changes"
_BTN_EXTRACT_KEY = "process_description_extract_from_doc"
FOCUS_PARAMS_TAB_AFTER_EXTRACT = "process_description_focus_params_tab"


def _sync_llm_extract_session() -> None:
    """이전 세션 키(`process_description_llm_changes`)를 추출 목록 키로 옮긴다."""
    if _LEGACY_LLM_CHANGES_SESSION_KEY not in st.session_state:
        return
    if _LLM_EXTRACTED_KEY not in st.session_state:
        st.session_state[_LLM_EXTRACTED_KEY] = st.session_state.pop(
            _LEGACY_LLM_CHANGES_SESSION_KEY
        )
    else:
        st.session_state.pop(_LEGACY_LLM_CHANGES_SESSION_KEY, None)


def _load_text() -> str:
    if not PROCESS_DOC_PATH.is_file():
        return ""
    return PROCESS_DOC_PATH.read_text(encoding="utf-8")


def _extract_with_doc_baseline(md_text: str):
    """문서 추출. 기준선이 없으면 비교 없이, 있으면 이전 적용값과 비교한다."""
    from config import DEFAULT_CONFIG
    from llm_config import extract_config_from_markdown
    from ui.doc_baseline import load_doc_baseline

    baseline_cfg, _ = load_doc_baseline()
    is_initial = baseline_cfg is None
    return (
        extract_config_from_markdown(
            md_text,
            DEFAULT_CONFIG,
            diff_against=baseline_cfg,
            suppress_diff=is_initial,
        ),
        is_initial,
    )


def render() -> None:
    is_editing = bool(st.session_state.get(_EDIT_MODE_KEY, False))

    # 편집 모드에서만: 디스크 재로드(위젯 `key=_SESSION_DRAFT_KEY` 보다 먼저 실행)
    if is_editing and st.session_state.pop(_RELOAD_FROM_DISK_FLAG, False):
        st.session_state[_SESSION_DRAFT_KEY] = _load_text()

    if st.session_state.pop(_OPEN_EDITOR_FLAG, False):
        st.session_state[_EDIT_MODE_KEY] = True
        st.session_state[_SESSION_DRAFT_KEY] = _load_text()
        is_editing = True

    if st.session_state.pop(_CLOSE_EDITOR_FLAG, False):
        st.session_state[_EDIT_MODE_KEY] = False
        st.session_state.pop(_SESSION_DRAFT_KEY, None)
        is_editing = False

    if is_editing and _SESSION_DRAFT_KEY not in st.session_state:
        st.session_state[_SESSION_DRAFT_KEY] = _load_text()

    st.header("📄 공정 설명 문서")
    st.caption(
        f"파일: `{PROCESS_DOC_PATH.relative_to(PROCESS_DOC_PATH.parent.parent)}` — "
        "기본은 읽기 전용입니다. **편집**으로 수정하거나, 아래에서 **.md 파일**을 가져오기/보내기 할 수 있습니다. "
        "읽기 화면에서는 숫자·단위만 자동 강조되며, 파일에는 HTML 태그를 넣지 않아도 됩니다. "
        "아래 **문서에서 파라미터 추출**로 시뮬 설정을 뽑은 뒤 **📊 파라메터** 탭에서 확인·적용하세요."
    )

    if not PROCESS_DOC_PATH.is_file():
        st.warning(
            "아직 파일이 없습니다. **편집**에서 내용을 입력한 뒤 **파일에 저장**하면 `data/` 아래에 생성됩니다."
        )

    with st.expander("Markdown 파일(.md) 가져오기 /보내기", expanded=False):
        ex_c1, ex_c2 = st.columns(2)
        with ex_c1:
            st.caption("불러오기")
            upload_key = f"process_description_md_upload_{st.session_state.get(_UPLOAD_NONCE_KEY, 0)}"
            uploaded = st.file_uploader(
                "Markdown 파일 선택",
                type=["md"],
                label_visibility="collapsed",
                key=upload_key,
                help="UTF-8(또는 BOM 있는 UTF-8) .md 파일을 불러옵니다. 불러오면 편집 화면에 반영됩니다.",
            )
        with ex_c2:
            st.caption("보내기")
            _export_text = (
                str(st.session_state.get(_SESSION_DRAFT_KEY, ""))
                if is_editing
                else _load_text()
            )
            st.download_button(
                label=f"{PROCESS_DOC_PATH.name} 받기",
                data=_export_text.encode("utf-8"),
                file_name=PROCESS_DOC_PATH.name,
                mime="text/markdown; charset=utf-8",
                use_container_width=True,
                help="지금 보이는 내용(읽기: 디스크 기준, 편집: 편집 중인 초안)을 .md 파일로 저장합니다.",
            )

    if uploaded is not None:
        try:
            text = uploaded.getvalue().decode("utf-8-sig")
        except UnicodeDecodeError:
            st.error("UTF-8 텍스트로 된 .md 파일만 불러올 수 있습니다.")
        else:
            st.session_state[_SESSION_DRAFT_KEY] = text
            st.session_state[_EDIT_MODE_KEY] = True
            st.session_state[_UPLOAD_NONCE_KEY] = st.session_state.get(_UPLOAD_NONCE_KEY, 0) + 1
            if not is_editing:
                st.rerun()

    save = False
    if is_editing:
        st.text_area(
            "Markdown 원문",
            height=520,
            key=_SESSION_DRAFT_KEY,
            label_visibility="collapsed",
            placeholder="# 제목\n\n내용을 입력하세요.",
        )
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            if st.button("초기화", help="저장하지 않은 편집 내용은 버려집니다."):
                st.session_state[_RELOAD_FROM_DISK_FLAG] = True
                st.rerun()
        with c2:
            if st.button("취소", help="편집을 닫고 디스크 내용 기준으로 돌아갑니다. 저장하지 않은 변경은 사라집니다."):
                st.session_state[_CLOSE_EDITOR_FLAG] = True
                st.rerun()
        with c3:
            save = st.button("파일에 저장", type="primary")
    else:
        body = _load_text()
        if body.strip():
            st.markdown(markdown_for_preview(body), unsafe_allow_html=True)
        else:
            st.info("파일이 비어 있거나 없습니다. **편집**을 눌러 내용을 작성하세요.")
        _, btn_col = st.columns([4, 1])
        with btn_col:
            if st.button("편집", type="secondary", use_container_width=True):
                st.session_state[_OPEN_EDITOR_FLAG] = True
                st.rerun()

    if save:
        try:
            PROCESS_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
            PROCESS_DOC_PATH.write_text(
                str(st.session_state.get(_SESSION_DRAFT_KEY, "")),
                encoding="utf-8",
            )
            st.session_state[_EDIT_MODE_KEY] = False
            st.session_state.pop(_SESSION_DRAFT_KEY, None)
            st.success("저장했습니다.")
            st.rerun()
        except OSError as e:
            st.error(f"저장에 실패했습니다: {e}")

    _render_extract_from_doc(is_editing)


def _render_extract_from_doc(is_editing: bool) -> None:
    """문서 본문에서 시뮬 파라미터를 추출한다. 완료 시 파라메터 탭으로 이동한다."""
    _sync_llm_extract_session()

    st.divider()
    st.subheader("문서에서 파라미터 추출")
    st.caption(
        "문서 본문의 숫자를 읽어 시뮬레이션 파라미터로 추출합니다. "
        "**처음 추출**은 문서 값을 바로 적용하며, **이후에는 마지막 적용값과 비교**해 "
        "문서를 수정한 경우에만 변경 내역을 표시합니다. "
        "(Google Gemini API 키 필요 — **⚙️ 설정** 탭에서 등록, "
        "또는 [Google AI Studio](https://aistudio.google.com/apikey)에서 발급)"
    )

    current_text = (
        str(st.session_state.get(_SESSION_DRAFT_KEY, "")) if is_editing else _load_text()
    )
    if is_editing:
        st.caption(
            "⚠️ 편집 중인 초안 기준으로 추출합니다. "
            "디스크에 저장된 내용으로 하려면 먼저 **파일에 저장**하세요."
        )
    elif not current_text.strip():
        st.info("문서가 없습니다. 위에서 내용을 작성·저장한 뒤 추출하세요.")

    if st.button(
        "문서에서 파라미터 추출",
        type="secondary",
        disabled=not current_text.strip(),
        help="문서를 분석해 입력 파라미터를 뽑습니다. 문서 수정 후에는 이전 적용값과 비교합니다.",
        key=_BTN_EXTRACT_KEY,
    ):
        from ui.doc_baseline import apply_doc_extract_config

        with st.spinner("문서에서 파라미터를 추출하는 중..."):
            try:
                (proposed, _changes, extracted), is_initial = _extract_with_doc_baseline(
                    current_text
                )
            except Exception as e:  # noqa: BLE001
                st.session_state.pop(_LLM_PROPOSED_KEY, None)
                st.session_state.pop(_LLM_EXTRACTED_KEY, None)
                st.error(f"추출에 실패했습니다: {e}")
            else:
                if is_initial:
                    apply_doc_extract_config(proposed, [], md_text=current_text)
                    st.session_state.pop(_LLM_PROPOSED_KEY, None)
                    st.session_state.pop(_LLM_EXTRACTED_KEY, None)
                    st.session_state["_llm_apply_toast"] = (
                        "문서에서 파라미터를 처음 추출해 사이드바에 적용했습니다."
                    )
                    st.rerun()
                else:
                    st.session_state[_LLM_PROPOSED_KEY] = proposed
                    st.session_state[_LLM_EXTRACTED_KEY] = extracted
                    st.session_state[FOCUS_PARAMS_TAB_AFTER_EXTRACT] = True
                    st.rerun()
