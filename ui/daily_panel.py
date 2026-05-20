"""일별 생산량 패널."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from report import Analysis


def render_daily_panel(analysis: Analysis, *, expanded: bool = True) -> None:
    if not expanded or not analysis.daily_production:
        return

    st.subheader("📅 일별 생산량")
    rows = []
    for day in sorted(analysis.daily_production):
        d = analysis.daily_production[day]
        rows.append(
            {
                "일": day + 1,
                "큐프레이크 (t)": d.get("flake", 0.0),
                "SCR (t)": d.get("scr", 0.0),
            }
        )
    daily_df = pd.DataFrame(rows)
    fig = px.bar(
        daily_df,
        x="일",
        y=["큐프레이크 (t)", "SCR (t)"],
        barmode="stack",
        color_discrete_map={"큐프레이크 (t)": "#3b82f6", "SCR (t)": "#ef4444"},
    )
    fig.update_layout(height=350, yaxis_title="톤", legend_title=None)
    st.plotly_chart(fig, use_container_width=True)
