"""멕시코 CMS 전선공장 시뮬레이션 탭.

`data/공정설명260521.md` (SOP v0.3)를 사양서로 삼아 만든 SimPy 모델을 실행하고
결과를 보여 준다. 엔진은 `cms_simulation.py`, 해석은 `cms_report.py`.
"""

from __future__ import annotations

import time
import pandas as pd
import streamlit as st

from cms_config import DEFAULT_CMS_CONFIG, CmsConfig
from cms_report import LINE_LABELS, CmsAnalysis, analyze_cms
from cms_simulation import run_cms_simulation

_RUN_KEY = "cms_last_run"


def _render_changed_from_sop(cfg: CmsConfig) -> None:
    """SOP 기재값과 달라진 설정을 알려 준다 — 결과를 SOP 탓으로 오해하지 않도록."""
    diffs: list[str] = []
    for key, spec in cfg.equipment.items():
        base = DEFAULT_CMS_CONFIG.equipment[key]
        if spec.count != base.count:
            diffs.append(f"{spec.label} {base.count}대 → **{spec.count}대**")
    if cfg.cu44_shield_ratio != DEFAULT_CMS_CONFIG.cu44_shield_ratio:
        diffs.append(
            f"차폐 비율 {DEFAULT_CMS_CONFIG.cu44_shield_ratio:.0%} → "
            f"**{cfg.cu44_shield_ratio:.0%}**"
        )
    if cfg.inbound.cu_trucks_per_month != DEFAULT_CMS_CONFIG.inbound.cu_trucks_per_month:
        diffs.append(
            f"Cu 월 트럭 {DEFAULT_CMS_CONFIG.inbound.cu_trucks_per_month}대 → "
            f"**{cfg.inbound.cu_trucks_per_month}대**"
        )
    if diffs:
        st.info("SOP 기재값에서 바꾼 설정 — " + " · ".join(diffs))


def _render_capacity(a: CmsAnalysis) -> None:
    st.markdown("#### 📐 설비별 월 능력 대비 부하")
    st.caption(
        "SOP의 입고량(Cu 월 257.4t · AL 24t · 실리콘 350,000m)을 다 흘리려면 각 설비가 "
        "몇 시간 돌아야 하는지를, 캘린더가 주는 가용시간과 비교한 값입니다. "
        "**100%를 넘으면 그 설비는 물리적으로 물량을 소화할 수 없습니다.** "
        "시뮬레이션과 별개로 계산하므로 두 결과가 일치하면 진단을 믿어도 됩니다."
    )
    rows = [
        {
            "설비": r.label + (" ⚠TBD" if r.tbd_count else ""),
            "대수": r.count,
            "부하": r.load,
            "요구(시간/월)": round(r.demand_min / 60),
            "가용(시간/월)": round(r.capacity_min / 60),
        }
        for r in a.capacity
    ]
    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "부하": st.column_config.ProgressColumn(
                "부하", format="%.0f%%", min_value=0.0, max_value=2.5
            ),
        },
    )


def _render_bottlenecks(a: CmsAnalysis) -> None:
    st.markdown("#### 🚦 시뮬레이션 가동률과 대기")
    st.caption(
        "실제로 돌려 보니 각 설비가 얼마나 바빴고, 로트가 앞에서 얼마나 기다렸는지입니다. "
        "가동률이 95%를 넘고 대기열이 길면 그곳이 병목입니다. "
        "능력이 모자란 설비는 그 앞이 막혀 오히려 가동률이 낮게 보일 수 있으니 위 표와 함께 보세요."
    )
    rows = [
        {
            "설비": b.label + (" ⚠TBD" if b.tbd_count else ""),
            "대수": b.count,
            "가동률": b.utilization,
            "평균 대기(시간)": round(b.avg_wait_min / 60, 1),
            "최대 대기열": b.max_queue,
        }
        for b in a.bottlenecks
        if b.utilization > 0 or b.max_queue
    ]
    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "가동률": st.column_config.ProgressColumn(
                "가동률", format="%.0f%%", min_value=0.0, max_value=1.0
            ),
        },
    )


def _render_output(a: CmsAnalysis) -> None:
    st.markdown("#### 📦 라인별 생산량과 리드타임")
    rows = []
    for key, label in LINE_LABELS.items():
        m = a.finished_m.get(key, 0.0)
        if not m and key not in a.finished_lots:
            continue
        rows.append(
            {
                "라인": label,
                "완성 로트": a.finished_lots.get(key, 0),
                "생산량(m)": round(m),
                "월 환산(m)": round(m * 30 / max(1, a.days)),
                "평균 리드타임(시간)": round(a.lead_hours.get(key, 0.0), 1),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    if a.pallets:
        pal = " · ".join(
            f"{LINE_LABELS.get(k, k)} {v:,}파렛트" for k, v in a.pallets.items()
        )
        st.caption(f"완성 파렛트 (SOP 7.6 — Cu44 18보빈 / Cu19 45다발): {pal}")


def render_page(cfg: CmsConfig | None = None, run: bool = False) -> None:
    st.header("🏭 CMS 전선공장 시뮬레이션")
    st.caption(
        "**📄 공정 설명** 탭의 SOP(멕시코 CMS 공장 v0.3)를 사양서로 삼아 만든 모델입니다. "
        "설비 대수·공유 관계는 SOP 6.1, 라우팅과 단계 시간은 5.1~5.4, 로트 변환은 7.3, "
        "교체 시간은 6.2, 캘린더(주 116시간 가동·가동률 92.6%)는 6.3을 그대로 따릅니다. "
        "**설비 대수와 시나리오는 왼쪽 사이드바**에서 공정별로 조정합니다."
    )

    cfg = cfg or DEFAULT_CMS_CONFIG
    _render_changed_from_sop(cfg)

    if run:
        bar = st.progress(0.0, text="시뮬레이션 준비 중...")

        def cb(frac: float, sim_min: float) -> None:
            bar.progress(min(1.0, frac), text=f"가상 시각 {sim_min/1440:.1f}일 — {frac*100:.0f}%")

        t0 = time.time()
        metrics = run_cms_simulation(cfg, progress=cb)
        elapsed = time.time() - t0
        bar.empty()
        st.session_state[_RUN_KEY] = {
            "analysis": analyze_cms(metrics, cfg),
            "metrics": metrics,
            "elapsed": elapsed,
        }

    run_state = st.session_state.get(_RUN_KEY)
    if run_state is None:
        st.info(
            "사이드바의 **🚀 시뮬레이션 실행**을 누르면 SOP 기준으로 한 달치 공장을 돌려 봅니다."
        )
        return

    a: CmsAnalysis = run_state["analysis"]
    st.success(f"✅ {a.days}일 시뮬레이션 완료 — 실측 {run_state['elapsed']:.2f}초")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("총 생산량", f"{a.total_m/1_000_000:.2f}M m")
    k2.metric("가동 가능 시간", f"{a.uptime_min/60:,.0f} h", help="주말 정지·월요일 스타트업 제외")
    k3.metric("기말 재공(WIP)", f"{a.wip_end:,} 로트", delta=f"{a.wip_end - a.wip_start:+,}")
    over = sum(1 for r in a.capacity if r.load > 1.0)
    k4.metric("능력 부족 설비", f"{over} 개", delta="문제" if over else "여유", delta_color="inverse")

    if a.findings:
        st.markdown("#### 🔎 진단")
        for f in a.findings:
            st.markdown(f"- {f}")

    st.divider()
    _render_capacity(a)
    st.divider()
    _render_bottlenecks(a)
    st.divider()
    _render_output(a)

    with st.expander("이 모델이 세운 가정 (SOP가 미확정으로 남긴 부분)", expanded=False):
        for n in a.notes:
            st.markdown(f"- {n}")
