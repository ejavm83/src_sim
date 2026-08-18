"""공정 시뮬레이션 — Streamlit 대시보드.

실행: `streamlit run webapp.py`
"""

from __future__ import annotations

import time

import streamlit as st

from config import DEFAULT_CONFIG, SimulationConfig
from config_sanitize import sanitize_for_simulation, simulation_config_issues
from report import Analysis, analyze
from run_compare import MAX_SNAPSHOTS, flatten_config, snapshot
from simulation import run_simulation
from cms_config import DEFAULT_CMS_CONFIG as CMS_DEFAULT_CONFIG
from ui.app_settings import sync_gemini_api_key_session
from ui.cms_sidebar import render_cms_sidebar
from ui.compare_panel import render_compare_panel
from ui.results import render_results
from ui.sidebar_params import render_config_sidebar
from ui.snapshot_store import load_saved_snapshots, save_snapshots_to_disk
from views import (
    ai_chat_view,
    cms_sim_view,
    domain_analysis_view,
    parameter_reference,
    process_description,
    process_parameters,
    process_tree_view,
    schema_table_view,
    settings,
    standard_schema_view,
    tech_glossary,
    used_technology,
)
from views.process_description import FOCUS_PARAMS_TAB_AFTER_EXTRACT


def _default_snapshot_display_name(snapshot_idx: int) -> str:
    """자동 저장·사이드바 기본값에 쓰는 다음 스냅샷 표시 이름."""
    return f"테스트 #{snapshot_idx}"


st.set_page_config(
    page_title="공정 분석 플랫폼",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="collapsed",
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
sync_gemini_api_key_session()

# 탭 위젯은 본문에서 먼저 만들어지므로, 같은 런의 사이드바 등에서는 이 플래그만 세우고 다음 rerun 초기에
# `MAIN_TABS_WIDGET_KEY`를 설정한다(Streamlit은 위젯 생성 이후 해당 key의 session_state를 같은 런에서 수정할 수 없음).
_FOCUS_SIM_TAB_AFTER_RUN = "_focus_sim_tab_after_run"
# snap_name 텍스트 입력은 사이드바에서 먼저 만들어지므로, 같은 런에서 snap_name을 바꾸면 예외가 난다. 다음 런 초기에 반영한다.
_PENDING_SNAP_NAME = "_pending_snap_name"
_pending_default_title = st.session_state.pop(_PENDING_SNAP_NAME, None)
if _pending_default_title is not None:
    st.session_state.snap_name = _pending_default_title

# 앱 버전(사이드바 상단 표기)
APP_VERSION_INFO = "v0.3.1-generic (2026.08.18 22:26)"

# 탭 라벨·세션 키(시뮬 완료 후 시뮬 탭으로 포커스할 때 사용)
MAIN_TABS_KEY = "main_tabs"
MAIN_TABS_WIDGET_KEY = f"{MAIN_TABS_KEY}_v16"
TAB_SIM_LABEL = "🔬 분석 결과"
TAB_CMS_SIM_LABEL = "🏭 CMS 공장 시뮬레이션"
TAB_SCR_SIM_LABEL = "🏭 SCR 공장 시뮬레이션"
CMS_CFG_KEY = "cms_sidebar_cfg"
TAB_COMPARE_LABEL = "🆚 스냅샷 비교"

# 공정 모델 선택 — 두 도메인을 선택적으로 쓴다.
MODEL_KEY = "active_process_model"
MODEL_CMS = "CMS 전선공장"
MODEL_SCR = "SCR 구리공장"
MODEL_CAPTIONS = {
    MODEL_CMS: "멕시코 CMS 공장 SOP v0.3 — 신선·연선·절연·조사·편조·시스·재권취",
    MODEL_SCR: "구 모델 — 입고·선별·용해·주조·출하",
}


def active_model() -> str:
    return st.session_state.get(MODEL_KEY, MODEL_CMS)
TAB_PROCESS_DOC_LABEL = "📄 공정 설명"
TAB_PROCESS_TREE_LABEL = "🌳 공정 트리"
TAB_STANDARD_JSON_LABEL = "📐 표준 JSON"
TAB_SCHEMA_TABLE_LABEL = "📋 공정 데이터"
TAB_AI_CHAT_LABEL = "💬 AI 어시스턴트"
TAB_EXTRACTED_PARAMS_LABEL = "📊 파라메터"
TAB_PARAMS_LABEL = "📋 파라미터·단위"
TAB_USED_TECH_LABEL = "📘 사용 기술"
TAB_TERMS_LABEL = "🔤 용어·약어"
TAB_SETTINGS_LABEL = "⚙️ 설정"


def _settings_tab_label() -> str:
    from llm_config import api_key_configured

    if api_key_configured():
        return f"{TAB_SETTINGS_LABEL} ✅"
    return f"{TAB_SETTINGS_LABEL} ⚠️"
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
    """Shift+F12로 공정 트리·파라미터·단위·용어·약어 탭 표시를 토글한다."""
    if _DEV_TABS_VISIBLE_KEY not in st.session_state:
        st.session_state[_DEV_TABS_VISIBLE_KEY] = False

    if st.query_params.get(_DEV_TABS_TOGGLE_QP):
        st.session_state[_DEV_TABS_VISIBLE_KEY] = not st.session_state[_DEV_TABS_VISIBLE_KEY]
        del st.query_params[_DEV_TABS_TOGGLE_QP]
        st.rerun()

    st.html(
        f"""
        <script>
        (function() {{
            if (window.__simDevTabsShortcutBound) return;
            window.__simDevTabsShortcutBound = true;
            window.addEventListener("keydown", function(e) {{
                if (e.shiftKey && e.key === "F12") {{
                    e.preventDefault();
                    const url = new URL(window.location.href);
                    url.searchParams.set("{_DEV_TABS_TOGGLE_QP}", "1");
                    window.location.href = url.toString();
                }}
            }}, true);
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _visible_main_tab_labels() -> list[str]:
    labels = [TAB_SIM_LABEL]
    # 선택한 공정 모델의 시뮬레이션 탭만 띄운다.
    if active_model() == MODEL_CMS:
        labels.append(TAB_CMS_SIM_LABEL)
    else:
        labels.extend([TAB_SCR_SIM_LABEL, TAB_COMPARE_LABEL])
    labels.append(TAB_PROCESS_DOC_LABEL)
    if st.session_state.get(_DEV_TABS_VISIBLE_KEY, False):
        labels.append(TAB_PROCESS_TREE_LABEL)
    labels.extend(
        [
            TAB_STANDARD_JSON_LABEL,
            TAB_SCHEMA_TABLE_LABEL,
            TAB_AI_CHAT_LABEL,
        ]
    )
    if st.session_state.get(_DEV_TABS_VISIBLE_KEY, False):
        labels.extend([TAB_EXTRACTED_PARAMS_LABEL, TAB_PARAMS_LABEL])
    labels.append(TAB_USED_TECH_LABEL)
    if st.session_state.get(_DEV_TABS_VISIBLE_KEY, False):
        labels.append(TAB_TERMS_LABEL)
    labels.append(_settings_tab_label())
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
    "🔬 공정 분석 플랫폼</p>",
    unsafe_allow_html=True,
)

_handle_dev_tabs_shortcut()
_bootstrap_doc_extracted_config()

# 공정 모델 선택 — 탭 구성이 여기에 좌우되므로 `st.tabs`보다 먼저 그린다.
with st.sidebar:
    st.caption(APP_VERSION_INFO)
    st.radio(
        "🏭 공정 모델",
        [MODEL_CMS, MODEL_SCR],
        key=MODEL_KEY,
        captions=[MODEL_CAPTIONS[MODEL_CMS], MODEL_CAPTIONS[MODEL_SCR]],
        help="어느 공장을 시뮬레이션할지 고릅니다. 파라미터와 탭이 함께 바뀝니다.",
    )
    st.divider()

# 시뮬 완료·파라미터 추출 완료: 다음 rerun 직후·`st.tabs` 이전에 해당 탭으로 포커스
if st.session_state.pop(_FOCUS_SIM_TAB_AFTER_RUN, False):
    st.session_state[MAIN_TABS_WIDGET_KEY] = TAB_SCR_SIM_LABEL
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


_SHOW_SIM_PARAMS_KEY = "_show_sim_params"

_MODEL = active_model()

# 선택한 모델의 파라미터만 사이드바에 그린다.
cms_cfg, cms_run_btn = st.session_state.get(CMS_CFG_KEY, CMS_DEFAULT_CONFIG), False
cfg, run_btn = DEFAULT_CONFIG, False

with st.sidebar:
    domain_name = st.session_state.get("_domain_name", "")
    if domain_name:
        st.caption(f"🏷️ **{domain_name}**")

    st.header("⚙️ 시뮬레이션 파라미터")

    if _MODEL == MODEL_CMS:
        # 항상 사양 파일을 다시 읽는다 — MD에서 사양을 재생성하면 바로 반영되도록.
        cms_cfg, cms_run_btn = render_cms_sidebar()
        st.session_state[CMS_CFG_KEY] = cms_cfg
    else:
        try:
            from excel_config import default_excel_path
            st.caption(f"기본값 파일: `{default_excel_path().name}` (`data/`)")
        except Exception:
            st.caption("기본값: 코드 내장")

        from llm_config import EXTRACTED_CHANGE_DETAILS_KEY, EXTRACTED_CHANGED_LABELS_KEY
        cfg_base = st.session_state.get("extracted_config", DEFAULT_CONFIG)
        _changed_labels = st.session_state.get(EXTRACTED_CHANGED_LABELS_KEY) or set()
        _change_details = st.session_state.get(EXTRACTED_CHANGE_DETAILS_KEY) or {}
        _cfg_nonce = st.session_state.get("config_nonce", 0)
        cfg = render_config_sidebar(
            cfg_base,
            key_suffix=f"_v{_cfg_nonce}",
            highlight_labels=_changed_labels,
            change_details=_change_details,
        )
        run_btn = st.button("🚀 시뮬레이션 실행", type="primary", use_container_width=True)
        st.divider()
        st.text_input("다음 실행 시 저장될 제목", key="snap_name", label_visibility="collapsed")

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
    domain_analysis_view.render_page()

if TAB_CMS_SIM_LABEL in _tab_by_label:
    with _tab_by_label[TAB_CMS_SIM_LABEL]:
        cms_sim_view.render_page(cms_cfg, cms_run_btn)

if TAB_SCR_SIM_LABEL in _tab_by_label:
    with _tab_by_label[TAB_SCR_SIM_LABEL]:
        st.header("🏭 SCR 구리공장 시뮬레이션")
        st.caption(
            "입고·선별/압착·용해·주조·출하의 5단계 물류 모델입니다. "
            "파라미터는 왼쪽 사이드바에서 조정하고, 실행할 때마다 스냅샷이 자동 저장됩니다."
        )
        run = st.session_state.last_run
        if run is None:
            st.info("사이드바의 **🚀 시뮬레이션 실행**을 누르면 결과가 여기에 표시됩니다.")
        else:
            render_results(run["metrics"], run["cfg"], run["analysis"])

if TAB_COMPARE_LABEL in _tab_by_label:
    with _tab_by_label[TAB_COMPARE_LABEL]:
        st.markdown(
            "저장해 둔 **SCR 공장** 실행 스냅샷끼리 "
            "**KPI·파라미터·자원 가동률·일별 생산 추이**를 한 화면에서 비교합니다."
        )
        if st.session_state.saved_runs:
            render_compare_panel(st.session_state.saved_runs, expanded=True)
        else:
            st.info("아직 저장된 스냅샷이 없습니다. 사이드바에서 한 번 실행하면 쌓입니다.")

with _tab_by_label[TAB_PROCESS_DOC_LABEL]:
    process_description.render()

if TAB_PROCESS_TREE_LABEL in _tab_by_label:
    with _tab_by_label[TAB_PROCESS_TREE_LABEL]:
        process_tree_view.render_page()

with _tab_by_label[TAB_STANDARD_JSON_LABEL]:
    standard_schema_view.render_page()

with _tab_by_label[TAB_SCHEMA_TABLE_LABEL]:
    schema_table_view.render_page()

with _tab_by_label[TAB_AI_CHAT_LABEL]:
    ai_chat_view.render_page()

if TAB_EXTRACTED_PARAMS_LABEL in _tab_by_label:
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

with _tab_by_label[_settings_tab_label()]:
    settings.render()
