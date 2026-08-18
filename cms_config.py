"""멕시코 CMS 전선공장 시뮬레이션 파라미터.

출처: `data/공정설명260521.md` (멕시코 CMS 공장 SOP v0.3, 2026-08-14).
 - 설비 대수·공유 관계 → SOP 6.1
 - 품종 교체(셋업) 시간 → SOP 6.2
 - 운영 캘린더 → SOP 6.3
 - 라인별 라우팅·단계 시간 → SOP 5.1~5.4
 - 로트 변환 규칙 → SOP 7.3
 - 스케줄·순서 규칙 → SOP 7.2

시간 단위는 분(min), 길이 단위는 미터(m), 중량 단위는 톤(t)이다.
SOP에서 ⚠TBD로 표시된 값은 `tbd=True`로 표시하고, UI에서 가정임을 알린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── 설비 ──────────────────────────────────────────────────────────────────
# SOP 6.1 설비 마스터. `setup_min`은 SOP 6.2 교체 매트릭스의 대표값.


@dataclass
class Equipment:
    key: str
    label: str
    count: int
    setup_min: float = 0.0
    shared_by: tuple[str, ...] = ()
    tbd_count: bool = False  # 대수가 SOP 미확인(질문 #1)


def default_equipment() -> dict[str, Equipment]:
    """SOP 6.1 표를 그대로 옮긴 설비 마스터."""
    specs = [
        # 도체 구간
        Equipment("taeshin", "태신선기", 1, 120.0, ("CU44", "CU19")),
        Equipment("multi", "멀티신선기", 1, 120.0, ("CU44", "CU19")),
        Equipment("bunch19", "집합기(Cu19)", 10, 120.0, ("CU19",)),
        Equipment("strand", "연선기", 6, 120.0, ("CU44", "CU19")),
        Equipment("tubular", "튜블러연선기", 1, 120.0, ("CU19",)),
        # AL16 전용 도체 설비 — 대수 미확인(질문 #1)
        Equipment("multi_al", "멀티신선기(AL)", 1, 120.0, ("AL16",), tbd_count=True),
        Equipment("bunch_al_dbl", "집합기(AL·더블)", 1, 120.0, ("AL16",), tbd_count=True),
        Equipment("bunch_al_sgl", "집합기(AL·싱글)", 12, 120.0, ("AL16",)),
        Equipment("bunch_al_fin", "집합기(AL·합사)", 1, 120.0, ("AL16",), tbd_count=True),
        # 피복 구간 — 공유 설비
        Equipment("ins_ext", "절연압출기", 2, 60.0, ("CU44", "CU19", "AL16")),
        Equipment("irradiator", "조사기", 1, 30.0, ("CU44", "CU19", "AL16")),
        # 차폐 구간
        Equipment("braider", "편조기(Cu)", 21, 60.0, ("CU44",)),
        Equipment("taping", "테이핑기", 4, 30.0, ("CU44",)),
        Equipment("sheath_ext", "시스압출기", 2, 60.0, ("CU44",)),
        # 재권취
        Equipment("rewind1050", "재권취기(1050Φ)", 2, 30.0, ("CU44", "AL16")),
        Equipment("rewind1250", "재권취기(1250Φ)", 2, 30.0, ("CU19",)),
        # 실리콘 HV 전용 — 편조·테이핑·시스 대수 미확인(질문 #1)
        Equipment("sil_ext", "실리콘 압출기", 2, 60.0, ("SIL",)),
        Equipment("sil_braider", "편조기(실리콘)", 10, 60.0, ("SIL",), tbd_count=True),
        Equipment("sil_taping", "테이핑기(실리콘)", 2, 30.0, ("SIL",), tbd_count=True),
        Equipment("sil_sheath", "시스압출기(실리콘)", 2, 60.0, ("SIL",), tbd_count=True),
        # 검사 — 시간·인원 미확인(SOP 5.x '◆6.2 검사' TBD)
        Equipment("inspect", "검사(육안)", 4, 0.0, ("CU44", "CU19", "AL16", "SIL"), tbd_count=True),
    ]
    return {e.key: e for e in specs}


# ── 공정 단계 ─────────────────────────────────────────────────────────────


@dataclass
class Step:
    """라인의 한 공정 단계.

    `minutes`는 아웃풋 로트 1개를 처리하는 순수 가공시간(SOP 5.x '단계 시간').
    `split`은 인풋 로트 1개가 아웃풋 로트 몇 개로 나뉘는지(SOP 7.3 로트 변환).
    """

    seq: str          # SOP 공정 순번 (예: "2.1")
    label: str
    equip: str        # Equipment.key
    minutes: float
    split: int = 1
    out_len_m: float = 0.0   # 아웃풋 로트 1개의 길이(m) — 물량 집계용
    tbd_time: bool = False


@dataclass
class Line:
    key: str
    label: str
    steps: list[Step]
    color: str = "#4C78A8"


def _cu44_steps(shielded: bool) -> list[Step]:
    """SOP 5.1 Cu44 라우팅. 태신선·멀티신선은 별도 배치 공정으로 앞단에서 처리."""
    steps = [
        # 100,000m 소선 보빈 → 24,000m 도체 보빈 ×4
        Step("2.4", "연선", "strand", 400.0, split=4, out_len_m=24_000),
        Step("3.1", "절연 압출", "ins_ext", 150.0, out_len_m=24_000),
        Step("3.3", "조사 ①(절연 가교)", "irradiator", 116.5, out_len_m=24_000),
    ]
    if shielded:
        steps += [
            # 24,000m → 12,000m ×2, 각 8,000분 (1.5m/min)
            Step("4.1", "편조(차폐)", "braider", 8_000.0, split=2, out_len_m=12_000),
            Step("4.2", "테이핑", "taping", 600.0, out_len_m=12_000),
            Step("5.1", "시스 압출", "sheath_ext", 200.0, out_len_m=12_000),
            Step("5.2", "조사 ②(시스 가교)", "irradiator", 61.5, out_len_m=12_000),
            Step("6.1", "재권취(1050Φ)", "rewind1050", 240.0, out_len_m=12_000),
        ]
    else:
        # 비차폐 경로: 24,000m를 그대로 재권취 (480분 = 24,000m ÷ 50m/min)
        steps += [Step("6.1", "재권취(1050Φ)", "rewind1050", 480.0, out_len_m=24_000)]
    steps += [Step("6.2", "검사(육안)", "inspect", 10.0, tbd_time=True)]
    return steps


def _cu19_steps() -> list[Step]:
    """SOP 5.2 Cu19 라우팅. 튜블러(2.5)는 병합 공정이라 엔진에서 별도 처리."""
    return [
        # 튜블러 이후 구간만 여기서 정의 (앞단은 엔진의 병합 로직)
        Step("3.1", "절연 압출", "ins_ext", 83.3, split=4, out_len_m=5_000),
        Step("3.3", "조사(절연 가교)", "irradiator", 33.3, out_len_m=5_000),
        Step("6.1", "재권취(1250Φ)", "rewind1250", 100.0, out_len_m=5_000),
        Step("6.2", "검사(육안)", "inspect", 10.0, tbd_time=True),
    ]


def _al16_steps() -> list[Step]:
    """SOP 5.3 AL16 라우팅.

    ⚠집합 구간의 로트 변환(40,000m → 800m → 400m, 13가닥 합사)은 SOP 7.3에서
    '분할+병합'으로만 기재되어 가닥 수지가 닫히지 않는다(질문 #1). 여기서는
    SOP 5.3이 못 박은 페이스('하루 10보빈')에 맞춰 40,000m 보빈 1개가
    최종 400m 도체 보빈 1개가 되는 것으로 두고, 단계 시간은 표를 그대로 쓴다.
    """
    return [
        Step("2.3a", "집합(더블)", "bunch_al_dbl", 8.0, out_len_m=800),
        Step("2.3b", "집합(싱글 1~12호기)", "bunch_al_sgl", 18.2, out_len_m=800),
        Step("2.3c", "집합(합사)", "bunch_al_fin", 12.5, out_len_m=400),
        Step("3.1", "절연 압출", "ins_ext", 8.0, out_len_m=400),
        Step("3.3", "조사(전자빔 가교)", "irradiator", 3.6, out_len_m=400),
        Step("6.1", "재권취(1050Φ)", "rewind1050", 8.0, out_len_m=400),
        Step("6.2", "검사(육안)", "inspect", 10.0, tbd_time=True),
    ]


def _sil_steps() -> list[Step]:
    """SOP 5.4 실리콘 HV 라우팅. 실리콘은 압출 중 가교되어 조사 공정이 없다."""
    return [
        # 5,000m 도체 → 1,000m 보빈 ×5
        Step("3.2", "실리콘 압출", "sil_ext", 50.0, split=5, out_len_m=1_000),
        Step("4.1", "편조(차폐)", "sil_braider", 666.7, out_len_m=1_000),
        Step("4.2", "테이핑", "sil_taping", 50.0, out_len_m=1_000),
        Step("5.1", "시스 압출", "sil_sheath", 66.7, out_len_m=1_000),
        Step("6.2", "검사", "inspect", 10.0),
    ]


# ── 입고·배치 ─────────────────────────────────────────────────────────────


@dataclass
class InboundConfig:
    """SOP 7.2 입고 규칙."""

    # Cu 로드: 월 13대, 1대 6롤(19.8t) = 257.4t/월, 월초 집중
    cu_trucks_per_month: int = 13
    cu_ton_per_truck: float = 19.8
    cu_arrival_window_days: float = 5.0   # 월초 집중 도착 창
    # AL 선재: 월초부터 12일간 하루 2롤(2t)
    al_days: int = 12
    al_ton_per_day: float = 2.0
    # 실리콘용 도체: 2주 1회 5t (1t ≈ 케이블 14,000m)
    sil_interval_days: float = 14.0
    sil_ton_per_delivery: float = 5.0
    sil_m_per_ton: float = 14_000.0


@dataclass
class ConductorConfig:
    """SOP 5.1·5.2 도체 앞단(태신선·멀티신선) — Cu44/Cu19 공유 구간."""

    # 태신선: 3.3t 보빈 1개 → 1t 캐리어 3개, 60분/보빈
    taeshin_bobbin_ton: float = 3.3
    taeshin_min_per_bobbin: float = 60.0
    carriers_per_bobbin: int = 3
    # 멀티신선: 캐리어 24개(24t) 배치
    multi_carriers_per_batch: int = 24
    multi_cu44_min: float = 83.3
    multi_cu44_bobbins: int = 9          # 100,000m ×9
    multi_cu44_len_m: float = 100_000
    multi_cu19_min: float = 66.7
    multi_cu19_bobbins: int = 11         # 80,000m ×11
    multi_cu19_len_m: float = 80_000
    # SOP 7.2: Cu44 4회 → Cu19 1회 사이클
    cycle_cu44: int = 4
    cycle_cu19: int = 1
    # Cu19 3단 꼬임 (SOP 5.2)
    bunch19_min: float = 800.0           # 집합, 80,000m
    strand19_min: float = 1333.3         # 연선, 80,000m
    tubular_min: float = 181.8           # 집합1 + 연선1 → 20,000m ×4
    tubular_out_lots: int = 4
    tubular_out_len_m: float = 20_000
    # AL16 멀티신선: 2롤(2t) → 40,000m 보빈, 144분
    multi_al_min: float = 144.0
    multi_al_len_m: float = 40_000


@dataclass
class CalendarConfig:
    """SOP 6.3·7.5 운영 캘린더."""

    hours_per_day: float = 24.0
    weekend_stop_hours: float = 52.0     # 주말 52시간 정지
    monday_startup_hours: float = 3.0    # ⚠해석(질문 #3): 월요일 공정별 3시간 스타트업
    availability: float = 0.926          # 실효 가동률 92.6%


@dataclass
class PalletConfig:
    """SOP 7.6 파렛트 완성 조건."""

    cu44_bobbins_per_pallet: int = 18
    cu19_bundles_per_pallet: int = 45


@dataclass
class CmsConfig:
    sim_days: int = 30                   # SOP 7.5: 시뮬레이션 기간 1개월
    random_seed: int = 42
    # SOP 7.2·질문 #5: 차폐 경로를 타는 Cu44 SKU 비율 — 시나리오 변수
    cu44_shield_ratio: float = 0.20
    # SOP 5.4·질문 #18: 실리콘 월 물량 (AL 기준 350,000m)
    sil_month_m: float = 350_000.0

    equipment: dict[str, Equipment] = field(default_factory=default_equipment)
    inbound: InboundConfig = field(default_factory=InboundConfig)
    conductor: ConductorConfig = field(default_factory=ConductorConfig)
    calendar: CalendarConfig = field(default_factory=CalendarConfig)
    pallet: PalletConfig = field(default_factory=PalletConfig)

    @property
    def sim_horizon_min(self) -> int:
        return int(self.sim_days * 24 * 60)

    def lines(self) -> dict[str, Line]:
        return {
            "CU44": Line("CU44", "Cu44 (44/0.29)", _cu44_steps(shielded=False), "#4C78A8"),
            "CU44S": Line("CU44S", "Cu44 차폐 SKU", _cu44_steps(shielded=True), "#3B6BA5"),
            "CU19": Line("CU19", "Cu19 (19/9/0.315)", _cu19_steps(), "#F58518"),
            "AL16": Line("AL16", "AL16 (16㎟)", _al16_steps(), "#54A24B"),
            "SIL": Line("SIL", "실리콘 HV", _sil_steps(), "#E45756"),
        }


DEFAULT_CMS_CONFIG = CmsConfig()
