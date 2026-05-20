"""사이드바에서 SimulationConfig 전체를 편집한다."""

from __future__ import annotations

import streamlit as st

from config import (
    CastingConfig,
    InboundConfig,
    MeltingConfig,
    OutboundConfig,
    SimulationConfig,
    SortingConfig,
)


def _slider_int(label: str, lo: int, hi: int, default: int, step: int = 1, **kw) -> int:
    return int(st.slider(label, lo, hi, default, step, **kw))


def _slider_float(label: str, lo: float, hi: float, default: float, step: float, **kw) -> float:
    return float(st.slider(label, lo, hi, float(default), step, **kw))


def render_config_sidebar(d: SimulationConfig) -> SimulationConfig:
    """기본값 `d`(엑셀·코드)를 초기값으로 하는 위젯을 그리고 최종 SimulationConfig를 돌려준다."""

    sim_days = _slider_int("시뮬레이션 일수", 1, 30, d.sim_days, 1, help="가상 시간 = 일수 × 24시간")

    with st.expander("공통·운영", expanded=False):
        arrival_start_min = _slider_int(
            "입고 창 시작 (분, 자정 기준)", 0, 1440, d.inbound.arrival_start_min, 15
        )
        arrival_end_min = _slider_int(
            "입고 창 종료 (분)", 0, 1440, d.inbound.arrival_end_min, 15
        )
        morning_cutoff_min = _slider_int(
            "오전·오후 구분 시각 (분)", 0, 1440, d.inbound.morning_cutoff_min, 15
        )
        morning_share = _slider_float(
            "오전 입고 비율", 0.0, 1.0, d.inbound.morning_share, 0.05
        )

    with st.expander("① 입고 / 하역", expanded=False):
        trucks_per_day = _slider_int("일 입고 트럭 수", 1, 50, d.inbound.trucks_per_day, 1)
        truck_load_ton = _slider_float("트럭 적재 (t)", 5.0, 40.0, d.inbound.truck_load_ton, 0.5)
        weighbridges = _slider_int("계근대 수", 1, 4, d.inbound.weighbridges, 1)
        weigh_in_min = _slider_float("1차 계근 (분)", 1.0, 30.0, d.inbound.weigh_in_min, 0.5)
        weigh_out_min = _slider_float("2차 계근 (분)", 1.0, 30.0, d.inbound.weigh_out_min, 0.5)
        unloading_bays = _slider_int("하역 베이 수", 1, 8, d.inbound.unloading_bays, 1)
        unload_min = _slider_float("하역 시간 (분/대)", 5.0, 120.0, d.inbound.unload_min, 1.0)

    with st.expander("② 선별 / 압착", expanded=False):
        sorters = _slider_int("선별 작업조 수", 1, 8, d.sorting.sorters, 1)
        sort_min_per_truck = _slider_float(
            "트럭당 선별 시간 (분)", 5.0, 120.0, d.sorting.sort_min_per_truck, 1.0
        )
        subpiles_per_truck = _slider_int(
            "더미당 sub-pile 수", 1, 20, d.sorting.subpiles_per_truck, 1
        )
        subpile_ton = _slider_float("sub-pile 중량 (t)", 0.5, 10.0, d.sorting.subpile_ton, 0.1)
        blocks_per_subpile = _slider_int(
            "sub-pile당 블록 수", 1, 20, d.sorting.blocks_per_subpile, 1
        )
        block_ton = _slider_float("블록 중량 (t)", 0.1, 5.0, d.sorting.block_ton, 0.1)
        forklift_min_per_block = _slider_float(
            "지게차 투입 (분/블록)", 1.0, 30.0, d.sorting.forklift_min_per_block, 0.5
        )
        press_min_per_block = _slider_float(
            "압착 (분/블록)", 0.5, 20.0, d.sorting.press_min_per_block, 0.5
        )
        pallet_load_min_per_block = _slider_float(
            "파레트 적재 (분/블록)", 0.5, 30.0, d.sorting.pallet_load_min_per_block, 0.5
        )
        presses = _slider_int("압착기 대수", 1, 6, d.sorting.presses, 1)
        pallet_buffer_cap = _slider_int(
            "파레트 버퍼 (개)", 20, 500, d.sorting.pallet_buffer_cap, 10
        )

    with st.expander("③ 장입 / 용해", expanded=False):
        furnace_count = _slider_int("반사로 대수", 1, 6, d.melting.furnace_count, 1)
        batch_ton = _slider_float("배치 장입량 (t)", 20.0, 200.0, d.melting.batch_ton, 2.5)
        pallet_ton = _slider_float(
            "파레트 1개 중량 (t)",
            0.5,
            10.0,
            d.melting.pallet_ton,
            0.1,
            help="배치당 파레트 수 = 배치톤 ÷ 파레트톤(내림)",
        )
        elevator_count = _slider_int("엘리베이터 대수", 1, 4, d.melting.elevator_count, 1)
        elevator_pallets_per_trip = _slider_int(
            "엘리베이터 1회 운반 파레트 수", 1, 8, d.melting.elevator_pallets_per_trip, 1
        )
        elevator_cycle_min = _slider_float(
            "엘리베이터 왕복 (분)", 1.0, 30.0, d.melting.elevator_cycle_min, 0.5
        )
        setup_min = _slider_float(
            "반사로 셋업·가열 (분)", 0.0, 600.0, d.melting.setup_min, 5.0
        )
        melting_min = _slider_float(
            "용해·정련·슬래깅 등 (분)", 60.0, 2000.0, d.melting.melting_min, 10.0
        )

    with st.expander("④ 주조", expanded=False):
        flake_ratio = _slider_float("큐프레이크 생산 비율", 0.0, 1.0, d.casting.flake_ratio, 0.01)
        flake_unit_ton = _slider_float("큐프레이크 단위 (t)", 0.1, 5.0, d.casting.flake_unit_ton, 0.1)
        flake_min_per_unit = _slider_float(
            "큐프레이크 단위당 시간 (분)", 0.5, 60.0, d.casting.flake_min_per_unit, 0.1
        )
        scr_unit_ton = _slider_float("SCR 단위 (t)", 0.5, 20.0, d.casting.scr_unit_ton, 0.5)
        scr_min_per_unit = _slider_float(
            "SCR 단위당 시간 (분)", 1.0, 120.0, d.casting.scr_min_per_unit, 0.5
        )
        holding_setup_min = _slider_float(
            "홀딩로 셋업 (분)", 0.0, 300.0, d.casting.holding_setup_min, 5.0
        )
        flake_buffer_cap = _slider_int(
            "큐프레이크 야적 (단위)", 10, 500, d.casting.flake_buffer_cap, 5
        )
        scr_buffer_cap = _slider_int("SCR 야적 (단위)", 10, 500, d.casting.scr_buffer_cap, 5)

    with st.expander("⑤ 출하", expanded=False):
        truck_interval_min = _slider_float(
            "출하 트럭 평균 간격 (분)", 5.0, 360.0, d.outbound.truck_interval_min, 5.0
        )
        truck_capacity_ton = _slider_float(
            "출하 트럭 만재 (t)", 5.0, 40.0, d.outbound.truck_capacity_ton, 0.5
        )
        flake_truck_prob = _slider_float(
            "출하 큐프레이크 트럭 확률", 0.0, 1.0, d.outbound.flake_truck_prob, 0.05
        )
        out_weigh_in = _slider_float("출하 1차 계근 (분)", 1.0, 30.0, d.outbound.weigh_in_min, 0.5)
        out_weigh_out = _slider_float("출하 2차 계근 (분)", 1.0, 30.0, d.outbound.weigh_out_min, 0.5)
        load_min = _slider_float("상차 시간 (분)", 1.0, 120.0, d.outbound.load_min, 1.0)
        max_wait_min = _slider_float(
            "재고 부족 시 최대 대기 (분)", 30.0, 720.0, d.outbound.max_wait_min, 15.0
        )

    return SimulationConfig(
        sim_days=sim_days,
        random_seed=d.random_seed,
        inbound=InboundConfig(
            trucks_per_day=trucks_per_day,
            truck_load_ton=truck_load_ton,
            arrival_start_min=arrival_start_min,
            arrival_end_min=arrival_end_min,
            morning_cutoff_min=morning_cutoff_min,
            morning_share=morning_share,
            weigh_in_min=weigh_in_min,
            weigh_out_min=weigh_out_min,
            unload_min=unload_min,
            unloading_bays=unloading_bays,
            weighbridges=weighbridges,
        ),
        sorting=SortingConfig(
            sort_min_per_truck=sort_min_per_truck,
            subpiles_per_truck=subpiles_per_truck,
            subpile_ton=subpile_ton,
            blocks_per_subpile=blocks_per_subpile,
            block_ton=block_ton,
            forklift_min_per_block=forklift_min_per_block,
            press_min_per_block=press_min_per_block,
            pallet_load_min_per_block=pallet_load_min_per_block,
            sorters=sorters,
            presses=presses,
            pallet_buffer_cap=pallet_buffer_cap,
        ),
        melting=MeltingConfig(
            batch_ton=batch_ton,
            pallet_ton=pallet_ton,
            elevator_pallets_per_trip=elevator_pallets_per_trip,
            elevator_cycle_min=elevator_cycle_min,
            setup_min=setup_min,
            melting_min=melting_min,
            furnace_count=furnace_count,
            elevator_count=elevator_count,
        ),
        casting=CastingConfig(
            flake_ratio=flake_ratio,
            flake_unit_ton=flake_unit_ton,
            flake_min_per_unit=flake_min_per_unit,
            scr_unit_ton=scr_unit_ton,
            scr_min_per_unit=scr_min_per_unit,
            holding_setup_min=holding_setup_min,
            flake_buffer_cap=flake_buffer_cap,
            scr_buffer_cap=scr_buffer_cap,
        ),
        outbound=OutboundConfig(
            truck_interval_min=truck_interval_min,
            truck_capacity_ton=truck_capacity_ton,
            flake_truck_prob=flake_truck_prob,
            weigh_in_min=out_weigh_in,
            weigh_out_min=out_weigh_out,
            load_min=load_min,
            max_wait_min=max_wait_min,
        ),
    )
