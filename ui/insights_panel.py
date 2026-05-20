"""자동 인사이트 패널."""

from __future__ import annotations

import streamlit as st

from report import Analysis


def render_insights_panel(analysis: Analysis, *, expanded: bool = True) -> None:
    if not expanded:
        return
    if not (analysis.insights or analysis.recommendations):
        return

    st.subheader("💡 자동 인사이트")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**관찰**")
        if analysis.insights:
            for ins in analysis.insights:
                st.markdown(f"- {ins}")
        else:
            st.caption("특이사항 없음")
    with c2:
        st.markdown("**권장사항**")
        if analysis.recommendations:
            for rec in analysis.recommendations:
                st.markdown(f"- {rec}")
        else:
            st.caption("권장사항 없음")
