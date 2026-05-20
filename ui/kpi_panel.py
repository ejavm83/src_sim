"""KPI 카드 패널."""

from __future__ import annotations

import streamlit as st

from config import SimulationConfig
from metrics import Metrics
from report import Analysis, KPI_HELP


def render_kpi_panel(
    metrics: Metrics,
    cfg: SimulationConfig,
    analysis: Analysis,
    *,
    expanded: bool = True,
) -> None:
    if not expanded:
        return

    k = analysis.summary
    st.subheader("📊 핵심 지표")
    row1 = st.columns(5)
    row1[0].metric("입고 트럭", f"{k['inbound_trucks']:,} 대", help=KPI_HELP["inbound_trucks"])
    row1[1].metric("완료 배치", f"{k['batches_completed']:,} 회", help=KPI_HELP["batches_completed"])
    row1[2].metric("총 생산", f"{k['total_ton']:,.1f} t", help=KPI_HELP["total_ton"])
    row1[3].metric("출하 트럭", f"{k['outbound_trucks']:,} 대", help=KPI_HELP["outbound_trucks"])
    row1[4].metric("일평균 생산", f"{k['daily_avg_ton']:,.1f} t/일", help=KPI_HELP["daily_avg_ton"])

    row2 = st.columns(5)
    row2[0].metric("큐프레이크", f"{k['flake_ton']:,.1f} t", help=KPI_HELP["flake_ton"])
    row2[1].metric("SCR", f"{k['scr_ton']:,.1f} t", help=KPI_HELP["scr_ton"])
    row2[2].metric("평균 입고 체류", f"{k['avg_inbound_min']:,.0f} 분", help=KPI_HELP["avg_inbound_min"])
    row2[3].metric("평균 출하 체류", f"{k['avg_outbound_min']:,.0f} 분", help=KPI_HELP["avg_outbound_min"])
    row2[4].metric("평균 배치 사이클", f"{k['avg_batch_min']:,.0f} 분", help=KPI_HELP["avg_batch_min"])

    if k["aborted_outbound"] > 0:
        st.warning(
            f"⚠️ 야적 재고 부족으로 출하 트럭 **{k['aborted_outbound']}회** abort 되었습니다."
        )
