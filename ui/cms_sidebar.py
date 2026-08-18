"""CMS 전선공장 시뮬레이션 파라미터 사이드바.

SOP(`data/공정설명260521.md`)의 대공정 구조를 그대로 메뉴로 삼는다 —
①원자재 입고 → ②도체 → ③절연·조사 → ④차폐 → ⑤시스 → ⑥완성·출하,
그리고 도체 공정을 거치지 않는 실리콘 HV 라인을 따로 둔다.

⚠ 표시는 SOP가 미확정으로 남긴 값(9장 질문 리스트)이다.
"""

from __future__ import annotations

from dataclasses import replace

import streamlit as st

from cms_config import DEFAULT_CMS_CONFIG, CmsConfig

_TBD = "⚠"

# 사양을 다시 만들면 이 값을 올린다 — 위젯 key가 바뀌어야 새 기본값을 따른다.
SPEC_NONCE_KEY = "cms_spec_nonce"


def bump_spec_nonce() -> None:
    """사양이 갱신됐음을 알린다. 다음 실행에서 사이드바가 새 값으로 다시 그려진다."""
    st.session_state[SPEC_NONCE_KEY] = st.session_state.get(SPEC_NONCE_KEY, 0) + 1


def _count(cfg: CmsConfig, key: str, label: str, hi: int, help: str = "") -> int:
    """설비 대수 슬라이더. SOP 미확인 대수는 라벨에 ⚠를 붙인다."""
    spec = cfg.equipment[key]
    shown = f"{_TBD} {label}" if spec.tbd_count else label
    tip = help
    if spec.tbd_count:
        tip = (tip + " ") if tip else ""
        tip += "SOP 미확인(질문 #1) — 가정값입니다."
    return int(
        st.slider(shown, 1, hi, max(1, min(hi, spec.count)), 1, help=tip or None,
                  key=f"cms_n_{key}_v{st.session_state.get(SPEC_NONCE_KEY, 0)}")
    )


def spec_config() -> CmsConfig:
    """공정 사양 파일(`data/process_spec_cms.json`)에서 기본 설정을 만든다.

    사양은 공정 설명 MD의 표에서 생성된 것이라, MD를 고치고 다시 생성하면
    설비·라우팅·단계 시간이 코드 수정 없이 바뀐다. 파일이 없거나 깨졌으면
    코드 내장 기본값으로 물러난다.
    """
    try:
        from process_spec import DEFAULT_SPEC_PATH, load_config

        if DEFAULT_SPEC_PATH.is_file():
            return load_config()
    except Exception as exc:  # 사양이 깨져도 앱은 떠야 한다
        st.warning(f"공정 사양을 읽지 못해 코드 기본값을 씁니다: {exc}")
    return DEFAULT_CMS_CONFIG


def render_cms_sidebar(base: CmsConfig | None = None) -> tuple[CmsConfig, bool]:
    """CMS 파라미터를 그리고 (설정, 실행버튼눌림)을 돌려준다."""
    cfg = base or spec_config()
    eq = {k: replace(v) for k, v in cfg.equipment.items()}
    cal, inb, cond, pal = cfg.calendar, cfg.inbound, cfg.conductor, cfg.pallet

    st.caption("기준 문서: `공정설명260521.md` — 멕시코 CMS 공장 SOP v0.3")

    sim_days = int(
        st.slider("시뮬레이션 기간 (일)", 7, 180, cfg.sim_days, 1,
                  help="SOP 7.5 기본은 1개월(30일). 재공이 쌓이는 라인은 길게 볼수록 정체가 뚜렷해집니다.")
    )

    with st.expander("🗓 공통 · 운영 캘린더"):
        st.caption("SOP 6.3 — 하루 24시간 연속 가동, 주말 정지, 월요일 스타트업.")
        weekend = st.slider("주말 정지 (시간/주)", 0.0, 72.0, cal.weekend_stop_hours, 1.0,
                            help="SOP 6.3 기본 52시간. 0으로 두면 완전 무정지 가동입니다.")
        startup = st.slider("월요일 스타트업 (시간)", 0.0, 12.0, cal.monday_startup_hours, 0.5,
                            help=f"{_TBD} SOP 6.3의 '공정별 3시간' 기재를 해석한 값(질문 #3).")
        avail = st.slider("실효 가동률 (%)", 50, 100, int(round(cal.availability * 100)), 1,
                          help="SOP 6.3 근거값 92.6%. 가공시간을 이 비율로 나눠 늘립니다.")
        seed = int(st.number_input("난수 시드", 0, 9999, cfg.random_seed, 1,
                                   help="같은 시드는 같은 결과를 냅니다. 바꿔서 변동성을 보세요."))

    with st.expander("🚚 ① 원자재 입고"):
        st.caption("SOP 7.2 — Cu는 월초 집중, AL은 12일간 분산, 실리콘은 2주 주기.")
        cu_trucks = int(st.slider("Cu 로드 월 트럭 수", 1, 40, inb.cu_trucks_per_month, 1,
                                  help="SOP 기본 13대 × 19.8t = 월 257.4t"))
        cu_ton = st.slider("트럭 1대 적재 (t)", 5.0, 40.0, inb.cu_ton_per_truck, 0.1,
                           help="3.3t 보빈 6롤 = 19.8t")
        cu_window = st.slider("Cu 도착 집중 창 (일)", 1.0, 30.0, inb.cu_arrival_window_days, 1.0,
                              help="월초 며칠 안에 몰아서 도착하는지. SOP는 '대부분 월초'.")
        al_days = int(st.slider("AL 입고 일수", 1, 30, inb.al_days, 1, help="SOP: 월초부터 12일간"))
        al_ton = st.slider("AL 일 입고 (t)", 0.5, 10.0, inb.al_ton_per_day, 0.5,
                           help="SOP: 하루 2롤(2t) = 40,000m 보빈 10개")
        sil_m = st.number_input("실리콘 HV 월 물량 (m)", 0, 5_000_000, int(cfg.sil_month_m), 10_000,
                                help=f"{_TBD} SOP 5.4는 AL 기준 350,000m. CU 물량은 미확인(질문 #18).")

    with st.expander("🔩 ② 도체 공정 (신선 · 연선)"):
        st.caption("SOP 5.1·5.2 — 태신선·멀티신선·연선기는 Cu44와 Cu19가 함께 씁니다.")
        eq["taeshin"] = replace(eq["taeshin"], count=_count(cfg, "taeshin", "태신선기 대수", 6,
                                                            "8mm→2mm 1차 인발. Cu44·Cu19 공유."))
        taeshin_min = st.slider("태신선 (분/보빈)", 10.0, 240.0, cond.taeshin_min_per_bobbin, 5.0,
                                help="3.3t 보빈 1개 → 1t 캐리어 3개")
        eq["multi"] = replace(eq["multi"], count=_count(cfg, "multi", "멀티신선기 대수", 6,
                                                        "2mm→0.29/0.315mm. Cu44·Cu19 공유."))
        c44 = int(st.slider("멀티신선 사이클 — Cu44 횟수", 1, 10, cond.cycle_cu44, 1,
                            help="SOP 7.2: Cu44 4회 → Cu19 1회 반복. 임의 순서로 섞으면 안 됩니다."))
        c19 = int(st.slider("멀티신선 사이클 — Cu19 횟수", 1, 10, cond.cycle_cu19, 1))
        eq["strand"] = replace(eq["strand"], count=_count(cfg, "strand", "연선기 대수", 30,
                                                          "1대당 하루 약 80,000m. Cu44·Cu19 공유."))
        eq["bunch19"] = replace(eq["bunch19"], count=_count(cfg, "bunch19", "집합기 대수 (Cu19)", 30))
        eq["tubular"] = replace(eq["tubular"], count=_count(cfg, "tubular", "튜블러연선기 대수", 6,
                                                            "집합 완료 1 + 연선 완료 1을 병합."))
        eq["multi_al"] = replace(eq["multi_al"], count=_count(cfg, "multi_al", "멀티신선기 대수 (AL)", 10))
        eq["bunch_al_dbl"] = replace(eq["bunch_al_dbl"],
                                     count=_count(cfg, "bunch_al_dbl", "집합기 (AL·더블)", 10))
        eq["bunch_al_sgl"] = replace(eq["bunch_al_sgl"],
                                     count=_count(cfg, "bunch_al_sgl", "집합기 (AL·싱글)", 30))
        eq["bunch_al_fin"] = replace(eq["bunch_al_fin"],
                                     count=_count(cfg, "bunch_al_fin", "집합기 (AL·합사)", 10))

    with st.expander("🧵 ③ 절연 · 조사", expanded=True):
        st.caption("SOP 6.1 — 세 라인(Cu44·Cu19·AL16)이 함께 쓰는 최대 환승역입니다.")
        eq["ins_ext"] = replace(eq["ins_ext"], count=_count(cfg, "ins_ext", "절연압출기 대수", 12,
                                                            "Cu44·Cu19·AL16 공유."))
        eq["irradiator"] = replace(
            eq["irradiator"],
            count=_count(cfg, "irradiator", "조사기 대수", 12,
                         "SOP는 1대가 절연 조사와 시스 조사를 겸한다고 기재(질문 #19)."),
        )

    with st.expander("🛡 ④ 차폐 · ⑤ 시스 (Cu44 차폐 SKU)"):
        st.caption("SOP 5.1 — 편조는 1.5m/min으로 라인에서 가장 느립니다(보빈 1개에 5~6일).")
        shield_pct = int(
            st.slider("Cu44 차폐 SKU 비율 (%)", 0, 100,
                      int(round(cfg.cu44_shield_ratio * 100)), 1,
                      help=f"{_TBD} 어느 SKU가 편조~조사② 구간을 타는지 미확정(질문 #5). 시나리오 변수입니다.")
        )
        eq["braider"] = replace(eq["braider"], count=_count(cfg, "braider", "편조기 대수 (Cu)", 100))
        eq["taping"] = replace(eq["taping"], count=_count(cfg, "taping", "테이핑기 대수", 30))
        eq["sheath_ext"] = replace(eq["sheath_ext"], count=_count(cfg, "sheath_ext", "시스압출기 대수", 12))

    with st.expander("📦 ⑥ 완성 · 출하"):
        st.caption("SOP 6.1·7.6 — 재권취는 보빈 규격에 따라 설비가 나뉘고, 파렛트가 차야 출하됩니다.")
        eq["rewind1050"] = replace(eq["rewind1050"],
                                   count=_count(cfg, "rewind1050", "재권취기 대수 (1050Φ)", 20,
                                                "Cu44·AL16 공유."))
        eq["rewind1250"] = replace(eq["rewind1250"],
                                   count=_count(cfg, "rewind1250", "재권취기 대수 (1250Φ)", 20,
                                                "Cu19 전용."))
        eq["inspect"] = replace(eq["inspect"],
                                count=_count(cfg, "inspect", "검사 작업조 수 (E24·E25)", 30,
                                             "Cu44·Cu19·AL16 공용. SOP는 검사 시간을 TBD로 남겼습니다."))
        cu44_pal = int(st.slider("파렛트 조건 — Cu44 (보빈/파렛트)", 1, 60,
                                 pal.cu44_bobbins_per_pallet, 1, help="SOP 7.6: 18보빈"))
        cu19_pal = int(st.slider("파렛트 조건 — Cu19 (다발/파렛트)", 1, 120,
                                 pal.cu19_bundles_per_pallet, 1, help="SOP 7.6: 45다발"))

    with st.expander("🔴 실리콘 HV 라인 (도체 공정 없음)"):
        st.caption("SOP 5.4 — 압출 중 가교되어 조사 공정이 없고, 편조가 병목입니다.")
        eq["sil_ext"] = replace(eq["sil_ext"], count=_count(cfg, "sil_ext", "실리콘 압출기 대수", 12,
                                                            "좌: CU, 우: AL"))
        eq["sil_braider"] = replace(eq["sil_braider"],
                                    count=_count(cfg, "sil_braider", "편조기 대수 (실리콘 S4·S5)", 60))
        eq["sil_taping"] = replace(eq["sil_taping"],
                                   count=_count(cfg, "sil_taping", "테이핑기 대수 (실리콘 S6·S7)", 20))
        eq["inspect_sil"] = replace(eq["inspect_sil"],
                                    count=_count(cfg, "inspect_sil", "검사 작업조 수 (실리콘 S9)", 20,
                                                 "위치가 E24·E25와 달라 Cu·AL 검사와 별도 설비입니다 (SOP 2.6)."))
        st.caption(
            "시스 압출은 별도 설비가 아니라 **절연과 같은 실리콘 압출기**(S2·S3)를 "
            "다시 씁니다 — SOP 2.6 위치 코드 해석(질문 #18)."
        )

    new_cfg = replace(
        cfg,
        sim_days=sim_days,
        random_seed=seed,
        cu44_shield_ratio=shield_pct / 100.0,
        sil_month_m=float(sil_m),
        equipment=eq,
        calendar=replace(cal, weekend_stop_hours=weekend,
                         monday_startup_hours=startup, availability=avail / 100.0),
        inbound=replace(inb, cu_trucks_per_month=cu_trucks, cu_ton_per_truck=cu_ton,
                        cu_arrival_window_days=cu_window, al_days=al_days, al_ton_per_day=al_ton),
        conductor=replace(cond, taeshin_min_per_bobbin=taeshin_min,
                          cycle_cu44=c44, cycle_cu19=c19),
        pallet=replace(pal, cu44_bobbins_per_pallet=cu44_pal,
                       cu19_bundles_per_pallet=cu19_pal),
    )

    run = st.button("🚀 시뮬레이션 실행", type="primary", use_container_width=True)
    return new_cfg, run
