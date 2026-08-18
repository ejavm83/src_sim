"""멕시코 CMS 전선공장 시뮬레이션 탭.

`data/공정설명260521.md` (SOP v0.3)를 사양서로 삼아 만든 SimPy 모델을 실행하고
결과를 보여 준다. 엔진은 `cms_simulation.py`, 해석은 `cms_report.py`.
"""

from __future__ import annotations

import time
import pandas as pd
import streamlit as st

from cms_config import DEFAULT_CMS_CONFIG, CmsConfig
from cms_report import LINE_LABELS, CmsAnalysis, analyze_cms, bottleneck_report
from cms_simulation import run_cms_simulation
from views import kpi_pipeline

_RUN_KEY = "cms_last_run"
# 다른 탭(프로세스 분석)이 마지막 시뮬레이션 결과를 재사용하기 위한 공개 이름
RUN_KEY = _RUN_KEY


def _render_spec_panel() -> None:
    """공정 사양(MD 표에서 생성) 상태와 재생성 버튼."""
    from pathlib import Path

    from process_spec import DEFAULT_SPEC_PATH, load_spec, save_spec, validate_spec
    from ui.cms_sidebar import bump_spec_nonce
    from spec_from_md import spec_from_markdown
    from views.process_description import doc_path

    with st.expander("📐 공정 사양 — 이 시뮬레이션이 무엇을 읽고 있나", expanded=False):
        st.caption(
            "설비 목록과 라인별 라우팅·단계 시간은 코드가 아니라 **사양 파일**에 들어 있고, "
            "그 사양은 **공정 설명 MD의 표**에서 만들어집니다. "
            "MD의 「6.1 설비 마스터」·「5.1~5.4 라우팅」·「7.3 로트 변환」 표를 고친 뒤 "
            "아래 버튼을 누르면 코드 수정 없이 시뮬레이션이 바뀝니다."
        )

        if not DEFAULT_SPEC_PATH.is_file():
            st.warning("사양 파일이 없습니다. 아래 버튼으로 MD에서 생성하세요.")
        else:
            spec = load_spec()
            steps = sum(len(r.get("steps", [])) for r in spec.get("routes", {}).values())
            st.markdown(
                f"- 파일: `{DEFAULT_SPEC_PATH.relative_to(Path.cwd()) if DEFAULT_SPEC_PATH.is_relative_to(Path.cwd()) else DEFAULT_SPEC_PATH.name}`\n"
                f"- 설비 **{len(spec.get('equipment', []))}종** · "
                f"라인 **{len(spec.get('routes', {}))}개** · 공정 단계 **{steps}개**\n"
                f"- 출처 문서: `{spec.get('_meta', {}).get('source_doc', '?')}`"
            )

        if st.button("📄 공정 설명 MD에서 사양 다시 생성", use_container_width=True):
            doc = doc_path()
            if not doc.is_file():
                st.error(f"공정 설명 문서를 찾지 못했습니다: {doc.name}")
            else:
                base = load_spec() if DEFAULT_SPEC_PATH.is_file() else None
                new_spec, notes = spec_from_markdown(
                    doc.read_text(encoding="utf-8"), base=base
                )
                problems = validate_spec(new_spec)
                if problems:
                    st.error("사양이 올바르지 않아 저장하지 않았습니다:")
                    for p in problems[:10]:
                        st.markdown(f"- {p}")
                else:
                    save_spec(new_spec)
                    for n in notes:
                        st.info(n)
                    # 사이드바 위젯이 새 사양 값을 따르도록 key를 갈아끼우고 다시 그린다
                    bump_spec_nonce()
                    st.session_state.pop(_RUN_KEY, None)
                    st.session_state["_cms_spec_toast"] = (
                        f"사양을 다시 만들었습니다 — 설비 {len(new_spec['equipment'])}종 · "
                        f"단계 {sum(len(r['steps']) for r in new_spec['routes'].values())}개. "
                        "사이드바 값이 갱신되었습니다."
                    )
                    st.rerun()


def _render_changed_from_sop(cfg: CmsConfig) -> None:
    """사양(MD 기재값)과 달라진 설정을 알려 준다 — 결과를 SOP 탓으로 오해하지 않도록."""
    from ui.cms_sidebar import spec_config

    ref = spec_config()
    diffs: list[str] = []
    for key, spec in cfg.equipment.items():
        base = ref.equipment.get(key)
        if base is None:
            continue
        if spec.count != base.count:
            diffs.append(f"{spec.label} {base.count}대 → **{spec.count}대**")
    if cfg.cu44_shield_ratio != ref.cu44_shield_ratio:
        diffs.append(
            f"차폐 비율 {ref.cu44_shield_ratio:.0%} → "
            f"**{cfg.cu44_shield_ratio:.0%}**"
        )
    if cfg.inbound.cu_trucks_per_month != ref.inbound.cu_trucks_per_month:
        diffs.append(
            f"Cu 월 트럭 {ref.inbound.cu_trucks_per_month}대 → "
            f"**{cfg.inbound.cu_trucks_per_month}대**"
        )
    if diffs:
        st.info("사양(MD) 기재값에서 바꾼 설정 — " + " · ".join(diffs))


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


def _render_bottlenecks(a: CmsAnalysis, run: dict | None = None) -> None:
    st.markdown("#### 🚦 병목 진단 — 무엇이, 누구를, 얼마나 막았나")
    st.caption(
        "문서만 봐서는 '가장 느린 공정'까지만 알 수 있습니다. 여기서는 **돌려 봐야 아는 것**을 "
        "보여 줍니다 — 설비가 모자라 물리적으로 못 도는 곳, 여러 라인이 한 설비를 두고 다투며 "
        "생긴 대기, 그래서 어느 라인이 계획을 못 채웠는지입니다."
    )
    if not run:
        st.info("시뮬레이션을 실행하면 병목 진단이 표시됩니다.")
        return

    rep = bottleneck_report(run["metrics"], run["cfg"], a)

    for row in rep.rows[:6]:
        if row.load <= 0 and row.jobs == 0:
            continue
        tone = {"능력부족": ("#fdeaea", "#d9534f"), "경합": ("#fdf3e3", "#e08b3c")}.get(
            row.kind, ("#eef6ee", "#3f9e6a")
        )
        waits = " · ".join(
            f"{LINE_LABELS.get(ln, ln)} {h:,.0f}h" for ln, h in row.wait_by_line[:4]
        ) or "대기 없음"
        fix = (
            f"<br><small>🔧 <b>{row.add_needed}대 증설</b>하면 부하 "
            f"{row.load * 100:.0f}% → {row.load_after * 100:.0f}%</small>"
            if row.add_needed
            else ""
        )
        st.markdown(
            f'<div style="background:{tone[0]};border-left:4px solid {tone[1]};'
            f'border-radius:8px;padding:0.6rem 1rem;margin-bottom:0.5rem;color:#111827">'
            f'<b>{row.rank}. {row.label}</b> {row.count}대 '
            f'<span style="background:{tone[1]};color:#fff;border-radius:4px;'
            f'padding:0 6px;font-size:0.8em">{row.kind}</span>'
            f'<br><small>🧮 부하 <code>{row.demand_h:,.0f}h ÷ {row.capacity_h:,.0f}h = '
            f'{row.load * 100:.0f}%</code> · 가동률 {row.utilization * 100:.0f}% · '
            f'평균 대기 {row.avg_wait_h:.1f}h · 최대 대기열 {row.max_queue}개</small>'
            f'<br><small>🔀 이 설비를 두고 다툰 라인 <b>{len(row.lines)}개</b> — {waits}</small>'
            f'{fix}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("##### 📉 라인별 계획 대비 실적 — 경합에 밀린 결과")
    st.caption("달성률이 낮은 라인은 대개 공유 설비 앞에서 밀린 쪽입니다.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "라인": ln.label,
                    "달성률": ln.rate,
                    "계획(m)": round(ln.plan_m),
                    "실적(m)": round(ln.actual_m),
                    "대기 비중": ln.wait_share,
                    "가장 오래 막힌 곳": " · ".join(
                        f"{lb} {h:,.0f}h" for lb, h in ln.blocked_at[:2]
                    )
                    or "-",
                }
                for ln in rep.lines
            ]
        ),
        hide_index=True,
        use_container_width=True,
        column_config={
            "달성률": st.column_config.ProgressColumn(
                "달성률", format="%.0f%%", min_value=0.0, max_value=1.0
            ),
            "대기 비중": st.column_config.ProgressColumn(
                "대기 비중", format="%.0f%%", min_value=0.0, max_value=1.0
            ),
        },
    )


def _render_machines(a: CmsAnalysis) -> None:
    st.markdown("#### 🔧 개별 설비별 가동률과 공유 관계")
    st.caption(
        "같은 유형이라도 현장에서는 **위치·번호로 구분되는 개별 기계**입니다(SOP 2.6 — "
        "자원 풀은 지도의 역 하나하나에 대응). 아래는 기계 한 대 단위의 결과이고, "
        "**사용 라인**이 둘 이상이면 그 기계에서 라인 간 경합이 일어납니다."
    )
    rows = [
        {
            "설비 ID": r.machine_id,
            "유형": r.equip_label,
            "가동률": r.utilization,
            "처리 로트": r.jobs,
            "사용 라인 수": len(r.lines),
            "사용 라인": " · ".join(LINE_LABELS.get(x, x) for x in r.lines) or "-",
        }
        for r in a.machines
    ]
    only_shared = st.checkbox(
        "여러 라인이 함께 쓰는 설비만 보기", value=False, key="cms_only_shared"
    )
    if only_shared:
        rows = [r for r in rows if r["사용 라인 수"] > 1]
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


def _render_kpis(a: CmsAnalysis, cfg: CmsConfig) -> None:
    """핵심 KPI 4장 — 각 카드의 **🧮 근거**를 누르면 실제 숫자가 든 수식이 뜬다."""
    st.caption("각 카드 아래 **🧮 근거**를 누르면 그 숫자가 어떻게 나왔는지 수식으로 보여 줍니다.")
    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.metric("총 생산량", f"{a.total_m/1_000_000:.2f}M m")
        with st.popover("🧮 근거", use_container_width=True):
            st.markdown("**무엇인가요?** 시뮬레이션 기간 동안 재권취(최종 검사)까지 끝난 전선 길이의 합계입니다.")
            st.markdown("**어떻게 계산했나요?** 라인별 완성 길이를 전부 더합니다.")
            parts = [
                f"{LINE_LABELS.get(key, key)} {m:,.0f}m"
                for key, m in a.finished_m.items()
                if m
            ]
            st.markdown(
                "`" + " + ".join(parts) + f" = {a.total_m:,.0f}m`\n\n"
                f"`{a.total_m:,.0f}m ÷ 1,000,000 = {a.total_m/1_000_000:.2f}M m`"
            )

    with k2:
        cal = cfg.calendar
        week_up_h = 24 * 7 - cal.weekend_stop_hours - cal.monday_startup_hours
        st.metric("가동 가능 시간", f"{a.uptime_min/60:,.0f} h", help="주말 정지·월요일 스타트업 제외")
        with st.popover("🧮 근거", use_container_width=True):
            st.markdown(
                "**무엇인가요?** 캘린더(SOP 6.3)상 설비가 실제로 돌 수 있는 시간입니다. "
                "주말 정지와 월요일 스타트업은 뺍니다."
            )
            st.markdown(
                f"**어떻게 계산했나요?**\n\n"
                f"`1주 = 168h − 주말 정지 {cal.weekend_stop_hours:.0f}h − "
                f"월요일 스타트업 {cal.monday_startup_hours:.0f}h = {week_up_h:.0f}h/주`\n\n"
                f"`{a.days}일 ≈ {a.days/7:.1f}주 → 합계 {a.uptime_min/60:,.0f}h` "
                f"(마지막 주가 잘리면 그만큼만 계산)"
            )
            st.markdown(
                f"참고: 실효 가동률 {cal.availability:.1%}는 여기가 아니라 "
                "각 작업 시간을 늘리는 쪽(시간 ÷ 가동률)에 반영됩니다."
            )

    with k3:
        st.metric("기말 재공(WIP)", f"{a.wip_end:,} 로트", delta=f"{a.wip_end - a.wip_start:+,}")
        with st.popover("🧮 근거", use_container_width=True):
            st.markdown(
                "**무엇인가요?** 시뮬레이션이 끝난 시점에 공장 안에 남아 있던(아직 완성 전인) 로트 수입니다."
            )
            st.markdown(
                f"**어떻게 계산했나요?**\n\n"
                f"`기말 재공 {a.wip_end:,}개 − 기초 재공 {a.wip_start:,}개 = "
                f"{a.wip_end - a.wip_start:+,}개 변화`"
            )
            if a.wip_growing:
                st.markdown(
                    "⚠️ 재공이 계속 늘고 있습니다 — 들어오는 물량이 설비 능력보다 많아 "
                    "재고가 쌓이는 상태라는 뜻입니다."
                )
            else:
                st.markdown("재공이 안정 범위라 투입과 산출이 대체로 균형입니다.")

    with k4:
        over_rows = [r for r in a.capacity if r.load > 1.0]
        st.metric(
            "능력 부족 설비",
            f"{len(over_rows)} 개",
            delta="문제" if over_rows else "여유",
            delta_color="inverse",
        )
        with st.popover("🧮 근거", use_container_width=True):
            st.markdown(
                "**무엇인가요?** 월 입고량을 다 처리하기에 시간이 모자라는 설비 수입니다. "
                "부하 = 필요한 시간 ÷ 쓸 수 있는 시간이고, **100%를 넘으면 물리적으로 불가능**합니다."
            )
            if over_rows:
                st.markdown("**어떤 설비가, 얼마나 넘나요?**")
                for r in over_rows[:6]:
                    st.markdown(
                        f"- **{r.label}** ({r.count}대): "
                        f"`요구 {r.demand_min/60:,.0f}h ÷ 가용 {r.capacity_min/60:,.0f}h "
                        f"= {r.load:.0%}`"
                    )
                if len(over_rows) > 6:
                    st.caption(f"…외 {len(over_rows) - 6}개 (아래 능력 표 참조)")
            else:
                worst = a.capacity[0] if a.capacity else None
                if worst:
                    st.markdown(
                        f"모든 설비가 100% 이하입니다. 가장 빠듯한 곳은 **{worst.label}**: "
                        f"`요구 {worst.demand_min/60:,.0f}h ÷ 가용 {worst.capacity_min/60:,.0f}h "
                        f"= {worst.load:.0%}`"
                    )


def _render_optimizer(a: CmsAnalysis, cfg: CmsConfig) -> None:
    """CP-SAT 설비 증설 최적화 — '그럼 어떻게 바꿔야 하나'에 답한다."""
    from cms_optimizer import apply_additions, solve_max_throughput, solve_min_additions

    st.markdown("#### 🎯 설비 증설 최적화 (CP-SAT)")
    st.caption(
        "시뮬레이션이 **지금 구성에서 무슨 일이 벌어지는지**를 보여 준다면, 여기서는 "
        "**어디에 몇 대를 더 놓아야 하는지**를 풉니다. 정수계획 문제라 CP-SAT이 "
        "최적해를 보장합니다 — 슬라이더를 돌려 찾은 값이 아니라 증명된 최소 조합입니다."
    )

    mode = st.radio(
        "무엇을 풀까요?",
        ["최소 증설 — 모든 병목 해소", "예산 제한 — 주어진 대수로 최대 물량"],
        key="cms_opt_mode",
        horizontal=True,
    )
    min_mode = mode.startswith("최소")

    c1, c2 = st.columns(2)
    with c1:
        if min_mode:
            target = st.slider(
                "목표 부하 상한 (%)", 70, 100, 100, 5,
                help="모든 설비를 이 부하 아래로 낮춥니다. 100%는 '겨우 소화', "
                     "85%는 변동에 견딜 여유를 둔 설계입니다.",
            )
        else:
            budget = st.slider("증설 가능 대수", 1, 60, 10, 1)
    with c2:
        st.caption(
            "비용은 설비 유형별 상대 가중치입니다 — 조사기 8 · 압출기 4 · "
            "편조기 1 · 검사 0.5. 실제 견적이 있으면 알려 주세요."
        )

    if not st.button("🧮 최적 구성 계산", use_container_width=True, key="cms_opt_run"):
        return

    try:
        res = (
            solve_min_additions(cfg, a, target_load=target / 100.0)
            if min_mode
            else solve_max_throughput(cfg, a, budget_units=budget)
        )
    except RuntimeError as exc:
        st.error(str(exc))
        return

    if not res.ok:
        st.error(f"{res.message} (상태: {res.status})")
        return

    if min_mode:
        st.success(
            f"최적해({res.status}) — **총 {res.total_added}대 증설**, "
            f"가중비용 {res.total_cost:.1f}"
        )
    else:
        st.success(
            f"최적해({res.status}) — 증설 {res.total_added}대로 "
            f"**계획 물량의 {res.throughput_ratio:.0%}**까지 소화"
        )

    if res.changed:
        st.dataframe(
            pd.DataFrame([
                {
                    "설비": r.label,
                    "현재": r.now,
                    "증설": f"+{r.add}",
                    "변경 후": r.now + r.add,
                    "부하(현재)": r.load_before,
                    "부하(변경 후)": r.load_after,
                }
                for r in res.changed
            ]),
            hide_index=True,
            use_container_width=True,
            column_config={
                "부하(현재)": st.column_config.ProgressColumn(
                    "부하(현재)", format="%.0f%%", min_value=0.0, max_value=2.5
                ),
                "부하(변경 후)": st.column_config.ProgressColumn(
                    "부하(변경 후)", format="%.0f%%", min_value=0.0, max_value=2.5
                ),
            },
        )
    else:
        st.info("증설 없이도 목표를 만족합니다.")

    for n in res.notes:
        st.caption(n)

    if res.changed:
        st.session_state["_cms_opt_cfg"] = apply_additions(cfg, res)
        st.caption(
            "이 구성으로 실제로 돌려 보려면 사이드바에서 위 대수를 반영한 뒤 "
            "**🚀 시뮬레이션 실행**을 누르세요. 정적 계산과 시뮬 결과가 일치하는지 "
            "확인하는 것이 이 도구의 검증 방법입니다."
        )


def render_page(cfg: CmsConfig | None = None, run: bool = False) -> None:
    st.header("🏭 CMS 전선공장 시뮬레이션")
    st.caption(
        "**📄 공정 설명** 탭의 SOP(멕시코 CMS 공장 v0.3)를 사양서로 삼아 만든 모델입니다. "
        "설비 대수·공유 관계는 SOP 6.1, 라우팅과 단계 시간은 5.1~5.4, 로트 변환은 7.3, "
        "교체 시간은 6.2, 캘린더(주 116시간 가동·가동률 92.6%)는 6.3을 그대로 따릅니다. "
        "**설비 대수와 시나리오는 왼쪽 사이드바**에서 공정별로 조정합니다."
    )

    if st.session_state.get("_cms_spec_toast"):
        st.success(st.session_state.pop("_cms_spec_toast"))

    cfg = cfg or DEFAULT_CMS_CONFIG
    _render_spec_panel()
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
            "cfg": cfg,
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

    _render_kpis(a, cfg)

    if a.findings:
        st.markdown("#### 🔎 진단")
        for f in a.findings:
            st.markdown(f"- {f}")

    st.divider()
    _render_capacity(a)
    st.divider()
    _render_bottlenecks(a, run_state)
    st.divider()
    _render_machines(a)
    st.divider()
    _render_output(a)
    st.divider()
    kpi_pipeline.render(run_state)
    st.divider()
    _render_optimizer(a, cfg)

    with st.expander("이 모델이 세운 가정 (SOP가 미확정으로 남긴 부분)", expanded=False):
        for n in a.notes:
            st.markdown(f"- {n}")
