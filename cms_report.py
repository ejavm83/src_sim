"""CMS 시뮬레이션 결과 해석 — KPI·병목·능력 대비 부하.

시뮬레이션(동적)과 별개로 정적 능력 계산도 함께 낸다. 두 값이 어긋나면
모델 버그이고, 일치하면 병목 진단의 신뢰도가 올라간다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cms_config import CmsConfig, line_inputs_per_month, planned_equip_load
from cms_simulation import CmsMetrics

__all__ = ["line_inputs_per_month", "planned_equip_load", "analyze_cms", "CmsAnalysis"]

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
    machines: list["MachineRow"] = field(default_factory=list)
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


def _monthly_demand_min(cfg: CmsConfig) -> dict[str, float]:
    """설비별 월 요구 가공시간(분) — 라인별 계획 부하를 설비 단위로 합산한 값.

    계산 자체는 `cms_config.planned_equip_load`가 한다. 시뮬레이션의 공유 설비
    배분도 같은 값을 쓰므로, 진단 표와 시뮬레이션이 같은 기준을 본다.
    """
    return {
        equip: sum(by_line.values())
        for equip, by_line in planned_equip_load(cfg).items()
    }


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
        machines=machine_rows(m),
        wip_start=m.wip_samples[0][1] if m.wip_samples else 0,
        wip_end=m.wip_samples[-1][1] if m.wip_samples else 0,
        notes=list(m.notes),
    )
    a.findings = _findings(a, cfg) + shared_machine_findings(a.machines)
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


@dataclass
class MachineRow:
    """개별 설비 1대 — SOP 2.6의 '역' 하나에 대응."""

    machine_id: str
    equip_key: str
    equip_label: str
    utilization: float
    jobs: int
    lines: tuple[str, ...]

    @property
    def shared(self) -> bool:
        return len(self.lines) > 1


def machine_rows(m: CmsMetrics) -> list[MachineRow]:
    """개별 설비별 가동률과 사용 라인. 공유 설비를 지목할 수 있게 한다."""
    cap = max(1.0, m.uptime_min)
    rows: list[MachineRow] = []
    for key, ids in m.machine_ids.items():
        for mid in ids:
            k = (key, mid)
            rows.append(
                MachineRow(
                    machine_id=mid,
                    equip_key=key,
                    equip_label=m.equip_label.get(key, key),
                    utilization=(m.machine_busy[k] + m.machine_setup[k]) / cap,
                    jobs=m.machine_jobs[k],
                    lines=tuple(sorted(m.machine_lines[k])),
                )
            )
    return sorted(rows, key=lambda r: -r.utilization)


def shared_machine_findings(rows: list[MachineRow], top: int = 3) -> list[str]:
    """'이 설비를 여러 라인이 함께 써서 병목' 형태의 진단 문장."""
    out: list[str] = []
    busy_shared = [r for r in rows if r.shared and r.utilization > 0.8]
    for r in busy_shared[:top]:
        names = " · ".join(LINE_LABELS.get(x, x) for x in r.lines)
        out.append(
            f"**{r.machine_id}** ({r.equip_label})는 가동률 {r.utilization * 100:.0f}%인데 "
            f"**{len(r.lines)}개 라인이 함께 씁니다** — {names}. "
            "한 라인이 쓰는 동안 나머지가 대기하므로 여기서 경합이 발생합니다."
        )
    if not busy_shared:
        idle_shared = [r for r in rows if r.shared]
        if idle_shared:
            out.append(
                f"여러 라인이 함께 쓰는 설비 {len(idle_shared)}대는 모두 가동률 80% 미만이라 "
                "공유 자체가 병목을 만들고 있지는 않습니다."
            )
    return out
