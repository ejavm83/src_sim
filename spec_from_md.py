"""공정 설명 마크다운의 표 → 공정 사양(JSON).

SOP는 사람이 읽는 문서지만, 설비 대수와 라인별 라우팅·단계 시간은 이미 표로
정리되어 있다. 이 모듈이 그 표를 읽어 `process_spec` 사양을 만든다.
따라서 **MD의 표를 고치면 시뮬레이션이 따라 바뀐다.**

읽는 표
 - 「6.1 설비 마스터」  → 설비 목록(대수·교체시간·공유 라인)
 - 「5.1~5.4 라인별 라우팅」 → 라인별 공정 단계(설비·단계 시간·로트 변환)

설비 연결은 SOP가 스스로 정의한 **공정 순번 체계**(1.3절: 2.1 태신선, 4.1 편조…)를
기준으로 한다. 순번은 문서 안에서 일관되므로 이름 표기가 흔들려도 안전하다.
같은 순번이 라인마다 다른 설비를 쓰는 경우(재권취 1050Φ/1250Φ 등)만
`_EQUIP_BY_SEQ`에서 라인별로 갈라 준다.

LLM을 쓰지 않는다 — 같은 문서는 항상 같은 사양을 만든다.
"""

from __future__ import annotations

import re
from typing import Any

# 공정 순번 → 설비 키. 값이 dict면 라인별로 다른 설비를 쓴다는 뜻.
_EQUIP_BY_SEQ: dict[str, str | dict[str, str]] = {
    "2.1": "taeshin",
    "2.2": {"AL16": "multi_al", "*": "multi"},
    "2.3": {"AL16": "bunch_al", "*": "bunch19"},
    "2.4": "strand",
    "2.5": "tubular",
    "3.1": "ins_ext",
    # 실리콘 압출기는 재질 전용(좌 CU·우 AL)이라 서로 대신 쓸 수 없다 — SOP 6.1·실리콘!C3.
    # 모델이 도는 물량은 AL 기준 350,000m이므로(질문 #18) 우측 전용기를 쓴다.
    "3.2": "sil_ext_al",
    "3.3": "irradiator",
    "4.1": {"SIL": "sil_braider", "*": "braider"},
    "4.2": {"SIL": "sil_taping", "*": "taping"},
    # 실리콘 시스는 절연 압출과 위치가 같아(S2·S3) 같은 전용 압출기를 다시 쓴다 — SOP 2.6·질문 #18
    "5.1": {"SIL": "sil_ext_al", "*": "sheath_ext"},
    "5.2": "irradiator",
    "6.1": {"CU19": "rewind1250", "*": "rewind1050"},
    # 검사도 위치가 갈린다 — E24·E25(Cu·AL) vs S9(실리콘), SOP 2.6
    "6.2": {"SIL": "inspect_sil", "*": "inspect"},
}

def _normalize_equip_label(label: str) -> str:
    """설비 표기에서 위치 코드 꼬리를 떼어 낸다.

    SOP v0.3(md_4)부터 「편조기(Cu) — E18」처럼 위치 코드가 붙었다.
    앞부분의 설비 이름만 남겨 조회한다.
    """
    return re.split(r"\s*[—–]\s*", label)[0].strip().lower()


# 설비 마스터의 표기 → 설비 키
_EQUIP_BY_LABEL: dict[str, str] = {
    "태신선기": "taeshin",
    "멀티신선기": "multi",
    "집합기(cu19)": "bunch19",
    "연선기": "strand",
    "튜블러연선기": "tubular",
    "절연압출기": "ins_ext",
    "조사기": "irradiator",
    "편조기(cu)": "braider",
    "테이핑기": "taping",
    "시스압출기": "sheath_ext",
    "재권취기(1050φ)": "rewind1050",
    "재권취기(1250φ)": "rewind1250",
    "실리콘 압출기": "sil_ext",
}

# 한 줄로 적혔지만 실제로는 '서로 대신 못 쓰는' 전용 설비로 갈라야 하는 것.
# 실리콘 압출기 2대는 좌측이 CU, 우측이 AL 전용이다(SOP 6.1·실리콘!C3). 하나의
# 풀로 두면 한 재질이 2대를 다 쓸 수 있는 것처럼 능력이 부풀려진다.
_DEDICATED_SPLIT: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    # 원본 키 -> ((새 키, 라벨 꼬리, 담당 라인, 설비 식별자), ...)
    "sil_ext": (
        ("sil_ext_al", "우 · AL 전용", "SIL", "S2-R"),
        ("sil_ext_cu", "좌 · CU 전용", "SIL_CU", "S2-L"),
    ),
}

# 라우팅 표의 제목 → 라인 키
_LINE_BY_HEADING: tuple[tuple[str, str], ...] = (
    ("5.1 Cu44", "CU44"),
    ("5.2 Cu19", "CU19"),
    ("5.3 AL16", "AL16"),
    ("5.4 실리콘", "SIL"),
)

# 엔진의 `flow` 로직이 직접 돌리는 공정 순번 — 라우팅에 또 넣으면 이중 계산된다.
# (SOP 7.2·5.2의 산문 규칙: 태신선 배치, 멀티신선 4:1 사이클, Cu19 3단 꼬임·병합)
FLOW_HANDLED_SEQ: dict[str, tuple[str, ...]] = {
    "CU44": ("2.1", "2.2"),
    "CU19": ("2.1", "2.2", "2.3", "2.4", "2.5"),
    "AL16": ("2.2",),
    "SIL": (),
}

_LINE_LABELS = {
    "CU44": "Cu44 (44/0.29)",
    "CU19": "Cu19 (19/9/0.315)",
    "AL16": "AL16 (16㎟)",
    "SIL": "실리콘 HV",
}
_LINE_COLORS = {"CU44": "#4C78A8", "CU19": "#F58518", "AL16": "#54A24B", "SIL": "#E45756"}


# ── 마크다운 표 읽기 ─────────────────────────────────────────────────────


def _clean(cell: str) -> str:
    """강조·확인표시(⚠ ◆ **)를 걷어내고 공백을 정리한다."""
    s = re.sub(r"\*\*|__", "", cell)
    s = s.replace("⚠", "").replace("◆", "")
    return s.strip()


def iter_tables(md: str):
    """(직전 제목, 헤더 리스트, 데이터행 리스트) 를 차례로 내놓는다."""
    heading = ""
    block: list[str] = []
    for line in md.splitlines() + [""]:
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        if line.lstrip().startswith("|"):
            block.append(line)
            continue
        if block:
            rows = [
                [_clean(c) for c in r.strip().strip("|").split("|")]
                for r in block
            ]
            # 2행째는 구분선(---)
            if len(rows) >= 3:
                yield heading, rows[0], rows[2:]
            block = []


# ── 값 파싱 ───────────────────────────────────────────────────────────────


def _num(text: str) -> float | None:
    m = re.search(r"(\d[\d,]*\.?\d*)", text.replace(" ", ""))
    return float(m.group(1).replace(",", "")) if m else None


def parse_minutes(text: str) -> float | None:
    """'400분' · '2h' · '1시간 23분' → 분. '0.5~1h' 같은 범위는 **하한**을 쓴다."""
    t = text.replace(",", "").strip()
    if not t or t.upper() == "TBD" or t == "-":
        return None

    # 범위 표기('0.5~1h')는 하한을 채택 — 보수적으로 잡으면 능력을 과대평가한다.
    m = re.match(r"(\d+\.?\d*)\s*[~∼-]\s*(\d+\.?\d*)\s*(시간|h|분|min)", t, re.I)
    if m:
        unit = 60.0 if m.group(3).lower() in ("시간", "h") else 1.0
        return float(m.group(1)) * unit

    total = 0.0
    hit = False
    for v, unit in re.findall(r"(\d+\.?\d*)\s*(시간|h|분|min)", t, re.I):
        total += float(v) * (60.0 if unit.lower() in ("시간", "h") else 1.0)
        hit = True
    return total if hit else None


def parse_lot(text: str) -> tuple[int, float]:
    """로트 표기 → (개수, 1개당 길이 m).

    '1보빈(24,000m)' → (1, 24000) · '12,000m×2개' → (2, 12000)
    '610m×19개' → (19, 610) · '캐리어(1t)×3' → (3, 0)
    """
    t = text.replace(" ", "")
    if not t or t == "-":
        return 1, 0.0

    # A×N개  (A 안에 길이가 있는 형태)
    m = re.search(r"([\d,]+)m\s*[×x]\s*(\d+)", t)
    if m:
        return int(m.group(2)), float(m.group(1).replace(",", ""))

    # 접미 ×N (길이는 괄호 안이거나 없음)
    count = 1
    m = re.search(r"[×x]\s*(\d+)\s*개?$", t)
    if m:
        count = int(m.group(1))

    m = re.search(r"\(([^)]*?)([\d,]+)m", t) or re.search(r"([\d,]+)m", t)
    length = float(m.group(m.lastindex).replace(",", "")) if m else 0.0
    return count, length


def parse_speed(text: str) -> float | None:
    """'160m/m' · '1.5m/m' → 분당 미터. 시간 표기('60분')면 None."""
    m = re.search(r"([\d,]+\.?\d*)\s*m\s*/\s*m", text.replace(" ", ""), re.I)
    return float(m.group(1).replace(",", "")) if m else None


def _seq_and_label(cell: str) -> tuple[str, str]:
    """'2.4 연선(도체 꼬임 완성) — 설비 6대(Cu19 공유)' → ('2.4', '연선(도체 꼬임 완성)')."""
    body = re.split(r"\s+[—–-]\s+설비", cell)[0].strip()
    m = re.match(r"(\d+\.\d+)\s*(.*)", body)
    return (m.group(1), m.group(2).strip()) if m else ("", body)


# AL16의 집합(2.3)은 한 순번에 설비가 셋이라 단계 이름으로 갈라야 한다 (SOP 5.3).
_AL_BUNCH_BY_KEYWORD: tuple[tuple[str, str], ...] = (
    ("더블", "bunch_al_dbl"),
    ("합사", "bunch_al_fin"),
    ("최종", "bunch_al_fin"),
    ("싱글", "bunch_al_sgl"),
)


def _equip_for(seq: str, line: str, label: str = "") -> str | None:
    rule = _EQUIP_BY_SEQ.get(seq)
    if rule is None:
        return None
    key = rule if isinstance(rule, str) else rule.get(line, rule.get("*"))
    if key == "bunch_al":
        for word, target in _AL_BUNCH_BY_KEYWORD:
            if word in label:
                return target
        return "bunch_al_sgl"
    return key


# ── 표 → 사양 조각 ───────────────────────────────────────────────────────


def parse_equipment_master(md: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """「6.1 설비 마스터」 표 → 설비 목록. (설비dict, 미해결 표기 목록)"""
    equipment: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []

    for heading, header, rows in iter_tables(md):
        if not heading.startswith("6.1") or header[:2] != ["설비", "대수"]:
            continue
        for r in rows:
            if len(r) < 4:
                continue
            label, count_s, shared_s, setup_s = r[0], r[1], r[2], r[3]
            key = _EQUIP_BY_LABEL.get(_normalize_equip_label(label))
            if key is None:
                unresolved.append(label)
                continue
            tbd = count_s.strip().upper() == "TBD"
            base = {
                "key": key,
                "label": label,
                "count": 1 if tbd else int(_num(count_s) or 1),
                "setup_min": parse_minutes(setup_s) or 0.0,
                "shared_by": re.findall(r"CU44|CU19|AL16|SIL", shared_s.upper()),
                "tbd_count": tbd,
            }
            split = _DEDICATED_SPLIT.get(key)
            if not split:
                equipment[key] = base
                continue
            # 전용 설비로 분할 — 대수를 나눠 갖는다 (2대 = 좌 1 + 우 1)
            per = max(1, base["count"] // len(split))
            for new_key, tail, line, machine_id in split:
                entry = {
                    **base,
                    "key": new_key,
                    "label": f"{_normalize_equip_label(label)}({tail})",
                    "count": per,
                    "shared_by": [line],
                }
                if per == 1:
                    entry["machines"] = [machine_id]
                    entry["machines_fixed"] = True
                equipment[new_key] = entry
            equipment.pop(key, None)
    return equipment, unresolved


def parse_lot_conversions(md: str) -> dict[tuple[str, str], tuple[int, float]]:
    """「7.3 로트 변환 규칙」 표 → {(라인, 순번): (분할 수, 아웃풋 길이)}.

    라우팅 표는 '아웃풋 1보빈'처럼 대표 1개만 적는 경우가 있어, 분할 수는
    이 표가 정본이다(예: 연선 '100,000m → 24,000m 보빈 ×4').
    """
    out: dict[tuple[str, str], tuple[int, float]] = {}
    for heading, header, rows in iter_tables(md):
        if not heading.startswith("7.3") or header[:3] != ["라인", "공정", "변환"]:
            continue
        for r in rows:
            if len(r) < 3:
                continue
            line = r[0].strip().upper()
            m = re.match(r"(\d+\.\d+)", r[1].strip())
            if not m:
                continue
            # '→' 뒤쪽이 아웃풋
            after = r[2].split("→")[-1] if "→" in r[2] else r[2]
            count, length = parse_lot(after)
            if count > 1 or length:
                out[(line, m.group(1))] = (count, length)
    return out


def parse_routes(md: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """「5.1~5.4 라인별 라우팅」 표 → 라인별 공정 단계. (routes, 경고 목록)"""
    routes: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    conversions = parse_lot_conversions(md)
    flow_locs: dict[str, list[str]] = {}   # flow가 담당하는 앞단 설비의 위치

    for heading, header, rows in iter_tables(md):
        if header[:3] != ["No", "위치", "공정 순번·단계"]:
            continue
        line = next((k for pre, k in _LINE_BY_HEADING if heading.startswith(pre)), None)
        if line is None:
            warnings.append(f"라인을 알 수 없는 라우팅 표: 「{heading}」")
            continue

        steps: list[dict[str, Any]] = []
        carried_len = 0.0
        for r in rows:
            if len(r) < 9 or r[3] not in ("공정", "검사"):
                continue  # 물류·창고 행은 가공 단계가 아니다
            seq, label = _seq_and_label(r[2])
            if seq in FLOW_HANDLED_SEQ.get(line, ()):
                # 라우팅에는 넣지 않지만(이중 계산 방지) 위치는 설비 식별에 쓴다
                eq_key = _equip_for(seq, line, label)
                if eq_key:
                    flow_locs.setdefault(eq_key, []).append(r[1])
                continue
            equip = _equip_for(seq, line, label)
            if equip is None:
                warnings.append(f"{line} 「{r[2][:30]}」: 순번 {seq or '?'}에 설비 매핑 없음")
                continue

            minutes = parse_minutes(r[8])
            tbd_time = minutes is None
            split, out_len = parse_lot(r[6])

            # 7.3 로트 변환 표가 분할의 정본
            conv = conversions.get((line, seq))
            if conv:
                split, out_len = conv[0], (conv[1] or out_len)

            # 길이를 안 적은 단계는 직전 길이를 이어받는다(길이 유지 공정)
            if out_len:
                carried_len = out_len
            else:
                out_len = carried_len

            # SOP의 「단계 시간」 열은 기준이 오락가락한다 — 연선은 아웃풋 1개분,
            # 재권취는 인풋 전체분이다. 「속도」가 있으면 아웃풋 길이 ÷ 선속으로
            # 다시 계산해 **아웃풋 로트 1개당 시간**으로 통일한다.
            # (SOP 10.3이 '재권취 19개 × 12.2분'으로 같은 계산을 해 두었다.)
            speed = parse_speed(r[7])
            if speed and out_len:
                minutes = out_len / speed
                tbd_time = False

            steps.append({
                "seq": seq,
                "label": label,
                "equip": equip,
                "loc": r[1].strip(),
                "minutes": minutes if minutes else 10.0,
                **({"split": split} if split != 1 else {}),
                **({"out_len_m": out_len} if out_len else {}),
                **({"tbd_time": True} if tbd_time else {}),
            })

        if steps:
            routes[line] = {
                "label": _LINE_LABELS.get(line, line),
                "color": _LINE_COLORS.get(line, "#4C78A8"),
                "steps": steps,
            }

    # SOP 5.1의 Cu44 표는 **차폐 경로**를 적어 두었고, 비차폐 경로는 산문으로만
    # 설명한다("차폐를 거치지 않는 경로라면 약 21.5시간"). 차폐 구간(4.x·5.x)을
    # 걷어내 비차폐 라인을 파생시킨다 — 어느 SKU가 어느 쪽인지는 질문 #5.
    if "CU44" in routes:
        shielded = routes.pop("CU44")
        routes["CU44S"] = {**shielded, "label": "Cu44 차폐 SKU", "color": "#3B6BA5"}

        plain: list[dict[str, Any]] = []
        for s in shielded["steps"]:
            if s["seq"].split(".")[0] in ("4", "5"):
                continue  # 편조·테이핑·시스·조사② 는 차폐 SKU 전용
            plain.append(dict(s))
        routes["CU44"] = {
            "label": _LINE_LABELS["CU44"],
            "color": _LINE_COLORS["CU44"],
            "steps": _rescale_plain_cu44(plain),
        }
        warnings.append(
            "Cu44 비차폐 경로는 표에 없어 차폐 경로에서 4.x·5.x 구간을 뺀 것으로 "
            "파생했습니다(SOP 5.1 산문 근거, 질문 #5)."
        )

    return routes, warnings, flow_locs


def _rescale_plain_cu44(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """비차폐 경로: 편조에서 12,000m로 쪼개지지 않아 재권취 인풋이 24,000m다.

    보빈 1개(610m)당 시간은 그대로고, 분할 수만 2배가 된다.
    """
    for s in steps:
        if s["equip"] == "rewind1050":
            s["split"] = round(24_000 / 610)
            s["out_len_m"] = 610.0
            s["minutes"] = 610 / 50.0
    return steps


def station_codes(raw_loc: str) -> list[str]:
    """위치 표기 → 설비가 놓인 **지점** 코드 목록.

    화살표(→)는 한 설비의 시작→완료이므로 첫 코드만 남긴다.
    가운뎃점(·)·쉼표는 서로 다른 지점이므로 모두 남긴다.
    """
    text = str(raw_loc).upper()
    if "→" in text or "->" in text:
        text = re.split(r"→|->", text)[0]
    return re.findall(r"[A-Z]+\d+", text)


def assign_machine_ids(
    equipment: dict[str, dict[str, Any]],
    routes: dict[str, dict[str, Any]],
    extra_locs: dict[str, list[str]] | None = None,
) -> None:
    """라우팅 표의 위치 코드로 개별 설비 식별자를 부여한다 (SOP 2.6).

    **위치 코드는 설비 번호가 아니라 공정 지점이다.** 원본 엑셀을 보면
    「A2 멀티신선 시작 / A3 멀티신선 완료」, 「S4 편조기 시작 / S5 편조기 완료」처럼
    한 설비가 시작·완료 두 지점을 갖는다. MD 라우팅 표는 이를 화살표로 적는다.

      "E12→E13"  한 설비의 시작→완료  → 설비 위치는 **E12** 하나
      "A6·A7"    서로 다른 두 지점      → 설비 위치는 A6, A7 둘

    그래서 화살표는 첫 코드만 취하고, 가운뎃점·쉼표는 모두 취한다. 대수가
    지점 수보다 많으면 지점 안에서 번호를 매긴다(편조기 21대 -> E18-1..E18-21).
    """
    locs: dict[str, list[str]] = {}

    def add(key: str, raw_loc: str) -> None:
        bucket = locs.setdefault(key, [])
        for code in station_codes(raw_loc):
            if code not in bucket:
                bucket.append(code)

    for key, raws in (extra_locs or {}).items():
        for raw in raws:
            add(key, raw)
    for route in routes.values():
        for step in route.get("steps", []):
            add(str(step.get("equip")), str(step.get("loc", "")))

    for key, spec in equipment.items():
        if spec.get("machines_fixed"):
            continue  # 전용 분할처럼 좌/우가 정해진 설비는 위치 코드를 덮어쓰지 않는다
        codes = locs.get(key, [])
        n = max(1, int(spec.get("count", 1)))
        if not codes:
            spec["machines"] = []
        elif len(codes) == n:
            spec["machines"] = codes
        elif n < len(codes):
            spec["machines"] = codes[:n]
        else:
            out: list[str] = []
            for i in range(n):
                loc = codes[i % len(codes)]
                out.append(f"{loc}-{i // len(codes) + 1}")
            spec["machines"] = out


def spec_from_markdown(md: str, base: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    """MD 표에서 사양을 만든다.

    `base`를 주면 그 사양 위에 덮어쓴다 — MD 표로 알 수 없는 부분
    (흐름 규칙·입고·캘린더·시나리오)은 base 값을 유지한다.
    돌려주는 두 번째 값은 사람이 확인해야 할 경고 목록.
    """
    import copy

    spec = copy.deepcopy(base) if base else {}
    notes: list[str] = []

    equipment, unresolved = parse_equipment_master(md)
    routes, warns, flow_locs = parse_routes(md)
    notes.extend(warns)
    for label in unresolved:
        notes.append(f"설비 마스터의 「{label}」는 설비 키에 연결되지 않아 건너뛰었습니다.")

    if equipment:
        # base에만 있는 설비(문서가 대수를 안 밝힌 것)는 남겨 둔다.
        merged = {e["key"]: e for e in spec.get("equipment", [])}
        merged.update(equipment)
        # 전용 설비로 갈라진 옛 통합 키는 버린다 (예: sil_ext -> sil_ext_al/cu)
        for old_key, split in _DEDICATED_SPLIT.items():
            if any(new_key in merged for new_key, *_ in split):
                merged.pop(old_key, None)
        assign_machine_ids(merged, routes or spec.get("routes", {}), flow_locs)
        spec["equipment"] = list(merged.values())
    else:
        notes.append("「6.1 설비 마스터」 표를 찾지 못했습니다.")

    if routes:
        spec.setdefault("routes", {})
        spec["routes"].update(routes)
    else:
        notes.append("라인별 라우팅 표(5.1~5.4)를 찾지 못했습니다.")

    spec.setdefault("_meta", {})["derived_from_markdown"] = True
    return spec, notes
