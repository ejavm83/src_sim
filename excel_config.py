"""`data/` 폴더의 공정 설정 Excel에서 SimulationConfig를 읽는다.

시트 **「설비·공정 확인」**의 `No` / **시뮬 현재값** 열을 기준으로 매핑한다.
파일이 없거나 파싱에 실패하면 호출 측에서 내장 기본값으로 폴백한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from config import (
    CastingConfig,
    InboundConfig,
    MeltingConfig,
    OutboundConfig,
    SimulationConfig,
    SortingConfig,
)


def default_excel_path(project_root: Path | None = None) -> Path:
    root = project_root or Path(__file__).resolve().parent
    data = root / "data"
    candidates = sorted(
        p for p in data.glob("*.xlsx") if not p.name.startswith("~$")
    )
    if not candidates:
        raise FileNotFoundError(f"No .xlsx under {data}")
    return candidates[0]


def _cell_str(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _parse_time_range(s: str) -> tuple[int, int] | None:
    """'09:00~18:00' → (540, 1080)."""
    s = _cell_str(s)
    m = re.search(
        r"(\d{1,2})\s*:\s*(\d{2})\s*~\s*(\d{1,2})\s*:\s*(\d{2})",
        s,
    )
    if not m:
        return None
    h1, mi1, h2, mi2 = (int(m.group(i)) for i in range(1, 5))
    return h1 * 60 + mi1, h2 * 60 + mi2


def _parse_slash_pair(s: str) -> tuple[float, float] | None:
    """'5.0 / 5.0' 또는 '2개 / 5.0분' 형태에서 숫자 두 개."""
    s = _cell_str(s)
    nums = re.findall(r"(\d+(?:\.\d+)?)", s)
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    return None


def _parse_subpiles(s: str) -> tuple[int, float] | None:
    m = re.search(r"(\d+)\s*개\s*[×xX]\s*(\d+(?:\.\d+)?)\s*t", _cell_str(s), re.I)
    if m:
        return int(m.group(1)), float(m.group(2))
    return None


def _parse_pallet_spec(s: str) -> tuple[float, int] | None:
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*t\s*\(\s*(\d+)\s*블록",
        _cell_str(s),
        re.I,
    )
    if m:
        return float(m.group(1)), int(m.group(2))
    return None


def _parse_minutes_token(s: str) -> float | None:
    s = _cell_str(s)
    m = re.search(r"(\d+(?:\.\d+)?)\s*분", s)
    if m:
        return float(m.group(1))
    m2 = re.search(r"(\d+(?:\.\d+)?)", s)
    if m2 and "분" in s:
        return float(m2.group(1))
    return None


def _parse_t_per_min_load(s: str) -> float | None:
    """'0.6분/t → 약 12분' 등에서 마지막 분 단위 숫자 우선."""
    s = _cell_str(s)
    for m in re.finditer(r"약\s*(\d+(?:\.\d+)?)\s*분", s):
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*분\s*/\s*t", s)
    if m:
        return float(m.group(1))
    return None


def _parse_ratio_percent(s: str) -> float | None:
    """'20% : 80%' → 0.2."""
    s = _cell_str(s)
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
    if m:
        return float(m.group(1)) / 100.0
    return None


def _parse_t_min_pair(s: str) -> tuple[float, float] | None:
    """'1.0t / 3.1분' 형태."""
    s = _cell_str(s)
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*t\s*/\s*(\d+(?:\.\d+)?)\s*분",
        s,
        re.I,
    )
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def _parse_int_prefix(s: str) -> int | None:
    s = _cell_str(s)
    m = re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else None


def load_simulation_config_from_excel(
    path: str | Path | None = None,
    *,
    project_root: Path | None = None,
) -> SimulationConfig:
    p = Path(path) if path is not None else default_excel_path(project_root)
    df = pd.read_excel(p, sheet_name="설비·공정 확인", header=None)

    header_row = None
    for i in range(min(15, len(df))):
        row = df.iloc[i].tolist()
        if any(_cell_str(c) == "시뮬 현재값" for c in row):
            header_row = i
            break
    if header_row is None:
        raise ValueError("시뮬 현재값 열을 찾지 못했습니다.")

    by_no: dict[int, object] = {}
    for j in range(header_row + 1, len(df)):
        row = df.iloc[j].tolist()
        if len(row) < 5:
            continue
        raw_no = row[0]
        if raw_no is None or (isinstance(raw_no, float) and pd.isna(raw_no)):
            continue
        try:
            no = int(float(raw_no))
        except (TypeError, ValueError):
            continue
        by_no[no] = row[4]

    def num(no: int, default: float) -> float:
        v = by_no.get(no)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = _cell_str(v)
        m = re.match(r"^(\d+(?:\.\d+)?)", s)
        return float(m.group(1)) if m else default

    def raw(no: int) -> object | None:
        v = by_no.get(no)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return v

    # --- No.1 입고 시간대
    arrival_start = 9 * 60
    arrival_end = 18 * 60
    r1 = raw(1)
    if r1 is not None:
        tr = _parse_time_range(_cell_str(r1))
        if tr:
            arrival_start, arrival_end = tr

    morning_share = 0.80
    morning_cutoff = 12 * 60

    # --- No.3~10 입고·하역
    trucks_per_day = int(num(3, 10))
    truck_load_ton = num(4, 20.0)
    weighbridges = int(num(6, 1))
    wpair = _parse_slash_pair(_cell_str(raw(7) or ""))
    weigh_in = wpair[0] if wpair else 5.0
    weigh_out = wpair[1] if wpair else 5.0
    unloading_bays = int(num(8, 2))
    unload_min = num(9, 20.0)

    # --- No.11~21 선별·압착
    sorters = int(num(11, 2))
    sort_min = num(12, 30.0)
    sp = _parse_subpiles(_cell_str(raw(13) or ""))
    subpiles_per_truck = sp[0] if sp else 8
    subpile_ton = sp[1] if sp else 2.5
    presses = int(num(14, 1))
    block_ton = num(15, 0.5)
    forklift_min = num(16, 5.0)
    press_block = num(17, 1.5)
    pallet_load_min = num(18, 3.0)
    ps = _parse_pallet_spec(_cell_str(raw(20) or ""))
    pallet_ton = ps[0] if ps else subpile_ton
    blocks_per_subpile = ps[1] if ps else 5
    pallet_buffer_cap = int(num(21, 160))

    # --- No.22~26 장입·용해 (설비)
    furnace_count = int(num(22, 2))
    batch_ton = num(23, 80.0)
    elevator_count = int(num(25, 1))
    epair = _parse_slash_pair(_cell_str(raw(26) or ""))
    elevator_pallets = int(epair[0]) if epair else 2
    elevator_cycle = epair[1] if epair else 5.0

    # --- 용해 단계: 8×60 + 산화 60 + 환원 240 = 780 (엑셀 행 28~40)
    charge_rows = [n for n in range(28, 36) if n in by_no]
    per_charge = 60.0
    if charge_rows:
        first = _cell_str(raw(charge_rows[0]))
        m = re.search(r"=\s*(\d+)\s*분", first)
        if m:
            per_charge = float(m.group(1))
    melt_core = float(len(charge_rows)) * per_charge
    ox = _parse_minutes_token(_cell_str(raw(37) or "")) or 60.0
    red = _parse_minutes_token(_cell_str(raw(38) or "")) or 240.0
    melting_min = melt_core + ox + red
    if melting_min <= 0:
        melting_min = 780.0

    setup_min = 120.0

    holding_setup = num(39, 60.0)

    # --- No.40~45 주조·버퍼
    flake_ratio = _parse_ratio_percent(_cell_str(raw(40) or "")) or 0.20
    fq = _parse_t_min_pair(_cell_str(raw(41) or ""))
    flake_unit_ton = fq[0] if fq else 1.0
    flake_min_per_unit = fq[1] if fq else 3.1
    sq = _parse_t_min_pair(_cell_str(raw(42) or ""))
    scr_unit_ton = sq[0] if sq else 4.0
    scr_min_per_unit = sq[1] if sq else 12.5

    flake_buffer_cap = _parse_int_prefix(_cell_str(raw(44) or "")) or 100
    scr_buffer_cap = _parse_int_prefix(_cell_str(raw(45) or "")) or 75

    # --- No.46~49 출하
    out_truck_cap = num(46, 20.0)
    load_min = _parse_t_per_min_load(_cell_str(raw(47) or "")) or 12.0
    truck_interval = num(48, 60.0)
    max_wait = num(49, 240.0)

    return SimulationConfig(
        sim_days=7,
        random_seed=42,
        inbound=InboundConfig(
            trucks_per_day=trucks_per_day,
            truck_load_ton=truck_load_ton,
            arrival_start_min=int(arrival_start),
            arrival_end_min=int(arrival_end),
            morning_cutoff_min=int(morning_cutoff),
            morning_share=morning_share,
            weigh_in_min=weigh_in,
            weigh_out_min=weigh_out,
            unload_min=unload_min,
            unloading_bays=unloading_bays,
            weighbridges=weighbridges,
        ),
        sorting=SortingConfig(
            sort_min_per_truck=sort_min,
            subpiles_per_truck=subpiles_per_truck,
            subpile_ton=subpile_ton,
            blocks_per_subpile=blocks_per_subpile,
            block_ton=block_ton,
            forklift_min_per_block=forklift_min,
            press_min_per_block=press_block,
            pallet_load_min_per_block=pallet_load_min,
            sorters=sorters,
            presses=presses,
            pallet_buffer_cap=pallet_buffer_cap,
        ),
        melting=MeltingConfig(
            batch_ton=batch_ton,
            pallet_ton=pallet_ton,
            elevator_pallets_per_trip=elevator_pallets,
            elevator_cycle_min=elevator_cycle,
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
            holding_setup_min=holding_setup,
            flake_buffer_cap=flake_buffer_cap,
            scr_buffer_cap=scr_buffer_cap,
        ),
        outbound=OutboundConfig(
            truck_interval_min=truck_interval,
            truck_capacity_ton=out_truck_cap,
            flake_truck_prob=flake_ratio,
            weigh_in_min=weigh_in,
            weigh_out_min=weigh_out,
            load_min=load_min,
            max_wait_min=max_wait,
        ),
    )
