"""logistics_process ↔ SimulationConfig 브리지.

표준 JSON(L1 확장)의 `logistics_process` 섹션과 시뮬레이션 설정을 동기화한다.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Any

from config import (
    CastingConfig,
    InboundConfig,
    MeltingConfig,
    OutboundConfig,
    SimulationConfig,
    SortingConfig,
)

LOGISTICS_KEY = "logistics_process"

_SUBSECTIONS: tuple[tuple[str, type], ...] = (
    ("inbound", InboundConfig),
    ("sorting", SortingConfig),
    ("melting", MeltingConfig),
    ("casting", CastingConfig),
    ("outbound", OutboundConfig),
)


def build_logistics_section(cfg: SimulationConfig | None = None) -> dict[str, Any]:
    """SimulationConfig → 표준 JSON `logistics_process` 섹션."""
    cfg = cfg or SimulationConfig()
    section: dict[str, Any] = {
        "description": "하이브리드 물류 시뮬레이션 파라미터 (시간=분, 중량=톤)",
        "unit_convention": {"time": "min", "weight": "t", "ratio": "0~1"},
    }
    for name, cls in _SUBSECTIONS:
        section[name] = asdict(getattr(cfg, name))
    section["simulation"] = {
        "sim_days": cfg.sim_days,
        "random_seed": cfg.random_seed,
    }
    return section


def _subsection_from_dict(data: dict[str, Any] | None, cls: type) -> Any:
    if not isinstance(data, dict):
        return cls()
    allowed = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in allowed})


def logistics_to_config(section: dict[str, Any] | None) -> SimulationConfig:
    """표준 JSON `logistics_process` → SimulationConfig."""
    if not isinstance(section, dict):
        return SimulationConfig()
    sim = section.get("simulation") if isinstance(section.get("simulation"), dict) else {}
    kwargs: dict[str, Any] = {}
    for name, cls in _SUBSECTIONS:
        kwargs[name] = _subsection_from_dict(section.get(name), cls)
    if isinstance(sim.get("sim_days"), int):
        kwargs["sim_days"] = sim["sim_days"]
    if isinstance(sim.get("random_seed"), int):
        kwargs["random_seed"] = sim["random_seed"]
    return SimulationConfig(**kwargs)


def ensure_logistics_section(schema: dict[str, Any], cfg: SimulationConfig | None = None) -> dict[str, Any]:
    """스키마에 `logistics_process`가 없으면 기본 섹션을 채운다."""
    if LOGISTICS_KEY not in schema:
        schema[LOGISTICS_KEY] = build_logistics_section(cfg)
    return schema
