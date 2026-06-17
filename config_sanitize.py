"""시뮬레이션 실행 전 SimulationConfig 유효성 검사·보정."""

from __future__ import annotations

from dataclasses import replace

from config import SimulationConfig


def simulation_config_issues(cfg: SimulationConfig) -> list[str]:
    """SimPy `Resource` 등 실행 불가 설정을 사람이 읽을 수 있는 문장으로 반환."""
    issues: list[str] = []
    checks: list[tuple[bool, str, int | float]] = [
        (cfg.sim_days < 1, "시뮬레이션 일수", cfg.sim_days),
        (cfg.inbound.trucks_per_day < 1, "일 입고 트럭 수", cfg.inbound.trucks_per_day),
        (cfg.inbound.weighbridges < 1, "계근대 수", cfg.inbound.weighbridges),
        (cfg.inbound.unloading_bays < 1, "하역 베이 수", cfg.inbound.unloading_bays),
        (cfg.sorting.sorters < 1, "선별 작업조 수", cfg.sorting.sorters),
        (cfg.sorting.presses < 1, "압착기 대수", cfg.sorting.presses),
        (cfg.melting.furnace_count < 1, "반사로 대수", cfg.melting.furnace_count),
        (cfg.melting.elevator_count < 1, "엘리베이터 대수", cfg.melting.elevator_count),
    ]
    for bad, label, val in checks:
        if bad:
            issues.append(f"**{label}**({val}) — 1 이상이어야 합니다.")
    return issues


def sanitize_for_simulation(cfg: SimulationConfig) -> SimulationConfig:
    """SimPy 실행에 필요한 정수·용량 하한을 맞춘다(문서 추출값 보정)."""
    return replace(
        cfg,
        sim_days=max(1, cfg.sim_days),
        inbound=replace(
            cfg.inbound,
            trucks_per_day=max(1, cfg.inbound.trucks_per_day),
            weighbridges=max(1, cfg.inbound.weighbridges),
            unloading_bays=max(1, cfg.inbound.unloading_bays),
        ),
        sorting=replace(
            cfg.sorting,
            sorters=max(1, cfg.sorting.sorters),
            presses=max(1, cfg.sorting.presses),
            subpiles_per_truck=max(1, cfg.sorting.subpiles_per_truck),
            blocks_per_subpile=max(1, cfg.sorting.blocks_per_subpile),
            pallet_buffer_cap=max(1, cfg.sorting.pallet_buffer_cap),
        ),
        melting=replace(
            cfg.melting,
            furnace_count=max(1, cfg.melting.furnace_count),
            elevator_count=max(1, cfg.melting.elevator_count),
            elevator_pallets_per_trip=max(1, cfg.melting.elevator_pallets_per_trip),
        ),
        casting=replace(
            cfg.casting,
            flake_buffer_cap=max(1, cfg.casting.flake_buffer_cap),
            scr_buffer_cap=max(1, cfg.casting.scr_buffer_cap),
        ),
    )
