"""저장된 실행 스냅샷을 로컬 JSON에 보관해 재접속 후에도 비교 패널에서 쓸 수 있게 한다."""

from __future__ import annotations

import json
import os
from typing import Any

import streamlit as st

from run_compare import MAX_SNAPSHOTS

SNAPSHOTS_FILE = "saved_snapshots.json"


def load_saved_snapshots() -> tuple[list[dict[str, Any]], int]:
    """디스크에서 스냅샷 목록과 다음 실행 번호를 불러온다."""
    default_runs: list[dict[str, Any]] = []
    default_idx = 1
    if not os.path.exists(SNAPSHOTS_FILE):
        return default_runs, default_idx
    try:
        with open(SNAPSHOTS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_runs, default_idx

    runs: list[dict[str, Any]]
    idx: int
    if isinstance(raw, list):
        runs = raw
        idx = len(runs) + 1
    elif isinstance(raw, dict):
        r = raw.get("saved_runs", [])
        runs = r if isinstance(r, list) else []
        try:
            idx = int(raw.get("snapshot_idx", len(runs) + 1))
        except (TypeError, ValueError):
            idx = len(runs) + 1
    else:
        return default_runs, default_idx

    while len(runs) > MAX_SNAPSHOTS:
        runs.pop(0)
    idx = max(1, idx)
    return runs, idx


def save_snapshots_to_disk(runs: list[dict[str, Any]], snapshot_idx: int) -> None:
    """현재 스냅샷 목록·실행 번호를 디스크에 기록한다."""
    payload = {
        "version": 1,
        "snapshot_idx": snapshot_idx,
        "saved_runs": runs,
    }
    try:
        with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except OSError as e:
        st.error(f"스냅샷 파일 저장 중 오류: {e}")
