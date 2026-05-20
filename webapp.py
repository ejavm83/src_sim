"""군산 SCR 공정 시뮬레이션 — Streamlit 대시보드.

실행: `streamlit run webapp.py`
"""

from __future__ import annotations

import time

import streamlit as st

from config import (
    DEFAULT_CONFIG,
    CastingConfig,
    InboundConfig,
    MeltingConfig,
    OutboundConfig,
    SimulationConfig,
    SortingConfig,
)
from report import analyze
from run_compare import MAX_SNAPSHOTS, flatten_config, snapshot
from simulation import run_simulation
from ui.compare_panel import render_compare_panel
from ui.results import render_results
from ui.snapshot_store import load_saved_snapshots, save_snapshots_to_disk
from views import parameter_reference, process_guide


st.set_page_config(
    page_title="군산 SCR 공정 시뮬레이션",
    page_icon="🏭",
    layout="wide",
)

if "last_run" not in st.session_state:
    st.session_state.last_run = None
if "saved_runs" not in st.session_state:
    loaded_runs, loaded_idx = load_saved_snapshots()
    st.session_state.saved_runs = loaded_runs
    st.session_state.snapshot_idx = loaded_idx
if "snap_name" not in st.session_state:
    st.session_state.snap_name = f"실행 {st.session_state.snapshot_idx}"

# 시뮬 완료 후 다음 rerun에서만 탭 키를 쓰기 위해 사용(Streamlit은 위젯 생성 이후 해당 key의 session_state를 같은 런에서 수정할 수 없음)
_FOCUS_SIM_TAB_AFTER_RUN = "_focus_sim_tab_after_run"


def save_snapshot() -> None:
    run = st.session_state.last_run
    if run is None:
        return
    snap = snapshot(
        st.session_state.snap_name.strip() or f"실행 {st.session_state.snapshot_idx}",
        run["cfg"],
        run["analysis"],
    )
    saved = st.session_state.saved_runs
    if len(saved) >= MAX_SNAPSHOTS:
        saved.pop(0)
    saved.append(snap)
    st.session_state.snapshot_idx += 1
    st.session_state.snap_name = f"실행 {st.session_state.snapshot_idx}"
    st.session_state._save_toast = (
        f"스냅샷 '{snap['name']}' 저장됨 ({len(saved)}/{MAX_SNAPSHOTS})"
    )
    save_snapshots_to_disk(saved, st.session_state.snapshot_idx)


st.title("🏭 군산 SCR 공정 물류 시뮬레이션")
st.caption(
    "스크랩 구리 입고 → 선별/압착 → 장입/용해 → 하이브리드 주조 → 출하의 5단계 공정을 "
    "SimPy 이산사건 시뮬레이션으로 분석합니다."
)
with st.expander("🧩 기술 구성 요약", expanded=False):
    st.markdown(
        "- **SimPy** — 5단계 공정의 **이산사건 시뮬** 본체(설비·버퍼·대기열).\n"
        "- **OR-Tools CP-SAT** — 결과 탭 **고급 분석**에서 반사로 **FIFO 실측**과 "
        "**이론상 최적 makespan**만 비교(전 공정을 대체하지 않음).\n"
        "- **Streamlit·Plotly·Pandas** — 웹 UI·차트·표 처리."
    )

# 탭 라벨·세션 키: 시뮬 완료 후 결과가 보이는 탭으로 포커스 이동
MAIN_TABS_KEY = "main_tabs"
MAIN_TABS_WIDGET_KEY = f"{MAIN_TABS_KEY}_v2"
TAB_SIM_LABEL = "🏭 시뮬레이션"
_tab_labels = [
    TAB_SIM_LABEL,
    "🆚 스냅샷 비교",
    "📖 공정 설명",
    "📋 파라미터·단위",
]

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
tab_process = _tab_ctxs[_i]
_i += 1
tab_params = _tab_ctxs[_i]


def build_config(
    sim_days: int,
    trucks_per_day: int,
    truck_load_ton: float,
    sorters: int,
    presses: int,
    pallet_cap: int,
    furnace_count: int,
    melting_min: int,
    flake_ratio: float,
    out_interval: int,
) -> SimulationConfig:
    return SimulationConfig(
        sim_days=sim_days,
        random_seed=DEFAULT_CONFIG.random_seed,
        inbound=InboundConfig(
            trucks_per_day=trucks_per_day,
            truck_load_ton=truck_load_ton,
        ),
        sorting=SortingConfig(
            sorters=sorters,
            presses=presses,
            pallet_buffer_cap=pallet_cap,
        ),
        melting=MeltingConfig(
            furnace_count=furnace_count,
            melting_min=float(melting_min),
        ),
        casting=CastingConfig(flake_ratio=float(flake_ratio)),
        outbound=OutboundConfig(truck_interval_min=float(out_interval)),
    )


with st.sidebar:
    st.header("⚙️ 시뮬레이션 파라미터")

    sim_days = st.slider(
        "시뮬레이션 일수", 1, 30, DEFAULT_CONFIG.sim_days,
        help="가상 시간 = sim_days × 24시간",
    )

    with st.expander("① 입고 / 하역", expanded=False):
        trucks_per_day = st.slider(
            "일 트럭 수", 1, 40, DEFAULT_CONFIG.inbound.trucks_per_day
        )
        truck_load_ton = st.slider(
            "트럭 적재 (t)", 5.0, 30.0, DEFAULT_CONFIG.inbound.truck_load_ton, 0.5
        )

    with st.expander("② 선별 / 압착", expanded=False):
        sorters = st.slider("선별기 대수", 1, 5, DEFAULT_CONFIG.sorting.sorters)
        presses = st.slider("압착기 대수", 1, 5, DEFAULT_CONFIG.sorting.presses)
        pallet_cap = st.slider(
            "파레트 버퍼 용량", 40, 320, DEFAULT_CONFIG.sorting.pallet_buffer_cap, 20
        )

    with st.expander("③ 용해 / 주조", expanded=False):
        furnace_count = st.slider(
            "반사로 대수", 1, 4, DEFAULT_CONFIG.melting.furnace_count
        )
        melting_min = st.slider(
            "용해·정련 시간 (분)", 300, 1200, int(DEFAULT_CONFIG.melting.melting_min), 30
        )
        flake_ratio = st.slider(
            "큐프레이크 비율", 0.0, 1.0, DEFAULT_CONFIG.casting.flake_ratio, 0.05
        )

    with st.expander("④ 출하", expanded=False):
        out_interval = st.slider(
            "출하 평균 간격 (분)", 15, 240, int(DEFAULT_CONFIG.outbound.truck_interval_min), 5
        )

    run_btn = st.button("🚀 시뮬레이션 실행", type="primary", use_container_width=True)

    st.divider()
    st.markdown("**💾 결과 스냅샷**")
    st.text_input(
        "스냅샷 이름",
        key="snap_name",
        label_visibility="collapsed",
    )
    can_save = st.session_state.last_run is not None
    if can_save:
        current_cfg = flatten_config(st.session_state.last_run["cfg"])
        for saved in st.session_state.saved_runs:
            if current_cfg == saved["config"]:
                can_save = False
                break

    st.button(
        "이번 결과 저장",
        use_container_width=True,
        disabled=not can_save,
        on_click=save_snapshot,
    )

if st.session_state.get("_save_toast"):
    st.toast(st.session_state.pop("_save_toast"), icon="💾")

cfg = build_config(
    sim_days, trucks_per_day, truck_load_ton,
    sorters, presses, pallet_cap,
    furnace_count, melting_min, flake_ratio, out_interval,
)

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
    st.session_state[_FOCUS_SIM_TAB_AFTER_RUN] = True
    st.success(
        f"✅ 시뮬레이션 완료 — 실측 {elapsed:.2f}초 · 이벤트 {len(metrics.events):,}건"
    )
    st.rerun()


with tab_process:
    process_guide.render()

with tab_params:
    parameter_reference.render()

with tab_sim:
    run = st.session_state.last_run

    if run is None:
        st.info("👈 사이드바에서 파라미터를 조정하고 **시뮬레이션 실행** 버튼을 누르세요.")
        st.markdown(
            "공정 흐름·설비 모델은 **공정 설명** 탭, "
            "전체 파라미터 기본값·단위는 **파라미터·단위** 탭에서 확인할 수 있습니다."
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
        "새 스냅샷을 쌓으려면 **🏭 시뮬레이션** 탭에서 실행한 뒤 사이드바 **이번 결과 저장**을 사용하세요."
    )
    if st.session_state.saved_runs:
        render_compare_panel(st.session_state.saved_runs, expanded=True)
    else:
        st.info(
            "아직 저장된 스냅샷이 없습니다. 시뮬레이션을 실행한 뒤 사이드바에서 "
            "**이번 결과 저장**으로 스냅샷을 추가하세요."
        )

