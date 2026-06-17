"""공정 설명 문서에서 추출·적용한 파라미터 기준선 — `local_settings.json`에 저장."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any

import streamlit as st

from config import (
    CastingConfig,
    InboundConfig,
    MeltingConfig,
    OutboundConfig,
    SimulationConfig,
    SortingConfig,
)
from ui.app_settings import load_settings, save_settings

_BASELINE_CONFIG_KEY = "doc_baseline_config"
_BASELINE_MD_HASH_KEY = "doc_baseline_md_sha256"


def md_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_to_storage(cfg: SimulationConfig) -> dict[str, Any]:
    return asdict(cfg)


def config_from_storage(data: dict[str, Any]) -> SimulationConfig:
    return SimulationConfig(
        sim_days=int(data["sim_days"]),
        random_seed=int(data["random_seed"]),
        inbound=InboundConfig(**data["inbound"]),
        sorting=SortingConfig(**data["sorting"]),
        melting=MeltingConfig(**data["melting"]),
        casting=CastingConfig(**data["casting"]),
        outbound=OutboundConfig(**data["outbound"]),
    )


def load_doc_baseline() -> tuple[SimulationConfig | None, str | None]:
    """저장된 문서 기준 Config와 당시 MD 해시를 돌려준다."""
    data = load_settings()
    raw = data.get(_BASELINE_CONFIG_KEY)
    fp = data.get(_BASELINE_MD_HASH_KEY)
    if not isinstance(raw, dict):
        return None, None
    try:
        cfg = config_from_storage(raw)
    except (KeyError, TypeError, ValueError):
        return None, None
    return cfg, str(fp) if fp else None


def save_doc_baseline(cfg: SimulationConfig, md_text: str) -> None:
    data = load_settings()
    data[_BASELINE_CONFIG_KEY] = config_to_storage(cfg)
    data[_BASELINE_MD_HASH_KEY] = md_fingerprint(md_text)
    save_settings(data)


def apply_doc_extract_config(
    cfg: SimulationConfig,
    changes: list[dict[str, str]],
    *,
    md_text: str,
    bump_nonce: bool = True,
) -> None:
    """추출·적용 결과를 세션·로컬 기준선에 반영한다."""
    from llm_config import (
        EXTRACTED_CHANGE_DETAILS_KEY,
        EXTRACTED_CHANGED_LABELS_KEY,
        highlight_from_extract_changes,
    )

    labels, details = highlight_from_extract_changes(changes)
    st.session_state["extracted_config"] = cfg
    st.session_state[EXTRACTED_CHANGED_LABELS_KEY] = labels
    st.session_state[EXTRACTED_CHANGE_DETAILS_KEY] = details
    if bump_nonce:
        st.session_state["config_nonce"] = st.session_state.get("config_nonce", 0) + 1
    save_doc_baseline(cfg, md_text)
