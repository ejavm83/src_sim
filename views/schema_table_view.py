"""표준 공정 JSON을 한글 항목명 트리 표로 표시·편집한다.

모든 항목을 펼쳐서 보여주며, '값' 칸을 직접 고친 뒤 JSON으로 내보낼 수 있다.
📐 표준 JSON 탭에서 MD 추출 결과가 있으면 그 결과를, 없으면 표준 베이스를 보여준다.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pandas as pd
import streamlit as st

from schema_extract import load_base_schema

_EDITOR_KEY = "schema_tbl_editor"
_SRC_HASH_KEY = "_tbl_src_hash"
_ORIG_ROWS_KEY = "_tbl_orig_rows"
_EXPAND_ALL_KEY = "schema_tbl_expand_all"
_FILTER_KEY = "schema_tbl_section_filter"
_INDENT = "    "

# ─── 한글 레이블 ─────────────────────────────────────────────────────────────────
_KO: dict[str, str] = {
    # 최상위 섹션
    "_meta": "메타 정보",
    "product_master": "제품 마스터",
    "bom": "자재명세서 (BOM)",
    "process_routing": "공정 라우팅",
    "work_order": "작업 지시",
    "lot_tracking": "로트 추적",
    "equipment_master": "설비 마스터",
    "recipe": "레시피",
    "quality": "품질 기준",
    "workforce": "인력 / 교대",
    "production_plan": "생산 계획",
    "logistics_process": "물류 시뮬레이션",
    "simulation_config": "시뮬레이션 설정",
    # 메타
    "schema_version": "스키마 버전",
    "industry": "산업 분야",
    "created_by": "작성자",
    "created_at": "작성일",
    "last_modified_by": "최종 수정자",
    "last_modified_at": "최종 수정일",
    "history": "이력",
    # 제품 마스터
    "product_id": "제품 ID",
    "product_name": "제품명",
    "product_type": "제품 유형",
    "unit": "단위",
    "standard_weight": "표준 중량 (kg/m)",
    "outer_diameter": "외경 (mm)",
    "description": "설명",
    "status": "상태",
    "cable_design": "케이블 설계",
    # 도체
    "conductor": "도체",
    "material": "재질",
    "cross_section": "단면적 (mm²)",
    "wire_count": "소선 수",
    "wire_diameter": "소선 직경 (mm)",
    "stranding_type": "연선 방식",
    "lay_direction": "연입 방향",
    # 절연
    "insulation": "절연",
    "thickness": "두께 (mm)",
    "core_count": "심 수",
    "color_sequence": "색상 배열",
    # 성케이블
    "cabling": "성케이블 (연합)",
    "pitch": "피치 (mm)",
    "filler": "충진재 사용",
    "tape": "테이프 사용",
    # 시스
    "sheath": "시스 (외피)",
    "color": "색상",
    # BOM
    "version": "버전",
    "components": "구성 부품",
    "component_id": "부품 ID",
    "component_name": "부품명",
    "component_type": "부품 유형",
    "quantity": "수량",
    "loss_rate": "손실률",
    "parent_id": "상위 부품 ID",
    # 공정 라우팅
    "steps": "공정 단계",
    "step_no": "단계 번호",
    "process_id": "공정 ID",
    "process_name": "공정명",
    "input_item_id": "투입 품목 ID",
    "input_qty_per": "단위 투입량",
    "output_item_id": "산출 품목 ID",
    "equipment_group": "설비 그룹",
    "std_speed": "표준 속도 (m/min)",
    "std_time_per": "단위 표준 시간 (h/m)",
    "flow_type": "흐름 유형",
    "next_steps": "다음 단계",
    "condition": "조건",
    "parallel_group_id": "병렬 그룹 ID",
    "join_condition": "합류 조건",
    "production_type": "생산 유형",
    # 페이오프 / 테이크업
    "pay_off": "공급 장치 (페이오프)",
    "input_count": "투입 보빈 수",
    "min_length": "최소 길이 (m)",
    "change_time": "교체 시간 (분)",
    "take_up": "권취 장치 (테이크업)",
    "max_length": "최대 길이 (m)",
    "traverse": "트래버스 사용",
    # 케이블 공정 파라미터
    "cable_process": "케이블 공정 파라미터",
    "drawing": "신선 (Wire Drawing)",
    "die_sequence": "다이 순서",
    "stage": "다이 단계",
    "die_diameter": "다이 직경 (mm)",
    "reduction_rate": "단면 압축률",
    "lubricant": "윤활제",
    "cooling_temp": "냉각 온도 (℃)",
    "annealing": "소둔 처리",
    "stranding": "연선 (Stranding)",
    "bobbin_count": "보빈 수",
    "tension_per_wire": "소선당 장력 (N)",
    "bind_wire": "결속선 사용",
    "extrusion": "압출 (Extrusion)",
    "die_size": "다이 크기",
    "nipple_size": "니플 크기",
    "draw_ratio": "드로우 비율",
    "cooling_water_temp": "냉각수 온도 (℃)",
    "cooling_length": "냉각 구간 길이 (m)",
    "material_lot": "원료 로트",
    # 작업 지시
    "wo_id": "작업지시 ID",
    "priority": "우선순위",
    "order_date": "주문일",
    "due_date": "납기일",
    "plan_id": "계획 ID",
    "note": "비고",
    # 로트 추적
    "lot_id": "로트 ID",
    "item_id": "품목 ID",
    "equipment_id": "설비 ID",
    "input_lots": "투입 로트",
    "output": "산출",
    "weight": "중량 (kg)",
    "reel_id": "릴 ID",
    "reel_info": "릴 정보",
    "reel_type": "릴 유형",
    "reel_weight": "릴 자체 중량 (kg)",
    "gross_weight": "총 중량 (kg)",
    "net_weight": "순 중량 (kg)",
    "length": "길이 (m)",
    "length_tracking": "길이 추적",
    "input_length": "투입 길이 (m)",
    "output_length": "산출 길이 (m)",
    "loss_length": "손실 길이 (m)",
    "next_process_id": "다음 공정 ID",
    # 설비 마스터
    "equipment_name": "설비명",
    "equipment_type": "설비 유형",
    "group_id": "그룹 ID",
    "capable_range": "가공 가능 범위",
    "cross_section_min": "최소 단면적 (mm²)",
    "cross_section_max": "최대 단면적 (mm²)",
    "outer_dia_max": "최대 외경 (mm)",
    "speed_min": "최소 속도 (m/min)",
    "speed_max": "최대 속도 (m/min)",
    "payoff": "공급 장치",
    "max_weight": "최대 중량 (kg)",
    "max_diameter": "최대 직경 (mm)",
    "holder_count": "홀더 수",
    "takeup": "권취 장치",
    "continuous_production": "연속 생산",
    "is_continuous": "연속 생산 여부",
    "min_run_length": "최소 연속 생산 길이 (m)",
    "reel_change_time": "릴 교체 시간 (분)",
    "line_speed_unit": "속도 단위",
    # 레시피
    "recipe_id": "레시피 ID",
    "speed": "속도",
    "fixed": "고정 속도",
    "variable": "가변 속도 범위",
    "min": "최솟값",
    "max": "최댓값",
    "distribution": "분포 형태",
    "mode": "속도 모드",
    "setup_time": "준비 시간 (분)",
    "length_factor": "길이 계수",
    "input_per_output": "투입 / 산출 비율",
    "cable_recipe": "케이블 레시피",
    "temperature_profile": "온도 프로파일",
    "zone": "구역",
    "value": "설정값",
    # 품질
    "quality_id": "품질 기준 ID",
    "inspection_items": "검사 항목",
    "item_name": "검사명",
    "nominal": "기준값",
    "upper_limit": "상한",
    "lower_limit": "하한",
    "method": "검사 방법",
    "frequency": "검사 주기",
    "defect_types": "불량 유형",
    "defect_id": "불량 ID",
    "defect_name": "불량명",
    "defect_rate": "불량률",
    "action": "조치",
    # 인력/교대
    "shifts": "교대 근무",
    "shift_id": "교대 ID",
    "shift_name": "교대명",
    "start_time": "시작 시간",
    "end_time": "종료 시간",
    "work_days": "근무 요일",
    "assignments": "인력 배치",
    "headcount": "인원 수",
    "skill_level": "숙련도",
    # 생산 계획
    "plan_name": "계획명",
    "period": "기간",
    "start_date": "시작일",
    "end_date": "종료일",
    "daily_plan": "일별 계획",
    "date": "날짜",
    "items": "품목 계획",
    "target_qty": "목표 수량",
    "monthly_summary": "월별 요약",
    "total_target": "총 목표 수량",
    # 물류 시뮬레이션
    "unit_convention": "단위 규약",
    "time": "시간 단위",
    "weight": "중량 단위",
    "ratio": "비율 표기",
    "simulation": "시뮬레이션 실행",
    "sim_days": "시뮬레이션 기간 (일)",
    "inbound": "① 입고 / 하역",
    "sorting": "② 선별 / 압착",
    "melting": "③ 장입 / 용해",
    "casting": "④ 하이브리드 주조",
    "outbound": "⑤ 출하",
    "trucks_per_day": "일 입고 트럭 수",
    "truck_load_ton": "트럭 적재량 (t)",
    "arrival_start_min": "입고 도착 시작 (분, 자정 기준)",
    "arrival_end_min": "입고 도착 종료 (분)",
    "morning_cutoff_min": "오전·오후 구분 시각 (분)",
    "morning_share": "오전 도착 비율",
    "weigh_in_min": "1차 계근 시간 (분)",
    "weigh_out_min": "2차 계근 시간 (분)",
    "unload_min": "하역 시간 (분/대)",
    "unloading_bays": "하역 베이 수",
    "weighbridges": "계근대 수",
    "sort_min_per_truck": "트럭당 선별 시간 (분)",
    "subpiles_per_truck": "트럭당 sub-pile 수",
    "subpile_ton": "sub-pile 중량 (t)",
    "blocks_per_subpile": "sub-pile당 블록 수",
    "block_ton": "블록 중량 (t)",
    "forklift_min_per_block": "지게차 이송 (분/블록)",
    "press_min_per_block": "압착 (분/블록)",
    "pallet_load_min_per_block": "파레트 적재 (분/블록)",
    "sorters": "선별 작업조 수",
    "presses": "압착기 대수",
    "pallet_buffer_cap": "파레트 버퍼 용량",
    "batch_ton": "배치 톤수 (t)",
    "pallet_ton": "파레트 단위 중량 (t)",
    "elevator_pallets_per_trip": "엘리베이터 1회 적재 (파레트)",
    "elevator_cycle_min": "엘리베이터 왕복 시간 (분)",
    "setup_min": "배치 사전 준비 (분)",
    "melting_min": "용해·정련 시간 (분)",
    "furnace_count": "반사로 대수",
    "elevator_count": "엘리베이터 대수",
    "flake_ratio": "큐프레이크 생산 비율",
    "flake_unit_ton": "큐프레이크 단위 (t)",
    "flake_min_per_unit": "큐프레이크 단위 시간 (분)",
    "scr_unit_ton": "SCR 단위 (t)",
    "scr_min_per_unit": "SCR 단위 시간 (분)",
    "holding_setup_min": "홀딩로 셋업 (분)",
    "flake_buffer_cap": "큐프레이크 야적 버퍼",
    "scr_buffer_cap": "SCR 야적 버퍼",
    "truck_interval_min": "출하 트럭 평균 간격 (분)",
    "truck_capacity_ton": "출하 트럭 적재 (t)",
    "flake_truck_prob": "큐프레이크 출하 확률",
    "load_min": "상차 시간 (분)",
    "max_wait_min": "재고 대기 한도 (분)",
    # 시뮬레이션 설정
    "config_id": "설정 ID",
    "config_name": "설정명",
    "duration_days": "시뮬레이션 기간 (일)",
    "time_unit": "시간 단위",
    "speed_mode": "속도 모드",
    "include_breakdown": "설비 고장 포함",
    "include_pm": "예방정비 포함",
    "defect_mode": "불량 모드",
    "objective": "최적화 목표",
    "primary": "1순위 목표",
    "secondary": "2순위 목표",
    "tertiary": "3순위 목표",
    "repeat_count": "반복 횟수",
    "random_seed": "난수 시드",
}

# 최상위 섹션 아이콘
_SECTION_ICON: dict[str, str] = {
    "_meta": "ℹ️",
    "product_master": "📦",
    "bom": "🧾",
    "process_routing": "🔁",
    "work_order": "📋",
    "lot_tracking": "🏷️",
    "equipment_master": "⚙️",
    "recipe": "🧪",
    "quality": "✅",
    "workforce": "👷",
    "production_plan": "📅",
    "logistics_process": "🚛",
    "simulation_config": "🖥️",
}


def _ko(key: str) -> str:
    return _KO.get(str(key), str(key).replace("_", " "))


# ─── JSON → 행 목록 ───────────────────────────────────────────────────────────────

def _val_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    return str(v)


def _item_display(row: dict) -> str:
    """깊이 기반 들여쓰기로 트리 항목을 표시한다."""
    pad = _INDENT * row["_depth"]
    label = row["_label"]
    if row["_is_leaf"]:
        return f"{pad}{label}"
    return f"{pad}▸ {label}"


def _flatten(
    obj: Any,
    path: str,
    depth: int,
    section: str,
    rows: list[dict],
) -> None:
    if isinstance(obj, dict):
        items = list(obj.items())
        for k, v in items:
            child_path = f"{path}.{k}" if path else k
            label = _ko(k)
            sec_key = section or k

            if isinstance(v, (dict, list)):
                child_count = len(v)
                rows.append({
                    "분류": _ko(sec_key) if depth == 0 else _ko(section),
                    "항목": _item_display({
                        "_depth": depth,
                        "_label": label,
                        "_is_leaf": False,
                    }),
                    "값": f"({child_count}개 항목)" if child_count else "",
                    "_path": child_path,
                    "_section_key": sec_key,
                    "_depth": depth,
                    "_label": label,
                    "_is_leaf": False,
                    "_orig": None,
                })
                _flatten(v, child_path, depth + 1, sec_key, rows)
            else:
                rows.append({
                    "분류": _ko(section),
                    "항목": _item_display({
                        "_depth": depth,
                        "_label": label,
                        "_is_leaf": True,
                    }),
                    "값": _val_str(v),
                    "_path": child_path,
                    "_section_key": sec_key,
                    "_depth": depth,
                    "_label": label,
                    "_is_leaf": True,
                    "_orig": v,
                })

    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            child_path = f"{path}[{i}]"
            idx_label = f"[{i + 1}번]"

            if isinstance(v, (dict, list)):
                child_count = len(v)
                rows.append({
                    "분류": _ko(section),
                    "항목": _item_display({
                        "_depth": depth,
                        "_label": idx_label,
                        "_is_leaf": False,
                    }),
                    "값": f"({child_count}개 항목)" if child_count else "",
                    "_path": child_path,
                    "_section_key": section,
                    "_depth": depth,
                    "_label": idx_label,
                    "_is_leaf": False,
                    "_orig": None,
                })
                _flatten(v, child_path, depth + 1, section, rows)
            else:
                rows.append({
                    "분류": _ko(section),
                    "항목": _item_display({
                        "_depth": depth,
                        "_label": idx_label,
                        "_is_leaf": True,
                    }),
                    "값": _val_str(v),
                    "_path": child_path,
                    "_section_key": section,
                    "_depth": depth,
                    "_label": idx_label,
                    "_is_leaf": True,
                    "_orig": v,
                })


def json_to_rows(obj: dict) -> list[dict]:
    rows: list[dict] = []
    _flatten(obj, "", 0, "", rows)
    return rows


def _section_order(rows: list[dict]) -> list[str]:
    seen: list[str] = []
    for r in rows:
        key = r["_section_key"]
        if key not in seen:
            seen.append(key)
    return seen


def _rows_for_section(rows: list[dict], section_key: str) -> list[dict]:
    sec_rows = [r for r in rows if r["_section_key"] == section_key]
    if (
        sec_rows
        and sec_rows[0]["_depth"] == 0
        and not sec_rows[0]["_is_leaf"]
        and len(sec_rows) > 1
    ):
        return sec_rows[1:]
    return sec_rows


def _section_title(section_key: str, sec_rows: list[dict]) -> str:
    icon = _SECTION_ICON.get(section_key, "📁")
    name = _ko(section_key)
    leaves = sum(1 for r in sec_rows if r["_is_leaf"])
    return f"{icon} {name} · 편집 {leaves}건 · {len(sec_rows)}행"


def _merge_editor_states(orig_rows: list[dict], section_keys: list[str]) -> dict | None:
    """섹션별 data_editor 상태를 전역 행 인덱스로 합친다."""
    path_to_idx = {r["_path"]: i for i, r in enumerate(orig_rows)}
    merged: dict[str, dict] = {}

    for sec_key in section_keys:
        sec_rows = _rows_for_section(orig_rows, sec_key)
        editor = st.session_state.get(f"{_EDITOR_KEY}_{sec_key}")
        if not editor:
            continue
        for pos_str, changes in (editor.get("edited_rows") or {}).items():
            try:
                local_idx = int(pos_str)
            except (TypeError, ValueError):
                continue
            if local_idx < 0 or local_idx >= len(sec_rows):
                continue
            global_idx = path_to_idx.get(sec_rows[local_idx]["_path"])
            if global_idx is None:
                continue
            merged[str(global_idx)] = changes

    return {"edited_rows": merged} if merged else None


def _inject_page_css() -> None:
    st.markdown(
        """
<style>
.schema-tbl-metrics {
    display: flex; flex-wrap: wrap; gap: 0.5rem 1.25rem;
    padding: 0.55rem 0.85rem; margin-bottom: 0.65rem;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    font-size: 0.82rem; color: #475569;
}
.schema-tbl-metrics strong { color: #0f172a; }
.schema-tbl-banner {
    border-left: 4px solid #3b82f6; border-radius: 6px;
    padding: 0.55rem 0.85rem; margin-bottom: 0.75rem;
    background: #eff6ff; color: #1e40af; font-size: 0.88rem; line-height: 1.45;
}
div[data-testid="stExpander"]:has(.schema-tbl-section) {
    border: 1px solid #e2e8f0; border-radius: 8px;
    background: #fafbfc; margin-bottom: 0.35rem;
}
div[data-testid="stExpander"]:has(.schema-tbl-section) summary {
    font-weight: 600; font-size: 0.92rem;
}
div[data-testid="stExpander"]:has(.schema-tbl-section) [data-testid="stDataFrame"],
div[data-testid="stExpander"]:has(.schema-tbl-section) [data-testid="stDataEditor"] {
    font-size: 0.86rem;
}
.schema-tbl-section-key {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 0.75rem; color: #64748b; margin-top: -0.25rem; margin-bottom: 0.35rem;
}
</style>
        """.strip(),
        unsafe_allow_html=True,
    )


# ─── 편집된 행 → JSON ─────────────────────────────────────────────────────────────

def rows_to_json(base: dict, orig_rows: list[dict], editor_state: dict | None) -> dict:
    """편집된 값을 base JSON 사본에 적용해 돌려준다."""
    from schema_extract import _coerce_like, _navigate, _parse_path

    updated = copy.deepcopy(base)
    if not editor_state:
        return updated

    edited = editor_state.get("edited_rows") or {}
    for pos_str, changes in edited.items():
        try:
            idx = int(pos_str)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(orig_rows):
            continue
        row = orig_rows[idx]
        if not row["_is_leaf"]:
            continue
        if "값" not in changes:
            continue

        path = row["_path"]
        toks = _parse_path(path)
        if not toks:
            continue
        ok, old = _navigate(updated, toks)
        if not ok or isinstance(old, (dict, list)):
            continue
        ok2, parent = _navigate(updated, toks[:-1]) if len(toks) > 1 else (True, updated)
        if not ok2:
            continue
        new_val = _coerce_like(str(changes["값"]), old)
        try:
            parent[toks[-1]] = new_val
        except Exception:
            pass

    return updated


# ─── 렌더링 ───────────────────────────────────────────────────────────────────────

def _path_matches(path: str, roots: set[str]) -> bool:
    for root in roots:
        if path == root or path.startswith(root + ".") or path.startswith(root + "["):
            return True
    return False


def _render_section_editor(
    section_key: str,
    sec_rows: list[dict],
    md_paths: set[str],
    ai_paths: set[str],
    *,
    expanded: bool,
) -> None:
    def _marker(row: dict) -> str:
        path = row["_path"]
        if _path_matches(path, md_paths):
            return "🟢"
        if path in ai_paths:
            return "🔄"
        for ap in ai_paths:
            if path.startswith(ap):
                return "🆕"
        return ""

    display_df = pd.DataFrame(
        [{
            "": _marker(r),
            "항목": r["항목"],
            "값": r["값"],
        } for r in sec_rows]
    )
    row_h = 32
    table_h = min(len(sec_rows) * row_h + 42, 420 if len(sec_rows) > 8 else len(sec_rows) * row_h + 42)

    with st.expander(_section_title(section_key, sec_rows), expanded=expanded):
        st.markdown(
            f'<div class="schema-tbl-section"></div>'
            f'<div class="schema-tbl-section-key">{section_key}</div>',
            unsafe_allow_html=True,
        )
        st.data_editor(
            display_df,
            key=f"{_EDITOR_KEY}_{section_key}",
            use_container_width=True,
            hide_index=True,
            disabled=["", "항목"],
            column_config={
                "": st.column_config.TextColumn("", width=28),
                "항목": st.column_config.TextColumn(
                    "항목",
                    width="large",
                    help="필드 이름 — 들여쓰기로 계층을 나타냅니다.",
                ),
                "값": st.column_config.TextColumn(
                    "값",
                    width="medium",
                    help="이 칸만 수정할 수 있습니다. 그룹 행(▸, 괄호 표시)은 건드리지 마세요.",
                ),
            },
            height=table_h,
        )


def render_page() -> None:
    _inject_page_css()

    st.header("📋 공정 데이터")
    st.caption(
        "표준 공정 JSON을 **섹션별·한글 트리**로 표시합니다. "
        "'값'만 수정한 뒤 **JSON보내기**로 저장하세요. "
        "MD 추출 변경은 🟢, **💬 AI 어시스턴트** 변경은 🔄 열에 표시됩니다."
    )

    # 소스 JSON 결정
    result = st.session_state.get("std_schema_result")
    if isinstance(result, dict) and "updated" in result:
        src_json = result["updated"]
        source_note = "📐 표준 JSON 탭에서 추출·갱신된 데이터를 표시합니다."
    else:
        src_json = load_base_schema()
        source_note = "표준 베이스 JSON입니다. 📐 표준 JSON 탭에서 MD 추출 후 여기 반영됩니다."

    st.markdown(f'<div class="schema-tbl-banner">{source_note}</div>', unsafe_allow_html=True)

    # MD 추출·AI 어시스턴트가 수정한 경로 세트
    md_paths: set[str] = st.session_state.get("_md_extract_changed_paths") or set()
    if not md_paths and isinstance(result, dict):
        md_paths = {d["경로"] for d in (result.get("diffs") or []) if d.get("경로")}
    ai_paths: set[str] = st.session_state.get("_ai_changed_paths") or set()

    # MD 추출 변경 배너
    if md_paths:
        md_diffs = (result or {}).get("diffs") or [] if isinstance(result, dict) else []
        lines = []
        for d in md_diffs[:10]:
            if d.get("경로") in md_paths:
                lines.append(
                    f"- `{d['경로']}` : ~~{d.get('표준값', '?')}~~ → **{d.get('추출값', '?')}**"
                )
        with st.container():
            st.markdown(
                f"""
<div style="border:2px solid #22c55e;border-radius:8px;padding:0.75rem 1rem;
background:linear-gradient(135deg,#f0fdf4,#dcfce7);margin-bottom:0.75rem;">
  <div style="font-weight:700;color:#166534;font-size:1rem;">
    🟢 MD 추출로 갱신된 항목 — {len(md_paths)}개 경로 (표에서 🟢 표시)
  </div>
  <div style="color:#15803d;font-size:0.85rem;margin-top:0.4rem;">
    {'<br>'.join(lines) if lines else '변경 경로가 표에 반영되었습니다.'}
  </div>
</div>
                """.strip(),
                unsafe_allow_html=True,
            )
        c1, _ = st.columns([1, 4])
        with c1:
            if st.button("✔️ MD 강조 해제", key="md_paths_clear", use_container_width=True):
                st.session_state.pop("_md_extract_changed_paths", None)
                st.rerun()

    # AI 수정 내역 배너
    if ai_paths:
        ai_diffs = (result or {}).get("diffs") or [] if isinstance(result, dict) else []
        recent = [d for d in ai_diffs if d.get("경로") in ai_paths]
        lines = []
        for d in recent[:8]:
            lines.append(f"- `{d['경로']}` : **{d['표준값']}** → **{d['추출값']}**")
        patch_paths = [p for p in ai_paths if not any(d.get("경로") == p for d in ai_diffs)]
        for p in patch_paths[:4]:
            lines.append(f"- `{p}` (구조 변경)")

        with st.container():
            st.markdown(
                f"""
<div style="border:2px solid #22c55e;border-radius:8px;padding:0.75rem 1rem;
background:linear-gradient(135deg,#f0fdf4,#dcfce7);margin-bottom:0.75rem;">
  <div style="font-weight:700;color:#166534;font-size:1rem;">
    ✅ AI 어시스턴트가 JSON을 수정했습니다 — {len(ai_paths)}개 경로 변경
  </div>
  <div style="color:#15803d;font-size:0.85rem;margin-top:0.4rem;">
    {'<br>'.join(lines) if lines else '구조 변경 포함'}
  </div>
</div>
                """.strip(),
                unsafe_allow_html=True,
            )
        if st.button("✔️ 확인 (강조 해제)", key="ai_paths_clear", use_container_width=False):
            st.session_state.pop("_ai_changed_paths", None)
            st.rerun()

    # 소스가 바뀌면 행 목록 재생성
    src_id = id(src_json)
    if st.session_state.get(_SRC_HASH_KEY) != src_id:
        st.session_state[_SRC_HASH_KEY] = src_id
        st.session_state[_ORIG_ROWS_KEY] = json_to_rows(src_json)
        for key in list(st.session_state.keys()):
            if isinstance(key, str) and key.startswith(f"{_EDITOR_KEY}_"):
                st.session_state.pop(key, None)
        st.session_state.pop(_EDITOR_KEY, None)

    orig_rows: list[dict] = st.session_state[_ORIG_ROWS_KEY]
    section_keys = _section_order(orig_rows)
    leaf_total = sum(1 for r in orig_rows if r["_is_leaf"])

    st.markdown(
        f'<div class="schema-tbl-metrics">'
        f"<span><strong>{len(section_keys)}</strong>개 섹션</span>"
        f"<span>편집 가능 <strong>{leaf_total}</strong>건</span>"
        f"<span>전체 <strong>{len(orig_rows)}</strong>행</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    tool_c1, tool_c2, tool_c3 = st.columns([2, 2, 1])
    with tool_c1:
        filter_sel = st.multiselect(
            "섹션 필터",
            options=section_keys,
            default=section_keys,
            format_func=lambda k: f"{_SECTION_ICON.get(k, '📁')} {_ko(k)}",
            key=_FILTER_KEY,
            placeholder="표시할 섹션 선택",
        )
    with tool_c2:
        search_q = st.text_input(
            "항목·값 검색",
            placeholder="예: 트럭, product_id, 7",
            key="schema_tbl_search",
        ).strip().lower()
    with tool_c3:
        expand_all = st.toggle("모두 펼치기", key=_EXPAND_ALL_KEY)

    visible_keys = [k for k in section_keys if k in filter_sel]
    if search_q:
        matched: list[str] = []
        for sec_key in visible_keys:
            sec_rows = _rows_for_section(orig_rows, sec_key)
            if any(
                search_q in r["항목"].lower()
                or search_q in r["값"].lower()
                or search_q in r["_path"].lower()
                for r in sec_rows
            ):
                matched.append(sec_key)
        visible_keys = matched
        if not visible_keys:
            st.warning(f"검색어 '{search_q}'에 맞는 항목이 없습니다.")
            return

    default_open = {"_meta", "logistics_process", "product_master"}
    for sec_key in visible_keys:
        sec_rows = _rows_for_section(orig_rows, sec_key)
        if search_q:
            sec_rows = [
                r for r in sec_rows
                if search_q in r["항목"].lower()
                or search_q in r["값"].lower()
                or search_q in r["_path"].lower()
            ]
        if not sec_rows:
            continue
        expanded = expand_all or sec_key in default_open or bool(search_q)
        _render_section_editor(sec_key, sec_rows, md_paths, ai_paths, expanded=expanded)

    # 편집 결과로 JSON 재구성
    editor_state = _merge_editor_states(orig_rows, section_keys)
    result_json = rows_to_json(src_json, orig_rows, editor_state)

    changed = sum(
        1
        for pos_str, changes in (editor_state or {}).get("edited_rows", {}).items()
        if "값" in changes
    )

    st.divider()
    col1, col2 = st.columns([1, 3])
    with col1:
        st.download_button(
            f"⬇️ JSON 내보내기{f'  ({changed}건 수정)' if changed else ''}",
            data=json.dumps(result_json, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="process_standard_edited.json",
            mime="application/json",
            type="primary",
            use_container_width=True,
        )
    with col2:
        if changed:
            st.caption(f"✏️ {changed}개 항목이 수정되었습니다. 내보내기를 눌러 저장하세요.")
        else:
            st.caption("값을 수정하면 수정 건수가 표시되고 내보내기 버튼이 활성화됩니다.")
