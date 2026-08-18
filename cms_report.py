"""CMS 시뮬레이션 결과 해석 — KPI·병목·능력 대비 부하.

시뮬레이션(동적)과 별개로 정적 능력 계산도 함께 낸다. 두 값이 어긋나면
모델 버그이고, 일치하면 병목 진단의 신뢰도가 올라간다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cms_config import CmsConfig
from cms_simulation import CmsMetrics

LINE_LABELS = {
    "CU44": "Cu44 (비차폐)",
    "CU44S": "Cu44 (차폐 SKU)",
    "CU19": "Cu19",
    "AL16": "AL16",
    "SIL": "실리콘 HV",
}


@dataclass
class Bottleneck:
    key: str
    label: str
    count: int
    utilization: float
    avg_wait_min: float
    max_queue: int
    tbd_count: bool


@dataclass
class CapacityRow:
    """설비별 월 능력 대비 요구량(정적 계산)."""

    key: str
    label: str
    count: int
    demand_min: float
    capacity_min: float
    tbd_count: bool

    @property
    def load(self) -> float:
        return self.demand_min / self.capacity_min if self.capacity_min else 0.0


@dataclass
class CmsAnalysis:
    days: int
    uptime_min: float
    finished_m: dict[str, float]
    finished_lots: dict[str, int]
    pallets: dict[str, int]
    lead_hours: dict[str, float]
    bottlenecks: list[Bottleneck]
    capacity: list[CapacityRow] = field(default_factory=list)
    wip_start: int = 0
    wip_end: int = 0
    notes: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)

    @property
    def total_m(self) -> float:
        return sum(self.finished_m.values())

    @property
    def wip_growing(self) -> bool:
        return self.wip_end > self.wip_start * 1.5 + 10


def line_inputs_per_month(cfg: CmsConfig) -> dict[str, float]:
    """라인별로 한 달에 라우팅 첫 단계로 들어오는 로트 수.

    앞단(태신선·멀티신선·Cu19 3단 꼬임)은 산문 규칙이라 `flow` 값으로 계산한다.
    """
    cond, inb = cfg.conductor, cfg.inbound

    rod_bobbins = inb.cu_trucks_per_month * inb.cu_ton_per_truck / cond.taeshin_bobbin_ton
    batches = rod_bobbins * cond.carriers_per_bobbin / cond.multi_carriers_per_batch
    total_cycle = max(1, cond.cycle_cu44 + cond.cycle_cu19)
    b44 = batches * cond.cycle_cu44 / total_cycle
    b19 = batches * cond.cycle_cu19 / total_cycle

    # Cu44: 멀티신선이 낸 소선 보빈이 연선(라우팅 첫 단계)으로 들어간다
    cu44_bobbins = b44 * cond.multi_cu44_bobbins
    # Cu19: 집합·연선을 거쳐 튜블러가 낸 다발이 절연(라우팅 첫 단계)으로 들어간다
    pairs = b19 * cond.multi_cu19_bobbins / 2
    cu19_lots = pairs * cond.tubular_out_lots

    return {
        "CU44": cu44_bobbins * (1.0 - cfg.cu44_shield_ratio),
        "CU44S": cu44_bobbins * cfg.cu44_shield_ratio,
        "CU19": cu19_lots,
        "AL16": inb.al_days * (inb.al_ton_per_day / 0.2),
        "SIL": cfg.sil_month_m / 1_000 / 5,   # 5,000m 로트가 1,000m ×5로 갈라짐
    }


def _monthly_demand_min(cfg: CmsConfig) -> dict[str, float]:
    """설비별 월 요구 가공시간(분).

    **라우팅을 따라 걸으며** 계산하므로, 사양(JSON·MD)의 공정 단계를 고치면
    이 값도 함께 바뀐다. 앞단 공유 설비만 `flow` 값으로 따로 더한다.
    """
    cond, inb = cfg.conductor, cfg.inbound
    av = cfg.calendar.availability
    d: dict[str, float] = {}

    def add(key: str, minutes: float) -> None:
        d[key] = d.get(key, 0.0) + minutes / av

    # ── 앞단(산문 규칙 구간) ──
    rod_bobbins = inb.cu_trucks_per_month * inb.cu_ton_per_truck / cond.taeshin_bobbin_ton
    add("taeshin", rod_bobbins * cond.taeshin_min_per_bobbin)

    batches = rod_bobbins * cond.carriers_per_bobbin / cond.multi_carriers_per_batch
    total_cycle = max(1, cond.cycle_cu44 + cond.cycle_cu19)
    b44 = batches * cond.cycle_cu44 / total_cycle
    b19 = batches * cond.cycle_cu19 / total_cycle
    add("multi", b44 * cond.multi_cu44_min + b19 * cond.multi_cu19_min)

    bobbins19 = b19 * cond.multi_cu19_bobbins
    add("bunch19", bobbins19 * cond.bunch19_min)
    add("strand", bobbins19 / 2 * cond.strand19_min)   # 절반만 연선 (SOP 7.2)
    add("tubular", bobbins19 / 2 * cond.tubular_min)

    add("multi_al", inb.al_days * (inb.al_ton_per_day / 0.2) * cond.multi_al_min)

    # ── 라우팅 구간: 로트가 분할되며 흐르는 대로 따라 걷는다 ──
    lines = cfg.lines()
    for key, lots in line_inputs_per_month(cfg).items():
        line = lines.get(key)
        if line is None:
            continue
        for step in line.steps:
            lots *= step.split
            add(step.equip, lots * step.minutes)

    return d


def analyze_cms(m: CmsMetrics, cfg: CmsConfig) -> CmsAnalysis:
    util = m.utilization()
    wait = m.avg_wait()

    bottlenecks = sorted(
        (
            Bottleneck(
                key=k,
                label=m.equip_label[k],
                count=m.equip_count[k],
                utilization=util[k],
                avg_wait_min=wait[k],
                max_queue=m.max_queue[k],
                tbd_count=m.equip_tbd.get(k, False),
            )
            for k in m.equip_count
        ),
        key=lambda b: -b.utilization,
    )

    # 정적 능력 대비 부하 (월 기준)
    month_uptime = m.uptime_min * (30.0 / max(1, cfg.sim_days))
    demand = _monthly_demand_min(cfg)
    capacity = sorted(
        (
            CapacityRow(
                key=k,
                label=m.equip_label[k],
                count=m.equip_count[k],
                demand_min=v,
                capacity_min=m.equip_count[k] * month_uptime,
                tbd_count=m.equip_tbd.get(k, False),
            )
            for k, v in demand.items()
            if k in m.equip_count
        ),
        key=lambda r: -r.load,
    )

    lead_hours = {
        k: (sum(v) / len(v) / 60.0) for k, v in m.lead_min.items() if v
    }

    a = CmsAnalysis(
        days=cfg.sim_days,
        uptime_min=m.uptime_min,
        finished_m=dict(m.finished_m),
        finished_lots=dict(m.finished_lots),
        pallets=dict(m.pallets),
        lead_hours=lead_hours,
        bottlenecks=bottlenecks,
        capacity=capacity,
        wip_start=m.wip_samples[0][1] if m.wip_samples else 0,
        wip_end=m.wip_samples[-1][1] if m.wip_samples else 0,
        notes=list(m.notes),
    )
    a.findings = _findings(a, cfg)
    return a


def _findings(a: CmsAnalysis, cfg: CmsConfig) -> list[str]:
    out: list[str] = []

    over = [r for r in a.capacity if r.load > 1.0]
    if over:
        head = over[0]
        out.append(
            f"**능력 부족 {len(over)}건.** 가장 심한 곳은 **{head.label} {head.count}대**로, "
            f"SOP 입고량을 소화하려면 월 {head.demand_min/60:,.0f}시간이 필요한데 "
            f"가용은 {head.capacity_min/60:,.0f}시간뿐입니다 (부하 {head.load*100:.0f}%). "
            f"이 설비가 라인 전체의 처리량 상한을 정합니다."
        )
        if len(over) > 1:
            rest = " · ".join(f"{r.label} {r.load*100:.0f}%" for r in over[1:5])
            out.append(f"함께 넘치는 설비: {rest}")

    if a.wip_growing:
        out.append(
            f"**재공(WIP)이 발산합니다** — 기간 중 {a.wip_start}개 → {a.wip_end}개. "
            "투입이 능력을 넘어서 대기 재고가 계속 쌓이는 상태이고, "
            "리드타임 수치는 정상 상태가 아니라 '아직 밀리는 중'인 값으로 읽어야 합니다."
        )

    irr = next((r for r in a.capacity if r.key == "irradiator"), None)
    if irr and irr.load > 1.0:
        out.append(
            f"**조사기 1대 겸용 가정이 성립하지 않습니다** (부하 {irr.load*100:.0f}%). "
            "SOP 질문 #19(절연 조사·시스 조사 겸용 여부)가 확인되면 결과가 크게 바뀝니다. "
            "겸용이 사실이라면 증설 또는 2교대 분리가 필요합니다."
        )

    br = next((r for r in a.capacity if r.key == "braider"), None)
    if br:
        if br.load > 1.0:
            max_ratio = cfg.cu44_shield_ratio / br.load
            out.append(
                f"**차폐 비율 {cfg.cu44_shield_ratio:.0%}는 편조기 21대 능력을 넘습니다** "
                f"(부하 {br.load*100:.0f}%). 현 설비로 감당 가능한 상한은 약 "
                f"**{max_ratio*100:.0f}%**입니다 — SOP 10.3의 '편조 총능력 1.09M m/월'과 같은 결론입니다 "
                "(질문 #5)."
            )
        else:
            out.append(
                f"차폐 비율 {cfg.cu44_shield_ratio:.0%}에서 편조기 부하는 {br.load*100:.0f}%로 "
                "여유가 있습니다. 비율을 올리며 상한을 찾아보세요 (질문 #5)."
            )

    tbd = [r for r in a.capacity if r.tbd_count and r.load > 0.7]
    if tbd:
        names = " · ".join(r.label for r in tbd[:4])
        out.append(
            f"⚠ 대수가 SOP 미확인인 설비가 높은 부하로 나왔습니다 — {names}. "
            "가정값이므로 이 수치는 확정 전까지 참고용입니다 (질문 #1)."
        )

    return out
