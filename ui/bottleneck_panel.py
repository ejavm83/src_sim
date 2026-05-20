"""병목 진단 패널."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from config import SimulationConfig
from metrics import Metrics
from report import RESOURCE_LABELS, Analysis


STAGE_RESOURCES = {
    "① 입고/하역": ["weighbridge", "unloading_bay"],
    "② 선별/압착": ["sorter", "press"],
    "③ 장입/용해": ["elevator", "furnace"],
    "④ 주조": ["flake_line", "scr_line"],
    "⑤ 출하": ["weighbridge"],
}


def render_bottleneck_panel(
    metrics: Metrics,
    cfg: SimulationConfig,
    analysis: Analysis,
    *,
    expanded: bool = True,
) -> None:
    if not expanded:
        return

    st.subheader("🚧 병목 진단")
    bn_label = RESOURCE_LABELS.get(analysis.bottleneck, analysis.bottleneck or "—")
    bn_util = analysis.utilization.get(analysis.bottleneck, 0.0) * 100
    if bn_util >= 90:
        st.error(f"**병목 자원: {bn_label}** — 가동률 {bn_util:.1f}% (사실상 풀가동)")
    elif bn_util >= 70:
        st.warning(f"**병목 자원: {bn_label}** — 가동률 {bn_util:.1f}%")
    else:
        st.success(
            f"**병목 자원: {bn_label}** — 가동률 {bn_util:.1f}% "
            "(현재 시나리오는 자원 여유가 있는 편)"
        )

    cards = st.columns(5)
    for col, (label, resources) in zip(cards, STAGE_RESOURCES.items()):
        max_u = max((analysis.utilization.get(r, 0.0) for r in resources), default=0.0)
        is_bn = analysis.bottleneck in resources
        bg = "#dc3545" if is_bn else ("#ffc107" if max_u >= 0.7 else "#198754")
        col.markdown(
            f"""
<div style="background:{bg};color:white;padding:14px;border-radius:8px;text-align:center;">
  <div style="font-size:0.9em;">{label}</div>
  <div style="font-size:1.4em;font-weight:bold;">{max_u*100:.0f}%</div>
  <div style="font-size:0.75em;opacity:0.85;">가동률 최대</div>
</div>
            """,
            unsafe_allow_html=True,
        )

    st.caption(
        "가동률 = (자원 사용 시간) ÷ (자원 대수 × 시뮬 총 시간). "
        "녹색 < 70 % ≤ 노랑 < 90 % ≤ 빨강."
    )
    util_rows = sorted(
        ((RESOURCE_LABELS.get(n, n), u * 100) for n, u in analysis.utilization.items()),
        key=lambda x: -x[1],
    )
    colors = ["#dc3545" if u >= 90 else "#ffc107" if u >= 70 else "#28a745" for _, u in util_rows]
    fig = go.Figure(
        go.Bar(
            x=[r[0] for r in util_rows],
            y=[r[1] for r in util_rows],
            marker_color=colors,
            text=[f"{r[1]:.1f}%" for r in util_rows],
            textposition="outside",
        )
    )
    fig.update_layout(
        yaxis=dict(range=[0, 110], title="가동률 (%)"),
        xaxis_title=None,
        height=380,
        margin=dict(t=10, b=10, l=10, r=10),
    )
    st.plotly_chart(fig, use_container_width=True)
