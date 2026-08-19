"""병목 카드 — 어두운 테마·밝은 테마 양쪽에서 읽히는 상세 진단 표시.

색을 **반투명 틴트**로 깔고 글자색은 지정하지 않는다(테마 글자색을 그대로 상속).
배경을 흰색 계열로 못 박으면 어두운 테마에서 글자가 묻히기 때문이다.
수식은 `<code>`를 쓰지 않고 직접 스타일을 준다 — Streamlit의 코드 배경색이
카드 위에서 반대로 뒤집히는 문제를 피하기 위해서다.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

# (틴트 배경, 테두리) — 어느 테마에서도 카드 윤곽만 주고 글자는 테마색을 따른다
_TONE: dict[str, tuple[str, str]] = {
    "high": ("rgba(217, 83, 79, 0.14)", "#d9534f"),
    "능력부족": ("rgba(217, 83, 79, 0.14)", "#d9534f"),
    "medium": ("rgba(224, 139, 60, 0.14)", "#e08b3c"),
    "경합": ("rgba(224, 139, 60, 0.14)", "#e08b3c"),
    "low": ("rgba(63, 158, 106, 0.14)", "#3f9e6a"),
    "여유": ("rgba(63, 158, 106, 0.14)", "#3f9e6a"),
}
_DEFAULT_TONE = ("rgba(128, 128, 128, 0.12)", "#9ca3af")

_MONO = (
    "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:0.92em;"
    "background:rgba(128,128,128,0.18);padding:1px 6px;border-radius:4px"
)


def tone_of(kind: str) -> tuple[str, str]:
    return _TONE.get(str(kind).lower(), _TONE.get(str(kind), _DEFAULT_TONE))


def card(
    title: str,
    badge: str,
    blocks: list[tuple[str, str]],
    *,
    kind: str = "",
) -> None:
    """제목 + 배지 + (소제목, 본문HTML) 블록들로 이루어진 카드 하나를 그린다."""
    bg, edge = tone_of(kind or badge)
    html = [
        f'<div style="background:{bg};border-left:5px solid {edge};border-radius:10px;'
        f'padding:0.85rem 1.1rem;margin-bottom:0.75rem">',
        f'<div style="font-size:1.05em;font-weight:700;margin-bottom:0.5rem">{title}'
        f'<span style="background:{edge};color:#fff;border-radius:5px;padding:1px 8px;'
        f'font-size:0.72em;margin-left:8px;vertical-align:middle">{badge}</span></div>',
    ]
    for head, body in blocks:
        html.append(
            f'<div style="margin:0.42rem 0"><span style="opacity:0.72;font-size:0.86em;'
            f'font-weight:600">{head}</span><br>'
            f'<span style="font-size:0.94em">{body}</span></div>'
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def mono(text: str) -> str:
    """수식·수치를 카드 안에서 읽히게 감싼다."""
    return f'<span style="{_MONO}">{text}</span>'


def _hours(h: float) -> str:
    """시간을 '몇 일'로도 함께 읽어 준다 — 80.5h가 얼마나 긴지 감이 오도록."""
    if h >= 48:
        return f"{h:,.0f}시간(약 {h / 24:.1f}일)"
    return f"{h:,.1f}시간"


def render_sim_bottlenecks(rep: Any, line_labels: dict[str, str], top: int = 6) -> None:
    """SimPy 결과에서 나온 병목을 '왜·근거·실제·피해·해법' 5단으로 상세히 보여 준다."""
    shown = 0
    for row in rep.rows:
        if shown >= top or (row.load <= 0 and row.jobs == 0):
            continue
        shown += 1

        # ① 왜 병목인가 — 숫자를 말로 풀어 준다
        if row.load > 1.0:
            short_h = row.demand_h - row.capacity_h
            why = (
                f"한 달 물량을 다 처리하려면 이 설비가 <b>{row.demand_h:,.0f}시간</b> 돌아야 하는데, "
                f"{row.count}대가 한 달에 낼 수 있는 시간은 <b>{row.capacity_h:,.0f}시간</b>뿐입니다. "
                f"<b>{short_h:,.0f}시간이 부족</b>해서, 그만큼은 아무리 잘 굴려도 물리적으로 처리할 수 없습니다."
            )
        elif row.avg_wait_h > 1:
            why = (
                f"능력 자체는 부족하지 않지만(부하 {row.load * 100:.0f}%), "
                f"여러 라인이 동시에 몰려 로트가 평균 {_hours(row.avg_wait_h)} 줄을 섰습니다. "
                "물량이 한꺼번에 도착해 생기는 대기입니다."
            )
        else:
            why = f"여유 있습니다 (부하 {row.load * 100:.0f}%). 대기도 거의 없습니다."

        # ② 근거 — 산술식 그대로
        basis = (
            f"{mono(f'요구 {row.demand_h:,.0f}h ÷ 가용 {row.capacity_h:,.0f}h = 부하 {row.load * 100:.0f}%')}"
            f"<br>{mono(f'가용 {row.capacity_h:,.0f}h = {row.count}대 × 월 가동가능 {row.capacity_h / max(1, row.count):,.0f}h')}"
        )

        # ③ 실제로 무슨 일이 있었나
        actual = (
            f"가동률 <b>{row.utilization * 100:.0f}%</b>"
            + ("— 사실상 쉬지 않고 돌았습니다. " if row.utilization > 0.9 else ". ")
            + f"로트 하나가 이 설비 앞에서 평균 <b>{_hours(row.avg_wait_h)}</b> 기다렸고, "
            f"한때 <b>{row.max_queue:,}개</b>가 줄 서 있었습니다. "
            f"기간 중 {row.jobs:,}건을 처리했습니다."
        )
        if row.setup_share > 0.05:
            actual += (
                f" 가동시간의 <b>{row.setup_share * 100:.0f}%</b>는 품종 교체(세팅 변경)에 쓰였습니다."
            )

        # ④ 누가 피해를 봤나
        if row.wait_by_line:
            victims = " · ".join(
                f"{line_labels.get(ln, ln)} {h:,.0f}h" for ln, h in row.wait_by_line[:4]
            )
            worst = row.wait_by_line[0]
            impact = (
                f"이 설비를 <b>{len(row.lines)}개 라인</b>이 함께 씁니다. 라인별로 기다린 총 시간은 "
                f"{victims}이고, 가장 크게 밀린 쪽은 <b>{line_labels.get(worst[0], worst[0])}</b>입니다."
                if len(row.lines) > 1
                else f"이 설비는 <b>{line_labels.get(row.lines[0], row.lines[0]) if row.lines else '—'}</b> 전용이고, "
                f"그 라인이 여기서 총 {victims} 기다렸습니다."
            )
        else:
            impact = "대기가 발생하지 않았습니다."

        blocks = [
            ("❓ 왜 병목인가", why),
            ("🧮 계산 근거", basis),
            ("🔬 시뮬레이션에서 실제로", actual),
            ("📉 어느 라인이 밀렸나", impact),
        ]
        if row.add_needed:
            blocks.append(
                (
                    "🔧 해법과 예상 효과",
                    f"<b>{row.add_needed}대 증설</b>하면 "
                    + mono(f"부하 {row.load * 100:.0f}% → {row.load_after * 100:.0f}%")
                    + " 로 내려가 능력 부족이 해소됩니다.",
                )
            )
        if row.tbd_count:
            blocks.append(
                ("⚠ 주의", "이 설비의 <b>대수는 SOP 미확인 가정값</b>입니다(질문 #1). 확정 전까지 참고용입니다.")
            )

        card(
            f"{row.rank}. {row.label} · {row.count}대",
            row.kind,
            blocks,
            kind=row.kind,
        )
