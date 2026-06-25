"""공정 설명(자연어)에서 S88 스타일 '공정 구조 트리'를 추출한다.

`llm_config.py`(문서→평면 파라미터)의 계층 버전이다. 같은 Gemini structured-output
플러밍을 재사용해 문서를 batch → stage → operation → {parameter, characteristic}
트리로 분해한다.

- parameter 리프: 그 작업의 '입력값'. `llm_config.FIELDS`의 표준 필드(json_key)와
  매핑되므로 SimulationConfig 항목과 정합한다.
- characteristic 리프: 실행(시뮬레이션) 시 채워질 '기록값'의 이름/단위(값은 비움).

필요: 환경변수 `GEMINI_API_KEY`(또는 설정 탭/secrets), 패키지 `google-genai`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from typing import Any

# Gemini 플러밍·필드 정의는 평면 추출기(llm_config)와 공유한다.
from llm_config import (
    FIELDS,
    _SECTION_LABEL,
    _coerce,
    generate_structured_json,
)

# json_key -> (sub, attr, jtype, label, unit, hint)
_FIELD_BY_KEY: dict[str, tuple[str, str, str, str, str, str | None]] = {
    json_key: (sub, attr, jtype, label, unit, hint)
    for json_key, (sub, attr), jtype, label, unit, hint in FIELDS
}
_ALL_FIELD_KEYS: list[str] = [f[0] for f in FIELDS]
_STAGE_NAMES: list[str] = list(_SECTION_LABEL.values())


@dataclass
class Param:
    field: str  # FIELDS json_key
    label: str  # 표준 라벨(FIELDS 기준)
    unit: str
    value: float | int | None
    jtype: str = "number"  # "integer" | "number" (입력 위젯 정수/실수 구분)


@dataclass
class Characteristic:
    name: str
    unit: str = ""


@dataclass
class Operation:
    name: str
    parameters: list[Param] = dc_field(default_factory=list)
    characteristics: list[Characteristic] = dc_field(default_factory=list)


@dataclass
class Stage:
    name: str
    operations: list[Operation] = dc_field(default_factory=list)


@dataclass
class ProcessTree:
    product: str | None
    stages: list[Stage]
    batch_characteristics: list[Characteristic] = dc_field(default_factory=list)


def _tree_schema() -> dict[str, Any]:
    """Gemini JSON 스키마. parameter.field는 표준 필드 키로만 제한한다(설정 매핑 보장)."""
    characteristic = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "unit": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    parameter = {
        "type": "object",
        "properties": {
            "field": {"type": "string", "enum": _ALL_FIELD_KEYS},
            "value": {"type": "number"},
            "unit": {"type": "string"},
        },
        "required": ["field"],
        "additionalProperties": False,
    }
    operation = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "parameters": {"type": "array", "items": parameter},
            "characteristics": {"type": "array", "items": characteristic},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    stage = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "operations": {"type": "array", "items": operation},
        },
        "required": ["name", "operations"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "product": {"type": "string"},
            "stages": {"type": "array", "items": stage},
            "batch_characteristics": {"type": "array", "items": characteristic},
        },
        "required": ["stages"],
        "additionalProperties": False,
    }


def _tree_system_prompt() -> str:
    lines = [
        "당신은 배치 생산공정의 '공정 구조(트리)' 추출기입니다.",
        "주어지는 한국어 '공정 설명' 문서를 읽고 ISA-88(S88) 스타일 계층 구조로 분해해 JSON으로 반환하세요.",
        "",
        "구조:",
        "- product: 생산 제품명(문서에 있으면).",
        "- stages[]: 공정 단계. 가능하면 아래 '표준 단계 이름'을 그대로 사용하세요.",
        "- 각 stage.operations[]: 그 단계의 세부 작업(예: 계근, 하역, 출차계근, 선별, 압착, 파레트 적재, "
        "엘리베이터 장입, 셋업·예열, 용해·정련, 홀딩 안정화, 큐프레이크 주조, SCR 주조, 1차계근, 상차, 2차계근 등).",
        "- 각 operation.parameters[]: 그 작업의 '입력값'. field는 아래 '표준 필드 키' 중 하나여야 하고, "
        "value는 문서에 명시된 숫자입니다.",
        "- 각 operation.characteristics[]: 그 작업에서 '실행 중 기록되는 측정·결과값'의 이름과 단위(값은 넣지 않음).",
        "- batch_characteristics[]: 배치 전체 수준의 기록값(예: batch_id, start_time, end_time, product_made, cost).",
        "",
        "규칙:",
        "- 시간은 분(min), 중량은 톤(t). 시각은 자정 기준 분(09:00→540, 18:00→1080), 비율은 0~1 소수(80%→0.8, 20%→0.2).",
        "- parameter.value는 문서에 근거가 있는 값만. 추정·창작 금지. 파생 계산값(합계·왕복 횟수·시간당 산출 등)은 넣지 마세요.",
        "- 매칭되는 표준 필드 키가 없는 입력은 parameter에서 생략하세요.",
        "- characteristic은 '입력'이 아니라 '실행하면 기록되는 결과'만(실측 소요시간, 평균 온도/압력, 생산량, 소비 원료, 사이클타임 등). parameter와 중복 금지.",
        "",
        "표준 단계 이름:",
    ]
    lines += [f"- {name}" for name in _STAGE_NAMES]
    lines.append("")
    lines.append("표준 필드 키 (parameter.field 매핑용 — json_key: 라벨 (단위)):")
    for json_key, (_sub, _attr), _jtype, label, unit, _hint in FIELDS:
        lines.append(f"- {json_key}: {label} ({unit})")
    return "\n".join(lines)


def _parse_characteristics(items: Any) -> list[Characteristic]:
    out: list[Characteristic] = []
    for it in items or []:
        if isinstance(it, dict) and str(it.get("name", "")).strip():
            out.append(
                Characteristic(str(it["name"]).strip(), str(it.get("unit", "")).strip())
            )
    return out


def _parse_tree(data: dict[str, Any]) -> ProcessTree:
    stages: list[Stage] = []
    for s in data.get("stages", []) or []:
        if not isinstance(s, dict):
            continue
        operations: list[Operation] = []
        for o in s.get("operations", []) or []:
            if not isinstance(o, dict):
                continue
            params: list[Param] = []
            seen: set[str] = set()
            for p in o.get("parameters", []) or []:
                if not isinstance(p, dict):
                    continue
                key = str(p.get("field", "")).strip()
                meta = _FIELD_BY_KEY.get(key)
                if not meta or key in seen:
                    continue
                seen.add(key)
                _sub, _attr, jtype, label, unit, _hint = meta
                raw = p.get("value")
                try:
                    val: float | int | None = (
                        _coerce(float(raw), jtype) if raw is not None else None
                    )
                except (TypeError, ValueError):
                    val = None
                params.append(Param(key, label, unit, val, jtype))
            operations.append(
                Operation(
                    str(o.get("name", "")).strip() or "(작업)",
                    params,
                    _parse_characteristics(o.get("characteristics")),
                )
            )
        stages.append(Stage(str(s.get("name", "")).strip() or "(단계)", operations))

    product = data.get("product")
    return ProcessTree(
        product=str(product).strip() if product else None,
        stages=stages,
        batch_characteristics=_parse_characteristics(data.get("batch_characteristics")),
    )


def extract_process_tree_from_markdown(md_text: str) -> ProcessTree:
    """공정 설명 본문에서 S88 스타일 공정 구조 트리를 추출한다. 실패 시 RuntimeError."""
    if not md_text.strip():
        raise RuntimeError("문서가 비어 있습니다.")
    text = generate_structured_json(_tree_system_prompt(), _tree_schema(), md_text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"모델 응답을 JSON으로 해석하지 못했습니다: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError("모델 응답 형식이 올바르지 않습니다.")
    tree = _parse_tree(data)
    if not tree.stages:
        raise RuntimeError("문서에서 공정 단계를 찾지 못했습니다.")
    return tree


def _mm_label(text: str) -> str:
    """mermaid 노드 라벨용 안전 문자열."""
    return (
        text.replace('"', "'")
        .replace("[", "(")
        .replace("]", ")")
        .replace("\n", " ")
        .strip()
    )


def tree_to_mermaid(tree: ProcessTree) -> str:
    """batch → stage → operation 골격을 mermaid `graph TD`로 만든다.

    parameter/characteristic 세부는 노드가 너무 많아지므로 다이어그램에는 개수 배지만 싣고,
    값은 표(뷰)에서 따로 보여준다.
    """
    root = f"배치 · {tree.product}" if tree.product else "배치"
    lines = ["graph TD", f'  ROOT["{_mm_label(root)}"]']
    for si, stage in enumerate(tree.stages):
        sid = f"S{si}"
        lines.append(f'  {sid}["{_mm_label(stage.name)}"]')
        lines.append(f"  ROOT --> {sid}")
        for oi, op in enumerate(stage.operations):
            oid = f"S{si}O{oi}"
            badges = []
            if op.parameters:
                badges.append(f"p:{len(op.parameters)}")
            if op.characteristics:
                badges.append(f"c:{len(op.characteristics)}")
            suffix = f"<br/><small>{' '.join(badges)}</small>" if badges else ""
            lines.append(f'  {oid}["{_mm_label(op.name)}{suffix}"]')
            lines.append(f"  {sid} --> {oid}")
    return "\n".join(lines)


def _svg_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_num(v: float | int) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


def _render_node_tree(
    tree: ProcessTree, values: dict[str, float] | None = None
) -> dict[str, Any]:
    """ProcessTree → 렌더용 노드 트리. `values`(field→값)면 파라미터 라벨에 값을 함께 표시."""

    def char_leaf(c: Characteristic) -> dict[str, Any]:
        return {
            "label": c.name + (f" ({c.unit})" if c.unit else ""),
            "kind": "char",
            "children": [],
        }

    def param_leaf(p: Param) -> dict[str, Any]:
        v = values[p.field] if values is not None and p.field in values else p.value
        if v is not None:
            label = f"{p.label} = {_fmt_num(v)}" + (f" {p.unit}" if p.unit else "")
        else:
            label = p.label
        return {"label": label, "kind": "param", "children": []}

    def op_node(op: Operation) -> dict[str, Any]:
        children = [param_leaf(p) for p in op.parameters] + [
            char_leaf(c) for c in op.characteristics
        ]
        return {"label": op.name, "kind": "op", "children": children}

    def stage_node(s: Stage) -> dict[str, Any]:
        return {
            "label": s.name,
            "kind": "stage",
            "children": [op_node(o) for o in s.operations],
        }

    root_children = [char_leaf(c) for c in tree.batch_characteristics]
    root_children += [stage_node(s) for s in tree.stages]
    return {
        "label": f"배치 · {tree.product}" if tree.product else "배치",
        "kind": "root",
        "children": root_children,
    }


# 좌→우 브래킷 트리 SVG 레이아웃 상수
_SVG_FONT = 13
_SVG_ROW_H = 24
_SVG_TOP = 14
_SVG_LEFT = 12
_SVG_COL_GAP = 40  # 한 열 텍스트 끝 ~ 다음 열 시작 사이 여백(커넥터 공간)
_SVG_BUS = 16  # 자식 열 왼쪽에서 세로 버스까지의 거리
_SVG_TEXT_FILL = {
    "root": "#1f2937",
    "stage": "#1f2937",
    "op": "#374151",
    "param": "#1f2937",
    "char": "#6b7280",
}
_SVG_TEXT_WEIGHT = {"root": "700", "stage": "700", "op": "600"}


def _svg_text_width(label: str) -> float:
    """대략 텍스트 폭(px). CJK는 한 글자 폭, ASCII는 약 0.58배로 추정."""
    w = 0.0
    for ch in label:
        w += _SVG_FONT if ord(ch) > 0x2E80 else _SVG_FONT * 0.58
    return w


def tree_to_svg(
    tree: ProcessTree, values: dict[str, float] | None = None
) -> tuple[str, int, int]:
    """좌→우 브래킷 트리 SVG를 만든다(전체 계층). 반환 (svg, width, height).

    부모는 첫 자식 높이에 정렬하고 세로 버스를 아래로 내려, 캡처의 인덴트 트리 형태를 따른다.
    `values`(field→값)를 주면 파라미터 리프에 값을 함께 표시한다(편집값 반영).
    """
    root = _render_node_tree(tree, values)
    leaves: list[dict[str, Any]] = []
    max_w: dict[int, float] = {}

    def walk(node: dict[str, Any], depth: int) -> None:
        node["depth"] = depth
        max_w[depth] = max(max_w.get(depth, 0.0), _svg_text_width(node["label"]))
        children = node["children"]
        if children:
            for c in children:
                walk(c, depth + 1)
            node["y"] = children[0]["y"]  # 첫 자식에 정렬(top-aligned)
        else:
            node["y"] = _SVG_TOP + (len(leaves) + 0.5) * _SVG_ROW_H
            leaves.append(node)

    walk(root, 0)
    max_depth = max(max_w)
    col_x: dict[int, float] = {0: float(_SVG_LEFT)}
    for d in range(1, max_depth + 1):
        col_x[d] = col_x[d - 1] + max_w[d - 1] + _SVG_COL_GAP

    width = int(col_x[max_depth] + max_w[max_depth] + _SVG_LEFT + 6)
    height = int(_SVG_TOP * 2 + max(1, len(leaves)) * _SVG_ROW_H)

    paths: list[str] = []
    texts: list[str] = []

    def emit(node: dict[str, Any]) -> None:
        d = node["depth"]
        x = col_x[d]
        y = node["y"]
        fill = _SVG_TEXT_FILL.get(node["kind"], "#1f2937")
        weight = _SVG_TEXT_WEIGHT.get(node["kind"], "400")
        style = "italic" if node["kind"] == "char" else "normal"
        texts.append(
            f'<text x="{x:.1f}" y="{y + _SVG_FONT * 0.34:.1f}" fill="{fill}" '
            f'font-weight="{weight}" font-style="{style}">{_svg_escape(node["label"])}</text>'
        )
        children = node["children"]
        if children:
            bus = col_x[d + 1] - _SVG_BUS
            tx = x + _svg_text_width(node["label"]) + 5
            paths.append(f'<path d="M{tx:.1f} {y:.1f} H{bus:.1f}"/>')
            ys = [c["y"] for c in children]
            paths.append(f'<path d="M{bus:.1f} {min(ys):.1f} V{max(ys):.1f}"/>')
            for c in children:
                paths.append(
                    f'<path d="M{bus:.1f} {c["y"]:.1f} H{col_x[d + 1] - 3:.1f}"/>'
                )
                emit(c)

    emit(root)
    svg = (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        'xmlns="http://www.w3.org/2000/svg" '
        'font-family="Segoe UI, Malgun Gothic, AppleGothic, sans-serif" '
        f'font-size="{_SVG_FONT}">'
        '<rect width="100%" height="100%" fill="white"/>'
        '<g stroke="#9aa6c4" stroke-width="1" fill="none">' + "".join(paths) + "</g>"
        + "".join(texts)
        + "</svg>"
    )
    return svg, width, height


def tree_to_overrides(tree: ProcessTree) -> dict[str, float | int]:
    """parameter 리프 → {json_key: value} (값이 있는 것만).

    `llm_config._merge_and_diff`가 받는 평면 입력과 같은 형식이라, 평면 추출과 동일한
    적용·diff·기준선 파이프라인을 그대로 재사용할 수 있다.
    """
    out: dict[str, float | int] = {}
    for stage in tree.stages:
        for op in stage.operations:
            for p in op.parameters:
                if p.value is not None and p.field not in out:
                    out[p.field] = p.value
    return out


def tree_to_obj(tree: ProcessTree) -> dict[str, Any]:
    """직렬화(JSON 내려받기·디버그)용 dict."""
    return {
        "product": tree.product,
        "batch_characteristics": [
            {"name": c.name, "unit": c.unit} for c in tree.batch_characteristics
        ],
        "stages": [
            {
                "name": s.name,
                "operations": [
                    {
                        "name": o.name,
                        "parameters": [
                            {
                                "field": p.field,
                                "label": p.label,
                                "value": p.value,
                                "unit": p.unit,
                            }
                            for p in o.parameters
                        ],
                        "characteristics": [
                            {"name": c.name, "unit": c.unit} for c in o.characteristics
                        ],
                    }
                    for o in s.operations
                ],
            }
            for s in tree.stages
        ],
    }
