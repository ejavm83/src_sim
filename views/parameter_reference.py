"""시뮬레이션 조건 참조 뷰 (공정 설명 문서와 동일한 5단계 흐름)."""

from __future__ import annotations

import streamlit as st

from config import DEFAULT_CONFIG
from model_reference import PROCESS_STAGES, adjustable_parameters, parameters_dataframe


def render() -> None:
    st.header("📋 시뮬레이션 조건")
    st.caption(
        "**공정 설명** 문서(`data/공정설명260521.md`)와 같은 **5단계 공정 순서**로, 시뮬레이션에 반영된 조건을 나열합니다. "
        "표의 **«사이드바 조정»** 열이 **✓**인 항목만 **🏭 시뮬레이션** 탭 왼쪽 사이드바에서 슬라이더로 바꿀 수 있습니다. "
        "기본 숫자는 `data` 폴더의 설정 엑셀(있을 때) 또는 코드 기본값이며, **현재값**은 마지막 실행이 있으면 그 설정을 반영합니다."
    )

    run = st.session_state.get("last_run")
    cfg = run["cfg"] if run else None

    if cfg is not None:
        st.success(
            f"마지막 실행 기준 **현재값**을 표시합니다 "
            f"(시뮬 {cfg.sim_days}일, 시드 {cfg.random_seed})."
        )
    else:
        st.info(
            "아직 시뮬레이션을 실행하지 않았습니다. "
            "**현재값** 열은 엑셀·코드 기본 설정과 같습니다. "
            "**🏭 시뮬레이션** 탭에서 실행 후 이 탭을 다시 열면 마지막 실행 설정이 반영됩니다."
        )

    full_df = parameters_dataframe(cfg)
    n_sidebar = int((full_df["사이드바 조정"] == "✓").sum())
    n_total = len(full_df)
    st.markdown(
        f"등록된 조건 **{n_total}**행 중 **{n_sidebar}**행은 사이드바에서 조정할 수 있습니다. "
        "나머지는 파생값(예: 배치당 파레트 수)·실행 틀(총 시뮬 시간)·난수 시드 등입니다."
    )

    st.subheader("공정 단계별 조건")
    st.caption("단계 카드를 펼치면 공정 설명과 맞춘 요약·모델 설명과, 해당 구간 조건 표가 함께 표시됩니다.")

    common_df = full_df[full_df["구분"] == "공통"].copy()
    with st.expander("공통 · 시뮬 기간·난수", expanded=True):
        st.markdown(
            "**문서와의 연결:** 며칠 동안 가상 공장을 돌릴지, 입고·출하 무작위를 재현하기 위한 시드 등 "
            "실행의 뼈대입니다. **난수 시드**는 현재 웹 UI 슬라이더에는 없고 코드·엑셀 기본을 따릅니다."
        )
        st.dataframe(common_df, use_container_width=True, hide_index=True)

    for stage in PROCESS_STAGES:
        title = stage["단계"]
        part = full_df[full_df["구분"] == title].copy()
        with st.expander(f"{title} — {stage['자재']}", expanded=False):
            st.markdown(
                f"**설비·자재:** {stage['설비']}  \n"
                f"**시뮬에 넣은 요약:** {stage['요약']}  \n"
                f"**모델링:** {stage['모델']}"
            )
            if part.empty:
                st.caption("이 구간에 매핑된 조건 행이 없습니다.")
            else:
                st.dataframe(part, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("사이드바에서 조정 가능한 조건만 (요약)")
    st.caption("위 표와 동일하되, 슬라이더로 바꿀 수 있는 행만 모았습니다.")
    st.dataframe(adjustable_parameters(cfg), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("조건 전체표")
    show_diff_only = st.checkbox("기본값과 다른 항목만 보기", value=False)

    view_df = parameters_dataframe(cfg)
    if show_diff_only and cfg is not None:
        mask = view_df["기본값"] != view_df["현재값"]
        view_df = view_df[mask]
        if view_df.empty:
            st.caption("기본값과 다른 조건이 없습니다.")
        else:
            st.dataframe(view_df, use_container_width=True, hide_index=True)
    elif show_diff_only:
        st.caption("실행 기록이 없어 필터를 적용할 수 없습니다.")
    else:
        sections = view_df["구분"].unique().tolist()
        tab_labels = ["전체"] + sections
        tabs = st.tabs(tab_labels)
        with tabs[0]:
            st.dataframe(view_df, use_container_width=True, hide_index=True)
        for tab, section in zip(tabs[1:], sections):
            with tab:
                part = view_df[view_df["구분"] == section]
                st.dataframe(part, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("파생·계산 관계")
    d = DEFAULT_CONFIG
    trips = d.melting.pallets_per_batch // d.melting.elevator_pallets_per_trip
    block_cycle = (
        d.sorting.forklift_min_per_block
        + d.sorting.press_min_per_block
        + d.sorting.pallet_load_min_per_block
    )
    subpile_press = d.sorting.blocks_per_subpile * block_cycle

    st.markdown(
        f"""
| 관계 | 계산 | 기본값 예 |
|------|------|-----------|
| 배치당 파레트 | `batch_ton ÷ pallet_ton` | {d.melting.pallets_per_batch}개 |
| 엘리베이터 왕복 수 | `파레트 ÷ 1회 적재` | {trips}회 |
| sub-pile 압착 시간 | `블록 수 × (지게차+압착+적재)` | {subpile_press:.1f}분 |
| 트럭당 파레트 | `sub-pile 수` (각 {d.sorting.subpile_ton} t) | {d.sorting.subpiles_per_truck}개 |
| 일 입고량(이론) | `트럭 수 × 적재량` | {d.inbound.trucks_per_day * d.inbound.truck_load_ton:.0f} t/일 |
| 큐프레이크/SCR 분할 | `배치 × flake_ratio` | {d.melting.batch_ton * d.casting.flake_ratio:.0f} t / {d.melting.batch_ton * (1 - d.casting.flake_ratio):.0f} t |
"""
    )

    with st.expander("공정 설명에는 있으나 별도 슬라이더가 없는 서술", expanded=False):
        st.markdown(
            """
아래는 내러티브·배치감용으로 문서에만 쓰이고, **숫자 조건으로 분해되지 않은** 예시입니다.

- **더미·작업장 면적**(예: 바닥 5m×5m): 시뮬에는 면적 자체가 들어가지 않습니다.
- **반사로 설계 최대 200t** 같은 설비 상한: 현재 모델은 **배치 톤수** 등으로만 용량을 다룹니다.
- **출하 트럭 20~25t**처럼 범위를 쓴 문장: 시뮬은 **한 값(기본 20t)**으로 단순화되어 있습니다.
"""
        )
