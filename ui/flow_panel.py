"""공정 흐름 narrative 패널."""

from __future__ import annotations

import streamlit as st

from config import SimulationConfig
from metrics import Metrics
from report import Analysis, result_narrative


def render_flow_panel(
    metrics: Metrics,
    cfg: SimulationConfig,
    analysis: Analysis,
    *,
    expanded: bool = True,
) -> None:
    if not expanded:
        return

    st.subheader("📖 결과 종합 해석 (단계별)")
    st.caption(
        "5단계 공정의 흐름을 따라가며 이번 실행이 **왜 이런 수치를 만들었는지** 자동 해설합니다."
    )
    for para in result_narrative(metrics, cfg, analysis):
        st.markdown(f"**{para['단계']}**")
        st.markdown(para["본문"])
        st.write("")
