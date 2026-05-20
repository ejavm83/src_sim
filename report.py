"""KPI 집계와 규칙 기반 병목·인사이트 분석."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import SimulationConfig
from metrics import Metrics


RESOURCE_LABELS: dict[str, str] = {
    "weighbridge": "계근대",
    "unloading_bay": "하역 베이",
    "sorter": "선별기",
    "press": "압착기",
    "elevator": "엘리베이터",
    "furnace": "반사로",
    "flake_line": "큐프레이크 라인",
    "scr_line": "SCR 라인",
}


@dataclass
class Analysis:
    summary: dict[str, Any] = field(default_factory=dict)
    utilization: dict[str, float] = field(default_factory=dict)
    bottleneck: str = ""
    insights: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    daily_production: dict[int, dict[str, float]] = field(default_factory=dict)


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def analyze(metrics: Metrics, cfg: SimulationConfig) -> Analysis:
    horizon = cfg.sim_horizon_min
    utilization: dict[str, float] = {}
    for name, busy in metrics.resource_busy_time.items():
        cap = metrics.resource_capacity.get(name, 1)
        utilization[name] = min(1.0, busy / max(1.0, cap * horizon))

    bottleneck = max(utilization, key=utilization.get) if utilization else ""

    total_ton = metrics.flake_produced_ton + metrics.scr_produced_ton
    summary = {
        "inbound_trucks": metrics.inbound_truck_count,
        "outbound_trucks": metrics.outbound_truck_count,
        "batches_completed": metrics.batches_completed,
        "flake_ton": round(metrics.flake_produced_ton, 2),
        "scr_ton": round(metrics.scr_produced_ton, 2),
        "total_ton": round(total_ton, 2),
        "avg_inbound_min": round(_avg(metrics.inbound_truck_durations), 1),
        "avg_outbound_min": round(_avg(metrics.outbound_truck_durations), 1),
        "avg_batch_min": round(_avg(metrics.batch_durations), 1),
        "aborted_outbound": metrics.aborted_outbound,
        "daily_avg_ton": round(total_ton / max(1, cfg.sim_days), 2),
    }

    insights: list[str] = []
    recommendations: list[str] = []
    for name, util in sorted(utilization.items(), key=lambda x: -x[1]):
        label = RESOURCE_LABELS.get(name, name)
        pct = util * 100
        if util >= 0.90:
            insights.append(f"{label} 가동률 {pct:.1f}% — 사실상 풀가동(병목).")
            recommendations.append(f"{label} 증설 또는 사이클 타임 단축을 검토하세요.")
        elif util >= 0.70:
            insights.append(f"{label} 가동률 {pct:.1f}% — 고부하 구간.")
        elif util <= 0.10 and name in {"sorter", "press", "elevator"}:
            insights.append(f"{label} 가동률 {pct:.1f}% — 유휴, 상위 단계가 흐름을 막고 있을 수 있음.")

    if metrics.aborted_outbound > 0:
        insights.append(
            f"야적 재고 부족으로 출하 트럭 {metrics.aborted_outbound}회 abort — "
            "주조 산출 vs 출하 빈도 균형을 점검하세요."
        )
        recommendations.append("출하 간격을 늘리거나 주조 비율·반사로 가동을 늘려 재고 안정화.")

    if metrics.batches_completed == 0:
        insights.append("완료 배치가 0건 — 시뮬 기간이 1배치 사이클(약 18시간) 미만이거나 입고가 부족합니다.")

    return Analysis(
        summary=summary,
        utilization=utilization,
        bottleneck=bottleneck,
        insights=insights,
        recommendations=recommendations,
        daily_production=dict(metrics.daily_production),
    )


KPI_HELP: dict[str, str] = {
    "inbound_trucks": "1차 계근을 통과해 도착한 입고 트럭 수. 입고 도착 이벤트 카운트.",
    "outbound_trucks": "완제품을 싣고 출차한 트럭 수 (abort 제외). 출차 이벤트 카운트.",
    "batches_completed": "엘리베이터·용해·주조까지 완전히 끝난 반사로 배치 횟수. 1배치 = 80 t.",
    "flake_ton": "큐프레이크 라인 누적 산출 톤 (단위 1 t / 사이클 3.1분).",
    "scr_ton": "SCR 라인 누적 산출 톤 (코일 4 t / 사이클 12.5분).",
    "total_ton": "큐프레이크 + SCR 톤 합계.",
    "daily_avg_ton": "총 생산 ÷ 시뮬 일수의 단순 평균 (워밍업 미보정).",
    "avg_inbound_min": "입고 트럭당 (출차 - 도착) 시간 평균. 계근 + 하역 + 계근 + 대기 포함.",
    "avg_outbound_min": "출하 트럭 도착~출차 평균. 상차 대기·계근 포함.",
    "avg_batch_min": "엘리베이터 + 셋업 + 용해 + 홀딩 + 주조 종료까지 걸린 분 평균.",
    "aborted_outbound": "최대 대기 시간(기본 240분) 안에 야적 재고를 못 채워 abort 된 출하 트럭 수.",
}


def kpi_breakdown(metrics: Metrics, cfg: SimulationConfig) -> list[dict[str, Any]]:
    """각 KPI의 정의·산출 공식·원 데이터를 행 단위로 돌려준다."""

    def _avg_str(xs: list[float]) -> str:
        return f"{_avg(xs):.1f} 분 (표본 {len(xs)}건)" if xs else "표본 없음"

    total_ton = metrics.flake_produced_ton + metrics.scr_produced_ton
    flake_unit_ton = cfg.casting.flake_unit_ton
    scr_unit_ton = cfg.casting.scr_unit_ton
    flake_units = int(round(metrics.flake_produced_ton / flake_unit_ton)) if flake_unit_ton else 0
    scr_units = int(round(metrics.scr_produced_ton / scr_unit_ton)) if scr_unit_ton else 0
    expected_inbound = cfg.inbound.trucks_per_day * cfg.sim_days
    trips_per_batch = cfg.melting.pallets_per_batch // cfg.melting.elevator_pallets_per_trip
    elev_min = trips_per_batch * cfg.melting.elevator_cycle_min
    cast_min_est = (
        cfg.casting.holding_setup_min
        + (cfg.melting.batch_ton / scr_unit_ton) * cfg.casting.scr_min_per_unit
    )
    batch_cycle_est = (
        elev_min + cfg.melting.setup_min + cfg.melting.melting_min + cast_min_est
    )

    return [
        {
            "지표": "입고 트럭 (대)",
            "값": f"{metrics.inbound_truck_count} 대",
            "정의": "시뮬레이션 기간 동안 도착·처리된 입고 트럭 수.",
            "산출 공식": "입고 도착(`inbound_arrive`) 이벤트 카운트.",
            "원 데이터": (
                f"기대치 = 일 트럭 수 {cfg.inbound.trucks_per_day} × 시뮬 일수 {cfg.sim_days}"
                f" = {expected_inbound}대 / 실제 처리 {metrics.inbound_truck_count}대"
            ),
        },
        {
            "지표": "완료 배치 (회)",
            "값": f"{metrics.batches_completed} 회",
            "정의": "반사로 배치가 주조 종료까지 완료된 횟수. 1배치 = 파레트 32개 = 80 t.",
            "산출 공식": "`batch_complete` 이벤트 카운트.",
            "원 데이터": (
                f"이론상 배치 처리량 = {metrics.batches_completed}회 × {cfg.melting.batch_ton:.0f} t"
                f" = {metrics.batches_completed * cfg.melting.batch_ton:.0f} t"
            ),
        },
        {
            "지표": "총 생산 (t)",
            "값": f"{total_ton:.2f} t",
            "정의": "주조 단계에서 누적 산출된 큐프레이크와 SCR 톤 합계.",
            "산출 공식": "flake_produced_ton + scr_produced_ton",
            "원 데이터": (
                f"큐프레이크 {flake_units}단위 × {flake_unit_ton:.1f} t = {metrics.flake_produced_ton:.1f} t · "
                f"SCR {scr_units}코일 × {scr_unit_ton:.1f} t = {metrics.scr_produced_ton:.1f} t"
            ),
        },
        {
            "지표": "큐프레이크 생산 (t)",
            "값": f"{metrics.flake_produced_ton:.2f} t",
            "정의": "큐프레이크 라인이 산출한 누적 톤.",
            "산출 공식": "단위 산출 시마다 1 t 누적.",
            "원 데이터": (
                f"{flake_units}단위 × {flake_unit_ton:.1f} t / 단위 사이클 {cfg.casting.flake_min_per_unit}분"
            ),
        },
        {
            "지표": "SCR 생산 (t)",
            "값": f"{metrics.scr_produced_ton:.2f} t",
            "정의": "SCR 라인이 산출한 누적 톤.",
            "산출 공식": "코일 산출 시마다 4 t 누적.",
            "원 데이터": (
                f"{scr_units}코일 × {scr_unit_ton:.1f} t / 단위 사이클 {cfg.casting.scr_min_per_unit}분"
            ),
        },
        {
            "지표": "출하 트럭 (대)",
            "값": f"{metrics.outbound_truck_count} 대",
            "정의": "야적장에서 완제품을 싣고 출차한 트럭 수 (abort 제외).",
            "산출 공식": "`outbound_leave` 이벤트 카운트.",
            "원 데이터": (
                f"평균 도착 간격 {cfg.outbound.truck_interval_min:.0f}분 (지수분포). "
                f"abort {metrics.aborted_outbound}건은 별도 집계."
            ),
        },
        {
            "지표": "일평균 생산 (t/일)",
            "값": f"{total_ton / max(1, cfg.sim_days):.2f} t/일",
            "정의": "총 생산을 시뮬 일수로 나눈 단순 평균 (워밍업 미보정).",
            "산출 공식": "총 생산 ÷ 시뮬 일수",
            "원 데이터": f"{total_ton:.1f} t ÷ {cfg.sim_days}일",
        },
        {
            "지표": "평균 입고 체류 (분)",
            "값": _avg_str(metrics.inbound_truck_durations),
            "정의": "입고 트럭당 (출차 시각 - 도착 시각) 산술 평균. 계근 + 하역 + 계근 + 대기 합산.",
            "산출 공식": "mean(inbound_truck_durations)",
            "원 데이터": (
                f"이론 최소 = 계근 {cfg.inbound.weigh_in_min}분 + 하역 {cfg.inbound.unload_min}분"
                f" + 계근 {cfg.inbound.weigh_out_min}분 = "
                f"{cfg.inbound.weigh_in_min + cfg.inbound.unload_min + cfg.inbound.weigh_out_min:.0f}분"
            ),
        },
        {
            "지표": "평균 출하 체류 (분)",
            "값": _avg_str(metrics.outbound_truck_durations),
            "정의": "출하 트럭 도착부터 출차까지의 분 평균 (상차 대기 + 계근 포함).",
            "산출 공식": "mean(outbound_truck_durations)",
            "원 데이터": (
                f"이론 최소 = 계근 {cfg.outbound.weigh_in_min}분 + 상차 {cfg.outbound.load_min}분"
                f" + 계근 {cfg.outbound.weigh_out_min}분 = "
                f"{cfg.outbound.weigh_in_min + cfg.outbound.load_min + cfg.outbound.weigh_out_min:.0f}분"
            ),
        },
        {
            "지표": "평균 배치 사이클 (분)",
            "값": _avg_str(metrics.batch_durations),
            "정의": "엘리베이터 + 셋업 + 용해 + 홀딩 + 주조 종료까지 걸린 분 평균.",
            "산출 공식": "mean(batch_durations) — 배치 시작 시각 ~ 완료 시각.",
            "원 데이터": (
                f"엘리베이터 {trips_per_batch}회 × {cfg.melting.elevator_cycle_min}분 = {elev_min:.0f}분 + "
                f"셋업 {cfg.melting.setup_min:.0f}분 + 용해 {cfg.melting.melting_min:.0f}분 + "
                f"홀딩 {cfg.casting.holding_setup_min:.0f}분 + 주조 ≈ "
                f"총 ≈ {batch_cycle_est:.0f}분"
            ),
        },
        {
            "지표": "출하 abort (회)",
            "값": f"{metrics.aborted_outbound} 회",
            "정의": "최대 대기 시간 안에 야적 재고를 채우지 못해 빈 트럭으로 돌려보낸 횟수.",
            "산출 공식": "`outbound_abort` 이벤트 카운트.",
            "원 데이터": (
                f"최대 대기 = {cfg.outbound.max_wait_min:.0f}분. "
                f"전체 출하 시도 {metrics.outbound_truck_count + metrics.aborted_outbound}대 중 "
                f"{metrics.aborted_outbound}대가 abort."
            ),
        },
    ]


def result_narrative(
    metrics: Metrics, cfg: SimulationConfig, analysis: Analysis
) -> list[dict[str, str]]:
    """결과를 5단계 흐름 기준 narrative 로 분해.

    각 단락은 {"단계": ..., "본문": ..., "톤": "..."} 구조.
    """
    paragraphs: list[dict[str, str]] = []
    util = analysis.utilization
    summary = analysis.summary

    # 1. 입고/하역
    expected = cfg.inbound.trucks_per_day * cfg.sim_days
    actual = metrics.inbound_truck_count
    inbound_ton = actual * cfg.inbound.truck_load_ton
    theory_min = (
        cfg.inbound.weigh_in_min + cfg.inbound.unload_min + cfg.inbound.weigh_out_min
    )
    avg_in = summary.get("avg_inbound_min", 0)
    if expected and actual >= expected * 0.99:
        text = (
            f"예정된 **{expected}대 ({inbound_ton:.0f} t)** 입고 트럭이 모두 도착·처리되었습니다. "
            f"평균 체류 {avg_in:.0f}분은 이론 최소({theory_min:.0f}분) 대비 "
            f"**{avg_in / theory_min if theory_min else 0:.1f}배** — 계근·하역 대기를 포함한 값입니다. "
            "이 단계가 가동률 낮으면 보통 상위(트럭 도착량)가 결정합니다."
        )
    else:
        ratio = actual / expected * 100 if expected else 0
        text = (
            f"예정 {expected}대 중 **{actual}대 ({ratio:.0f}%)** 만 처리되었습니다. "
            "사이클 마감 시각에 입고 트럭이 잘려나갔거나, 1차 계근에서 대기가 누적되었을 수 있습니다."
        )
    paragraphs.append({"단계": "① 입고/하역", "본문": text})

    # 2. 선별/압착
    press_util = util.get("press", 0) * 100
    sorter_util = util.get("sorter", 0) * 100
    pallets_in = sum(
        1 for e in metrics.events if e.kind == "batch_start"
    ) * cfg.melting.pallets_per_batch
    if press_util >= 90:
        diag = (
            "**압착기가 풀가동** 상태입니다. 트럭당 8 sub-pile, 파레트당 약 47.5분 사이클로 "
            "들어오는 스크랩을 처리하는 속도가 시스템 전체의 속도 한계가 됩니다. "
            "압착기 증설이 처리량 향상에 가장 직접적입니다."
        )
    elif press_util >= 70:
        diag = (
            "압착기가 고부하지만 약간 여유가 있습니다. 입고가 더 들어오면 곧 풀가동에 도달할 수 있습니다."
        )
    else:
        diag = (
            "압착기에 여유가 있으므로 처리량은 **상위(입고량) 또는 하위(반사로) 단계**가 결정합니다."
        )
    text = (
        f"선별기 가동률 {sorter_util:.0f}% · 압착기 가동률 **{press_util:.0f}%**. "
        f"용해 단계로 약 **{pallets_in}개** 파레트가 공급되었습니다. {diag}"
    )
    paragraphs.append({"단계": "② 선별/압착", "본문": text})

    # 3. 장입/용해
    furnace_util = util.get("furnace", 0) * 100
    batches_done = metrics.batches_completed
    avg_cycle = summary.get("avg_batch_min", 0)
    trips = cfg.melting.pallets_per_batch // cfg.melting.elevator_pallets_per_trip
    elev_min = trips * cfg.melting.elevator_cycle_min
    theory_cycle = (
        elev_min
        + cfg.melting.setup_min
        + cfg.melting.melting_min
        + cfg.casting.holding_setup_min
    )
    cycle_ratio = (avg_cycle / theory_cycle) if theory_cycle else 1.0
    if furnace_util >= 80:
        diag = "**반사로가 시스템의 속도 한계 (병목)** 입니다. 반사로 증설 또는 용해 시간 단축이 효과적입니다."
    elif batches_done > 0:
        diag = (
            "반사로에 여유가 있습니다. 배치 시작이 자주 끊긴다면 "
            "**압착(상류) 또는 야적장 적체(하류)** 가 흐름을 막고 있을 가능성이 큽니다."
        )
    else:
        diag = "**완료된 배치가 없습니다.** 시뮬 기간이 1배치 사이클(약 18~22시간) 미만이거나 파레트 공급이 부족."
    text = (
        f"반사로 {cfg.melting.furnace_count}기로 총 **{batches_done}배치** 완료, "
        f"평균 사이클 **{avg_cycle:.0f}분** (이론 골격 {theory_cycle:.0f}분의 {cycle_ratio:.1f}배). "
        f"가동률 **{furnace_util:.0f}%**. {diag} "
        f"용해 단계는 한 배치당 {cfg.melting.melting_min:.0f}분의 통합 용해·정련 구간이 지배합니다."
    )
    paragraphs.append({"단계": "③ 장입/용해", "본문": text})

    # 4. 주조
    flake_util = util.get("flake_line", 0) * 100
    scr_util = util.get("scr_line", 0) * 100
    flake_ton = metrics.flake_produced_ton
    scr_ton = metrics.scr_produced_ton
    ratio = cfg.casting.flake_ratio
    text = (
        f"하이브리드 주조 결과: 큐프레이크 **{flake_ton:.0f} t** ({flake_util:.0f}% 가동) + "
        f"SCR **{scr_ton:.0f} t** ({scr_util:.0f}% 가동). "
        f"배치당 비율 {ratio:.0%}:{1-ratio:.0%}. "
        f"SCR 라인은 코일당 {cfg.casting.scr_min_per_unit}분으로 대개 주조 시간을 지배합니다 — "
        "큐프레이크 비율을 키우면 주조 구간이 짧아져 배치 사이클이 단축됩니다."
    )
    paragraphs.append({"단계": "④ 하이브리드 주조", "본문": text})

    # 5. 출하
    out_n = metrics.outbound_truck_count
    aborted = metrics.aborted_outbound
    total_try = out_n + aborted
    abort_pct = aborted / total_try * 100 if total_try else 0
    if abort_pct >= 50:
        diag = (
            f"**abort 비율이 매우 높습니다 ({abort_pct:.0f}%)** — 야적 재고가 자주 비어 트럭이 빈 차로 돌아갑니다. "
            "출하 평균 간격을 늘려 도착을 줄이거나, 주조 속도/배치 빈도를 높여 재고를 안정화하세요."
        )
    elif abort_pct >= 10:
        diag = (
            f"abort {abort_pct:.0f}% — 야적 재고와 출하 빈도가 약간 어긋남. "
            "도착 간격을 조금 늘리거나 생산 변동성을 점검하세요."
        )
    elif aborted == 0:
        diag = "야적 재고가 충분해 모든 출하 트럭이 정상 상차되었습니다."
    else:
        diag = f"abort {aborted}회({abort_pct:.0f}%) — 미세 변동, 대체로 균형 잡힘."
    text = (
        f"출하 트럭 **{out_n}대** 출차 (abort {aborted}회). "
        f"평균 도착 간격 {cfg.outbound.truck_interval_min:.0f}분(지수분포). {diag}"
    )
    paragraphs.append({"단계": "⑤ 야적/출하", "본문": text})

    return paragraphs


BUFFER_LABELS: dict[str, str] = {
    "pallet_buffer": "파레트 버퍼",
    "flake_buffer": "큐프레이크 야적",
    "scr_buffer": "SCR 야적",
}


def buffer_capacity(cfg: SimulationConfig, name: str) -> int:
    if name == "pallet_buffer":
        return cfg.sorting.pallet_buffer_cap
    if name == "flake_buffer":
        return cfg.casting.flake_buffer_cap
    if name == "scr_buffer":
        return cfg.casting.scr_buffer_cap
    return 1


def buffer_utilization_summary(
    metrics: Metrics, cfg: SimulationConfig
) -> list[dict[str, Any]]:
    """버퍼별 평균·최대 점유율과 포화(≥95%) 구간 비율."""
    horizon = max(1.0, cfg.sim_horizon_min)
    rows: list[dict[str, Any]] = []
    for name, samples in metrics.buffer_samples.items():
        cap = buffer_capacity(cfg, name)
        if not samples:
            rows.append(
                {
                    "버퍼": BUFFER_LABELS.get(name, name),
                    "용량": cap,
                    "평균 점유율 (%)": 0.0,
                    "최대 점유율 (%)": 0.0,
                    "포화 구간 (%)": 0.0,
                }
            )
            continue

        util_pcts: list[float] = []
        saturated_min = 0.0
        for i, (t0, level) in enumerate(samples):
            t1 = samples[i + 1][0] if i + 1 < len(samples) else horizon
            dur = max(0.0, t1 - t0)
            pct = min(100.0, level / max(1, cap) * 100)
            util_pcts.append(pct)
            if pct >= 95.0:
                saturated_min += dur

        rows.append(
            {
                "버퍼": BUFFER_LABELS.get(name, name),
                "용량": cap,
                "평균 점유율 (%)": round(sum(util_pcts) / len(util_pcts), 1),
                "최대 점유율 (%)": round(max(util_pcts), 1),
                "포화 구간 (%)": round(saturated_min / horizon * 100, 1),
            }
        )
    return rows


def utilization_breakdown(metrics: Metrics, cfg: SimulationConfig) -> list[dict[str, Any]]:
    """가동률 산출 근거 (총 사용 시간 ÷ (대수 × 시뮬 총 시간))."""
    horizon = cfg.sim_horizon_min
    rows: list[dict[str, Any]] = []
    for name, busy in sorted(metrics.resource_busy_time.items(), key=lambda x: -x[1]):
        cap = metrics.resource_capacity.get(name, 1)
        denom = cap * horizon
        util = min(1.0, busy / max(1.0, denom))
        rows.append(
            {
                "자원": RESOURCE_LABELS.get(name, name),
                "가동률 (%)": round(util * 100, 2),
                "총 사용 시간 (분)": round(busy, 1),
                "대수": cap,
                "이론 용량 (분)": f"{cap} × {horizon} = {denom:.0f}",
                "산출 공식": f"{busy:.0f} ÷ {denom:.0f}",
            }
        )
    return rows
