"""파라미터 참조 뷰."""

from __future__ import annotations

import streamlit as st

from config import DEFAULT_CONFIG
from model_reference import adjustable_parameters, parameters_dataframe


def render() -> None:
    st.header("📋 시뮬레이션 파라미터 참조")
    st.caption(
        "모델에 사용되는 파라미터, **기본값**, **단위**, UI에서 조정 가능 여부를 정리합니다. "
        "시간은 분(min), 중량은 톤(t)이 기본 단위입니다."
    )

    run = st.session_state.get("last_run")
    cfg = run["cfg"] if run else None

    if cfg is not None:
        st.success(
            f"마지막 실행 결과 기준 **현재값**을 표시합니다 "
            f"(시뮬 {cfg.sim_days}일, 시드 {cfg.random_seed})."
        )
    else:
        st.info(
            "아직 시뮬레이션을 실행하지 않았습니다. "
            "**현재값** 열은 `data/*.xlsx`(있을 때)에서 읽은 기본 설정과 동일합니다. "
            "**시뮬레이션** 탭에서 실행 후 이 탭을 다시 열면 마지막 실행 설정이 반영됩니다."
        )

    st.subheader("사이드바에서 조정 가능한 파라미터")
    st.dataframe(
        adjustable_parameters(cfg),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "위 항목은 **시뮬레이션** 탭 사이드바 슬라이더·숫자 입력으로 변경할 수 있습니다. "
        "제외된 행은 파생값(예: 총 시뮬 시간)이거나 표시용 합계입니다. "
        "전체 정의는 아래 표에서 확인하세요."
    )

    st.subheader("전체 파라미터")
    show_diff_only = st.checkbox("기본값과 다른 항목만 보기", value=False)

    full_df = parameters_dataframe(cfg)
    if show_diff_only and cfg is not None:
        mask = full_df["기본값"] != full_df["현재값"]
        full_df = full_df[mask]
        if full_df.empty:
            st.caption("기본값과 다른 파라미터가 없습니다.")
        else:
            st.dataframe(full_df, use_container_width=True, hide_index=True)
    elif show_diff_only:
        st.caption("실행 기록이 없어 필터를 적용할 수 없습니다.")
    else:
        sections = full_df["구분"].unique().tolist()
        tab_labels = ["전체"] + sections
        tabs = st.tabs(tab_labels)
        with tabs[0]:
            st.dataframe(full_df, use_container_width=True, hide_index=True)
        for tab, section in zip(tabs[1:], sections):
            with tab:
                part = full_df[full_df["구분"] == section]
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
