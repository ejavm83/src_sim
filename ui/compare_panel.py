"""스냅샷 비교 패널."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit import column_config as st_cc

from report import RESOURCE_LABELS
from ui.snapshot_store import save_snapshots_to_disk
from run_compare import (
    KPI_COMPARE_SPECS,
    KPI_HIGHER_BETTER,
    diff_config_items,
    kpi_changed,
    kpi_with_delta,
    localize_config,
    narrate_vs_baseline,
    significant_kpi_deltas,
    synthesize_implications,
)

_KPI_INT_KEYS = frozenset({"batches_completed", "inbound_trucks", "outbound_trucks", "aborted_outbound"})
_KPI_NEUTRAL_KEYS = frozenset({"inbound_trucks", "outbound_trucks"})


def _fmt_kpi_value(key: str, val: float | int) -> str:
    if key in _KPI_INT_KEYS:
        return f"{int(val):,}"
    return f"{val:.1f}"


def _fmt_delta_pct(pct: float | None) -> str:
    if pct is None:
        return ""
    if pct == float("inf"):
        return "+∞%"
    if pct == float("-inf"):
        return "−∞%"
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def _render_config_change_block(diffs: list[tuple[str, Any, Any]]) -> None:
    if not diffs:
        st.caption("기준 실행과 **입력 파라미터가 동일**합니다. (결과 차이는 시드·무작위만 다를 때 발생할 수 있습니다.)")
        return
    rows_html = "".join(
        "<tr>"
        f"<td style='padding:0.45rem 0.5rem;vertical-align:top;border-bottom:1px solid #eceff1'>"
        f"<strong style='color:#263238'>{label}</strong></td>"
        "<td style='padding:0.45rem 0.5rem;border-bottom:1px solid #eceff1;color:#546e7a;font-size:0.95em'>"
        f"{b_v}</td>"
        "<td style='padding:0.45rem 0.35rem;border-bottom:1px solid #eceff1;color:#90a4ae'>→</td>"
        "<td style='padding:0.45rem 0.5rem;border-bottom:1px solid #eceff1;color:#1565c0;font-weight:600'>"
        f"{t_v}</td>"
        "</tr>"
        for label, b_v, t_v in diffs
    )
    st.markdown(
        "<table style='width:100%;border-collapse:collapse;font-size:0.95rem'>"
        f"<thead><tr>"
        "<th style='text-align:left;padding:0.35rem 0.5rem;color:#607d8b;font-weight:600'>항목</th>"
        "<th style='text-align:left;padding:0.35rem 0.5rem;color:#607d8b;font-weight:600'>기준</th>"
        "<th></th><th style='text-align:left;padding:0.35rem 0.5rem;color:#607d8b;font-weight:600'>이 실행</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table>",
        unsafe_allow_html=True,
    )


def _render_kpi_impact_metrics(deltas: list[dict]) -> None:
    if not deltas:
        st.caption("기준과 **의미 있는 차이**(약 0.5% 이상)가 나는 KPI가 없습니다.")
        return
    n = len(deltas)
    cols = st.columns(min(n, 4))
    for i, d in enumerate(deltas):
        key = d["key"]
        val = d["value"]
        base = d["baseline"]
        delta = d["delta"]
        pct = d["delta_pct"]
        higher_better = d["higher_better"]
        with cols[i % len(cols)]:
            if isinstance(delta, (int, float)):
                if key in _KPI_INT_KEYS:
                    delta_str = f"{int(delta):+d}"
                else:
                    delta_str = f"{delta:+.1f}"
                if pct is not None and pct not in (float("inf"), float("-inf")):
                    delta_str = f"{delta_str} ({_fmt_delta_pct(pct)})"
                if key in _KPI_NEUTRAL_KEYS:
                    delta_color = "off"
                elif not higher_better:
                    delta_color = "inverse"
                else:
                    delta_color = "normal"
                st.metric(
                    d["label"],
                    _fmt_kpi_value(key, val),
                    delta=delta_str,
                    delta_color=delta_color,
                )
                st.caption(f"기준: {_fmt_kpi_value(key, base)}")
            else:
                st.metric(d["label"], str(val))


def _render_delta_bar_chart(
    baseline_name: str,
    target_name: str,
    deltas: list[dict],
) -> None:
    if not deltas:
        return
    rows = []
    for d in deltas:
        pct = d["delta_pct"]
        if pct is None or pct in (float("inf"), float("-inf")):
            continue
        key = d["key"]
        if key in _KPI_NEUTRAL_KEYS:
            direction = "변화"
        else:
            direction = "개선" if d.get("good") else "악화"
        rows.append(
            {
                "KPI": d["label"],
                "Δ% (기준 대비)": round(pct, 1),
                "방향": direction,
            }
        )
    if not rows:
        return
    fig = px.bar(
        pd.DataFrame(rows),
        y="KPI",
        x="Δ% (기준 대비)",
        color="방향",
        orientation="h",
        color_discrete_map={"개선": "#2e7d32", "악화": "#c62828", "변화": "#1565c0"},
        text="Δ% (기준 대비)",
    )
    fig.update_traces(texttemplate="%{x:+.1f}%", textposition="outside")
    fig.update_layout(
        template="plotly_white",
        height=max(240, 58 * len(rows)),
        margin=dict(l=8, r=52, t=40, b=8),
        legend_title=None,
        title=dict(
            text=f"「{target_name}」 vs 기준 「{baseline_name}」",
            font=dict(size=15),
        ),
        xaxis_title="기준 대비 변화율 (%) · 막대 오른쪽이 기준보다 큼",
        font=dict(size=13),
        yaxis=dict(tickfont=dict(size=12)),
    )
    fig.add_vline(x=0, line_width=1.5, line_color="#78909c")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "막대 색: **개선·악화**는 KPI마다 ‘클수록 좋음/작을수록 좋음’ 규칙에 따른 판정입니다. "
        "**변화**는 입·출하 트럭 수처럼 방향 판정을 붙이지 않은 지표입니다."
    )


def _render_impact_summary(baseline: dict, snaps: list[dict], baseline_idx: int) -> None:
    """설정 변경 → KPI 영향을 시나리오별로 요약."""
    st.markdown("### 📌 설정 변경과 결과 · 해석")
    st.caption(
        "왼쪽 열은 **기준 대비로 바뀐 입력(설정)**, 오른쪽은 **그에 따라 달라진 산출(KPI)**입니다. "
        "아래 **비교 요약**은 사실 위주, **시사점**은 그 결과가 의사결정에 주는 함의입니다."
    )

    targets = [(i, s) for i, s in enumerate(snaps) if i != baseline_idx]
    if not targets:
        st.info("비교할 다른 실행이 없습니다. 스냅샷을 하나 더 저장하세요.")
        return

    for _idx, target in targets:
        diffs = diff_config_items(baseline["config"], target["config"])
        deltas = significant_kpi_deltas(baseline["kpi"], target["kpi"])

        with st.container(border=True):
            st.markdown(
                f"#### {target['name']}"
                f"<span style='color:#78909c;font-weight:400;font-size:0.92em'> ← 기준: </span>"
                f"<span style='color:#1565c0;font-weight:600'>{baseline['name']}</span>",
                unsafe_allow_html=True,
            )

            cfg_col, kpi_col = st.columns([2, 2.2], gap="medium")
            with cfg_col:
                st.markdown('<p style="margin:0 0 0.35rem 0;font-size:0.9rem;color:#546e7a">⚙️ 바뀐 설정</p>', unsafe_allow_html=True)
                _render_config_change_block(diffs)
            with kpi_col:
                st.markdown('<p style="margin:0 0 0.35rem 0;font-size:0.9rem;color:#546e7a">📊 달라진 KPI</p>', unsafe_allow_html=True)
                _render_kpi_impact_metrics(deltas)

            notes = narrate_vs_baseline(target, baseline)
            implications = synthesize_implications(target, baseline)

            if notes:
                st.markdown("##### 📝 비교 요약 (무엇이 달라졌나)")
                for note in notes:
                    st.markdown(f"- {note}")
            elif not diffs:
                st.caption("설정 차이는 없고, KPI만 다른 경우에는 위 카드의 지표와 아래 막대 그래프를 참고하세요.")

            if implications:
                st.markdown("##### 💡 시사점 (이 비교가 주는 의미)")
                for imp in implications:
                    st.markdown(f"- {imp}")

            _render_delta_bar_chart(baseline["name"], target["name"], deltas)


def _render_compare_readme() -> None:
    """비교 화면 전체를 읽는 법(한 번만 펼쳐 보면 됨)."""
    with st.expander("📖 이 비교 화면 읽는 법 · 결과와 시사점 구분", expanded=False):
        st.markdown(
            """
**이 화면이 하는 일**  
저장된 스냅샷을 **하나의 기준 실행**에 맞춰 겹칩니다. 카드·표·막대의 증감(Δ)은 모두 **선택한 기준** 대비입니다.

**비교 요약 vs 시사점**  
- **비교 요약**: 설정·생산·병목 등 **무엇이 얼마나 달라졌는지** 사실 서술입니다.  
- **시사점**: 그 차이가 **의사결정·다음 실험**에 주는 함의(개선 후보인지, 위험인지, 변수를 쪼개 볼지 등)를 짧게 정리합니다.

**표의 ▲ / ▼**  
각 KPI마다 “값이 커질수록 좋은지·작아질수록 좋은지”가 정해져 있고, **기준 대비로 유리한 방향이면 ▲**, 불리하면 **▼**입니다.

**가동률 차트의 가로선**  
**90%**(빨간 점선)·**70%**(노란 점선)은 자원이 **포화에 가까운지** 가늠하는 참고선입니다. 실제 한계는 공정마다 다릅니다.

**일별 생산 곡선**  
가로축 **일**은 시뮬레이션 상의 **일 차수**(1일차, 2일차 …)이며, 세로축은 해당 일의 **총 생산량(t)** 합계입니다.
            """
        )


def render_compare_panel(
    saved_runs: list[dict],
    *,
    expanded: bool = True,
    default_baseline_idx: int = 0,
) -> None:
    if not expanded or not saved_runs:
        return

    snaps = saved_runs
    n_snap = len(snaps)
    st.markdown("---")
    st.subheader(f"🆚 실행 비교 ({n_snap}건)")
    st.caption(
        "**기준 실행**을 정하면, 나머지 스냅샷이 그 기준 대비로 어떻게 달라졌는지 KPI·설정·가동률·일별 추이로 묶어 보여 줍니다."
    )
    _render_compare_readme()

    ctl1, ctl2 = st.columns([4, 1])
    with ctl1:
        names = [s["name"] for s in snaps]
        baseline_idx = st.selectbox(
            "기준 실행 선택",
            options=range(n_snap),
            format_func=lambda i: names[i],
            index=min(default_baseline_idx, n_snap - 1),
            key="compare_baseline_idx",
        )
    with ctl2:
        st.write("")
        st.write("")
        if st.button("🗑️ 모두 삭제", use_container_width=True, key="compare_clear_all"):
            st.session_state.saved_runs = []
            save_snapshots_to_disk(
                st.session_state.saved_runs,
                st.session_state.snapshot_idx,
            )
            st.rerun()

    baseline = snaps[baseline_idx]

    st.markdown(
        "<div style='background:#e8f4fc;border-left:4px solid #1565c0;padding:0.65rem 1rem;"
        "margin:0.4rem 0 0.9rem 0;border-radius:6px;line-height:1.55'>"
        "<strong style='color:#0d47a1'>현재 기준</strong> · "
        f"<span style='font-weight:600;color:#1565c0'>{baseline['name']}</span> · "
        "아래 카드의 델타·KPI 표의 ▲▼·막대 그래프의 %는 <strong>모두 이 실행을 0점</strong>으로 한 상대 비교입니다."
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("### 📋 시나리오별 요약")
    st.caption("각 카드는 한 스냅샷의 핵심 지표입니다. 기준이 아닌 실행은 하단에 **비교 요약·시사점**을 펼칠 수 있습니다.")
    cards_per_row = 3
    for row_start in range(0, n_snap, cards_per_row):
        cols = st.columns(cards_per_row)
        for ci, si in enumerate(range(row_start, min(row_start + cards_per_row, n_snap))):
            s = snaps[si]
            is_base = si == baseline_idx
            k = s["kpi"]
            bk = baseline["kpi"]
            with cols[ci]:
                with st.container(border=True):
                    head1, head2 = st.columns([3, 1])
                    head1.markdown(f"**{s['name']}**")
                    head2.markdown(
                        "<span style='display:inline-block;padding:0.12rem 0.45rem;border-radius:6px;"
                        "font-size:0.78em;font-weight:600;background:#e3f2fd;color:#1565c0'>🎯 기준</span>"
                        if is_base
                        else "<span style='display:inline-block;padding:0.12rem 0.45rem;border-radius:6px;"
                        "font-size:0.78em;font-weight:600;background:#eceff1;color:#455a64'>🆚 비교</span>",
                        unsafe_allow_html=True,
                    )
                    st.caption(s["created_at"].replace("T", " "))

                    mc1, mc2 = st.columns(2)

                    def _delta(key: str, fmt: str = "{:+.1f}") -> str | None:
                        if is_base:
                            return None
                        d = k.get(key, 0) - bk.get(key, 0)
                        return None if d == 0 else fmt.format(d)

                    mc1.metric(
                        "총 생산 (t)",
                        f"{k.get('total_ton', 0):.0f}",
                        delta=_delta("total_ton", "{:+.0f} t"),
                    )
                    mc2.metric(
                        "일평균 (t/일)",
                        f"{k.get('daily_avg_ton', 0):.1f}",
                        delta=_delta("daily_avg_ton"),
                    )
                    mc3, mc4 = st.columns(2)
                    mc3.metric(
                        "완료 배치",
                        f"{k.get('batches_completed', 0)}",
                        delta=(
                            None
                            if is_base
                            else f"{k.get('batches_completed', 0) - bk.get('batches_completed', 0):+d}"
                        ),
                    )
                    mc4.metric(
                        "배치 사이클 (분)",
                        f"{k.get('avg_batch_min', 0):.0f}",
                        delta=_delta("avg_batch_min", "{:+.0f}"),
                        delta_color="inverse",
                    )

                    st.caption(
                        f"🚧 병목: **{RESOURCE_LABELS.get(s['bottleneck'], s['bottleneck'])}** "
                        f"({s['utilization'].get(s['bottleneck'], 0)*100:.0f}%)"
                    )

                    if not is_base:
                        diffs = diff_config_items(baseline["config"], s["config"])
                        if diffs:
                            with st.expander("⚙️ 기준 대비 설정 변경", expanded=False):
                                for label, b_v, t_v in diffs:
                                    st.markdown(f"- **{label}**: {b_v} → **{t_v}**")
                        notes = narrate_vs_baseline(s, baseline)
                        implications = synthesize_implications(s, baseline)
                        if notes or implications:
                            with st.expander("📝 비교 요약 · 시사점", expanded=True):
                                if notes:
                                    st.markdown("**무엇이 달라졌나**")
                                    for note in notes:
                                        st.markdown(f"- {note}")
                                if implications:
                                    st.markdown("**이게 시사하는 점**")
                                    for imp in implications:
                                        st.markdown(f"- {imp}")

    _render_impact_summary(baseline, snaps, baseline_idx)

    show_unchanged = st.checkbox(
        "변화 없는 KPI도 표에 포함",
        value=False,
        key="compare_show_unchanged_kpi",
    )
    kpi_specs = list(KPI_COMPARE_SPECS)
    if not show_unchanged:
        changed_keys: set[str] = set()
        for s in snaps:
            if s is baseline:
                continue
            for key, _label in KPI_COMPARE_SPECS:
                if kpi_changed(
                    s["kpi"].get(key, 0),
                    baseline["kpi"].get(key, 0),
                ):
                    changed_keys.add(key)
        kpi_specs = [(k, lb) for k, lb in KPI_COMPARE_SPECS if k in changed_keys]

    st.markdown("### 📊 KPI 상세 표")
    st.caption(
        "기준 행(🎯)은 절대값만 표시되고, 나머지 행은 **값 + ▲/▼ + 기준 대비 %** 형식입니다. "
        "▲는 해당 KPI 기준으로 **유리한 변화**입니다."
    )
    if not kpi_specs:
        st.caption("기준 대비 달라진 KPI가 없습니다. 위 요약을 참고하거나 ‘변화 없는 KPI도 표에 포함’을 켜세요.")
    else:
        rows = []
        for s in snaps:
            is_base = s is baseline
            row = {"이름": s["name"] + (" 🎯" if is_base else "")}
            for key, label in kpi_specs:
                higher_better = KPI_HIGHER_BETTER.get(key, True)
                fmt = "{:.1f}" if key not in _KPI_INT_KEYS else "{:.0f}"
                row[label] = kpi_with_delta(
                    s["kpi"].get(key, 0),
                    baseline["kpi"].get(key, 0),
                    is_base,
                    higher_better=higher_better,
                    fmt=fmt,
                )
            row["병목"] = RESOURCE_LABELS.get(s["bottleneck"], s["bottleneck"])
            rows.append(row)
        df_kpi = pd.DataFrame(rows)
        col_cfg: dict[str, Any] = {
            "이름": st_cc.TextColumn("실행 이름", width="medium"),
            "병목": st_cc.TextColumn("병목 자원", width="small"),
        }
        for c in df_kpi.columns:
            if c not in col_cfg:
                col_cfg[c] = st_cc.TextColumn(c, width="small")
        st.dataframe(
            df_kpi,
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg,
        )

    with st.expander("⚙️ 전체 설정 보기", expanded=False):
        cfg_rows = [{"이름": s["name"], **localize_config(s["config"])} for s in snaps]
        st.dataframe(pd.DataFrame(cfg_rows), use_container_width=True, hide_index=True)

    st.markdown("### 📈 자원 가동률 비교")
    util_rows = []
    for s in snaps:
        for n_res, u in s["utilization"].items():
            util_rows.append(
                {
                    "실행": s["name"] + (" 🎯" if s is baseline else ""),
                    "자원": RESOURCE_LABELS.get(n_res, n_res),
                    "가동률 (%)": round(u * 100, 1),
                }
            )
    fig = px.bar(
        pd.DataFrame(util_rows),
        x="자원",
        y="가동률 (%)",
        color="실행",
        barmode="group",
    )
    fig.update_layout(
        template="plotly_white",
        height=440,
        yaxis_range=[0, 110],
        legend_title=None,
        font=dict(size=13),
        xaxis_title="자원",
        yaxis_title="가동률 (%)",
    )
    fig.add_hline(y=90, line_dash="dash", line_color="#c62828", annotation_text="90%", annotation_position="right")
    fig.add_hline(y=70, line_dash="dot", line_color="#f9a825", annotation_text="70%", annotation_position="right")
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "막대가 **90% 선**에 가깝다면 해당 자원이 **한계에 가깝게 쓰인** 실행입니다. "
        "기준(🎯)과 다른 실행의 막대 높이를 자원별로 나란히 보면, **어느 공정에서 여유가 생겼는지·줌**이 드러납니다."
    )

    st.markdown("### 📅 일별 생산 추이 비교")
    daily_rows = []
    for s in snaps:
        dp = s.get("daily_production", {})
        for day, vals in sorted(dp.items()):
            total = (vals.get("flake", 0) or 0) + (vals.get("scr", 0) or 0)
            daily_rows.append(
                {
                    "실행": s["name"] + (" 🎯" if s is baseline else ""),
                    "일": int(day) + 1,
                    "총 생산 (t)": round(total, 2),
                }
            )
    if daily_rows:
        fig = px.line(
            pd.DataFrame(daily_rows),
            x="일",
            y="총 생산 (t)",
            color="실행",
            markers=True,
        )
        fig.update_layout(
            template="plotly_white",
            height=380,
            legend_title=None,
            xaxis=dict(dtick=1, title="시뮬레이션 일 차수"),
            yaxis_title="해당 일 총 생산 (t)",
            font=dict(size=13),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "선이 **위로 가파를수록** 그날 처리량이 많았다는 뜻입니다. "
            "기준 대비 다른 실행이 **전 구간에서 위**에 있으면 기간 전체 생산이 우세한 경우이고, "
            "**후반만 벌어지면** 초기에는 비슷하다가 후반에 병목·재고·출하 조건이 달라진 패턴일 수 있습니다."
        )
    else:
        st.caption("일별 생산 데이터가 없는 스냅샷입니다.")
