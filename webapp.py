"""공정 시뮬레이션 — Streamlit 대시보드.

실행: `streamlit run webapp.py`
"""

from __future__ import annotations

import time

import streamlit as st
import streamlit.components.v1 as components

from config import DEFAULT_CONFIG, SimulationConfig
from config_sanitize import sanitize_for_simulation, simulation_config_issues
from report import Analysis, analyze
from run_compare import MAX_SNAPSHOTS, flatten_config, snapshot
from simulation import run_simulation
from ui.app_settings import get_gemini_api_key, session_api_key_name
from ui.compare_panel import render_compare_panel
from ui.results import render_results
from ui.sidebar_params import render_config_sidebar
from ui.snapshot_store import load_saved_snapshots, save_snapshots_to_disk
from views import (
    parameter_reference,
    process_description,
    process_parameters,
    settings,
    tech_glossary,
    used_technology,
)
from views.process_description import FOCUS_PARAMS_TAB_AFTER_EXTRACT


def _default_snapshot_display_name(snapshot_idx: int) -> str:
    """자동 저장·사이드바 기본값에 쓰는 다음 스냅샷 표시 이름."""
    return f"테스트 #{snapshot_idx}"


st.set_page_config(
    page_title="공정 시뮬레이션",
    page_icon="🏭",
    layout="wide",
)

# 슬라이더 트랙 양끝 라벨 숨김 + 상단 헤더·탭 간격 축소
st.markdown(
    """
    <style>
    div[data-testid="stSliderTickBar"] {
        display: none !important;
    }
    [data-testid="stAppViewContainer"] .main .block-container {
        padding-top: 0.75rem;
        padding-bottom: 1rem;
    }
    [data-testid="stAppViewContainer"] .main .block-container > div:first-child {
        gap: 0.35rem;
    }
    .app-title {
        font-size: 1.15rem;
        font-weight: 600;
        margin: 0;
        padding: 0;
        line-height: 1.3;
        color: inherit;
    }
    .app-title-home {
        cursor: pointer;
        user-select: none;
    }
    .app-title-home:hover {
        opacity: 0.82;
    }
    div[data-testid="stTabs"] {
        margin-top: 0.15rem;
    }
    div[data-testid="stTabs"] [data-baseweb="tab-list"] {
        gap: 0.25rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if "last_run" not in st.session_state:
    st.session_state.last_run = None
if "saved_runs" not in st.session_state:
    loaded_runs, loaded_idx = load_saved_snapshots()
    st.session_state.saved_runs = loaded_runs
    st.session_state.snapshot_idx = loaded_idx
if "snap_name" not in st.session_state:
    st.session_state.snap_name = _default_snapshot_display_name(st.session_state.snapshot_idx)
if session_api_key_name() not in st.session_state:
    persisted_key = get_gemini_api_key()
    if persisted_key:
        st.session_state[session_api_key_name()] = persisted_key

# 탭 위젯은 본문에서 먼저 만들어지므로, 같은 런의 사이드바 등에서는 이 플래그만 세우고 다음 rerun 초기에
# `MAIN_TABS_WIDGET_KEY`를 설정한다(Streamlit은 위젯 생성 이후 해당 key의 session_state를 같은 런에서 수정할 수 없음).
_FOCUS_SIM_TAB_AFTER_RUN = "_focus_sim_tab_after_run"
# snap_name 텍스트 입력은 사이드바에서 먼저 만들어지므로, 같은 런에서 snap_name을 바꾸면 예외가 난다. 다음 런 초기에 반영한다.
_PENDING_SNAP_NAME = "_pending_snap_name"
_pending_default_title = st.session_state.pop(_PENDING_SNAP_NAME, None)
if _pending_default_title is not None:
    st.session_state.snap_name = _pending_default_title

# 앱 버전(사이드바 상단 표기)
APP_VERSION_INFO = "v0.2.0 (2026.06.17)"

# 탭 라벨·세션 키(시뮬 완료 후 시뮬 탭으로 포커스할 때 사용)
MAIN_TABS_KEY = "main_tabs"
MAIN_TABS_WIDGET_KEY = f"{MAIN_TABS_KEY}_v11"
TAB_SIM_LABEL = "🏭 시뮬레이션"
TAB_COMPARE_LABEL = "🆚 스냅샷 비교"
TAB_PROCESS_DOC_LABEL = "📄 공정 설명"
TAB_EXTRACTED_PARAMS_LABEL = "📊 파라메터"
TAB_PARAMS_LABEL = "📋 파라미터·단위"
TAB_USED_TECH_LABEL = "📘 사용 기술"
TAB_TERMS_LABEL = "🔤 용어·약어"
TAB_SETTINGS_LABEL = "⚙️ 설정"
_DEV_TABS_VISIBLE_KEY = "dev_tabs_visible"
_DEV_TABS_TOGGLE_QP = "__dev_tabs_toggle"
_DOC_BOOTSTRAP_KEY = "_doc_baseline_bootstrapped"


def _bootstrap_doc_extracted_config() -> None:
    """저장된 문서 기준선을 복원하거나, 없으면 최초 자동 추출을 시도한다."""
    if st.session_state.get(_DOC_BOOTSTRAP_KEY):
        return
    st.session_state[_DOC_BOOTSTRAP_KEY] = True

    from llm_config import EXTRACTED_CHANGE_DETAILS_KEY, EXTRACTED_CHANGED_LABELS_KEY
    from ui.doc_baseline import (
        apply_doc_extract_config,
        load_doc_baseline,
        md_fingerprint,
    )
    from views.process_description import _load_text

    md_text = _load_text()
    if not md_text.strip():
        return

    baseline_cfg, baseline_fp = load_doc_baseline()
    if baseline_cfg is not None:
        st.session_state["extracted_config"] = baseline_cfg
        st.session_state[EXTRACTED_CHANGED_LABELS_KEY] = set()
        st.session_state[EXTRACTED_CHANGE_DETAILS_KEY] = {}
        if baseline_fp and md_fingerprint(md_text) != baseline_fp:
            st.session_state["_doc_md_stale"] = True
        return

    from llm_config import api_key_configured

    if not api_key_configured():
        return

    try:
        from views.process_description import _extract_with_doc_baseline

        (proposed, _changes, _extracted), is_initial = _extract_with_doc_baseline(md_text)
        if is_initial:
            apply_doc_extract_config(proposed, [], md_text=md_text)
    except Exception:
        pass


def _handle_dev_tabs_shortcut() -> None:
    """Shift+F12로 파라미터·단위·용어·약어 탭 표시를 토글한다."""
    if _DEV_TABS_VISIBLE_KEY not in st.session_state:
        st.session_state[_DEV_TABS_VISIBLE_KEY] = False

    if st.query_params.get(_DEV_TABS_TOGGLE_QP):
        st.session_state[_DEV_TABS_VISIBLE_KEY] = not st.session_state[_DEV_TABS_VISIBLE_KEY]
        del st.query_params[_DEV_TABS_TOGGLE_QP]
        st.rerun()

    components.html(
        f"""
        <script>
        (function() {{
            try {{
                const w = window.top || window.parent;
                if (!w || w.__simDevTabsShortcutBound) return;
                w.__simDevTabsShortcutBound = true;
                w.addEventListener("keydown", function(e) {{
                    if (e.shiftKey && e.key === "F12") {{
                        e.preventDefault();
                        const url = new URL(w.location.href);
                        url.searchParams.set("{_DEV_TABS_TOGGLE_QP}", "1");
                        w.location.href = url.toString();
                    }}
                }}, true);
            }} catch (err) {{
                // iframe sandbox / cross-origin — 개발자 탭 단축키만 비활성
            }}
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def _visible_main_tab_labels() -> list[str]:
    labels = [TAB_SIM_LABEL, TAB_COMPARE_LABEL, TAB_PROCESS_DOC_LABEL, TAB_EXTRACTED_PARAMS_LABEL]
    if st.session_state.get(_DEV_TABS_VISIBLE_KEY, False):
        labels.append(TAB_PARAMS_LABEL)
    labels.append(TAB_USED_TECH_LABEL)
    if st.session_state.get(_DEV_TABS_VISIBLE_KEY, False):
        labels.append(TAB_TERMS_LABEL)
    labels.append(TAB_SETTINGS_LABEL)
    return labels


def _sanitize_main_tab_selection(visible_labels: list[str]) -> None:
    current = st.session_state.get(MAIN_TABS_WIDGET_KEY)
    if current and current not in visible_labels:
        st.session_state[MAIN_TABS_WIDGET_KEY] = TAB_SIM_LABEL


def persist_run_snapshot(cfg: SimulationConfig, analysis: Analysis) -> None:
    """시뮬 완료 직후 자동 저장. 동일 설정(평탄화된 config)이 이미 있으면 결과만 갱신하고 표시 이름·id는 유지한다."""
    flat = flatten_config(cfg)
    saved = st.session_state.saved_runs
    display_name = st.session_state.snap_name.strip() or _default_snapshot_display_name(
        st.session_state.snapshot_idx
    )
    new_snap = snapshot(display_name, cfg, analysis)
    for i, s in enumerate(saved):
        if s.get("config") == flat:
            new_snap["name"] = s["name"]
            if s.get("id"):
                new_snap["id"] = s["id"]
            saved[i] = new_snap
            st.session_state._save_toast = (
                f"스냅샷 '{new_snap['name']}' 동일 설정으로 자동 갱신됨 ({len(saved)}/{MAX_SNAPSHOTS})"
            )
            save_snapshots_to_disk(saved, st.session_state.snapshot_idx)
            return

    if len(saved) >= MAX_SNAPSHOTS:
        saved.pop(0)
    saved.append(new_snap)
    st.session_state.snapshot_idx += 1
    st.session_state[_PENDING_SNAP_NAME] = _default_snapshot_display_name(st.session_state.snapshot_idx)
    st.session_state._save_toast = (
        f"스냅샷 '{new_snap['name']}' 자동 저장됨 ({len(saved)}/{MAX_SNAPSHOTS})"
    )
    save_snapshots_to_disk(saved, st.session_state.snapshot_idx)


st.markdown(
    '<p class="app-title app-title-home" role="button" tabindex="0" '
    'title="홈 (새로고침)" '
    'onclick="window.parent.location.reload()">'
    "🏭 공정 물류 시뮬레이션</p>",
    unsafe_allow_html=True,
)

_handle_dev_tabs_shortcut()
_bootstrap_doc_extracted_config()

# 시뮬 완료·파라미터 추출 완료: 다음 rerun 직후·`st.tabs` 이전에 해당 탭으로 포커스
if st.session_state.pop(_FOCUS_SIM_TAB_AFTER_RUN, False):
    st.session_state[MAIN_TABS_WIDGET_KEY] = TAB_SIM_LABEL
if st.session_state.pop(FOCUS_PARAMS_TAB_AFTER_EXTRACT, False):
    st.session_state[MAIN_TABS_WIDGET_KEY] = TAB_EXTRACTED_PARAMS_LABEL

_tab_labels = _visible_main_tab_labels()
_sanitize_main_tab_selection(_tab_labels)
_tab_ctxs = st.tabs(
    _tab_labels,
    key=MAIN_TABS_WIDGET_KEY,
    on_change="rerun",
    default=TAB_SIM_LABEL,
)
_tab_by_label = dict(zip(_tab_labels, _tab_ctxs, strict=True))


with st.sidebar:
    st.caption(APP_VERSION_INFO)
    st.divider()
    st.header("⚙️ 시뮬레이션 파라미터")
    try:
        from excel_config import default_excel_path

        st.caption(f"기본값 파일: `{default_excel_path().name}` (`data/`)")
    except Exception:
        st.caption("기본값: 코드 내장( `data` 에 `.xlsx` 없음 )")

    # 공정 설명 문서에서 추출·적용한 값이 있으면 그걸 기본값으로 쓴다(없으면 엑셀·코드 기본).
    from llm_config import EXTRACTED_CHANGE_DETAILS_KEY, EXTRACTED_CHANGED_LABELS_KEY

    cfg_base = st.session_state.get("extracted_config", DEFAULT_CONFIG)
    _changed_labels = st.session_state.get(EXTRACTED_CHANGED_LABELS_KEY) or set()
    _change_details = st.session_state.get(EXTRACTED_CHANGE_DETAILS_KEY) or {}
    if "extracted_config" in st.session_state:
        if st.session_state.pop("_doc_md_stale", False):
            st.markdown(
                '<p style="margin:0 0 0.35rem 0;padding:0.45rem 0.55rem;'
                "background:#e3f2fd;border:1px solid #90caf9;border-radius:6px;"
                'font-size:0.82rem;line-height:1.4;color:#0d47a1;">'
                "📄 공정 설명 문서가 마지막 적용 이후 변경되었습니다. "
                "**📄 공정 설명** 탭에서 **문서에서 파라미터 추출**을 다시 실행하세요.</p>",
                unsafe_allow_html=True,
            )
        if _changed_labels:
            st.markdown(
                f'<p style="margin:0 0 0.35rem 0;padding:0.45rem 0.55rem;'
                "background:#fff3e0;border:1px solid #fcd34d;border-radius:6px;"
                'font-size:0.82rem;line-height:1.4;color:#92400e;">'
                f"📄 문서 추출로 <strong>{len(_changed_labels)}개</strong> 항목이 변경되었습니다. "
                "아래 주황 표시·펼쳐진 섹션을 확인하세요.</p>",
                unsafe_allow_html=True,
            )
            with st.expander("변경 내역 보기", expanded=True):
                for label in sorted(_changed_labels):
                    det = _change_details.get(label, {})
                    st.markdown(
                        f"- **{label}**: {det.get('기존값', '?')} → **{det.get('추출값', '?')}**"
                    )
        else:
            st.caption("📄 **공정 설명** 문서에서 추출한 값이 기본으로 반영되어 있습니다.")
    _cfg_nonce = st.session_state.get("config_nonce", 0)
    cfg = render_config_sidebar(
        cfg_base,
        key_suffix=f"_v{_cfg_nonce}",
        highlight_labels=_changed_labels,
        change_details=_change_details,
    )

    run_btn = st.button("🚀 시뮬레이션 실행", type="primary", use_container_width=True)

    st.divider()
    st.markdown("**💾 결과 스냅샷**")
    st.caption(
        "실행이 끝나면 자동으로 저장됩니다. 같은 설정으로 다시 돌리면 **이미 있는 항목의 결과만 갱신**되고 "
        "이름은 그대로 둡니다. 이름 바꾸기·삭제는 **🆚 스냅샷 비교** 탭 상단에서 할 수 있습니다."
    )
    st.text_input(
        "다음 실행 시 저장될 제목",
        key="snap_name",
        label_visibility="collapsed",
    )

if st.session_state.get("_save_toast"):
    st.toast(st.session_state.pop("_save_toast"), icon="💾")

if st.session_state.get("_llm_apply_toast"):
    st.toast(st.session_state.pop("_llm_apply_toast"), icon="📄")

if run_btn:
    issues = simulation_config_issues(cfg)
    cfg = sanitize_for_simulation(cfg)
    if issues:
        st.warning(
            "유효 범위를 벗어난 파라미터를 자동 보정했습니다. "
            "사이드바에서 값을 확인하세요. (" + " · ".join(issues) + ")"
        )

    progress_bar = st.progress(0.0, text="시뮬레이션 준비 중...")

    def progress_cb(frac: float, sim_min: float) -> None:
        day = sim_min / (24 * 60)
        progress_bar.progress(
            min(1.0, frac),
            text=f"가상 시각: {day:.2f}일 ({sim_min:.0f}분)  —  {frac*100:.1f}% 진행",
        )

    t0 = time.time()
    metrics = run_simulation(cfg, progress=progress_cb)
    elapsed = time.time() - t0
    analysis = analyze(metrics, cfg)
    progress_bar.empty()

    st.session_state.last_run = {
        "cfg": cfg,
        "metrics": metrics,
        "analysis": analysis,
        "elapsed_s": elapsed,
    }
    persist_run_snapshot(cfg, analysis)
    st.session_state[_FOCUS_SIM_TAB_AFTER_RUN] = True
    st.success(
        f"✅ 시뮬레이션 완료 — 실측 {elapsed:.2f}초 · 이벤트 {len(metrics.events):,}건"
    )
    st.rerun()


with _tab_by_label[TAB_SIM_LABEL]:
    run = st.session_state.last_run

    if run is None:
        st.info("👈 사이드바에서 파라미터를 조정하고 **시뮬레이션 실행** 버튼을 누르세요.")
        st.markdown(
            "핵심 기술 쉬운 설명은 **📘 사용 기술** 탭에서 확인할 수 있습니다. "
            "공정 서술은 **📄 공정 설명** 탭에서 `data/공정설명260521.md` 내용을 보거나 편집·저장할 수 있습니다."
        )
        if st.session_state.saved_runs:
            st.caption(
                f"💾 이전에 저장한 실행 {len(st.session_state.saved_runs)}건이 있습니다. "
                "**🆚 스냅샷 비교** 탭에서 KPI·설정·추이를 비교할 수 있습니다."
            )
    else:
        render_results(
            run["metrics"],
            run["cfg"],
            run["analysis"],
        )

with _tab_by_label[TAB_COMPARE_LABEL]:
    st.markdown(
        "저장해 둔 실행 스냅샷끼리 **KPI·파라미터·자원 가동률·일별 생산 추이**를 한 화면에서 비교합니다. "
        "각 블록 아래에는 **무엇이 달라졌는지(비교 요약)**와 **그 결과가 의미하는 바(시사점)**를 따로 적어 두었습니다. "
        "새 스냅샷은 **🏭 시뮬레이션** 탭에서 실행할 때마다 **자동 저장**됩니다."
    )
    if st.session_state.saved_runs:
        render_compare_panel(st.session_state.saved_runs, expanded=True)
    else:
        st.info(
            "아직 저장된 스냅샷이 없습니다. **🏭 시뮬레이션** 탭에서 한 번 실행하면 자동으로 첫 스냅샷이 쌓입니다."
        )

with _tab_by_label[TAB_PROCESS_DOC_LABEL]:
    process_description.render()

with _tab_by_label[TAB_EXTRACTED_PARAMS_LABEL]:
    process_parameters.render()

if TAB_PARAMS_LABEL in _tab_by_label:
    with _tab_by_label[TAB_PARAMS_LABEL]:
        parameter_reference.render()

with _tab_by_label[TAB_USED_TECH_LABEL]:
    used_technology.render()

if TAB_TERMS_LABEL in _tab_by_label:
    with _tab_by_label[TAB_TERMS_LABEL]:
        tech_glossary.render()

with _tab_by_label[TAB_SETTINGS_LABEL]:
    settings.render()
