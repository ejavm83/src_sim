"""KPI가 만들어지기까지 — MD 표에서 SimPy를 거쳐 지표가 나오는 데이터 파이프라인.

"이 숫자는 어디서 왔나"에 답하기 위한 화면이다. 각 단계에 **지금 실제로 흐르고
있는 데이터의 양**을 함께 보여 주므로, 문서를 고치면 어디가 어떻게 바뀌는지도
같이 읽힌다.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

_STAGE_FILL = ("#e8f0fe", "#fdf0e3", "#e9f7ef", "#e8eaf6", "#fdeaea")
_STAGE_EDGE = ("#4c78a8", "#e08b3c", "#3f9e6a", "#5c6bc0", "#d9534f")


def _md_table_counts(md: str) -> dict[str, int]:
    """파서가 MD에서 실제로 읽어 가는 표의 행 수."""
    from spec_from_md import iter_tables

    out = {"설비 마스터": 0, "라우팅": 0, "로트 변환": 0}
    for heading, header, rows in iter_tables(md):
        if heading.startswith("6.1") and header[:2] == ["설비", "대수"]:
            out["설비 마스터"] += len(rows)
        elif header[:3] == ["No", "위치", "공정 순번·단계"]:
            out["라우팅"] += len(rows)
        elif heading.startswith("7.3") and header[:3] == ["라인", "공정", "변환"]:
            out["로트 변환"] += len(rows)
    return out


def _stage_svg(stages: list[tuple[str, str, list[str]]]) -> str:
    """5단계 파이프라인을 가로 흐름 SVG로 그린다."""
    n = len(stages)
    bw, gap, bh = 212, 48, 152
    width = n * bw + (n - 1) * gap
    height = bh + 56
    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;height:auto;min-width:960px">',
        '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0 0 L10 5 L0 10 z" fill="#6b7280"/></marker></defs>',
    ]
    for i, (title, subtitle, bullets) in enumerate(stages):
        x = i * (bw + gap)
        fill, edge = _STAGE_FILL[i % 5], _STAGE_EDGE[i % 5]
        parts.append(
            f'<rect x="{x}" y="38" width="{bw}" height="{bh}" rx="12" '
            f'fill="{fill}" stroke="{edge}" stroke-width="2"/>'
        )
        parts.append(
            f'<circle cx="{x + 22}" cy="30" r="15" fill="{edge}"/>'
            f'<text x="{x + 22}" y="35" text-anchor="middle" font-size="15" '
            f'font-weight="700" fill="#ffffff">{i + 1}</text>'
        )
        parts.append(
            f'<text x="{x + 46}" y="35" font-size="14.5" font-weight="700" '
            f'fill="#1f2937">{title}</text>'
        )
        parts.append(
            f'<text x="{x + 14}" y="62" font-size="11.5" fill="#4b5563">{subtitle}</text>'
        )
        for j, b in enumerate(bullets[:4]):
            parts.append(
                f'<text x="{x + 14}" y="{88 + j * 20}" font-size="12" fill="#111827">'
                f"· {b}</text>"
            )
        if i < n - 1:
            ax = x + bw + 10
            ay = 38 + bh / 2
            parts.append(
                f'<path d="M{ax} {ay} L{ax + gap - 20} {ay}" '
                f'stroke="#6b7280" stroke-width="2.5" marker-end="url(#ar)"/>'
            )
    parts.append("</svg>")
    return "".join(parts)


# KPI 하나하나가 SimPy의 어떤 기록에서 나오는지 — 이 표가 추적의 핵심이다.
# sim_only=True 는 "문서를 읽어서는 알 수 없고, 돌려 봐야만 나오는 값"이다.
_KPI_TRACE: tuple[dict[str, Any], ...] = (
    {
        "KPI": "총 생산량 (m)",
        "기록": "finished_m — 로트가 마지막 공정을 통과할 때마다 길이를 더함",
        "계산식": "Σ 라인별 완성 길이",
        "출처": "7.3 로트 변환 규칙, 5.1~5.4 라우팅",
        "sim_only": True,
    },
    {
        "KPI": "설비 가동률 (%)",
        "기록": "busy_min + setup_min — 설비를 붙잡고 있던 시간",
        "계산식": "(가공 + 교체) ÷ (대수 × 가용시간)",
        "출처": "6.1 설비 대수, 6.2 교체시간, 6.3 캘린더",
        "sim_only": True,
    },
    {
        "KPI": "평균 대기 (h)",
        "기록": "wait_min ÷ wait_n — 설비가 빌 때까지 줄 선 시간",
        "계산식": "총 대기시간 ÷ 대기 횟수",
        "출처": "6.1 공유 관계 (누가 같은 설비를 쓰는가)",
        "sim_only": True,
    },
    {
        "KPI": "최대 대기열 (개)",
        "기록": "max_queue — 한 설비 앞에 동시에 밀린 로트 최대치",
        "계산식": "시뮬레이션 중 관측 최대값",
        "출처": "6.1 설비 대수",
        "sim_only": True,
    },
    {
        "KPI": "리드타임 (h)",
        "기록": "lead_min — 완료 시각 − 투입 시각",
        "계산식": "라인별 평균",
        "출처": "5.1~5.4 단계 시간 + 대기(시뮬레이션 산출)",
        "sim_only": True,
    },
    {
        "KPI": "기말 재공 WIP (로트)",
        "기록": "wip_samples — 투입·완료 때마다 남은 로트 수를 기록",
        "계산식": "마지막 표본값",
        "출처": "7.2 입고 규칙 (투입 속도)",
        "sim_only": True,
    },
    {
        "KPI": "라인별 대기 (h)",
        "기록": "wait_by_line — 어느 라인이 어느 설비 앞에서 밀렸는지",
        "계산식": "라인·설비별 대기 누적",
        "출처": "6.1 공유 관계",
        "sim_only": True,
    },
    {
        "KPI": "설비 부하 (%)",
        "기록": "(시뮬레이션과 별개) planned_equip_load — 라우팅을 따라 계산",
        "계산식": "월 요구시간 ÷ 가용시간",
        "출처": "5.x 단계 시간, 7.2 물량, 6.3 캘린더",
        "sim_only": False,
    },
    {
        "KPI": "가동 가능 시간 (h)",
        "기록": "uptime_min — 캘린더가 주는 실제 가동 구간",
        "계산식": "168h − 주말 52h − 스타트업 3h, 기간만큼 누적",
        "출처": "6.3 운영 캘린더",
        "sim_only": False,
    },
)

_SIMPY_ANALOGY = """
**SimPy는 '가상의 시계'를 돌리는 도구입니다.** 실제로 30일을 기다리는 대신,
사건이 일어나는 시각으로 시계를 건너뛰며 공장을 재현합니다.

| 공장의 현실 | 모델에서의 표현 |
|---|---|
| 보빈 하나가 공정을 따라 이동 | **프로세스** 하나 (자기 순서대로 설비를 요청) |
| 설비 N대 | **자원 풀** — 이용권 N장, 없으면 줄 서서 대기 |
| 여러 라인이 한 설비를 공유 | 같은 풀에 여러 프로세스가 요청 → **경합 발생** |
| 품종이 바뀌면 세팅 교체 | 직전 품종과 다르면 **교체 시간** 추가 |
| 주말 정지·월요일 스타트업 | **캘린더** — 정지 구간은 시계만 건너뜀 |

여기서 핵심은 **줄 서서 기다리는 시간**입니다. 문서에는 "이 공정 150분"이라고만
적혀 있지만, 실제로는 앞 로트가 설비를 쓰고 있어 몇십 시간을 기다리기도 합니다.
그 대기 시간은 설비 대수와 다른 라인의 물량에 따라 달라지므로 **돌려 보기 전에는
계산으로 알 수 없습니다.** 병목 진단에 시뮬레이션이 필요한 이유입니다.
"""


def render(run: dict | None = None) -> None:
    """파이프라인 시각화. `run`이 있으면 그 실행의 실제 수치를 함께 보여 준다."""
    from process_spec import DEFAULT_SPEC_PATH, load_spec
    from views.process_description import doc_path

    st.markdown("#### 🔗 이 KPI는 어디서 왔나 — MD → 사양 → SimPy → 지표")
    st.caption(
        "화면의 숫자는 어디선가 추정한 값이 아니라, **공정 설명 MD의 표**에서 출발해 "
        "**SimPy가 공장을 실제로 돌려 본 결과**입니다. 아래는 그 데이터가 지나온 길이고, "
        "각 단계에 지금 흐르고 있는 실제 양을 적었습니다."
    )

    doc = doc_path()
    md = doc.read_text(encoding="utf-8") if doc.is_file() else ""
    tbl = _md_table_counts(md) if md else {"설비 마스터": 0, "라우팅": 0, "로트 변환": 0}

    spec = load_spec() if DEFAULT_SPEC_PATH.is_file() else {}
    n_equip = len(spec.get("equipment", []))
    n_routes = len(spec.get("routes", {}))
    n_steps = sum(len(r.get("steps", [])) for r in spec.get("routes", {}).values())
    n_machines = sum(max(1, int(e.get("count", 1))) for e in spec.get("equipment", []))

    if run:
        m, a = run["metrics"], run["analysis"]
        stage4 = [
            f"투입 로트 {sum(m.started_lots.values()):,}개",
            f"설비 작업 {sum(m.machine_jobs.values()):,}건",
            f"{a.days}일치 가동을 재현",
        ]
        stage5 = [
            f"완성 {sum(m.finished_lots.values()):,}로트",
            f"총 생산 {a.total_m / 1_000_000:.2f}M m",
            f"능력 부족 설비 {sum(1 for r in a.capacity if r.load > 1.0)}종",
        ]
    else:
        stage4 = ["로트를 프로세스로 생성", "설비를 자원 풀로 점유", "대기·교체·캘린더 반영"]
        stage5 = ["아직 실행 전", "사이드바에서 실행하면", "실제 수치가 채워집니다"]

    stages = [
        (
            "공정 설명 MD",
            doc.name if doc.is_file() else "문서 없음",
            [
                f"6.1 설비 마스터 {tbl['설비 마스터']}행",
                f"5.1~5.4 라우팅 {tbl['라우팅']}행",
                f"7.3 로트 변환 {tbl['로트 변환']}행",
                "6.2 교체 · 6.3 캘린더",
            ],
        ),
        (
            "표 파서 (규칙 기반)",
            "spec_from_md.py · LLM 안 씀",
            [
                "공정 순번(2.1·3.1…)으로 설비 연결",
                "위치 코드(E12·S2)로 기계 식별",
                "같은 문서 → 항상 같은 사양",
            ],
        ),
        (
            "공정 사양 JSON",
            "data/process_spec_cms.json",
            [
                f"설비 {n_equip}종 (총 {n_machines}대)",
                f"라인 {n_routes}개",
                f"공정 단계 {n_steps}개",
            ],
        ),
        ("SimPy 엔진", "cms_simulation.py", stage4),
        ("KPI · 병목 진단", "cms_report.py", stage5),
    ]

    st.html(
        f'<div style="width:100%;overflow-x:auto;line-height:0">{_stage_svg(stages)}</div>'
    )

    st.markdown("##### 🧮 지표별 추적 — 이 값은 SimPy의 무엇에서 나왔나")
    st.caption(
        "**돌려야 나옴**에 ✅가 붙은 지표는 문서를 아무리 읽어도 알 수 없는 값입니다. "
        "설비가 몇 대인지, 누가 같은 설비를 두고 다투는지에 따라 달라지므로 "
        "시간을 흘려 봐야만 나옵니다."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "KPI": r["KPI"],
                    "돌려야 나옴": "✅" if r["sim_only"] else "—",
                    "SimPy가 기록한 원자료": r["기록"],
                    "계산식": r["계산식"],
                    "MD 출처": r["출처"],
                }
                for r in _KPI_TRACE
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )

    with st.expander("🧩 SimPy가 공장을 흉내 내는 방식 (비유로)", expanded=False):
        st.markdown(_SIMPY_ANALOGY)
