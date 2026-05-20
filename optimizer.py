"""CP-SAT 기반 반사로 배치 스케줄 최적화.

SimPy 시뮬레이션의 FIFO 정책과 CP-SAT 이론 최적 makespan을 비교한다.
반사로 배치 일정만 다루며, 전체 공정을 대체하지 않는다.
"""

from __future__ import annotations

from config import SimulationConfig
from metrics import Metrics


def estimate_batch_duration(cfg: SimulationConfig) -> float:
    """단일 배치의 이론 처리 시간 (분) 추정.

    엘리베이터 왕복 + 사전 준비 + 용해·정련 + 홀딩 + 주조(두 라인 중 긴 쪽).
    """
    trips = cfg.melting.pallets_per_batch // cfg.melting.elevator_pallets_per_trip
    elevator_min = trips * cfg.melting.elevator_cycle_min

    flake_ton = cfg.melting.batch_ton * cfg.casting.flake_ratio
    scr_ton = cfg.melting.batch_ton * (1 - cfg.casting.flake_ratio)
    flake_cast = (flake_ton / cfg.casting.flake_unit_ton) * cfg.casting.flake_min_per_unit
    scr_cast = (scr_ton / cfg.casting.scr_unit_ton) * cfg.casting.scr_min_per_unit

    return (
        elevator_min
        + cfg.melting.setup_min
        + cfg.melting.melting_min
        + cfg.casting.holding_setup_min
        + max(flake_cast, scr_cast)
    )


def extract_simpy_schedule(metrics: Metrics) -> list[dict]:
    """SimPy 이벤트 로그에서 배치별 시작·완료·반사로 ID를 추출한다."""
    starts: dict[int, dict] = {}
    schedule: list[dict] = []

    for ev in metrics.events:
        if ev.kind == "batch_start":
            bid = ev.detail.get("batch_id", 0)
            starts[bid] = {
                "batch_id": bid,
                "furnace_id": ev.detail.get("furnace_id", 0),
                "start_min": ev.time_min,
                "release_min": ev.time_min,
            }
        elif ev.kind == "batch_complete":
            bid = ev.detail.get("batch_id", 0)
            if bid in starts:
                row = dict(starts[bid])
                row["end_min"] = ev.time_min
                row["duration_min"] = ev.time_min - row["start_min"]
                schedule.append(row)

    return sorted(schedule, key=lambda x: x["start_min"])


def solve_furnace_schedule(
    batch_releases: list[float],
    batch_duration_min: float,
    furnace_count: int,
    timeout_s: float = 5.0,
) -> tuple[float | None, list[dict]]:
    """반사로 배치 NoOverlap 스케줄을 CP-SAT로 풀어 최적 makespan 과 스케줄을 반환한다.

    Args:
        batch_releases: 각 배치가 시작 가능한 최소 시각 (분). SimPy 의 batch_start 시각.
        batch_duration_min: 배치 처리 시간 (분). 모든 배치에 동일 적용.
        furnace_count: 반사로 대수.
        timeout_s: CP-SAT 최대 탐색 시간.

    Returns:
        (optimal_makespan_min, schedule) — 해가 없으면 (None, []).
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None, []

    if not batch_releases:
        return None, []

    # CP-SAT 는 정수 변수만 다루므로 0.1분 정밀도로 스케일업
    SCALE = 10
    dur = int(batch_duration_min * SCALE)
    releases = [int(r * SCALE) for r in batch_releases]
    n = len(batch_releases)
    horizon = max(releases) + n * dur * 2

    model = cp_model.CpModel()
    starts, ends, assigned = [], [], []
    intervals_per_furnace: list[list] = [[] for _ in range(furnace_count)]

    for i in range(n):
        s = model.new_int_var(releases[i], horizon, f"s{i}")
        e = model.new_int_var(releases[i] + dur, horizon + dur, f"e{i}")
        model.add(e == s + dur)
        starts.append(s)
        ends.append(e)

        av = [model.new_bool_var(f"a{i}_{f}") for f in range(furnace_count)]
        assigned.append(av)
        model.add_exactly_one(av)

        for f in range(furnace_count):
            iv = model.new_optional_interval_var(s, dur, e, av[f], f"iv{i}_{f}")
            intervals_per_furnace[f].append(iv)

    for f in range(furnace_count):
        model.add_no_overlap(intervals_per_furnace[f])

    makespan_var = model.new_int_var(0, horizon + dur, "makespan")
    model.add_max_equality(makespan_var, ends)
    model.minimize(makespan_var)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_s
    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, []

    opt_makespan = solver.value(makespan_var) / SCALE
    schedule = []
    for i in range(n):
        f_id = next(f for f in range(furnace_count) if solver.value(assigned[i][f]))
        schedule.append(
            {
                "batch_id": i,
                "furnace_id": f_id,
                "start_min": solver.value(starts[i]) / SCALE,
                "end_min": solver.value(ends[i]) / SCALE,
                "release_min": batch_releases[i],
            }
        )
    return opt_makespan, sorted(schedule, key=lambda x: x["start_min"])


def run_optimizer(metrics: Metrics, cfg: SimulationConfig) -> dict:
    """SimPy 결과를 받아 CP-SAT 비교 분석 결과를 돌려준다."""
    simpy_schedule = extract_simpy_schedule(metrics)

    if not simpy_schedule:
        return {"available": False, "reason": "완료된 배치가 없습니다."}

    batch_duration = estimate_batch_duration(cfg)
    releases = [row["start_min"] for row in simpy_schedule]

    opt_makespan, cpsat_schedule = solve_furnace_schedule(
        releases, batch_duration, cfg.melting.furnace_count
    )

    # SimPy makespan: 첫 배치 시작 ~ 마지막 배치 완료
    simpy_start = min(r["start_min"] for r in simpy_schedule)
    simpy_end = max(r["end_min"] for r in simpy_schedule)
    simpy_makespan = simpy_end - simpy_start

    if opt_makespan is None:
        return {
            "available": False,
            "reason": "CP-SAT 풀이 실패 (제한 시간 내 해 없음).",
            "simpy_schedule": simpy_schedule,
        }

    # CP-SAT makespan: 첫 릴리스 기준 상대 시간
    cpsat_relative = opt_makespan - simpy_start

    saving_min = simpy_makespan - cpsat_relative
    efficiency_pct = (cpsat_relative / simpy_makespan * 100) if simpy_makespan > 0 else 100.0

    return {
        "available": True,
        "batch_duration_min": round(batch_duration, 1),
        "batch_count": len(simpy_schedule),
        "simpy_makespan_min": round(simpy_makespan, 1),
        "cpsat_makespan_min": round(cpsat_relative, 1),
        "saving_min": round(saving_min, 1),
        "efficiency_pct": round(efficiency_pct, 1),
        "simpy_schedule": simpy_schedule,
        "cpsat_schedule": cpsat_schedule,
        "reference_min": simpy_start,
    }
