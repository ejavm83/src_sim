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
    _render_bottlenecks(a)
    st.divider()
    _render_machines(a)
    st.divider()
    _render_output(a)

    with st.expander("이 모델이 세운 가정 (SOP가 미확정으로 남긴 부분)", expanded=False):
        for n in a.notes:
            st.markdown(f"- {n}")
