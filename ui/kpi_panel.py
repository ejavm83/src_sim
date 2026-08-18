"""KPI 카드 패널."""

from __future__ import annotations

import streamlit as st

from config import SimulationConfig
from metrics import Metrics
from report import Analysis, KPI_HELP, kpi_breakdown

# KPI 키 → kpi_breakdown() 행의 "지표" 라벨 매핑
_BREAKDOWN_LABEL: dict[str, str] = {
    "inbound_trucks": "입고 트럭 (대)",
    "batches_completed": "완료 배치 (회)",
    "total_ton": "총 생산 (t)",
    "flake_ton": "큐프레이크 생산 (t)",
    "scr_ton": "SCR 생산 (t)",
    "outbound_trucks": "출하 트럭 (대)",
    "daily_avg_ton": "일평균 생산 (t/일)",
    "avg_inbound_min": "평균 입고 체류 (분)",
    "avg_outbound_min": "평균 출하 체류 (분)",
    "avg_batch_min": "평균 배치 사이클 (분)",
    "aborted_outbound": "출하 abort (회)",
}


def _metric_with_reason(
    col,
    key: str,
    label: str,
    value: str,
    breakdown: dict[str, dict],
) -> None:
    """KPI 카드 + '🧮 근거' 팝오버 — 클릭하면 실제 숫자가 든 수식과 설명이 뜬다."""
    with col:
        st.metric(label, value, help=KPI_HELP.get(key))
        row = breakdown.get(_BREAKDOWN_LABEL.get(key, ""))
        if row is None:
            return
        with st.popover("🧮 근거", use_container_width=True):
            st.markdown(f"**{row['지표']} = {row['값']}**")
            st.markdown(f"**무엇인가요?** {row['정의']}")
            st.markdown(f"**어떻게 계산했나요?** {row['산출 공식']}")
            st.markdown(f"**실제 숫자로 보면**\n\n`{row['원 데이터']}`")


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
    breakdown = {row["지표"]: row for row in kpi_breakdown(metrics, cfg)}

    st.subheader("📊 핵심 지표")
    st.caption("각 카드 아래 **🧮 근거**를 누르면 계산 수식과 설명이 나옵니다.")
    row1 = st.columns(5)
    _metric_with_reason(row1[0], "inbound_trucks", "입고 트럭", f"{k['inbound_trucks']:,} 대", breakdown)
    _metric_with_reason(row1[1], "batches_completed", "완료 배치", f"{k['batches_completed']:,} 회", breakdown)
    _metric_with_reason(row1[2], "total_ton", "총 생산", f"{k['total_ton']:,.1f} t", breakdown)
    _metric_with_reason(row1[3], "outbound_trucks", "출하 트럭", f"{k['outbound_trucks']:,} 대", breakdown)
    _metric_with_reason(row1[4], "daily_avg_ton", "일평균 생산", f"{k['daily_avg_ton']:,.1f} t/일", breakdown)

    row2 = st.columns(5)
    _metric_with_reason(row2[0], "flake_ton", "큐프레이크", f"{k['flake_ton']:,.1f} t", breakdown)
    _metric_with_reason(row2[1], "scr_ton", "SCR", f"{k['scr_ton']:,.1f} t", breakdown)
    _metric_with_reason(row2[2], "avg_inbound_min", "평균 입고 체류", f"{k['avg_inbound_min']:,.0f} 분", breakdown)
    _metric_with_reason(row2[3], "avg_outbound_min", "평균 출하 체류", f"{k['avg_outbound_min']:,.0f} 분", breakdown)
    _metric_with_reason(row2[4], "avg_batch_min", "평균 배치 사이클", f"{k['avg_batch_min']:,.0f} 분", breakdown)

    if k["aborted_outbound"] > 0:
        st.warning(
            f"⚠️ 야적 재고 부족으로 출하 트럭 **{k['aborted_outbound']}회** abort 되었습니다."
        )
