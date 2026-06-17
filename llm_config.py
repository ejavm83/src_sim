"""공정 설명 Markdown(자연어)에서 SimulationConfig 파라미터를 추출한다.

`excel_config.py`(엑셀→Config)의 자연어 버전이다. Gemini structured JSON으로
문서 본문에 흩어진 숫자를 구조화된 파라미터로 뽑아, 기존값과의 변경 내역(diff)과
함께 돌려준다. 호출 측(공정 설명 탭)이 diff를 보여주고 사용자가 승인하면 적용한다.

필요: 환경변수 `GEMINI_API_KEY`, 패키지 `google-genai`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from typing import Any

from config import SimulationConfig
from config_sanitize import sanitize_for_simulation

# `GEMINI_MODEL`이 있으면 해당 모델만, 없으면 아래 후보를 순서대로 시도한다.
_DEFAULT_MODELS = ("gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.0-flash-lite")
_RETRYABLE_CODES = frozenset({429, 500, 503})
_RETRY_DELAYS_SEC = (1.0, 2.0, 4.0)

# config.py의 SimulationConfig 필드를 그대로 반영한다.
# (json_key, (subconfig_attr, field_name), json_type, 라벨, 단위, 힌트)
# 파생값(배치당 파레트 수 등)·난수 시드·sim_days는 문서로 정하지 않으므로 제외한다.
FIELDS: list[tuple[str, tuple[str, str], str, str, str, str | None]] = [
    # ① 입고 / 하역
    ("inbound_trucks_per_day", ("inbound", "trucks_per_day"), "integer", "일 입고 트럭 수", "대/일", None),
    ("inbound_truck_load_ton", ("inbound", "truck_load_ton"), "number", "트럭 적재량", "t", None),
    ("inbound_arrival_start_min", ("inbound", "arrival_start_min"), "integer", "입고 도착 시작", "분(자정 기준)", "예: 09시 → 540"),
    ("inbound_arrival_end_min", ("inbound", "arrival_end_min"), "integer", "입고 도착 종료", "분(자정 기준)", "예: 18시 → 1080"),
    ("inbound_morning_cutoff_min", ("inbound", "morning_cutoff_min"), "integer", "오전 구분 시각", "분(자정 기준)", "예: 정오 → 720"),
    ("inbound_morning_share", ("inbound", "morning_share"), "number", "오전 도착 비율", "0~1", "예: 80% → 0.8"),
    ("inbound_weigh_in_min", ("inbound", "weigh_in_min"), "number", "입고 1차 계근 시간", "분", None),
    ("inbound_weigh_out_min", ("inbound", "weigh_out_min"), "number", "입고 2차 계근 시간", "분", None),
    ("inbound_unload_min", ("inbound", "unload_min"), "number", "하역 시간", "분/대", None),
    ("inbound_unloading_bays", ("inbound", "unloading_bays"), "integer", "하역 베이 수", "개", None),
    ("inbound_weighbridges", ("inbound", "weighbridges"), "integer", "계근대 수", "대", None),
    # ② 선별 / 압착
    ("sorting_sort_min_per_truck", ("sorting", "sort_min_per_truck"), "number", "트럭당 선별 시간", "분", None),
    ("sorting_subpiles_per_truck", ("sorting", "subpiles_per_truck"), "integer", "트럭당 sub-pile 수", "개", None),
    ("sorting_subpile_ton", ("sorting", "subpile_ton"), "number", "sub-pile 중량(=파레트)", "t", None),
    ("sorting_blocks_per_subpile", ("sorting", "blocks_per_subpile"), "integer", "sub-pile당 블록 수", "개", None),
    ("sorting_block_ton", ("sorting", "block_ton"), "number", "블록 중량", "t", None),
    ("sorting_forklift_min_per_block", ("sorting", "forklift_min_per_block"), "number", "지게차 이송/블록", "분", None),
    ("sorting_press_min_per_block", ("sorting", "press_min_per_block"), "number", "압착/블록", "분", "예: 약 90초 → 1.5"),
    ("sorting_pallet_load_min_per_block", ("sorting", "pallet_load_min_per_block"), "number", "파레트 적재/블록", "분", None),
    ("sorting_sorters", ("sorting", "sorters"), "integer", "선별 작업조 수", "조", None),
    ("sorting_presses", ("sorting", "presses"), "integer", "압착기 대수", "대", None),
    ("sorting_pallet_buffer_cap", ("sorting", "pallet_buffer_cap"), "integer", "파레트 버퍼 용량", "파레트", None),
    # ③ 장입 / 용해
    ("melting_batch_ton", ("melting", "batch_ton"), "number", "배치 톤수", "t", None),
    ("melting_pallet_ton", ("melting", "pallet_ton"), "number", "파레트 단위 중량", "t", None),
    ("melting_elevator_pallets_per_trip", ("melting", "elevator_pallets_per_trip"), "integer", "엘리베이터 1회 적재", "파레트", None),
    ("melting_elevator_cycle_min", ("melting", "elevator_cycle_min"), "number", "엘리베이터 왕복 시간", "분", None),
    ("melting_setup_min", ("melting", "setup_min"), "number", "배치 사전 준비(셋업)", "분", "예: 약 2시간 → 120"),
    ("melting_melting_min", ("melting", "melting_min"), "number", "용해·정련 시간", "분", "예: 약 13시간 → 780"),
    ("melting_furnace_count", ("melting", "furnace_count"), "integer", "반사로 대수", "기", None),
    ("melting_elevator_count", ("melting", "elevator_count"), "integer", "엘리베이터 대수", "대", None),
    # ④ 하이브리드 주조
    ("casting_flake_ratio", ("casting", "flake_ratio"), "number", "큐프레이크 비율", "0~1", "예: 20% → 0.2"),
    ("casting_flake_unit_ton", ("casting", "flake_unit_ton"), "number", "큐프레이크 단위 중량", "t", None),
    ("casting_flake_min_per_unit", ("casting", "flake_min_per_unit"), "number", "큐프레이크 단위 시간", "분/단위", None),
    ("casting_scr_unit_ton", ("casting", "scr_unit_ton"), "number", "SCR 단위 중량", "t", None),
    ("casting_scr_min_per_unit", ("casting", "scr_min_per_unit"), "number", "SCR 단위 시간", "분/단위", None),
    ("casting_holding_setup_min", ("casting", "holding_setup_min"), "number", "홀딩 셋업", "분", None),
    ("casting_flake_buffer_cap", ("casting", "flake_buffer_cap"), "integer", "큐프레이크 야적 버퍼", "단위", None),
    ("casting_scr_buffer_cap", ("casting", "scr_buffer_cap"), "integer", "SCR 야적 버퍼", "단위", None),
    # ⑤ 출하
    ("outbound_truck_interval_min", ("outbound", "truck_interval_min"), "number", "출하 트럭 평균 간격", "분", None),
    ("outbound_truck_capacity_ton", ("outbound", "truck_capacity_ton"), "number", "출하 트럭 적재", "t", None),
    ("outbound_flake_truck_prob", ("outbound", "flake_truck_prob"), "number", "큐프레이크 출하 확률", "0~1", None),
    ("outbound_weigh_in_min", ("outbound", "weigh_in_min"), "number", "출하 1차 계근 시간", "분", None),
    ("outbound_weigh_out_min", ("outbound", "weigh_out_min"), "number", "출하 2차 계근 시간", "분", None),
    ("outbound_load_min", ("outbound", "load_min"), "number", "상차 시간", "분", None),
    ("outbound_max_wait_min", ("outbound", "max_wait_min"), "number", "재고 대기 한도", "분", None),
]

_SECTION_LABEL = {
    "inbound": "① 입고 / 하역",
    "sorting": "② 선별 / 압착",
    "melting": "③ 장입 / 용해",
    "casting": "④ 하이브리드 주조",
    "outbound": "⑤ 출하",
}

# 사이드바 슬라이더 라벨(ui/sidebar_params.py)과 (subconfig, field) 매핑
SIDEBAR_LABEL_BY_FIELD: dict[tuple[str, str], str] = {
    ("inbound", "trucks_per_day"): "일 입고 트럭 수",
    ("inbound", "truck_load_ton"): "트럭 적재 (t)",
    ("inbound", "arrival_start_min"): "입고 창 시작 (분, 자정 기준)",
    ("inbound", "arrival_end_min"): "입고 창 종료 (분)",
    ("inbound", "morning_cutoff_min"): "오전·오후 구분 시각 (분)",
    ("inbound", "morning_share"): "오전 입고 비율",
    ("inbound", "weigh_in_min"): "1차 계근 (분)",
    ("inbound", "weigh_out_min"): "2차 계근 (분)",
    ("inbound", "unload_min"): "하역 시간 (분/대)",
    ("inbound", "unloading_bays"): "하역 베이 수",
    ("inbound", "weighbridges"): "계근대 수",
    ("sorting", "sort_min_per_truck"): "트럭당 선별 시간 (분)",
    ("sorting", "subpiles_per_truck"): "더미당 sub-pile 수",
    ("sorting", "subpile_ton"): "sub-pile 중량 (t)",
    ("sorting", "blocks_per_subpile"): "sub-pile당 블록 수",
    ("sorting", "block_ton"): "블록 중량 (t)",
    ("sorting", "forklift_min_per_block"): "지게차 투입 (분/블록)",
    ("sorting", "press_min_per_block"): "압착 (분/블록)",
    ("sorting", "pallet_load_min_per_block"): "파레트 적재 (분/블록)",
    ("sorting", "sorters"): "선별 작업조 수",
    ("sorting", "presses"): "압착기 대수",
    ("sorting", "pallet_buffer_cap"): "파레트 버퍼 (개)",
    ("melting", "batch_ton"): "배치 장입량 (t)",
    ("melting", "pallet_ton"): "파레트 1개 중량 (t)",
    ("melting", "elevator_pallets_per_trip"): "엘리베이터 1회 운반 파레트 수",
    ("melting", "elevator_cycle_min"): "엘리베이터 왕복 (분)",
    ("melting", "setup_min"): "반사로 셋업·가열 (분)",
    ("melting", "melting_min"): "용해·정련·슬래깅 등 (분)",
    ("melting", "furnace_count"): "반사로 대수",
    ("melting", "elevator_count"): "엘리베이터 대수",
    ("casting", "flake_ratio"): "큐프레이크 생산 비율",
    ("casting", "flake_unit_ton"): "큐프레이크 단위 (t)",
    ("casting", "flake_min_per_unit"): "큐프레이크 단위당 시간 (분)",
    ("casting", "scr_unit_ton"): "SCR 단위 (t)",
    ("casting", "scr_min_per_unit"): "SCR 단위당 시간 (분)",
    ("casting", "holding_setup_min"): "홀딩로 셋업 (분)",
    ("casting", "flake_buffer_cap"): "큐프레이크 야적 (단위)",
    ("casting", "scr_buffer_cap"): "SCR 야적 (단위)",
    ("outbound", "truck_interval_min"): "출하 트럭 평균 간격 (분)",
    ("outbound", "truck_capacity_ton"): "출하 트럭 만재 (t)",
    ("outbound", "flake_truck_prob"): "출하 큐프레이크 트럭 확률",
    ("outbound", "weigh_in_min"): "출하 1차 계근 (분)",
    ("outbound", "weigh_out_min"): "출하 2차 계근 (분)",
    ("outbound", "load_min"): "상차 시간 (분)",
    ("outbound", "max_wait_min"): "재고 부족 시 최대 대기 (분)",
}

_LLM_LABEL_TO_SIDEBAR: dict[str, str] = {
    label: SIDEBAR_LABEL_BY_FIELD[(sub, attr)]
    for _json_key, (sub, attr), _jtype, label, _unit, _hint in FIELDS
}

EXTRACTED_CHANGED_LABELS_KEY = "extracted_changed_labels"
EXTRACTED_CHANGE_DETAILS_KEY = "extracted_change_details"


def highlight_from_extract_changes(
    changes: list[dict[str, str]],
) -> tuple[set[str], dict[str, dict[str, str]]]:
    """추출 diff 행 → 사이드바 슬라이더 라벨·기존/추출값 상세."""
    labels: set[str] = set()
    details: dict[str, dict[str, str]] = {}
    for row in changes:
        sb_label = _LLM_LABEL_TO_SIDEBAR.get(row.get("항목", ""))
        if not sb_label:
            continue
        labels.add(sb_label)
        details[sb_label] = {
            "기존값": row.get("기존값", ""),
            "추출값": row.get("추출값", ""),
        }
    return labels, details


def _schema() -> dict[str, Any]:
    """Gemini JSON 스키마. 문서에 없는 필드는 생략하도록 required를 두지 않는다."""
    props = {
        json_key: {"type": jtype} for json_key, _path, jtype, *_rest in FIELDS
    }
    return {
        "type": "object",
        "properties": props,
        "additionalProperties": False,
    }


def _system_prompt() -> str:
    lines = [
        "당신은 공장 물류 시뮬레이션의 파라미터 추출기입니다.",
        "주어지는 한국어 '공정 설명' 문서를 읽고, 각 파라미터의 현재 값을 JSON으로 반환하세요.",
        "",
        "규칙:",
        "- 문서에 명시되었거나 단일 숫자로 분명히 함의된 값만 채우고, 근거가 없으면 null로 두세요.",
        "- 시간은 분(min), 중량은 톤(t) 단위입니다. 시각은 자정 기준 분으로 환산하세요(09:00 → 540, 18:00 → 1080).",
        "- 비율은 0~1 사이 소수로 환산하세요(80% → 0.8, 20% → 0.2).",
        "- 계산으로 도출되는 파생값(사이클 합계, 왕복 횟수, 시간당 산출량 등)은 추출하지 마세요. 입력 파라미터만.",
        "- 범위(예: 20~25t), 면적(예: 5m×5m), 설계 상한(예: 반사로 200t)처럼 모델 입력이 아닌 서술은 무시하세요.",
        "- 추정하거나 만들어내지 마세요. 문서에 근거가 없으면 반드시 null.",
        "- 설비·작업조·베이·계근대 등 **대수·개수**는 1 이상의 정수만(0이면 null).",
        "",
        "필드 설명:",
    ]
    for json_key, _path, jtype, label, unit, hint in FIELDS:
        suffix = f" — {hint}" if hint else ""
        lines.append(f"- {json_key}: {label} (단위 {unit}, {jtype}){suffix}")
    return "\n".join(lines)


def _coerce(raw: float, jtype: str) -> int | float:
    return int(round(raw)) if jtype == "integer" else float(raw)


def _num_eq(a: object, b: object) -> bool:
    return abs(float(a) - float(b)) < 1e-9


def _fmt(v: object) -> str:
    if isinstance(v, float):
        return f"{v:g}" if v == int(v) else f"{v:.4g}"
    return str(v)


def _merge_and_diff(
    base: SimulationConfig,
    data: dict[str, Any],
    *,
    diff_against: SimulationConfig | None = None,
    suppress_diff: bool = False,
) -> tuple[SimulationConfig, list[dict[str, str]], list[dict[str, str]]]:
    """`base` 위에 문서 값을 덮어쓴 Config를 만들고, 변경 여부를 판별한다.

    - `diff_against`가 있으면 그 Config와 비교(문서 기준선).
    - `suppress_diff`이면 비교 표시·변경 목록을 만들지 않는다(최초 적용).
    - 둘 다 없으면 `base`(엑셀·코드 기본)와 비교한다.
    """
    overrides: dict[str, dict[str, Any]] = {}
    changes: list[dict[str, str]] = []
    extracted: list[dict[str, str]] = []
    compare_cfg = diff_against if diff_against is not None else base
    for json_key, (sub, attr), jtype, label, unit, _hint in FIELDS:
        raw = data.get(json_key)
        if raw is None:
            continue
        val = _coerce(raw, jtype)
        cur = getattr(getattr(compare_cfg, sub), attr)
        is_changed = not suppress_diff and not _num_eq(cur, val)
        row = {
            "단계": _SECTION_LABEL[sub],
            "항목": label,
            "단위": unit,
            "기존값": _fmt(cur),
            "추출값": _fmt(val),
            "변경": "예" if is_changed else "아니오",
        }
        extracted.append(row)
        overrides.setdefault(sub, {})[attr] = val
        if is_changed:
            changes.append(row)

    new_cfg = base
    for sub, fields in overrides.items():
        new_cfg = replace(new_cfg, **{sub: replace(getattr(new_cfg, sub), **fields)})
    return sanitize_for_simulation(new_cfg), changes, extracted


def _resolve_api_key() -> str | None:
    """API 키를 찾는다: 환경변수 → 세션/로컬 설정 → Streamlit Secrets 순."""
    key = os.environ.get("GEMINI_API_KEY")
    if key and str(key).strip():
        return str(key).strip()
    try:
        from ui.app_settings import get_gemini_api_key, session_api_key_name

        import streamlit as st

        sk = st.session_state.get(session_api_key_name())
        if sk and str(sk).strip():
            return str(sk).strip()
        persisted = get_gemini_api_key()
        if persisted:
            return persisted
        if "GEMINI_API_KEY" in st.secrets:
            val = str(st.secrets["GEMINI_API_KEY"]).strip()
            if val:
                return val
    except Exception:
        try:
            from ui.app_settings import get_gemini_api_key

            persisted = get_gemini_api_key()
            if persisted:
                return persisted
        except Exception:
            pass
    return None


def api_key_configured() -> bool:
    """Gemini API 키가 어떤 경로로든 설정되어 있는지."""
    return _resolve_api_key() is not None


def _model_candidates() -> tuple[str, ...]:
    env = os.environ.get("GEMINI_MODEL", "").strip()
    return (env,) if env else _DEFAULT_MODELS


def _is_retryable(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    return isinstance(code, int) and code in _RETRYABLE_CODES


def _generate_json_text(client: Any, model: str, md_text: str, config: Any) -> str:
    from google.genai import errors

    last_exc: BaseException | None = None
    for attempt, delay in enumerate((*_RETRY_DELAYS_SEC, None)):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=md_text,
                config=config,
            )
            text = (resp.text or "").strip()
            if text:
                return text
            raise RuntimeError("모델이 JSON 응답을 반환하지 않았습니다.")
        except errors.APIError as exc:
            last_exc = exc
            if not _is_retryable(exc) or delay is None:
                raise
            time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("모델 호출에 실패했습니다.")


def extract_config_from_markdown(
    md_text: str,
    base: SimulationConfig,
    *,
    diff_against: SimulationConfig | None = None,
    suppress_diff: bool = False,
) -> tuple[SimulationConfig, list[dict[str, str]], list[dict[str, str]]]:
    """공정 설명 본문에서 파라미터를 추출해 (새 Config, 변경 내역, 추출 전체)을 돌려준다.

    `base` 위에 문서에 명시된 값만 덮어쓴다. 변경 비교는 `diff_against`(문서 기준선) 또는
    `suppress_diff`로 제어한다. 실패 시 RuntimeError를 던진다.
    """
    if not md_text.strip():
        raise RuntimeError("문서가 비어 있습니다.")
    api_key = _resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY가 설정되지 않았습니다. **⚙️ 설정** 탭에서 키를 등록하거나, "
            "환경변수·`.streamlit/secrets.toml`로 설정하세요."
        )
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:  # noqa: TRY003
        raise RuntimeError(
            "`google-genai` 패키지가 필요합니다. `pip install google-genai`"
        ) from e

    client = genai.Client(api_key=api_key)
    gen_config = types.GenerateContentConfig(
        system_instruction=_system_prompt(),
        temperature=0,
        response_mime_type="application/json",
        response_json_schema=_schema(),
    )

    text = ""
    errors: list[str] = []
    for model in _model_candidates():
        try:
            text = _generate_json_text(client, model, md_text, gen_config)
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{model}: {exc}")
    else:
        detail = "\n".join(errors)
        raise RuntimeError(
            "Gemini 모델 호출에 모두 실패했습니다. 잠시 후 다시 시도하세요.\n" + detail
        )

    if not text:
        raise RuntimeError("모델이 JSON 응답을 반환하지 않았습니다.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:  # noqa: TRY003
        raise RuntimeError(f"모델 응답을 JSON으로 해석하지 못했습니다: {e}") from e
    return _merge_and_diff(
        base,
        data,
        diff_against=diff_against,
        suppress_diff=suppress_diff,
    )
