"""버퍼 점유율 시계열 패널."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import SimulationConfig
from metrics import Metrics
from report import BUFFER_LABELS, buffer_capacity, buffer_utilization_summary


def _utilization_series(
    metrics: Metrics, cfg: SimulationConfig, name: str
) -> pd.DataFrame:
    cap = buffer_capacity(cfg, name)
    horizon = cfg.sim_horizon_min
    samples = metrics.buffer_samples.get(name, [])
    if not samples:
        return pd.DataFrame(columns=["경과 (일)", "점유율 (%)"])

    rows: list[dict[str, float]] = []
    for i, (t0, level) in enumerate(samples):
        t1 = samples[i + 1][0] if i + 1 < len(samples) else float(horizon)
        pct = min(100.0, level / max(1, cap) * 100)
        rows.append({"경과 (일)": t0 / (24 * 60), "점유율 (%)": pct})
        rows.append({"경과 (일)": t1 / (24 * 60), "점유율 (%)": pct})
    return pd.DataFrame(rows)


def render_buffer_panel(
    metrics: Metrics,
    cfg: SimulationConfig,
    *,
    expanded: bool = True,
) -> None:
    if not expanded:
        return

    st.subheader("📦 보관·야적 여유 (버퍼 점유율)")
    st.caption(
        "파레트·큐프레이크·SCR 야적 버퍼의 시간별 점유율입니다. "
        "100%에 가까울수록 보관 공간이 포화되어 상·하류 흐름을 막을 수 있습니다."
    )

    summary = buffer_utilization_summary(metrics, cfg)
    st.dataframe(pd.DataFrame(summary), use_container_width=True, hide_index=True)

    fig = go.Figure()
    colors = {"pallet_buffer": "#6366f1", "flake_buffer": "#3b82f6", "scr_buffer": "#ef4444"}
    for name in ("pallet_buffer", "flake_buffer", "scr_buffer"):
        df = _utilization_series(metrics, cfg, name)
        if df.empty:
            continue
        label = BUFFER_LABELS.get(name, name)
        fig.add_trace(
            go.Scatter(
                x=df["경과 (일)"],
                y=df["점유율 (%)"],
                mode="lines",
                name=label,
                line=dict(color=colors.get(name, "#666"), width=2),
            )
        )

    fig.add_hline(
        y=100,
        line_dash="dash",
        line_color="#dc3545",
        annotation_text="용량 100%",
        annotation_position="right",
    )
    fig.add_hline(
        y=95,
        line_dash="dot",
        line_color="#ffc107",
        annotation_text="포화(95%)",
        annotation_position="right",
    )
    fig.update_layout(
        height=400,
        yaxis=dict(range=[0, 110], title="점유율 (%)"),
        xaxis_title="경과 (일)",
        legend_title=None,
        # 우측 임계선 주석과 겹치지 않도록 범례는 좌상단, 오른쪽 여백 확보
        legend=dict(x=0.02, y=0.98, xanchor="left", yanchor="top"),
        margin=dict(t=10, b=10, l=10, r=100),
    )
    st.plotly_chart(fig, use_container_width=True)
