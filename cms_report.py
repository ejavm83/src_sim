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


# ── 시뮬레이션 기반 병목 진단 ─────────────────────────────────────────────
# 문서를 읽고 "가장 느린 공정이 병목"이라고 말하는 것은 시뮬레이션이 필요 없다.
# 여기서는 **실제로 돌려 본 결과**에서만 알 수 있는 것을 뽑는다:
#   · 능력이 모자라 물리적으로 못 돌리는 설비 (요구시간 vs 가용시간)
#   · 여러 라인이 한 설비를 두고 다투며 생긴 대기 (누가 누구를 밀어냈는가)
#   · 그 경합 때문에 계획을 못 채운 라인 (굶은 라인)
#   · 재공이 쌓이는지 (투입이 능력을 넘었는가)


@dataclass
class BottleneckRow:
    """설비 1종에 대한 병목 진단 — 근거 수치를 모두 들고 다닌다."""

    rank: int
    key: str
    label: str
    count: int
    kind: str                 # 능력부족 / 경합 / 여유
    load: float               # 정적 부하 = 월 요구시간 ÷ 가용시간
    utilization: float        # 동적 가동률 = (가공+교체) ÷ 능력
    demand_h: float
    capacity_h: float
    avg_wait_h: float
    max_queue: int
    jobs: int
    setup_share: float        # 가동시간 중 교체가 차지한 비중
    lines: tuple[str, ...]    # 이 설비를 쓴 라인
    wait_by_line: tuple[tuple[str, float], ...]   # (라인, 총 대기시간 h) 내림차순
    add_needed: int           # 부하를 100% 이하로 낮추는 데 필요한 증설 대수
    load_after: float
    tbd_count: bool

    @property
    def shared(self) -> bool:
        return len(self.lines) > 1


@dataclass
class LineResult:
    """라인 1개의 계획 대비 실적 — 경합에 밀려 굶었는지 본다."""

    key: str
    label: str
    plan_m: float
    actual_m: float
    rate: float
    lead_h: float
    wait_h: float             # 이 라인이 설비 앞에서 기다린 총 시간
    process_h: float          # 실제 가공에 쓴 총 시간
    blocked_at: tuple[tuple[str, float], ...]   # (설비 라벨, 대기 h) 상위

    @property
    def wait_share(self) -> float:
        total = self.wait_h + self.process_h
        return self.wait_h / total if total else 0.0


@dataclass
class BottleneckReport:
    rows: list[BottleneckRow]
    lines: list[LineResult]
    wip_start: int
    wip_end: int
    days: int

    @property
    def over(self) -> list[BottleneckRow]:
        return [r for r in self.rows if r.load > 1.0]

    @property
    def starved(self) -> list[LineResult]:
        """계획의 절반도 못 채운 라인 — 대개 공유 설비 경합의 피해자다."""
        return [ln for ln in self.lines if ln.plan_m > 0 and ln.rate < 0.5]


def _plan_output_m(cfg: CmsConfig) -> dict[str, float]:
    """라인별 월 계획 산출량(m) — 라우팅의 분할을 따라 끝까지 걸어 계산한다."""
    out: dict[str, float] = {}
    lines = cfg.lines()
    for key, lots in line_inputs_per_month(cfg).items():
        line = lines.get(key)
        if line is None:
            continue
        last_len = 0.0
        for step in line.steps:
            lots *= step.split
            if step.out_len_m:
                last_len = step.out_len_m
        out[key] = lots * last_len
    return out


def bottleneck_report(m: CmsMetrics, cfg: CmsConfig, a: CmsAnalysis) -> BottleneckReport:
    """시뮬레이션 결과에서 병목을 근거와 함께 뽑아낸다."""
    util = m.utilization()
    cap_by_key = {r.key: r for r in a.capacity}
    month_scale = 30.0 / max(1, cfg.sim_days)

    rows: list[BottleneckRow] = []
    for key, count in m.equip_count.items():
        cap_row = cap_by_key.get(key)
        demand_h = (cap_row.demand_min / 60.0) if cap_row else 0.0
        capacity_h = (cap_row.capacity_min / 60.0) if cap_row else 0.0
        load = cap_row.load if cap_row else 0.0

        lines_used = sorted(
            {ln for (k, ln) in m.busy_by_line if k == key and m.busy_by_line[(k, ln)] > 0}
        )
        waits = sorted(
            ((ln, m.wait_by_line[(k, ln)] / 60.0) for (k, ln) in m.wait_by_line if k == key),
            key=lambda x: -x[1],
        )
        busy = m.busy_min[key] + m.setup_min[key]
        setup_share = (m.setup_min[key] / busy) if busy else 0.0

        # 부하를 100% 이하로 낮추려면 몇 대가 더 필요한가 (요구시간은 그대로)
        add = 0
        load_after = load
        if load > 1.0 and count > 0:
            import math

            need = math.ceil(load * count - 1e-9)
            add = max(0, need - count)
            load_after = load * count / max(1, count + add)

        if load > 1.0:
            kind = "능력부족"
        elif len(lines_used) > 1 and (m.wait_min[key] / max(1, m.wait_n[key])) > 60:
            kind = "경합"
        else:
            kind = "여유"

        rows.append(
            BottleneckRow(
                rank=0,
                key=key,
                label=m.equip_label.get(key, key),
                count=count,
                kind=kind,
                load=load,
                utilization=util.get(key, 0.0),
                demand_h=demand_h,
                capacity_h=capacity_h,
                avg_wait_h=(m.wait_min[key] / max(1, m.wait_n[key])) / 60.0,
                max_queue=m.max_queue[key],
                jobs=m.wait_n[key],
                setup_share=setup_share,
                lines=tuple(lines_used),
                wait_by_line=tuple(waits[:5]),
                add_needed=add,
                load_after=load_after,
                tbd_count=m.equip_tbd.get(key, False),
            )
        )

    # 능력 부족이 먼저, 그다음 총 대기시간이 큰 순서 — '얼마나 막았나'가 기준
    rows.sort(key=lambda r: (-(r.load > 1.0), -r.load, -m.wait_min[r.key]))
    for i, r in enumerate(rows, start=1):
        r.rank = i

    plan_m = _plan_output_m(cfg)
    line_rows: list[LineResult] = []
    for key, label in LINE_LABELS.items():
        plan = plan_m.get(key, 0.0) / month_scale   # 시뮬 기간에 맞춘 계획
        actual = m.finished_m.get(key, 0.0)
        if plan <= 0 and actual <= 0:
            continue
        wait_h = sum(v for (k, ln), v in m.wait_by_line.items() if ln == key) / 60.0
        proc_h = sum(v for (k, ln), v in m.busy_by_line.items() if ln == key) / 60.0
        blocked = sorted(
            (
                (m.equip_label.get(k, k), v / 60.0)
                for (k, ln), v in m.wait_by_line.items()
                if ln == key and v > 0
            ),
            key=lambda x: -x[1],
        )[:3]
        line_rows.append(
            LineResult(
                key=key,
                label=label,
                plan_m=plan,
                actual_m=actual,
                rate=(actual / plan) if plan else 0.0,
                lead_h=a.lead_hours.get(key, 0.0),
                wait_h=wait_h,
                process_h=proc_h,
                blocked_at=tuple(blocked),
            )
        )

    return BottleneckReport(
        rows=rows,
        lines=line_rows,
        wip_start=a.wip_start,
        wip_end=a.wip_end,
        days=a.days,
    )


def bottleneck_brief(r: BottleneckReport, top: int = 6) -> str:
    """병목 리포트를 LLM에 넘길 사실 묶음으로 만든다.

    여기 담긴 숫자는 전부 **실제로 30일을 돌려 본 결과**다. LLM이 문서를 읽고
    '가장 느린 공정이 병목'이라고 추측하는 대신, 이 수치를 인용해 설명하도록
    강제하기 위한 근거다.
    """
    out: list[str] = []
    out.append(
        f"[시뮬레이션 조건] {r.days}일 가동 · 재공(WIP) {r.wip_start} → {r.wip_end}개"
        + (" (발산: 투입이 능력을 넘음)" if r.wip_end > r.wip_start * 1.5 + 10 else " (안정)")
    )

    out.append("\n[설비별 병목 진단 — 부하 = 월 요구시간 ÷ 가용시간, 100% 초과면 물리적으로 불가능]")
    for row in r.rows[:top]:
        if row.load <= 0 and row.jobs == 0:
            continue
        lines = " · ".join(
            f"{LINE_LABELS.get(ln, ln)} {h:,.0f}h" for ln, h in row.wait_by_line[:4]
        ) or "없음"
        line = (
            f"{row.rank}. {row.label} {row.count}대 [{row.kind}] — "
            f"부하 {row.load*100:.0f}% (요구 {row.demand_h:,.0f}h ÷ 가용 {row.capacity_h:,.0f}h), "
            f"가동률 {row.utilization*100:.0f}%, 평균대기 {row.avg_wait_h:.1f}h, "
            f"최대 대기열 {row.max_queue}개, 처리 {row.jobs}건"
        )
        if row.setup_share > 0.05:
            line += f", 가동시간의 {row.setup_share*100:.0f}%가 품종 교체"
        line += f"\n   · 이 설비를 두고 다툰 라인 {len(row.lines)}개, 라인별 총 대기: {lines}"
        if row.add_needed:
            line += f"\n   · {row.add_needed}대 증설하면 부하 {row.load*100:.0f}% → {row.load_after*100:.0f}%"
        if row.tbd_count:
            line += "\n   · ⚠ 대수가 SOP 미확인인 가정값 (질문 #1)"
        out.append(line)

    out.append("\n[라인별 계획 대비 실적 — 경합에 밀려 못 채운 라인]")
    for ln in r.lines:
        blocked = " · ".join(f"{lb} {h:,.0f}h" for lb, h in ln.blocked_at) or "없음"
        out.append(
            f"- {ln.label}: 계획 {ln.plan_m:,.0f}m 중 {ln.actual_m:,.0f}m 생산 "
            f"(달성률 {ln.rate*100:.0f}%), 리드타임 {ln.lead_h:,.0f}h, "
            f"이 라인이 쓴 시간의 {ln.wait_share*100:.0f}%가 설비를 기다린 시간\n"
            f"   · 가장 오래 막힌 곳: {blocked}"
        )

    if r.starved:
        names = " · ".join(x.label for x in r.starved)
        out.append(f"\n[주의] 계획의 절반도 못 채운 라인: {names}")

    return "\n".join(out)
