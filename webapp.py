"""A 공정 시뮬레이션 — Streamlit 대시보드.

실행: `streamlit run webapp.py`
"""

from __future__ import annotations

import time

import streamlit as st
import streamlit.components.v1 as components

from config import DEFAULT_CONFIG, SimulationConfig
from report import Analysis, analyze
from run_compare import MAX_SNAPSHOTS, flatten_config, snapshot
from simulation import run_simulation
from ui.compare_panel import render_compare_panel
from ui.results import render_results
from ui.sidebar_params import render_config_sidebar
from ui.snapshot_store import load_saved_snapshots, save_snapshots_to_disk
from views import parameter_reference, process_description, tech_glossary, used_technology


def _default_snapshot_display_name(snapshot_idx: int) -> str:
    """자동 저장·사이드바 기본값에 쓰는 다음 스냅샷 표시 이름."""
    return f"테스트 #{snapshot_idx}"


st.set_page_config(
    page_title="A 공정 시뮬레이션",
    page_icon="🏭",
    layout="wide",
)

# 슬라이더 트랙 양끝의 최소·최대값 라벨 숨김(현재 thumb 위 값 표시는 유지)
st.markdown(
    """
    <style>
    div[data-testid="stSliderTickBar"] {
        display: none !important;
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

# 탭 위젯은 본문에서 먼저 만들어지므로, 같은 런의 사이드바 등에서는 이 플래그만 세우고 다음 rerun 초기에
# `MAIN_TABS_WIDGET_KEY`를 설정한다(Streamlit은 위젯 생성 이후 해당 key의 session_state를 같은 런에서 수정할 수 없음).
_FOCUS_SIM_TAB_AFTER_RUN = "_focus_sim_tab_after_run"
# snap_name 텍스트 입력은 사이드바에서 먼저 만들어지므로, 같은 런에서 snap_name을 바꾸면 예외가 난다. 다음 런 초기에 반영한다.
_PENDING_SNAP_NAME = "_pending_snap_name"
_pending_default_title = st.session_state.pop(_PENDING_SNAP_NAME, None)
if _pending_default_title is not None:
    st.session_state.snap_name = _pending_default_title

# 앱 버전(사이드바 상단 표기)
APP_VERSION_INFO = "v0.1.5 (2026.05.21)"

# 탭 라벨·세션 키(시뮬 완료 후 시뮬 탭으로 포커스할 때 사용)
MAIN_TABS_KEY = "main_tabs"
MAIN_TABS_WIDGET_KEY = f"{MAIN_TABS_KEY}_v8"
TAB_SIM_LABEL = "🏭 시뮬레이션"
_tab_labels = [
    TAB_SIM_LABEL,
    "🆚 스냅샷 비교",
    "📄 공정 설명",
    "📋 파라미터·단위",
    "📘 사용 기술",
    "🔤 용어·약어",
]


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


st.title("🏭 A 공정 물류 시뮬레이션")
st.caption(
    "스크랩 구리 입고 → 선별/압착 → 장입/용해 → 하이브리드 주조 → 출하의 5단계 공정을 "
    "SimPy 이산사건 시뮬레이션으로 분석합니다. "
    "**📘 사용 기술** 탭에서 SimPy·OR-Tools·Streamlit을 쉽게, **📄 공정 설명** 탭에서 공정 서술 문서를 보거나 고치고, "
    "**🔤 용어·약어** 탭에서 웹·IT 약어를 볼 수 있습니다."
)

# 시뮬 완료 등: 다음 rerun 직후·`st.tabs` 이전에 시뮬 탭으로 포커스
if st.session_state.pop(_FOCUS_SIM_TAB_AFTER_RUN, False):
    st.session_state[MAIN_TABS_WIDGET_KEY] = TAB_SIM_LABEL

_tab_ctxs = st.tabs(
    _tab_labels,
    key=MAIN_TABS_WIDGET_KEY,
    on_change="rerun",
    default=TAB_SIM_LABEL,
)
_i = 0
tab_sim = _tab_ctxs[_i]
_i += 1
tab_compare = _tab_ctxs[_i]
_i += 1
tab_process_doc = _tab_ctxs[_i]
_i += 1
tab_params = _tab_ctxs[_i]
_i += 1
tab_used_tech = _tab_ctxs[_i]
_i += 1
tab_terms = _tab_ctxs[_i]


with st.sidebar:
    _sb_home, _sb_ver = st.columns([1, 1.15], gap="small")
    with _sb_home:
        if st.button(
            "🏠 홈",
            use_container_width=True,
            help="브라우저 새로고침(F5)과 같습니다. 페이지·세션 상태가 처음부터 다시 로드됩니다.",
            key="nav_home_sidebar",
        ):
            # st.rerun()은 세션을 유지하므로, F5와 동일한 효과는 부모 창 전체 reload가 필요함
            components.html(
                "<script>window.parent.location.reload();</script>",
                height=0,
                width=0,
            )
    with _sb_ver:
        st.caption(APP_VERSION_INFO)
    st.divider()
    st.header("⚙️ 시뮬레이션 파라미터")
    try:
        from excel_config import default_excel_path

        st.caption(f"기본값 파일: `{default_excel_path().name}` (`data/`)")
    except Exception:
        st.caption("기본값: 코드 내장( `data` 에 `.xlsx` 없음 )")

    cfg = render_config_sidebar(DEFAULT_CONFIG)

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

if run_btn:
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


with tab_sim:
    run = st.session_state.last_run

    if run is None:
        st.info("👈 사이드바에서 파라미터를 조정하고 **시뮬레이션 실행** 버튼을 누르세요.")
        st.markdown(
            "전체 파라미터 기본값·단위는 **파라미터·단위** 탭, "
            "핵심 기술 쉬운 설명은 **📘 사용 기술** 탭, 웹·IT 약어는 **🔤 용어·약어** 탭에서 확인할 수 있습니다. "
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

with tab_compare:
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

with tab_process_doc:
    process_description.render()

with tab_params:
    parameter_reference.render()

with tab_used_tech:
    used_technology.render()

with tab_terms:
    tech_glossary.render()
