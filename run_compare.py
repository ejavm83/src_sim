"""다중 실행 스냅샷 저장·비교 헬퍼."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from config import SimulationConfig
from report import Analysis

MAX_SNAPSHOTS = 8


def flatten_config(cfg: SimulationConfig) -> dict[str, Any]:
    return {
        "sim_days": cfg.sim_days,
        "seed": cfg.random_seed,
        "trucks_per_day": cfg.inbound.trucks_per_day,
        "truck_load_ton": cfg.inbound.truck_load_ton,
        "sorters": cfg.sorting.sorters,
        "presses": cfg.sorting.presses,
        "pallet_buffer_cap": cfg.sorting.pallet_buffer_cap,
        "batch_ton": cfg.melting.batch_ton,
        "furnace_count": cfg.melting.furnace_count,
        "melting_min": cfg.melting.melting_min,
        "flake_ratio": cfg.casting.flake_ratio,
        "outbound_interval_min": cfg.outbound.truck_interval_min,
    }


def snapshot(name: str, cfg: SimulationConfig, analysis: Analysis) -> dict[str, Any]:
    return {
        "name": name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "config": flatten_config(cfg),
        "kpi": dict(analysis.summary),
        "utilization": dict(analysis.utilization),
        "bottleneck": analysis.bottleneck,
        "insights": list(analysis.insights),
        "recommendations": list(analysis.recommendations),
        "daily_production": {
            int(d): dict(v) for d, v in analysis.daily_production.items()
        },
    }


KPI_COMPARE_SPECS: list[tuple[str, str]] = [
    ("total_ton", "총 생산 (t)"),
    ("flake_ton", "큐프레이크 생산 (t)"),
    ("scr_ton", "SCR 생산 (t)"),
    ("batches_completed", "완료 배치"),
    ("inbound_trucks", "입고 트럭"),
    ("outbound_trucks", "출하 트럭"),
    ("daily_avg_ton", "일평균 생산 (t/일)"),
    ("avg_batch_min", "평균 배치 사이클 (분)"),
    ("avg_inbound_min", "평균 입고 체류 (분)"),
    ("avg_outbound_min", "평균 출하 체류 (분)"),
    ("aborted_outbound", "출하 abort 횟수"),
]


CONFIG_LABELS: dict[str, str] = {
    "sim_days": "시뮬레이션 일수",
    "seed": "난수 시드",
    "trucks_per_day": "일 입고 트럭 수",
    "truck_load_ton": "트럭 적재 (t)",
    "sorters": "선별기 대수",
    "presses": "압착기 대수",
    "pallet_buffer_cap": "파레트 버퍼 용량",
    "batch_ton": "배치 톤수 (t)",
    "furnace_count": "반사로 대수",
    "melting_min": "용해·정련 시간 (분)",
    "flake_ratio": "큐프레이크 비율",
    "outbound_interval_min": "출하 평균 간격 (분)",
}


def localize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """원 키를 한글 라벨로 치환한 사본을 돌려준다."""
    return {CONFIG_LABELS.get(k, k): v for k, v in cfg.items()}


def diff_config_items(
    baseline_cfg: dict[str, Any], target_cfg: dict[str, Any]
) -> list[tuple[str, Any, Any]]:
    """기준 대비 달라진 설정만 (한글 라벨, 기준값, 변경값) 리스트로 반환."""
    rows: list[tuple[str, Any, Any]] = []
    for key in CONFIG_LABELS:
        b = baseline_cfg.get(key)
        t = target_cfg.get(key)
        if b != t:
            rows.append((CONFIG_LABELS[key], b, t))
    return rows


# KPI 의미: 높은 게 좋은가(True) 낮은 게 좋은가(False)
KPI_HIGHER_BETTER: dict[str, bool] = {
    "total_ton": True,
    "flake_ton": True,
    "scr_ton": True,
    "batches_completed": True,
    "inbound_trucks": True,
    "outbound_trucks": True,
    "daily_avg_ton": True,
    "avg_batch_min": False,
    "avg_inbound_min": False,
    "avg_outbound_min": False,
    "aborted_outbound": False,
}


def narrate_vs_baseline(target: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """기준 실행과 비교한 자동 해석 문장 리스트.

    설정·KPI 차이를 사람이 읽는 한국어 문장으로 변환한다.
    """
    # 지연 import (RESOURCE_LABELS 의존)
    from report import RESOURCE_LABELS

    notes: list[str] = []
    bk = baseline.get("kpi", {})
    tk = target.get("kpi", {})

    # 1. 설정 변경 요약
    diffs = diff_config_items(baseline.get("config", {}), target.get("config", {}))
    if diffs:
        chg = ", ".join(f"{label} {b}→{t}" for label, b, t in diffs[:3])
        notes.append(f"⚙️ 설정 변경: {chg}" + (" 외" if len(diffs) > 3 else ""))

    # 2. 총 생산 변화
    base_ton = bk.get("total_ton", 0)
    if base_ton > 0:
        dp = (tk.get("total_ton", 0) - base_ton) / base_ton * 100
        if abs(dp) >= 1.0:
            arrow = "📈" if dp > 0 else "📉"
            notes.append(
                f"{arrow} 총 생산 {tk['total_ton']:.0f}t "
                f"({'+' if dp > 0 else ''}{dp:.1f}%, "
                f"{tk['total_ton']-base_ton:+.0f}t)"
            )

    # 3. 평균 배치 사이클 변화
    base_bc = bk.get("avg_batch_min", 0)
    if base_bc > 0:
        dc = tk.get("avg_batch_min", 0) - base_bc
        if abs(dc) >= 10:
            cause = "자원 경합으로 길어짐" if dc > 0 else "병렬화로 단축"
            notes.append(f"⏱️ 평균 배치 사이클 {tk['avg_batch_min']:.0f}분 ({dc:+.0f}분, {cause})")

    # 4. 병목 변화
    b_bn = baseline.get("bottleneck", "")
    t_bn = target.get("bottleneck", "")
    if b_bn and t_bn:
        if b_bn != t_bn:
            bl = RESOURCE_LABELS.get(b_bn, b_bn)
            tl = RESOURCE_LABELS.get(t_bn, t_bn)
            notes.append(f"🚧 병목 이동: {bl} → {tl}")
        else:
            b_util = baseline.get("utilization", {}).get(b_bn, 0) * 100
            t_util = target.get("utilization", {}).get(t_bn, 0) * 100
            if abs(t_util - b_util) >= 5:
                tl = RESOURCE_LABELS.get(t_bn, t_bn)
                notes.append(
                    f"🚧 병목({tl}) 가동률 {t_util:.0f}% ({t_util-b_util:+.0f}%p)"
                )

    # 5. 출하 abort 변화
    b_ab = bk.get("aborted_outbound", 0)
    t_ab = tk.get("aborted_outbound", 0)
    if abs(t_ab - b_ab) >= 1:
        sign = "+" if t_ab > b_ab else ""
        worse = " (악화)" if t_ab > b_ab else " (개선)"
        notes.append(f"🚛 출하 abort {t_ab}회 ({sign}{t_ab - b_ab}회{worse})")

    return notes


def synthesize_implications(target: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """기준 대비 비교 결과가 의사결정·후속 실험에 주는 시사점(짧은 문장).

    수치 요약(narrate)과 달리, '그래서 무엇을 하면 좋은가'에 가깝게 쓴다.
    """
    from report import RESOURCE_LABELS

    impl: list[str] = []
    bk = baseline.get("kpi", {})
    tk = target.get("kpi", {})
    diffs = diff_config_items(baseline.get("config", {}), target.get("config", {}))
    deltas = significant_kpi_deltas(bk, tk)

    diff_labels = {d[0] for d in diffs}
    only_seed = bool(diffs) and diff_labels == {"난수 시드"}

    if not diffs and not deltas:
        impl.append(
            "기준과 설정·주요 KPI가 같습니다. 다른 시드를 쓰지 않았다면 동일 시나리오로 보시면 됩니다."
        )
        return impl

    if only_seed and deltas:
        impl.append(
            "설정은 동일하고 난수 시드만 다릅니다. 보이는 차이는 확률적 변동일 수 있으니, "
            "결론을 내리기 전에 시드를 고정한 채 여러 번 돌려 분산을 확인하는 것이 좋습니다."
        )

    if len(diffs) >= 4:
        impl.append(
            "한 번에 여러 파라미터가 바뀌어 있어, 어떤 변경이 결과를 주도했는지 단정하기 어렵습니다. "
            "원인 분석이 필요하면 변수를 하나씩만 바꾼 스냅샷을 추가로 쌓아 보세요."
        )

    # 입·출하 트럭 수 등은 '좋다/나쁘다'로 묶지 않음 (중립 지표)
    _impl_neutral_keys = frozenset({"inbound_trucks", "outbound_trucks"})
    deltas_dir = [d for d in deltas if d.get("key") not in _impl_neutral_keys]
    good_n = sum(1 for d in deltas_dir if d.get("good") is True)
    bad_n = sum(1 for d in deltas_dir if d.get("good") is False)
    if deltas_dir:
        if good_n and not bad_n:
            impl.append(
                "기준 대비로 보면 주요 KPI가 일관되게 유리한 방향입니다. "
                "이 조합은 '개선 후보'로 두고, 가동률·출하 안정성까지 함께 만족하는지 확인하면 됩니다."
            )
        elif bad_n and not good_n:
            impl.append(
                "주요 KPI가 기준보다 불리한 쪽으로만 움직였습니다. "
                "이 설정 조합은 피하거나, 병목 자원을 추가로 살펴 재조정하는 편이 안전합니다."
            )
        elif good_n and bad_n:
            impl.append(
                "일부 KPI는 나아졌고 일부는 나빠졌습니다. "
                "현장에서 무엇을 최우선으로 볼지(처리량·체류·출하 등) 정한 뒤, 그 지표를 기준으로 승자를 정하는 것이 좋습니다."
            )

    base_ton = float(bk.get("total_ton", 0) or 0)
    tgt_ton = float(tk.get("total_ton", 0) or 0)
    if base_ton > 0 and abs(tgt_ton - base_ton) / base_ton >= 0.05:
        if tgt_ton > base_ton:
            impl.append(
                "총 생산이 눈에 띄게 증가했습니다. "
                "단, 병목 구간 가동률이 90%에 가깝게 붙었는지 확인하세요. "
                "여유가 없으면 실제 운영에서는 작은 교란에도 지연이 커질 수 있습니다."
            )
        else:
            impl.append(
                "총 생산이 기준보다 줄었습니다. "
                "병목이 바뀌었는지, 입고·출하 제약에 더 자주 걸렸는지(체류·abort)를 위쪽 해석과 함께 보시면 원인 단서가 됩니다."
            )

    b_bn = baseline.get("bottleneck", "")
    t_bn = target.get("bottleneck", "")
    if b_bn and t_bn and b_bn != t_bn:
        tl = RESOURCE_LABELS.get(t_bn, t_bn)
        impl.append(
            f"제약이 '{tl}' 쪽으로 옮겨졌습니다. "
            f"투자·인력·계획을 논의할 때는 이 자원이 새로운 한계 요인임을 전제로 두는 것이 맞습니다."
        )
    elif t_bn:
        b_u = float(baseline.get("utilization", {}).get(t_bn, 0) or 0)
        t_u = float(target.get("utilization", {}).get(t_bn, 0) or 0)
        if t_u >= 0.9 and t_u > b_u:
            impl.append(
                "병목 자원의 가동률이 매우 높습니다. "
                "스냅샷상으로는 처리량이 나와도, 버퍼·대기 시간이 늘어 운영 리스크가 커질 수 있으니 완충 여지를 검토하세요."
            )

    if not impl:
        impl.append(
            "수치 차이는 크지 않습니다. "
            "정책 결정용으로는 변동폭이 허용 범위인지, 아니면 더 긴 시뮬 기간으로 다시 볼지 판단하면 됩니다."
        )

    return impl


def kpi_delta_pct(val: float | int, baseline_val: float | int) -> float | None:
    """기준 대비 변화율(%). 기준이 0이면 None."""
    if baseline_val == 0:
        return None if val == 0 else float("inf") if val > 0 else float("-inf")
    return (val - baseline_val) / baseline_val * 100


def kpi_changed(
    val: Any,
    baseline_val: Any,
    *,
    threshold_pct: float = 0.5,
) -> bool:
    """KPI가 의미 있게 달라졌는지 (동일·미세 변화 제외)."""
    if val == baseline_val:
        return False
    if isinstance(val, (int, float)) and isinstance(baseline_val, (int, float)):
        pct = kpi_delta_pct(val, baseline_val)
        if pct is None:
            return val != baseline_val
        if pct in (float("inf"), float("-inf")):
            return True
        return abs(pct) >= threshold_pct
    return True


def significant_kpi_deltas(
    baseline_kpi: dict[str, Any],
    target_kpi: dict[str, Any],
    *,
    threshold_pct: float = 0.5,
) -> list[dict[str, Any]]:
    """기준 대비 달라진 KPI만 (라벨·값·Δ·Δ%·good 여부)."""
    rows: list[dict[str, Any]] = []
    for key, label in KPI_COMPARE_SPECS:
        val = target_kpi.get(key, 0)
        base = baseline_kpi.get(key, 0)
        if not kpi_changed(val, base, threshold_pct=threshold_pct):
            continue
        higher_better = KPI_HIGHER_BETTER.get(key, True)
        if isinstance(val, (int, float)) and isinstance(base, (int, float)):
            delta = val - base
            pct = kpi_delta_pct(val, base)
            good = (delta > 0) == higher_better if delta != 0 else None
        else:
            delta, pct, good = None, None, None
        rows.append(
            {
                "key": key,
                "label": label,
                "value": val,
                "baseline": base,
                "delta": delta,
                "delta_pct": pct,
                "higher_better": higher_better,
                "good": good,
            }
        )
    return rows


def kpi_with_delta(
    val: Any,
    baseline_val: Any,
    is_baseline: bool,
    higher_better: bool = True,
    fmt: str = "{:.1f}",
) -> str:
    """KPI 값 + 기준 대비 Δ%를 한 문자열로 포맷."""
    if isinstance(val, (int, float)) and isinstance(baseline_val, (int, float)):
        val_str = fmt.format(val) if isinstance(val, float) else f"{val:,}"
        if is_baseline:
            return val_str
        if baseline_val == 0:
            return val_str
        delta = val - baseline_val
        delta_pct = delta / baseline_val * 100
        sign = "+" if delta > 0 else ""
        # 의미 부호: higher_better 면 + 가 좋음(▲), 아니면 - 가 좋음(▼)
        good = (delta > 0) == higher_better
        mark = "▲" if good else "▼"
        return f"{val_str}  {mark} {sign}{delta_pct:.1f}%"
    return str(val)
