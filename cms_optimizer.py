"""CP-SAT 기반 설비 구성 최적화.

시뮬레이션(SimPy)이 "지금 구성으로 무슨 일이 벌어지는가"를 답한다면,
여기서는 "그럼 어떻게 바꿔야 하는가"를 답한다.

두 가지를 푼다.
 1. `solve_min_additions`  — 모든 설비의 부하를 목표치 이하로 낮추는
    **최소 증설 대수**. "무엇을 몇 대 더 놓아야 계획 물량이 흐르는가"
 2. `solve_max_throughput` — 증설을 N대로 제한했을 때 **감당 가능한 최대 물량 배수**.
    "예산이 N대뿐이라면 계획의 몇 %까지 소화되는가"

둘 다 정수 선형 모델이라 CP-SAT이 최적해를 보장한다(시뮬레이션의 근사가 아니다).
요구 시간은 `cms_report._monthly_demand_min` — 라우팅을 따라 계산한 값이라
사양(MD)을 고치면 최적화 입력도 함께 바뀐다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cms_config import CmsConfig
from cms_report import CmsAnalysis

# 증설이 현실적으로 불가능하거나 의미 없는 설비
_NOT_EXPANDABLE: frozenset[str] = frozenset()

# 설비 1대를 늘리는 상대 비용(기본 1). 크고 비싼 설비일수록 크게 둔다.
DEFAULT_COST: dict[str, float] = {
    "irradiator": 8.0,      # 전자빔 조사기 — 가장 비싼 설비
    "ins_ext": 4.0,
    "sheath_ext": 4.0,
    "sil_ext": 4.0,
    "multi": 3.0,
    "multi_al": 3.0,
    "taeshin": 3.0,
    "rewind1050": 2.0,
    "rewind1250": 2.0,
    "tubular": 2.0,
    "strand": 1.5,
    "bunch19": 1.5,
    "braider": 1.0,
    "sil_braider": 1.0,
    "taping": 1.0,
    "sil_taping": 1.0,
    "inspect": 0.5,         # 검사는 인원 배치라 상대적으로 싸다
    "inspect_sil": 0.5,
}


@dataclass
class AddRow:
    key: str
    label: str
    now: int
    add: int
    cost: float
    load_before: float
    load_after: float


@dataclass
class OptimizeResult:
    ok: bool
    status: str
    message: str = ""
    rows: list[AddRow] = field(default_factory=list)
    total_added: int = 0
    total_cost: float = 0.0
    throughput_ratio: float = 1.0   # 감당 가능한 계획 대비 배수
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> list[AddRow]:
        return [r for r in self.rows if r.add > 0]


def _inputs(analysis: CmsAnalysis) -> list[tuple[str, str, int, float, float]]:
    """(설비키, 라벨, 현재 대수, 월 요구 분, 1대당 월 가용 분)."""
    out = []
    for r in analysis.capacity:
        per_unit = r.capacity_min / max(1, r.count)
        out.append((r.key, r.label, r.count, r.demand_min, per_unit))
    return out


def _import_cp_model():
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:  # pragma: no cover - 환경 문제
        raise RuntimeError(
            "CP-SAT 최적화에는 ortools가 필요합니다. `pip install ortools`로 설치하세요."
        ) from exc
    return cp_model


def solve_min_additions(
    cfg: CmsConfig,
    analysis: CmsAnalysis,
    *,
    target_load: float = 1.0,
    max_add_per_equip: int = 40,
    cost: dict[str, float] | None = None,
    time_limit_s: float = 10.0,
) -> OptimizeResult:
    """모든 설비 부하를 `target_load` 이하로 낮추는 최소 증설을 찾는다."""
    cp_model = _import_cp_model()
    cost = {**DEFAULT_COST, **(cost or {})}

    rows = _inputs(analysis)
    if not rows:
        return OptimizeResult(False, "NO_DATA", "능력 계산 결과가 없습니다.")

    model = cp_model.CpModel()
    add_vars: dict[str, object] = {}
    terms = []

    for key, _label, count, demand, per_unit in rows:
        add = model.NewIntVar(0, max_add_per_equip, f"add_{key}")
        add_vars[key] = add
        if key in _NOT_EXPANDABLE:
            model.Add(add == 0)

        # (count + add) * per_unit * target_load >= demand
        # 정수 계수로 만들기 위해 분 단위를 정수로 반올림한다(1분 미만 오차는 무시 가능).
        need = int(round(demand))
        cap_per_unit = int(round(per_unit * target_load))
        if cap_per_unit <= 0:
            continue
        model.Add((count + add) * cap_per_unit >= need)
        terms.append(int(round(cost.get(key, 1.0) * 10)) * add)

    model.Minimize(sum(terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.Solve(model)
    name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return OptimizeResult(
            False, name,
            "해를 찾지 못했습니다. 증설 상한을 올리거나 목표 부하를 완화해 보세요.",
        )

    out_rows: list[AddRow] = []
    for key, label, count, demand, per_unit in rows:
        add = int(solver.Value(add_vars[key]))
        before = demand / (count * per_unit) if count * per_unit else 0.0
        after = demand / ((count + add) * per_unit) if (count + add) * per_unit else 0.0
        out_rows.append(
            AddRow(key, label, count, add, cost.get(key, 1.0), before, after)
        )

    out_rows.sort(key=lambda r: (-r.add, -r.load_before))
    return OptimizeResult(
        ok=True,
        status=name,
        rows=out_rows,
        total_added=sum(r.add for r in out_rows),
        total_cost=sum(r.add * r.cost for r in out_rows),
        notes=[
            f"목표: 모든 설비 부하 {target_load:.0%} 이하",
            "비용은 설비 유형별 상대 가중치입니다(조사기 8 · 압출기 4 · 편조기 1 · 검사 0.5). "
            "실제 견적이 있으면 바꿔 쓰세요.",
        ],
    )


def solve_max_throughput(
    cfg: CmsConfig,
    analysis: CmsAnalysis,
    *,
    budget_units: int,
    max_add_per_equip: int = 40,
    time_limit_s: float = 10.0,
) -> OptimizeResult:
    """증설을 `budget_units`대로 제한했을 때 감당 가능한 최대 물량 배수를 찾는다."""
    cp_model = _import_cp_model()
    rows = _inputs(analysis)
    if not rows:
        return OptimizeResult(False, "NO_DATA", "능력 계산 결과가 없습니다.")

    model = cp_model.CpModel()
    # 물량 배수를 0.1% 단위 정수로 다룬다 (1000 = 계획 100%)
    ratio = model.NewIntVar(0, 5000, "ratio")
    add_vars = {}
    for key, _label, count, demand, per_unit in rows:
        add = model.NewIntVar(0, max_add_per_equip, f"add_{key}")
        add_vars[key] = add
        need = int(round(demand))
        cap_unit = int(round(per_unit))
        if cap_unit <= 0 or need <= 0:
            continue
        # need * ratio/1000 <= (count+add) * cap_unit
        model.Add(need * ratio <= (count + add) * cap_unit * 1000)

    model.Add(sum(add_vars.values()) <= budget_units)
    model.Maximize(ratio)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    status = solver.Solve(model)
    name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return OptimizeResult(False, name, "해를 찾지 못했습니다.")

    r_val = solver.Value(ratio) / 1000.0
    out_rows: list[AddRow] = []
    for key, label, count, demand, per_unit in rows:
        add = int(solver.Value(add_vars[key]))
        before = demand / (count * per_unit) if count * per_unit else 0.0
        after = (
            demand * r_val / ((count + add) * per_unit)
            if (count + add) * per_unit else 0.0
        )
        out_rows.append(AddRow(key, label, count, add, 1.0, before, after))

    out_rows.sort(key=lambda r: (-r.add, -r.load_before))
    return OptimizeResult(
        ok=True,
        status=name,
        rows=out_rows,
        total_added=sum(r.add for r in out_rows),
        total_cost=float(sum(r.add for r in out_rows)),
        throughput_ratio=r_val,
        notes=[
            f"증설 {budget_units}대 제한에서 계획 물량의 **{r_val:.0%}**까지 소화 가능",
        ],
    )


def apply_additions(cfg: CmsConfig, result: OptimizeResult) -> CmsConfig:
    """최적화가 제안한 증설을 반영한 설정을 돌려준다(검증·재시뮬레이션용)."""
    from dataclasses import replace

    eq = {k: replace(v) for k, v in cfg.equipment.items()}
    for r in result.rows:
        if r.add and r.key in eq:
            eq[r.key] = replace(eq[r.key], count=eq[r.key].count + r.add)
    return replace(cfg, equipment=eq)
