"""공정 설명 뷰."""

from __future__ import annotations

import streamlit as st

from model_reference import PROCESS_STAGES


def render() -> None:
    st.header("📖 공정 설명")
    st.caption(
        "군산 스크랩 구리(SCR) 하이브리드 공정의 5단계 흐름과 "
        "본 시뮬레이션(SimPy)에서의 모델링 방식을 정리합니다."
    )

    st.markdown(
        """
### 전체 흐름

스크랩 구리가 공장에 들어와 선별·압착된 뒤 반사로에서 용해되고,
큐프레이크와 SCR 두 제품 라인으로 주조된 후 야적을 거쳐 출하됩니다.
"""
    )

    st.markdown(
        """
```mermaid
flowchart LR
    A[① 입고/하역<br/>트럭·계근] --> B[② 선별/압착<br/>파레트]
    B --> C[③ 장입/용해<br/>80t 배치]
    C --> D[④ 주조<br/>큐프레이크 / SCR]
    D --> E1[큐프레이크 야적]
    D --> E2[SCR 야적]
    E1 --> F[⑤ 출하]
    E2 --> F
```
"""
    )

    st.info(
        "시뮬레이션 엔진은 **SimPy** 이산사건 모델입니다. "
        "각 설비는 Resource(용량=대수), 중간 재고는 Store(용량=버퍼)로 표현하며, "
        "트럭·배치·출하는 비동기 프로세스로 상호 대기(블로킹)합니다."
    )

    for stage in PROCESS_STAGES:
        with st.container(border=True):
            st.subheader(stage["단계"])
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**투입·산출 자재:** {stage['자재']}")
                st.markdown(f"**주요 설비:** {stage['설비']}")
            with c2:
                st.markdown("**현장 개요**")
                st.write(stage["요약"])
            st.markdown("**시뮬레이션 모델**")
            st.write(stage["모델"])

    st.markdown("---")
    st.subheader("자원(병목)과 KPI")

    st.markdown(
        """
| 자원 키 | 한글명 | 소속 단계 |
|---------|--------|-----------|
| weighbridge | 계근대 | ① 입고, ⑤ 출하 (공유) |
| unloading_bay | 하역 베이 | ① |
| sorter | 선별기 | ② |
| press | 압착기 | ② |
| elevator | 엘리베이터 | ③ |
| furnace | 반사로 | ③·④ (용해~주조 점유) |
| flake_line | 큐프레이크 라인 | ④ |
| scr_line | SCR 라인 | ④ |

**가동률** = 자원 사용 시간 ÷ (자원 대수 × 시뮬레이션 총 시간).  
가동률이 가장 높은 자원이 **병목**으로 표시됩니다.

**시뮬레이션** 탭에서 실행하면 단계별 가동률 카드·막대 차트·자동 해설을 확인할 수 있습니다.
"""
    )
