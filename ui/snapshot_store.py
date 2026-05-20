"""저장된 실행 스냅샷을 사용자 PC 로컬 JSON에 보관해 재접속 후에도 비교 패널에서 쓸 수 있게 한다.

프로젝트(공유 드라이브·네트워크 폴더 등)와 무관하게, OS 사용자별 로컬 데이터 디렉터리에만
기록한다. (Windows: %LOCALAPPDATA%\\scr_sim, Linux/macOS: $XDG_STATE_HOME/scr_sim 또는 ~/.local/state/scr_sim)
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import streamlit as st

from run_compare import MAX_SNAPSHOTS


def _user_snapshot_dir() -> Path:
    """현재 OS 사용자·PC에만 해당하는 앱 데이터 디렉터리."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "scr_sim"
        return Path.home() / "AppData" / "Local" / "scr_sim"
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state) / "scr_sim"
    return Path.home() / ".local" / "state" / "scr_sim"


def snapshots_file() -> Path:
    return _user_snapshot_dir() / "saved_snapshots.json"


def _ensure_snapshot_ids(runs: list[dict[str, Any]]) -> bool:
    """스냅샷마다 고정 id가 있도록 보정한다. 기존 JSON에 id가 없을 때 한 번 부여한다."""
    changed = False
    for r in runs:
        if not isinstance(r, dict):
            continue
        if not r.get("id"):
            r["id"] = uuid.uuid4().hex
            changed = True
    return changed


def load_saved_snapshots() -> tuple[list[dict[str, Any]], int]:
    """디스크에서 스냅샷 목록과 다음 실행 번호를 불러온다."""
    default_runs: list[dict[str, Any]] = []
    default_idx = 1
    path = snapshots_file()
    if not path.is_file():
        return default_runs, default_idx
    try:
        with path.open(encoding="utf-8") as f:
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
    if _ensure_snapshot_ids(runs):
        save_snapshots_to_disk(runs, idx)
    return runs, idx


def save_snapshots_to_disk(runs: list[dict[str, Any]], snapshot_idx: int) -> None:
    """현재 스냅샷 목록·실행 번호를 디스크에 기록한다."""
    payload = {
        "version": 1,
        "snapshot_idx": snapshot_idx,
        "saved_runs": runs,
    }
    path = snapshots_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except OSError as e:
        st.error(f"스냅샷 파일 저장 중 오류: {e}")
