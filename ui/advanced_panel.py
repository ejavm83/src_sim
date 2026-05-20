"""CP-SAT·KPI·가동률 근거 등 고급 분석 패널."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import SimulationConfig
from metrics import Metrics
from optimizer import run_optimizer
from report import kpi_breakdown, utilization_breakdown


def render_advanced_panel(
    metrics: Metrics,
    cfg: SimulationConfig,
    *,
    expanded: bool = False,
) -> None:
    with st.expander("🔬 고급 분석 (CP-SAT · KPI · 가동률 근거)", expanded=expanded):
        st.markdown("##### 📐 KPI 산출 근거")
        st.dataframe(
            pd.DataFrame(kpi_breakdown(metrics, cfg)),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("##### 📐 가동률 산출 근거")
        st.dataframe(
            pd.DataFrame(utilization_breakdown(metrics, cfg)),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("##### 🔧 반사로 배치 최적화 (CP-SAT)")
        st.caption(
            "SimPy 는 **선착순(FIFO)** 으로 배치를 반사로에 배정합니다. "
            "CP-SAT 는 동일 릴리스·처리 시간 기준 **이론적 최적 makespan**을 계산합니다."
        )

        with st.spinner("CP-SAT 최적화 계산 중..."):
            opt_result = run_optimizer(metrics, cfg)

        if not opt_result["available"]:
            st.info(f"CP-SAT 분석 불가: {opt_result.get('reason', '알 수 없는 오류')}")
            return

        oc1, oc2, oc3, oc4 = st.columns(4)
        oc1.metric("배치 수", f"{opt_result['batch_count']} 회")
        oc2.metric("SimPy makespan", f"{opt_result['simpy_makespan_min']:.0f} 분")
        oc3.metric("CP-SAT 최적 makespan", f"{opt_result['cpsat_makespan_min']:.0f} 분")
        saving = opt_result["saving_min"]
        eff = opt_result["efficiency_pct"]
        delta_label = f"−{saving:.0f} 분 절감 가능" if saving > 0 else "이미 최적"
        oc4.metric(
            "스케줄링 효율",
            f"{eff:.1f} %",
            delta=delta_label if saving > 0 else None,
            delta_color="inverse",
        )

        if saving <= 0:
            st.success("FIFO 스케줄이 이미 이론 최적입니다.")
        else:
            st.warning(
                f"배치 순서 최적화로 **{saving:.0f}분 ({saving/60:.1f}시간) 단축** 가능합니다."
            )

        with st.expander("배치 처리 시간 산출 근거", expanded=False):
            bd = opt_result["batch_duration_min"]
            trips = cfg.melting.pallets_per_batch // cfg.melting.elevator_pallets_per_trip
            elev = trips * cfg.melting.elevator_cycle_min
            flake_ton = cfg.melting.batch_ton * cfg.casting.flake_ratio
            scr_ton = cfg.melting.batch_ton * (1 - cfg.casting.flake_ratio)
            flake_cast = (flake_ton / cfg.casting.flake_unit_ton) * cfg.casting.flake_min_per_unit
            scr_cast = (scr_ton / cfg.casting.scr_unit_ton) * cfg.casting.scr_min_per_unit
            rows_bd = [
                {"항목": "엘리베이터 왕복", "계산": f"{trips}회 × {cfg.melting.elevator_cycle_min}분", "분": elev},
                {"항목": "사전 준비 (셋업)", "계산": f"{cfg.melting.setup_min}분 고정", "분": cfg.melting.setup_min},
                {"항목": "용해·정련", "계산": f"{cfg.melting.melting_min}분 고정", "분": cfg.melting.melting_min},
                {"항목": "홀딩 셋업", "계산": f"{cfg.casting.holding_setup_min}분 고정", "분": cfg.casting.holding_setup_min},
                {"항목": "큐프레이크 주조", "계산": f"{flake_ton:.0f}t ÷ {cfg.casting.flake_unit_ton}t × {cfg.casting.flake_min_per_unit}분", "분": flake_cast},
                {"항목": "SCR 주조", "계산": f"{scr_ton:.0f}t ÷ {cfg.casting.scr_unit_ton}t × {cfg.casting.scr_min_per_unit}분", "분": scr_cast},
                {"항목": "⬤ 주조 병목 (긴 쪽)", "계산": "max(큐프레이크, SCR)", "분": max(flake_cast, scr_cast)},
                {"항목": "▶ 배치 합계", "계산": "엘리베이터+셋업+용해+홀딩+주조", "분": bd},
            ]
            st.dataframe(pd.DataFrame(rows_bd), use_container_width=True, hide_index=True)

        st.markdown("**반사로 배치 Gantt 비교**")
        gantt_tab1, gantt_tab2 = st.tabs(["SimPy 실측 (FIFO)", "CP-SAT 최적 순서"])
        ref = opt_result["reference_min"]

        def _make_gantt(schedule: list[dict], title: str) -> go.Figure:
            furnace_colors = ["#3b82f6", "#f97316", "#10b981", "#a855f7"]
            fig = go.Figure()
            furnace_count = cfg.melting.furnace_count
            for row in schedule:
                f = row["furnace_id"]
                start_h = (row["start_min"] - ref) / 60
                end_h = (row["end_min"] - ref) / 60
                dur_h = end_h - start_h
                color = furnace_colors[f % len(furnace_colors)]
                fig.add_trace(
                    go.Bar(
                        x=[dur_h],
                        y=[f"반사로 {f + 1}"],
                        base=[start_h],
                        orientation="h",
                        marker_color=color,
                        showlegend=False,
                        text=f"배치 {row['batch_id']}",
                        textposition="inside",
                    )
                )
                if "release_min" in row:
                    rel_h = (row["release_min"] - ref) / 60
                    fig.add_vline(x=rel_h, line_dash="dot", line_color="gray", line_width=1)

            fig.update_layout(
                title=title,
                xaxis_title="경과 시간 (시간, 첫 배치 기준)",
                yaxis=dict(
                    categoryorder="array",
                    categoryarray=[f"반사로 {i+1}" for i in range(furnace_count)],
                ),
                height=200 + furnace_count * 60,
                margin=dict(l=10, r=10, t=40, b=10),
                barmode="overlay",
            )
            return fig

        with gantt_tab1:
            st.plotly_chart(
                _make_gantt(opt_result["simpy_schedule"], "SimPy 실측 (FIFO)"),
                use_container_width=True,
            )
        with gantt_tab2:
            if opt_result["cpsat_schedule"]:
                st.plotly_chart(
                    _make_gantt(opt_result["cpsat_schedule"], "CP-SAT 최적 순서"),
                    use_container_width=True,
                )
