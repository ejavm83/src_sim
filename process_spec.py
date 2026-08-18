"""공정 사양(JSON) ↔ 시뮬레이션 설정 변환.

목적: 공정의 구조 — 설비 목록, 라인별 라우팅, 단계 시간, 로트 변환 — 를
**파이썬 코드가 아니라 데이터**로 두는 것. 사양 JSON만 바꾸면 시뮬레이션이
달라지므로, 새 공장을 붙일 때 엔진 코드를 건드리지 않아도 된다.

사양의 정본은 `data/process_spec_*.json`이고, 그 JSON은
① 사람이 직접 편집하거나 ② 공정 설명 MD의 표에서 뽑아 만든다(`spec_from_markdown`).

이 모듈은 구조(무엇이 어떤 설비를 얼마나 쓰는가)만 다룬다. 흐름 규칙 중
산문에만 있는 것(멀티신선 4:1 사이클, 튜블러 병합 등)은 `flow` 섹션에
명시적으로 적는다 — 문서에서 자동으로 알아낼 수 없기 때문이다.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from cms_config import (
    CalendarConfig,
    CmsConfig,
    ConductorConfig,
    Equipment,
    InboundConfig,
    Line,
    PalletConfig,
    Step,
)

SPEC_VERSION = "1.0"
_DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_SPEC_PATH = _DATA_DIR / "process_spec_cms.json"


# ── 설정 → 사양 ───────────────────────────────────────────────────────────


def _equipment_to_spec(eq: Equipment) -> dict[str, Any]:
    return {
        "key": eq.key,
        "label": eq.label,
        "count": eq.count,
        "setup_min": eq.setup_min,
        "shared_by": list(eq.shared_by),
        "tbd_count": eq.tbd_count,
    }


def _step_to_spec(s: Step) -> dict[str, Any]:
    d: dict[str, Any] = {
        "seq": s.seq,
        "label": s.label,
        "equip": s.equip,
        "minutes": s.minutes,
    }
    if s.split != 1:
        d["split"] = s.split
    if s.out_len_m:
        d["out_len_m"] = s.out_len_m
    if s.tbd_time:
        d["tbd_time"] = True
    return d


def config_to_spec(cfg: CmsConfig, *, name: str = "", source_doc: str = "") -> dict[str, Any]:
    """`CmsConfig` → 사양 dict. 코드에 있던 구조를 데이터로 꺼낸다."""
    return {
        "_meta": {
            "spec_version": SPEC_VERSION,
            "name": name or "멕시코 CMS 전선공장",
            "source_doc": source_doc or "공정설명260521.md",
        },
        "calendar": {
            "hours_per_day": cfg.calendar.hours_per_day,
            "weekend_stop_hours": cfg.calendar.weekend_stop_hours,
            "monday_startup_hours": cfg.calendar.monday_startup_hours,
            "availability": cfg.calendar.availability,
        },
        "equipment": [_equipment_to_spec(e) for e in cfg.equipment.values()],
        "routes": {
            key: {"label": line.label, "color": line.color,
                  "steps": [_step_to_spec(s) for s in line.steps]}
            for key, line in cfg.lines().items()
        },
        "inbound": {
            "cu_trucks_per_month": cfg.inbound.cu_trucks_per_month,
            "cu_ton_per_truck": cfg.inbound.cu_ton_per_truck,
            "cu_arrival_window_days": cfg.inbound.cu_arrival_window_days,
            "al_days": cfg.inbound.al_days,
            "al_ton_per_day": cfg.inbound.al_ton_per_day,
            "sil_interval_days": cfg.inbound.sil_interval_days,
            "sil_ton_per_delivery": cfg.inbound.sil_ton_per_delivery,
            "sil_m_per_ton": cfg.inbound.sil_m_per_ton,
        },
        # 산문에만 있어 문서에서 자동 추출이 안 되는 흐름 규칙 (SOP 7.2·5.2)
        "flow": {
            "taeshin": {
                "bobbin_ton": cfg.conductor.taeshin_bobbin_ton,
                "min_per_bobbin": cfg.conductor.taeshin_min_per_bobbin,
                "carriers_per_bobbin": cfg.conductor.carriers_per_bobbin,
            },
            "multi_cycle": {
                "carriers_per_batch": cfg.conductor.multi_carriers_per_batch,
                "cu44": {
                    "repeat": cfg.conductor.cycle_cu44,
                    "minutes": cfg.conductor.multi_cu44_min,
                    "bobbins": cfg.conductor.multi_cu44_bobbins,
                    "len_m": cfg.conductor.multi_cu44_len_m,
                },
                "cu19": {
                    "repeat": cfg.conductor.cycle_cu19,
                    "minutes": cfg.conductor.multi_cu19_min,
                    "bobbins": cfg.conductor.multi_cu19_bobbins,
                    "len_m": cfg.conductor.multi_cu19_len_m,
                },
            },
            "cu19_triple_twist": {
                "bunch_min": cfg.conductor.bunch19_min,
                "strand_min": cfg.conductor.strand19_min,
                "strand_share": 0.5,
                "tubular_min": cfg.conductor.tubular_min,
                "tubular_out_lots": cfg.conductor.tubular_out_lots,
                "tubular_out_len_m": cfg.conductor.tubular_out_len_m,
            },
            "al_multi": {
                "minutes": cfg.conductor.multi_al_min,
                "len_m": cfg.conductor.multi_al_len_m,
            },
        },
        "pallet": {
            "cu44_bobbins_per_pallet": cfg.pallet.cu44_bobbins_per_pallet,
            "cu19_bundles_per_pallet": cfg.pallet.cu19_bundles_per_pallet,
        },
        "scenario": {
            "sim_days": cfg.sim_days,
            "random_seed": cfg.random_seed,
            "cu44_shield_ratio": cfg.cu44_shield_ratio,
            "sil_month_m": cfg.sil_month_m,
        },
    }


# ── 사양 → 설정 ───────────────────────────────────────────────────────────


def _step_from_spec(d: dict[str, Any]) -> Step:
    return Step(
        seq=str(d.get("seq", "")),
        label=str(d.get("label", "")),
        equip=str(d["equip"]),
        minutes=float(d.get("minutes", 0.0)),
        split=int(d.get("split", 1)),
        out_len_m=float(d.get("out_len_m", 0.0)),
        tbd_time=bool(d.get("tbd_time", False)),
    )


def spec_to_config(spec: dict[str, Any]) -> CmsConfig:
    """사양 dict → `CmsConfig`. 라우팅은 `routes`로 주입되어 코드 리터럴을 대체한다."""
    equipment = {
        str(e["key"]): Equipment(
            key=str(e["key"]),
            label=str(e.get("label", e["key"])),
            count=int(e.get("count", 1)),
            setup_min=float(e.get("setup_min", 0.0)),
            shared_by=tuple(e.get("shared_by", ())),
            tbd_count=bool(e.get("tbd_count", False)),
        )
        for e in spec.get("equipment", [])
    }

    routes = {
        key: Line(
            key=key,
            label=str(r.get("label", key)),
            steps=[_step_from_spec(s) for s in r.get("steps", [])],
            color=str(r.get("color", "#4C78A8")),
        )
        for key, r in spec.get("routes", {}).items()
    }

    cal = spec.get("calendar", {})
    inb = spec.get("inbound", {})
    pal = spec.get("pallet", {})
    scn = spec.get("scenario", {})
    flow = spec.get("flow", {})
    tae = flow.get("taeshin", {})
    mc = flow.get("multi_cycle", {})
    m44, m19 = mc.get("cu44", {}), mc.get("cu19", {})
    tw = flow.get("cu19_triple_twist", {})
    alm = flow.get("al_multi", {})

    base = CmsConfig()
    cfg = replace(
        base,
        sim_days=int(scn.get("sim_days", base.sim_days)),
        random_seed=int(scn.get("random_seed", base.random_seed)),
        cu44_shield_ratio=float(scn.get("cu44_shield_ratio", base.cu44_shield_ratio)),
        sil_month_m=float(scn.get("sil_month_m", base.sil_month_m)),
        equipment=equipment or base.equipment,
        calendar=CalendarConfig(
            hours_per_day=float(cal.get("hours_per_day", 24.0)),
            weekend_stop_hours=float(cal.get("weekend_stop_hours", 52.0)),
            monday_startup_hours=float(cal.get("monday_startup_hours", 3.0)),
            availability=float(cal.get("availability", 0.926)),
        ),
        inbound=InboundConfig(
            cu_trucks_per_month=int(inb.get("cu_trucks_per_month", 13)),
            cu_ton_per_truck=float(inb.get("cu_ton_per_truck", 19.8)),
            cu_arrival_window_days=float(inb.get("cu_arrival_window_days", 5.0)),
            al_days=int(inb.get("al_days", 12)),
            al_ton_per_day=float(inb.get("al_ton_per_day", 2.0)),
            sil_interval_days=float(inb.get("sil_interval_days", 14.0)),
            sil_ton_per_delivery=float(inb.get("sil_ton_per_delivery", 5.0)),
            sil_m_per_ton=float(inb.get("sil_m_per_ton", 14_000.0)),
        ),
        conductor=ConductorConfig(
            taeshin_bobbin_ton=float(tae.get("bobbin_ton", 3.3)),
            taeshin_min_per_bobbin=float(tae.get("min_per_bobbin", 60.0)),
            carriers_per_bobbin=int(tae.get("carriers_per_bobbin", 3)),
            multi_carriers_per_batch=int(mc.get("carriers_per_batch", 24)),
            multi_cu44_min=float(m44.get("minutes", 83.3)),
            multi_cu44_bobbins=int(m44.get("bobbins", 9)),
            multi_cu44_len_m=float(m44.get("len_m", 100_000)),
            multi_cu19_min=float(m19.get("minutes", 66.7)),
            multi_cu19_bobbins=int(m19.get("bobbins", 11)),
            multi_cu19_len_m=float(m19.get("len_m", 80_000)),
            cycle_cu44=int(m44.get("repeat", 4)),
            cycle_cu19=int(m19.get("repeat", 1)),
            bunch19_min=float(tw.get("bunch_min", 800.0)),
            strand19_min=float(tw.get("strand_min", 1333.3)),
            tubular_min=float(tw.get("tubular_min", 181.8)),
            tubular_out_lots=int(tw.get("tubular_out_lots", 4)),
            tubular_out_len_m=float(tw.get("tubular_out_len_m", 20_000)),
            multi_al_min=float(alm.get("minutes", 144.0)),
            multi_al_len_m=float(alm.get("len_m", 40_000)),
        ),
        pallet=PalletConfig(
            cu44_bobbins_per_pallet=int(pal.get("cu44_bobbins_per_pallet", 18)),
            cu19_bundles_per_pallet=int(pal.get("cu19_bundles_per_pallet", 45)),
        ),
        routes=routes or None,
    )
    return cfg


# ── 파일 입출력 ───────────────────────────────────────────────────────────


def load_spec(path: Path | str = DEFAULT_SPEC_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_spec(spec: dict[str, Any], path: Path | str = DEFAULT_SPEC_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load_config(path: Path | str = DEFAULT_SPEC_PATH) -> CmsConfig:
    """사양 파일에서 바로 시뮬레이션 설정을 만든다."""
    return spec_to_config(load_spec(path))


def validate_spec(spec: dict[str, Any]) -> list[str]:
    """사양의 앞뒤가 맞는지 확인하고 문제 목록을 돌려준다(빈 목록이면 정상)."""
    problems: list[str] = []
    keys = {str(e.get("key")) for e in spec.get("equipment", [])}

    if not keys:
        problems.append("설비 목록(`equipment`)이 비어 있습니다.")

    for line_key, route in spec.get("routes", {}).items():
        steps = route.get("steps", [])
        if not steps:
            problems.append(f"라인 `{line_key}`에 공정 단계가 없습니다.")
        for i, s in enumerate(steps):
            equip = s.get("equip")
            if equip not in keys:
                problems.append(
                    f"라인 `{line_key}` {i + 1}번째 단계 「{s.get('label', '?')}」가 "
                    f"설비 목록에 없는 `{equip}`를 가리킵니다."
                )
            if float(s.get("minutes", 0)) <= 0:
                problems.append(
                    f"라인 `{line_key}` 「{s.get('label', '?')}」의 단계 시간이 0입니다."
                )

    cal = spec.get("calendar", {})
    av = float(cal.get("availability", 0.926))
    if not 0 < av <= 1:
        problems.append(f"실효 가동률이 0~1 범위를 벗어났습니다: {av}")

    return problems
