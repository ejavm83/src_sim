"""시뮬레이션 파라미터 (도메인 기본값).

도메인 출처: 군산 공정 상세 문서 (5단계 하이브리드 공정).
모든 시간 단위는 분(min), 중량 단위는 톤(t).
"""

from dataclasses import dataclass, field


@dataclass
class InboundConfig:
    trucks_per_day: int = 10
    truck_load_ton: float = 20.0
    arrival_start_min: int = 9 * 60
    arrival_end_min: int = 18 * 60
    morning_cutoff_min: int = 12 * 60
    morning_share: float = 0.80
    weigh_in_min: float = 5.0
    weigh_out_min: float = 5.0
    unload_min: float = 20.0
    unloading_bays: int = 2
    weighbridges: int = 1


@dataclass
class SortingConfig:
    sort_min_per_truck: float = 30.0
    subpiles_per_truck: int = 8
    subpile_ton: float = 2.5
    blocks_per_subpile: int = 5
    block_ton: float = 0.5
    forklift_min_per_block: float = 5.0
    press_min_per_block: float = 1.5
    pallet_load_min_per_block: float = 3.0
    sorters: int = 2
    presses: int = 1
    pallet_buffer_cap: int = 160


@dataclass
class MeltingConfig:
    batch_ton: float = 80.0
    pallet_ton: float = 2.5
    elevator_pallets_per_trip: int = 2
    elevator_cycle_min: float = 5.0
    setup_min: float = 120.0
    melting_min: float = 780.0
    furnace_count: int = 2
    elevator_count: int = 1

    @property
    def pallets_per_batch(self) -> int:
        return int(self.batch_ton / self.pallet_ton)


@dataclass
class CastingConfig:
    flake_ratio: float = 0.20
    flake_unit_ton: float = 1.0
    flake_min_per_unit: float = 3.1
    scr_unit_ton: float = 4.0
    scr_min_per_unit: float = 12.5
    holding_setup_min: float = 60.0
    flake_buffer_cap: int = 100
    scr_buffer_cap: int = 75


@dataclass
class OutboundConfig:
    truck_interval_min: float = 60.0
    truck_capacity_ton: float = 20.0
    flake_truck_prob: float = 0.20
    weigh_in_min: float = 5.0
    weigh_out_min: float = 5.0
    load_min: float = 12.0
    max_wait_min: float = 240.0


@dataclass
class SimulationConfig:
    sim_days: int = 7
    random_seed: int = 42
    inbound: InboundConfig = field(default_factory=InboundConfig)
    sorting: SortingConfig = field(default_factory=SortingConfig)
    melting: MeltingConfig = field(default_factory=MeltingConfig)
    casting: CastingConfig = field(default_factory=CastingConfig)
    outbound: OutboundConfig = field(default_factory=OutboundConfig)

    @property
    def sim_horizon_min(self) -> int:
        return self.sim_days * 24 * 60


def _default_config() -> SimulationConfig:
    try:
        from excel_config import load_simulation_config_from_excel

        return load_simulation_config_from_excel()
    except Exception:
        return SimulationConfig()


DEFAULT_CONFIG = _default_config()
