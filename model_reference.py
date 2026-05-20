"""공정 설명·파라미터 참조 데이터 (문서 페이지용)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from config import DEFAULT_CONFIG, SimulationConfig


def _fmt_time(minutes: int | float) -> str:
    m = int(minutes)
    return f"{m // 60:02d}:{m % 60:02d}"


@dataclass(frozen=True)
class ParamSpec:
    section: str
    label: str
    unit: str
    description: str
    getter: Callable[[SimulationConfig], Any]
    ui_adjustable: bool = False
    display: Callable[[Any], str] | None = None


def _display(v: Any, spec: ParamSpec) -> str:
    if spec.display is not None:
        return spec.display(v)
    if isinstance(v, float):
        return f"{v:g}" if v == int(v) else f"{v:.4g}"
    return str(v)


PARAM_SPECS: list[ParamSpec] = [
    # 공통
    ParamSpec(
        "공통",
        "시뮬레이션 일수",
        "일",
        "가상 시간 = 일수 × 24시간. KPI·일별 생산 집계 기간.",
        lambda c: c.sim_days,
        ui_adjustable=True,
    ),
    ParamSpec(
        "공통",
        "난수 시드",
        "—",
        "입고 도착·출하 간격 등 확률 과정의 재현성을 위한 시드.",
        lambda c: c.random_seed,
    ),
    ParamSpec(
        "공통",
        "시뮬레이션 총 시간",
        "분",
        "sim_days × 1,440. SimPy 환경 종료 시각.",
        lambda c: c.sim_horizon_min,
    ),
    # ① 입고
    ParamSpec(
        "① 입고 / 하역",
        "일 입고 트럭 수",
        "대/일",
        "각 시뮬레이션 일마다 생성되는 입고 트럭 수.",
        lambda c: c.inbound.trucks_per_day,
        ui_adjustable=True,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "트럭 적재량",
        "t",
        "트럭 1대당 하역되는 스크랩 중량(선별 큐로 전달).",
        lambda c: c.inbound.truck_load_ton,
        ui_adjustable=True,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "도착 시작 시각",
        "시:분",
        "당일 입고 가능 시작(분 단위 내부값을 시각으로 표시).",
        lambda c: c.inbound.arrival_start_min,
        display=_fmt_time,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "도착 종료 시각",
        "시:분",
        "당일 입고 가능 종료.",
        lambda c: c.inbound.arrival_end_min,
        display=_fmt_time,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "오전 구분 시각",
        "시:분",
        "이 시각 이전을 '오전' 구간으로 보고 도착 시간을 샘플링.",
        lambda c: c.inbound.morning_cutoff_min,
        display=_fmt_time,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "오전 도착 비율",
        "%",
        "트럭이 오전 구간에 도착할 확률.",
        lambda c: c.inbound.morning_share,
        display=lambda v: f"{float(v) * 100:.0f}",
    ),
    ParamSpec(
        "① 입고 / 하역",
        "1차 계근 시간",
        "분",
        "계근대 점유 시간(입차 계근).",
        lambda c: c.inbound.weigh_in_min,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "2차 계근 시간",
        "분",
        "하역 후 출차 계근.",
        lambda c: c.inbound.weigh_out_min,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "하역 시간",
        "분",
        "하역 베이 1곳 점유 시간.",
        lambda c: c.inbound.unload_min,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "하역 베이 수",
        "대",
        "동시 하역 가능 베이( SimPy Resource 용량).",
        lambda c: c.inbound.unloading_bays,
    ),
    ParamSpec(
        "① 입고 / 하역",
        "계근대 수",
        "대",
        "입·출고 계근 공유 자원 용량.",
        lambda c: c.inbound.weighbridges,
    ),
    # ② 선별
    ParamSpec(
        "② 선별 / 압착",
        "트럭당 선별 시간",
        "분",
        "선별기 1대가 트럭 1대 분량을 처리하는 시간.",
        lambda c: c.sorting.sort_min_per_truck,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "sub-pile 수 / 트럭",
        "개",
        "트럭 1대를 나누는 소분할 더미 수 → 압착 작업 수.",
        lambda c: c.sorting.subpiles_per_truck,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "sub-pile 중량",
        "t",
        "압착 완료 후 파레트 1개에 해당하는 중량.",
        lambda c: c.sorting.subpile_ton,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "블록 수 / sub-pile",
        "개",
        "sub-pile당 압착 블록 수.",
        lambda c: c.sorting.blocks_per_subpile,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "블록 중량",
        "t",
        "압착 1블록당 중량(모델 내 집계용).",
        lambda c: c.sorting.block_ton,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "지게차 이송 / 블록",
        "분",
        "블록 1개당 이송 시간(압착 사이클에 포함).",
        lambda c: c.sorting.forklift_min_per_block,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "압착 / 블록",
        "분",
        "블록 1개당 압착 시간.",
        lambda c: c.sorting.press_min_per_block,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "파레트 적재 / 블록",
        "분",
        "블록 1개당 파레트 적재 시간.",
        lambda c: c.sorting.pallet_load_min_per_block,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "선별기 대수",
        "대",
        "병렬 선별 자원 용량.",
        lambda c: c.sorting.sorters,
        ui_adjustable=True,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "압착기 대수",
        "대",
        "병렬 압착 자원 용량.",
        lambda c: c.sorting.presses,
        ui_adjustable=True,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "파레트 버퍼 용량",
        "파레트",
        "장입 대기 파레트 저장소 최대 개수.",
        lambda c: c.sorting.pallet_buffer_cap,
        ui_adjustable=True,
    ),
    ParamSpec(
        "② 선별 / 압착",
        "블록 1사이클 합계",
        "분",
        "지게차+압착+적재 시간 합(모델 내부 사용).",
        lambda c: (
            c.sorting.forklift_min_per_block
            + c.sorting.press_min_per_block
            + c.sorting.pallet_load_min_per_block
        ),
    ),
    # ③ 용해
    ParamSpec(
        "③ 장입 / 용해",
        "배치 톤수",
        "t",
        "반사로 1회 처리 목표 용량.",
        lambda c: c.melting.batch_ton,
    ),
    ParamSpec(
        "③ 장입 / 용해",
        "파레트 단위 중량",
        "t",
        "장입 1파레트 중량.",
        lambda c: c.melting.pallet_ton,
    ),
    ParamSpec(
        "③ 장입 / 용해",
        "배치당 파레트 수",
        "개",
        "batch_ton ÷ pallet_ton (정수, 80÷2.5=32).",
        lambda c: c.melting.pallets_per_batch,
    ),
    ParamSpec(
        "③ 장입 / 용해",
        "엘리베이터 1회 적재",
        "파레트",
        "왕복 1회에 올리는 파레트 수.",
        lambda c: c.melting.elevator_pallets_per_trip,
    ),
    ParamSpec(
        "③ 장입 / 용해",
        "엘리베이터 왕복 시간",
        "분",
        "엘리베이터 자원 점유 시간 / 1회.",
        lambda c: c.melting.elevator_cycle_min,
    ),
    ParamSpec(
        "③ 장입 / 용해",
        "배치 사전 준비",
        "분",
        "장입 후 용해 전 셋업.",
        lambda c: c.melting.setup_min,
    ),
    ParamSpec(
        "③ 장입 / 용해",
        "용해·정련 시간",
        "분",
        "반사로 내 용해·정련(약 13시간 = 780분).",
        lambda c: c.melting.melting_min,
        ui_adjustable=True,
    ),
    ParamSpec(
        "③ 장입 / 용해",
        "반사로 대수",
        "기",
        "병렬 반사로 자원 용량.",
        lambda c: c.melting.furnace_count,
        ui_adjustable=True,
    ),
    # ④ 주조
    ParamSpec(
        "④ 하이브리드 주조",
        "큐프레이크 비율",
        "—",
        "배치 톤수 중 큐프레이크 라인으로 가는 비율(나머지는 SCR).",
        lambda c: c.casting.flake_ratio,
        ui_adjustable=True,
        display=lambda v: f"{float(v):.2f} ({float(v)*100:.0f}%)",
    ),
    ParamSpec(
        "④ 하이브리드 주조",
        "큐프레이크 단위",
        "t",
        "큐프레이크 주조 1회 단위 중량.",
        lambda c: c.casting.flake_unit_ton,
    ),
    ParamSpec(
        "④ 하이브리드 주조",
        "큐프레이크 단위 시간",
        "분/단위",
        "단위 1개 주조 소요.",
        lambda c: c.casting.flake_min_per_unit,
    ),
    ParamSpec(
        "④ 하이브리드 주조",
        "SCR 단위",
        "t",
        "SCR 주조 1회 단위 중량.",
        lambda c: c.casting.scr_unit_ton,
    ),
    ParamSpec(
        "④ 하이브리드 주조",
        "SCR 단위 시간",
        "분/단위",
        "단위 1개 주조 소요.",
        lambda c: c.casting.scr_min_per_unit,
    ),
    ParamSpec(
        "④ 하이브리드 주조",
        "홀딩 셋업",
        "분",
        "용해 후 주조 전 홀딩 준비.",
        lambda c: c.casting.holding_setup_min,
    ),
    ParamSpec(
        "④ 하이브리드 주조",
        "큐프레이크 야적 버퍼",
        "단위",
        "출하 대기 큐프레이크 저장 한도.",
        lambda c: c.casting.flake_buffer_cap,
    ),
    ParamSpec(
        "④ 하이브리드 주조",
        "SCR 야적 버퍼",
        "단위",
        "출하 대기 SCR 저장 한도.",
        lambda c: c.casting.scr_buffer_cap,
    ),
    # ⑤ 출하
    ParamSpec(
        "⑤ 출하",
        "출하 트럭 평균 간격",
        "분",
        "지수분포 평균(λ=1/간격)으로 다음 출하 트럭 생성.",
        lambda c: c.outbound.truck_interval_min,
        ui_adjustable=True,
    ),
    ParamSpec(
        "⑤ 출하",
        "출하 트럭 적재",
        "t",
        "1대당 목표 상차 중량.",
        lambda c: c.outbound.truck_capacity_ton,
    ),
    ParamSpec(
        "⑤ 출하",
        "큐프레이크 출하 확률",
        "%",
        "출하 트럭이 큐프레이크 야적을 방문할 확률.",
        lambda c: c.outbound.flake_truck_prob,
        display=lambda v: f"{float(v) * 100:.0f}",
    ),
    ParamSpec(
        "⑤ 출하",
        "출하 1차 계근",
        "분",
        "상차 전 계근.",
        lambda c: c.outbound.weigh_in_min,
    ),
    ParamSpec(
        "⑤ 출하",
        "출하 2차 계근",
        "분",
        "상차 후 계근.",
        lambda c: c.outbound.weigh_out_min,
    ),
    ParamSpec(
        "⑤ 출하",
        "상차 시간",
        "분",
        "야적에서 제품 적재.",
        lambda c: c.outbound.load_min,
    ),
    ParamSpec(
        "⑤ 출하",
        "재고 대기 한도",
        "분",
        "야적 재고가 없을 때 최대 대기 후 abort.",
        lambda c: c.outbound.max_wait_min,
    ),
]


PROCESS_STAGES: list[dict[str, str]] = [
    {
        "단계": "① 입고 / 하역",
        "자재": "스크랩 구리 (트럭)",
        "설비": "계근대, 하역 베이",
        "요약": (
            "09:00–18:00 사이에 일별 고정 대수의 트럭이 도착합니다. "
            "오전(09–12시)에 80%가 몰리도록 균등 분포로 시각을 뽑고, "
            "나머지는 오후 구간에 배치합니다."
        ),
        "모델": (
            "1차 계근 → 하역 베이 점유·하역 → 선별 큐에 트럭 적재량(t) 투입 → 2차 계근. "
            "계근대는 입고·출하가 공유하므로 대기가 발생할 수 있습니다."
        ),
    },
    {
        "단계": "② 선별 / 압착",
        "자재": "트럭 하역분 → sub-pile → 파레트",
        "설비": "선별기, 압착기, 파레트 버퍼",
        "요약": (
            "트럭 1대당 선별 30분 후, 8개 sub-pile(각 2.5 t)로 쪼개 압착 큐에 넣습니다. "
            "sub-pile마다 5블록을 지게차·압착·적재 사이클로 처리해 파레트 1개를 버퍼에 적재합니다."
        ),
        "모델": (
            "선별기·압착기는 각각 Resource로 병렬 처리. "
            "파레트 버퍼가 가득 차면 압착 공정이 블로킹됩니다."
        ),
    },
    {
        "단계": "③ 장입 / 용해",
        "자재": "파레트 32개 = 80 t 배치",
        "설비": "엘리베이터, 반사로",
        "요약": (
            "반사로 워커가 파레트 32개가 모일 때까지 대기한 뒤 배치를 시작합니다. "
            "엘리베이터로 2파레트씩 왕복 장입 후, 셋업·용해·정련(기본 780분)을 수행합니다."
        ),
        "모델": (
            "반사로는 FIFO로 배치를 가져가며, 배치당 처리 시간은 "
            "엘리베이터 왕복 + setup + melting + holding_setup + 주조(병렬)로 구성됩니다."
        ),
    },
    {
        "단계": "④ 하이브리드 주조",
        "자재": "용융 동 (배치 톤수 분할)",
        "설비": "큐프레이크 라인, SCR 라인, 야적 버퍼",
        "요약": (
            "배치 톤수를 flake_ratio(기본 20%)와 SCR(80%)로 나눕니다. "
            "두 라인은 동시에 주조하며, 라인별 단위 중량·단위 시간으로 처리합니다."
        ),
        "모델": (
            "큐프레이크: 1 t 단위 × 3.1분, SCR: 4 t 단위 × 12.5분. "
            "완성품은 각 야적 버퍼에 적재되며 용량 초과 시 블로킹됩니다."
        ),
    },
    {
        "단계": "⑤ 출하",
        "자재": "큐프레이크 / SCR (야적)",
        "설비": "계근대, 상차장",
        "요약": (
            "평균 간격(기본 60분)의 지수분포로 출하 트럭이 생성됩니다. "
            "20% 확률로 큐프레이크, 80% SCR 야적을 방문합니다."
        ),
        "모델": (
            "재고가 없으면 최대 240분 대기 후 abort. "
            "계근 → 야적에서 단위 수만큼 인출 → 상차 → 계근. "
            "트럭 적재 20 t에 맞춰 필요한 단위 수를 계산합니다."
        ),
    },
]


def parameters_dataframe(
    cfg: SimulationConfig | None = None,
    *,
    defaults_only: bool = False,
) -> pd.DataFrame:
    """파라미터 표용 DataFrame."""
    current = cfg or DEFAULT_CONFIG
    default = DEFAULT_CONFIG
    rows: list[dict[str, str]] = []
    for spec in PARAM_SPECS:
        def_val = spec.getter(default)
        cur_val = spec.getter(current)
        rows.append(
            {
                "구분": spec.section,
                "파라미터": spec.label,
                "기본값": _display(def_val, spec),
                "현재값": _display(cur_val, spec) if not defaults_only else _display(def_val, spec),
                "단위": spec.unit,
                "UI 조정": "✓" if spec.ui_adjustable else "—",
                "설명": spec.description,
            }
        )
    return pd.DataFrame(rows)


def adjustable_parameters(cfg: SimulationConfig | None = None) -> pd.DataFrame:
    df = parameters_dataframe(cfg)
    return df[df["UI 조정"] == "✓"].reset_index(drop=True)
