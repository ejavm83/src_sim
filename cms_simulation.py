"""멕시코 CMS 전선공장 SimPy 시뮬레이션.

`data/공정설명260521.md` (SOP v0.3)의 라우팅·설비·제약을 그대로 옮긴 모델이다.

모델링 방침
 - 공유 설비는 하나의 자원 풀로 정의해 라인 간 경합을 발생시킨다 (SOP 7.1).
 - 품종이 바뀐 설비에서만 교체(셋업) 시간이 발생한다 (SOP 6.2).
 - 캘린더는 주 116시간 가동 + 주말 52시간 정지 + 월요일 스타트업이며,
   가공시간은 실효 가동률 92.6%로 나눠 늘린다 (SOP 6.3·7.5).
 - 로트 분할·병합은 SOP 7.3 변환표를 따른다.
 - 수율 100%·설비 고장 없음 — SOP 7.7이 데이터 부재로 그렇게 두라고 명시.
 - 운반(AMR·지게차) 시간은 0 — SOP 7.6이 거리 매트릭스 미확보로 그렇게 두라고 명시.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import simpy

from cms_config import CmsConfig, Equipment, Step, planned_equip_load

ProgressFn = Callable[[float, float], None]

WEEK_MIN = 7 * 24 * 60


# ── 캘린더 ────────────────────────────────────────────────────────────────


class Calendar:
    """주 단위 가동 캘린더. 주 시작(월 00:00)부터 116시간 가동, 이후 52시간 정지."""

    def __init__(self, cfg: CmsConfig) -> None:
        cal = cfg.calendar
        self.uptime_min = WEEK_MIN - cal.weekend_stop_hours * 60
        self.startup_min = cal.monday_startup_hours * 60
        self.availability = max(0.05, min(1.0, cal.availability))

    def is_up(self, t: float) -> bool:
        w = t % WEEK_MIN
        return self.startup_min <= w < self.uptime_min

    def next_up(self, t: float) -> float:
        """`t` 이후 가장 이른 가동 시각."""
        w = t % WEEK_MIN
        base = t - w
        if w < self.startup_min:
            return base + self.startup_min
        if w < self.uptime_min:
            return t
        return base + WEEK_MIN + self.startup_min

    def down_at(self, t: float) -> float:
        """`t` 시점이 속한 가동 구간이 끝나는 시각."""
        return (t - t % WEEK_MIN) + self.uptime_min


def work(env: simpy.Environment, cal: Calendar, minutes: float):
    """가동시간만 소비하며 `minutes`만큼 작업한다. 정지 구간은 건너뛴다.

    실효 가동률을 반영해 소요를 늘린다(92.6% → 소요 ÷ 0.926).
    """
    remaining = minutes / cal.availability
    while remaining > 1e-9:
        if not cal.is_up(env.now):
            yield env.timeout(cal.next_up(env.now) - env.now)
            continue
        chunk = min(remaining, cal.down_at(env.now) - env.now)
        if chunk <= 0:
            yield env.timeout(cal.next_up(env.now + 1) - env.now)
            continue
        yield env.timeout(chunk)
        remaining -= chunk


# ── 설비 풀 ───────────────────────────────────────────────────────────────


class Pool:
    """설비 대수만큼의 개별 유닛을 담은 풀. 유닛마다 마지막 생산 품종을 기억한다.

    대기 순서는 **계획 물량에 비례한 몫**으로 정한다(선착순 아님). 각 라인이
    이 설비에서 이미 쓴 시간을 자기 계획 시간으로 나눈 값이 작은 라인,
    즉 '자기 몫보다 덜 받은' 라인이 먼저 들어간다. 물량이 큰 라인은 몫이
    크므로 여전히 많이 쓰지만, 물량이 작은 라인도 자기 몫만큼은 받는다.
    선착순이면 큰 라인이 낸 로트 뭉치가 줄을 채워 작은 라인이 영영 굶는다.
    """

    def __init__(
        self,
        env: simpy.Environment,
        spec: Equipment,
        plan_min: dict[str, float] | None = None,
    ) -> None:
        self.spec = spec
        self.ids = spec.machine_ids()
        self.res = simpy.PriorityResource(env, capacity=len(self.ids))
        self.free: list[dict[str, Any]] = [
            {"unit": i, "id": mid, "group": None} for i, mid in enumerate(self.ids)
        ]
        self.plan_min = plan_min or {}
        self.served_min: dict[str, float] = defaultdict(float)

    def priority(self, group: str) -> float:
        """작을수록 먼저. '자기 몫 대비 이미 받은 비율'."""
        share = self.plan_min.get(group, 0.0)
        if share <= 0:
            # 계획에 없는 라인(앞단 배치 등)은 덜 쓴 쪽이 먼저 — 굶지 않게만 한다
            return self.served_min[group]
        return self.served_min[group] / share

    def take(self, group: str) -> dict[str, Any]:
        """빈 설비 1대를 고른다. 같은 품종을 마지막에 돌린 설비를 우선 골라
        불필요한 교체(셋업)를 줄인다 — 실제 작업자도 그렇게 배정한다."""
        for i, u in enumerate(self.free):
            if u["group"] == group:
                return self.free.pop(i)
        for i, u in enumerate(self.free):
            if u["group"] is None:
                return self.free.pop(i)
        return self.free.pop(0)

    def give(self, unit: dict[str, Any]) -> None:
        self.free.append(unit)


# ── 지표 ──────────────────────────────────────────────────────────────────


@dataclass
class CmsMetrics:
    horizon_min: float = 0.0
    uptime_min: float = 0.0

    equip_label: dict[str, str] = field(default_factory=dict)
    equip_count: dict[str, int] = field(default_factory=dict)
    equip_tbd: dict[str, bool] = field(default_factory=dict)
    busy_min: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    # 개별 설비(위치·번호) 단위 — SOP 2.6 자원 풀 정의
    machine_ids: dict[str, list[str]] = field(default_factory=dict)
    machine_busy: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    machine_setup: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    machine_lines: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    machine_jobs: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    setup_min: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    wait_min: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    wait_n: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    max_queue: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _queue: dict[str, int] = field(default_factory=lambda: defaultdict(int), repr=False)

    step_busy: dict[tuple[str, str], float] = field(default_factory=lambda: defaultdict(float))

    finished_lots: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    finished_m: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    lead_min: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    daily_m: dict[int, dict[str, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    pallets: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    started_lots: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    wip_samples: list[tuple[float, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    _wip: int = field(default=0, repr=False)
    _next_id: int = field(default=0, repr=False)

    def new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def enqueue(self, key: str) -> None:
        self._queue[key] += 1
        self.max_queue[key] = max(self.max_queue[key], self._queue[key])

    def dequeue(self, key: str, waited: float) -> None:
        self._queue[key] -= 1
        self.wait_min[key] += waited
        self.wait_n[key] += 1

    def wip(self, t: float, delta: int) -> None:
        self._wip += delta
        self.wip_samples.append((t, self._wip))

    # ── 파생 지표 ──
    def utilization(self) -> dict[str, float]:
        """설비별 가동률 = (가공+교체) ÷ (대수 × 가용시간)."""
        out = {}
        for key, count in self.equip_count.items():
            cap = max(1, count) * max(1.0, self.uptime_min)
            out[key] = (self.busy_min[key] + self.setup_min[key]) / cap
        return out

    def avg_wait(self) -> dict[str, float]:
        return {
            k: (self.wait_min[k] / n if (n := self.wait_n[k]) else 0.0)
            for k in self.equip_count
        }


# ── 공정 실행 ─────────────────────────────────────────────────────────────


class Plant:
    def __init__(self, env: simpy.Environment, cfg: CmsConfig, m: CmsMetrics) -> None:
        self.env = env
        self.cfg = cfg
        self.m = m
        self.cal = Calendar(cfg)
        # 공유 설비를 라인별로 얼마씩 나눠 줄지의 기준 — 진단 표와 같은 계산을 쓴다
        plan = planned_equip_load(cfg)
        self.pools = {
            k: Pool(env, spec, plan.get(k)) for k, spec in cfg.equipment.items()
        }
        for k, spec in cfg.equipment.items():
            m.equip_label[k] = spec.label
            m.equip_count[k] = max(1, spec.count)
            m.equip_tbd[k] = spec.tbd_count
            m.machine_ids[k] = spec.machine_ids()

        # Cu19 튜블러 병합 대기열 (SOP 2.5)
        self.cu19_bunched: simpy.Store = simpy.Store(env)
        self.cu19_stranded: simpy.Store = simpy.Store(env)
        self.cu19_toggle = 0
        # 파렛트 완성 카운터 (SOP 7.6)
        self.pallet_count: dict[str, int] = defaultdict(int)


def run_on(plant: Plant, equip: str, group: str, minutes: float, step_label: str = ""):
    """설비 1대를 잡아 교체(필요 시) 후 `minutes`만큼 가공한다.

    설비가 다 차 있으면 여기서 멈춰 기다린다 — 이것이 '설비가 모자라면
    두 라인이 동시에 못 쓴다'는 제약의 실체다. 기다리는 순서는 `Pool.priority`
    (계획 물량에 비례한 몫)로 정한다.
    """
    env, m = plant.env, plant.m
    pool = plant.pools[equip]

    t0 = env.now
    m.enqueue(equip)
    with pool.res.request(priority=pool.priority(group)) as req:
        yield req
        m.dequeue(equip, env.now - t0)

        unit = pool.take(group)
        mid = (equip, unit["id"])
        try:
            if unit["group"] is not None and unit["group"] != group:
                setup = pool.spec.setup_min
                if setup > 0:
                    yield from work(env, plant.cal, setup)
                    eff_setup = setup / plant.cal.availability
                    m.setup_min[equip] += eff_setup
                    m.machine_setup[mid] += eff_setup
                    pool.served_min[group] += eff_setup
            unit["group"] = group

            yield from work(env, plant.cal, minutes)
            eff = minutes / plant.cal.availability
            m.busy_min[equip] += eff
            m.machine_busy[mid] += eff
            m.machine_lines[mid].add(group)
            m.machine_jobs[mid] += 1
            pool.served_min[group] += eff
            if step_label:
                m.step_busy[(equip, step_label)] += eff
        finally:
            pool.give(unit)


def run_steps(plant: Plant, lot: dict[str, Any], steps: list[Step], start_at: int = 0):
    """로트를 `steps[start_at:]`에 통과시킨다. 분할이 나오면 자식 로트를 병렬로 띄운다."""
    env, m = plant.env, plant.m
    group = lot["group"]

    for i, step in enumerate(steps[start_at:], start=start_at):
        if step.split > 1:
            # 분할: 자식 로트 N개가 각자 설비를 잡고 이후 공정을 따라간다
            children = []
            for _ in range(step.split):
                child = dict(lot)
                child["id"] = m.new_id()
                child["len_m"] = step.out_len_m or lot["len_m"] / step.split
                m.wip(env.now, +1)
                children.append(env.process(_run_split_child(plant, child, steps, i)))
            m.wip(env.now, -1)
            yield env.all_of(children)
            return

        yield from run_on(plant, step.equip, group, step.minutes, step.label)
        if step.out_len_m:
            lot["len_m"] = step.out_len_m

    _finish(plant, lot)


def _run_split_child(plant: Plant, lot: dict[str, Any], steps: list[Step], idx: int):
    """분할된 자식 로트: 자기 몫의 분할 단계를 수행한 뒤 나머지 공정을 잇는다."""
    step = steps[idx]
    yield from run_on(plant, step.equip, lot["group"], step.minutes, step.label)
    lot["len_m"] = step.out_len_m or lot["len_m"]
    yield from run_steps(plant, lot, steps, start_at=idx + 1)


def _finish(plant: Plant, lot: dict[str, Any]) -> None:
    env, m, cfg = plant.env, plant.m, plant.cfg
    line = lot["line"]
    m.finished_lots[line] += 1
    m.finished_m[line] += lot["len_m"]
    m.lead_min[line].append(env.now - lot["born"])
    m.daily_m[int(env.now // 1440)][line] += lot["len_m"]
    m.wip(env.now, -1)

    # SOP 7.6 파렛트 완성 조건
    if line.startswith("CU44"):
        per = cfg.pallet.cu44_bobbins_per_pallet
    elif line == "CU19":
        per = cfg.pallet.cu19_bundles_per_pallet
    else:
        per = 0
    if per:
        plant.pallet_count[line] += 1
        if plant.pallet_count[line] >= per:
            plant.pallet_count[line] -= per
            m.pallets[line] += 1


def _spawn(plant: Plant, line: str, group: str, len_m: float, steps: list[Step]):
    m = plant.m
    lot = {
        "id": m.new_id(),
        "line": line,
        "group": group,
        "len_m": len_m,
        "born": plant.env.now,
    }
    m.started_lots[line] += 1
    m.wip(plant.env.now, +1)
    return plant.env.process(run_steps(plant, lot, steps))


# ── 라인별 소스·앞단 공정 ────────────────────────────────────────────────


def cu_inbound(plant: Plant, rod_store: simpy.Store, rng: random.Random):
    """SOP 7.2: Cu 로드 월 13대가 월초에 집중 도착. 1대 = 3.3t 보빈 6개."""
    env, cfg = plant.env, plant.cfg
    inb, cond = cfg.inbound, cfg.conductor
    bobbins_per_truck = int(round(inb.cu_ton_per_truck / cond.taeshin_bobbin_ton))
    months = max(1, int(cfg.sim_days / 30) + 1)

    for mth in range(months):
        base = mth * 30 * 1440
        times = sorted(
            base + rng.uniform(0, inb.cu_arrival_window_days * 1440)
            for _ in range(inb.cu_trucks_per_month)
        )
        for t in times:
            if t < env.now:
                continue
            yield env.timeout(t - env.now)
            for _ in range(bobbins_per_truck):
                yield rod_store.put({"ton": cond.taeshin_bobbin_ton})


def taeshin_worker(plant: Plant, rod_store: simpy.Store, carrier_store: simpy.Store):
    """SOP 2.1 태신선: 3.3t 보빈 1개 → 1t 캐리어 3개, 60분/보빈. Cu44·Cu19 공유."""
    cond = plant.cfg.conductor
    while True:
        yield rod_store.get()
        yield from run_on(plant, "taeshin", "CU", cond.taeshin_min_per_bobbin, "태신선")
        for _ in range(cond.carriers_per_bobbin):
            yield carrier_store.put({"ton": 1.0})


def multi_worker(plant: Plant, carrier_store: simpy.Store, rng: random.Random):
    """SOP 2.2 멀티신선 + 7.2 사이클 규칙: Cu44 4회 → Cu19 1회 반복."""
    env, cfg, m = plant.env, plant.cfg, plant.m
    cond = cfg.conductor
    lines = cfg.lines()
    cycle = ["CU44"] * cond.cycle_cu44 + ["CU19"] * cond.cycle_cu19
    idx = 0

    while True:
        for _ in range(cond.multi_carriers_per_batch):
            yield carrier_store.get()

        kind = cycle[idx % len(cycle)]
        idx += 1

        if kind == "CU44":
            yield from run_on(plant, "multi", "CU44", cond.multi_cu44_min, "멀티신선")
            for _ in range(cond.multi_cu44_bobbins):
                # SOP 7.2·질문 #5: 차폐 SKU 비율은 시나리오 변수
                shielded = rng.random() < cfg.cu44_shield_ratio
                key = "CU44S" if shielded else "CU44"
                _spawn(plant, key, key, cond.multi_cu44_len_m, lines[key].steps)
        else:
            yield from run_on(plant, "multi", "CU19", cond.multi_cu19_min, "멀티신선")
            for _ in range(cond.multi_cu19_bobbins):
                env.process(cu19_conductor(plant, cond.multi_cu19_len_m))
                m.started_lots["CU19"] += 1
                m.wip(env.now, +1)


def cu19_conductor(plant: Plant, len_m: float):
    """SOP 2.3~2.5: 집합 후 절반은 연선으로, 나머지는 대기했다가 튜블러에서 병합."""
    env, cond = plant.env, plant.cfg.conductor
    yield from run_on(plant, "bunch19", "CU19", cond.bunch19_min, "집합")

    slot = plant.cu19_bunched
    plant.cu19_toggle += 1
    if plant.cu19_toggle % 2 == 0:
        # SOP 7.2: 절반은 연선으로 (1:1 교대 배분)
        yield from run_on(plant, "strand", "CU19", cond.strand19_min, "연선")
        yield plant.cu19_stranded.put({"len_m": len_m, "born": env.now})
    else:
        yield slot.put({"len_m": len_m, "born": env.now})


def tubular_worker(plant: Plant):
    """SOP 2.5 튜블러: 집합 완료 1 + 연선 완료 1이 모두 도착해야 시작되는 병합 공정."""
    env, cfg, m = plant.env, plant.cfg, plant.m
    cond = cfg.conductor
    steps = cfg.lines()["CU19"].steps

    while True:
        a = yield plant.cu19_bunched.get()
        b = yield plant.cu19_stranded.get()
        born = min(a["born"], b["born"])
        yield from run_on(plant, "tubular", "CU19", cond.tubular_min, "튜블러")
        m.wip(env.now, -2)
        for _ in range(cond.tubular_out_lots):
            lot = {
                "id": m.new_id(),
                "line": "CU19",
                "group": "CU19",
                "len_m": cond.tubular_out_len_m,
                "born": born,
            }
            m.wip(env.now, +1)
            env.process(run_steps(plant, lot, steps))


def al_inbound(plant: Plant):
    """SOP 7.2·5.3: AL16은 월초부터 12일간 하루 2롤(2t)씩 입고, 이후 정지.

    2t/일은 SOP 10.3 검증대로 40,000m·200kg 보빈 10개에 해당하고,
    라인의 페이스메이커도 '하루 10보빈'이다. ⚠집합 구간의 가닥 수지가
    SOP에 명시되지 않아(질문 #1) 보빈 1개가 최종 400m 도체 보빈 1개가
    되는 것으로 두고, 각 단계 시간은 SOP 5.3 표를 그대로 쓴다.
    """
    env, cfg = plant.env, plant.cfg
    inb, cond = cfg.inbound, cfg.conductor
    steps = cfg.lines()["AL16"].steps
    bobbins_per_day = int(round(inb.al_ton_per_day / 0.2))  # 200kg/보빈

    for day in range(cfg.sim_days):
        if day % 30 < inb.al_days:
            for _ in range(bobbins_per_day):
                env.process(_al_batch(plant, cond.multi_al_min, steps))
        yield env.timeout(1440)


def _al_batch(plant: Plant, minutes: float, steps: list[Step]):
    """AL 멀티신선(144분) 후 집합~재권취 라우팅."""
    env, m, cond = plant.env, plant.m, plant.cfg.conductor
    m.started_lots["AL16"] += 1
    m.wip(env.now, +1)
    yield from run_on(plant, "multi_al", "AL16", minutes, "멀티신선(AL)")
    lot = {
        "id": m.new_id(),
        "line": "AL16",
        "group": "AL16",
        "len_m": cond.multi_al_len_m,
        "born": env.now,
    }
    yield from run_steps(plant, lot, steps)


def sil_inbound(plant: Plant):
    """SOP 5.4·10.3: 실리콘 HV 월 물량 350,000m(25t)를 2주 주기 입고로 투입."""
    env, cfg = plant.env, plant.cfg
    steps = cfg.lines()["SIL"].steps
    interval = cfg.inbound.sil_interval_days * 1440
    lot_m = 5_000.0
    per_delivery_m = cfg.sil_month_m * (interval / (30 * 1440))

    while True:
        for _ in range(max(1, int(per_delivery_m / lot_m))):
            _spawn(plant, "SIL", "SIL", lot_m, steps)
        yield env.timeout(interval)


# ── 진입점 ────────────────────────────────────────────────────────────────


def run_cms_simulation(cfg: CmsConfig, progress: ProgressFn | None = None) -> CmsMetrics:
    rng = random.Random(cfg.random_seed)
    env = simpy.Environment()
    m = CmsMetrics()
    plant = Plant(env, cfg, m)

    horizon = cfg.sim_horizon_min
    m.horizon_min = horizon
    # 가용시간 = 캘린더상 실제 가동 가능한 시간(주말 정지·월요일 스타트업 제외)
    cal = plant.cal
    full_weeks, rem = divmod(float(horizon), WEEK_MIN)
    week_up = cal.uptime_min - cal.startup_min
    m.uptime_min = full_weeks * week_up + max(
        0.0, min(rem, cal.uptime_min) - cal.startup_min
    )

    rod_store: simpy.Store = simpy.Store(env)
    carrier_store: simpy.Store = simpy.Store(env)

    env.process(cu_inbound(plant, rod_store, rng))
    env.process(taeshin_worker(plant, rod_store, carrier_store))
    env.process(multi_worker(plant, carrier_store, rng))
    env.process(tubular_worker(plant))
    env.process(al_inbound(plant))
    env.process(sil_inbound(plant))

    if progress is not None:
        env.process(_ticker(env, horizon, progress))

    env.run(until=horizon)

    if progress is not None:
        progress(1.0, float(horizon))

    m.notes = [
        "수율 100%·설비 고장 없음 가정 (SOP 7.7 — 수율·MTBF/MTTR 데이터 부재, 질문 #2·#4)",
        "운반(AMR·지게차) 시간 0 가정 (SOP 7.6 — 거리 매트릭스 미확보, 질문 #14)",
        "버퍼 용량 무한 가정 (SOP 7.4 — 보관 용량 미확인, 질문 #15)",
        f"Cu44 차폐 SKU 비율 {cfg.cu44_shield_ratio:.0%} (SOP 7.2 — 시나리오 변수, 질문 #5)",
        "AL16 도체 설비·실리콘 차폐 설비 대수는 SOP 미확인분을 가정값으로 채움 (질문 #1)",
    ]
    return m


def _ticker(env: simpy.Environment, horizon: float, progress: ProgressFn):
    step = max(60.0, horizon / 200)
    while env.now < horizon:
        yield env.timeout(step)
        progress(min(1.0, env.now / horizon), env.now)
