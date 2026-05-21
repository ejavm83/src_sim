"""웹·대시보드 용어 약어 — 읽기 전용 (「📘 사용 기술」 탭과 분리)."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import streamlit as st

from views.display_sanitize import sanitize_display_text

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CANONICAL_PROCESS_DOC = _PROJECT_ROOT / "data" / "공정설명260521.md"
_WEB_TERMS_SECTION_START = "# 웹·대시보드에서 쓰는 용어 약어"
_WEB_TERMS_SECTION_END = "\n---\n\n# 적용 기술과 본 프로젝트에서의 활용"


def _parse_frontmatter(raw: str) -> Tuple[dict[str, str], str]:
    text = raw.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}, text
    block = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body.lstrip("\n")


def _read_process_doc_body(path: Path) -> str:
    if not path.is_file():
        return ""
    raw = path.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(raw)
    return body


def load_web_terminology_markdown() -> str | None:
    """`data/공정설명260521.md`에서 용어 약어 절만 읽습니다. 구조가 맞지 않으면 None."""
    body = _read_process_doc_body(_CANONICAL_PROCESS_DOC)
    if not body or _WEB_TERMS_SECTION_START not in body:
        return None
    i = body.index(_WEB_TERMS_SECTION_START)
    j = body.find(_WEB_TERMS_SECTION_END, i)
    if j == -1:
        return None
    chunk = body[i:j].strip()
    return chunk or None

_WEB_ABBREV_FALLBACK_MD = """
아래는 **이 Streamlit 대시보드**와 일반 웹·IT 문서에서 자주 나오는 약어입니다. **한글 용어** 열은 관행적 한국어 이름·풀이를 짧게 적었습니다.

공정 약어 **SCR**은 이 문서·앱에서 **구리선 코일 제품**을 가리키며, 웹의 “스크립트(script)”와는 다릅니다.

#### 일반 웹·IT

| 약어 | 한글 용어 | 풀어쓴 말 | 이 화면에서의 느낌 |
|------|-----------|-----------|-------------------|
| **UI** | 사용자 인터페이스 | User Interface | 버튼·탭·차트 등 **눈에 보이는 화면** |
| **UX** | 사용자 경험 | User Experience | 찾기 쉬운 배치, 안내 문구 등 **쓰기 편함** |
| **URL** | 통합 자원 위치 지시자 | Uniform Resource Locator | 브라우저 주소창에 보이는 **페이지 주소** |
| **HTTP / HTTPS** | 초본문 전송 규약 / 보안 연결 | HyperText Transfer Protocol (+ Secure) | 브라우저와 서버가 **데이터를 주고받는 규약**. `S`는 암호화(자물쇠 아이콘) |
| **HTML** | 초본문 표기 언어 | HyperText Markup Language | 웹 문서의 **뼈대(제목·표·링크)** |
| **CSS** | 연쇄 스타일 시트 | Cascading Style Sheets | 글꼴·색·여백 등 **모양** |
| **JS** | 자바스크립트 | JavaScript | 브라우저 안에서 도는 **동작·반응** 코드 |
| **API** | 응용 프로그램 인터페이스 | Application Programming Interface | 프로그램끼리 **기능을 빌려 쓰는 창구**(데이터 요청·응답) |
| **REST** | 표현 상태 전송 | Representational State Transfer | API를 **URL·HTTP 메서드**로 단순하게 쓰는 설계 스타일(자주 REST API라고 부름) |
| **JSON** | 자바스크립트 객체 표기법 | JavaScript Object Notation | `{ "키": 값 }` 형태의 **가벼운 데이터 교환 형식** |
| **CSV** | 쉼표로 구분한 값 | Comma-Separated Values | 쉼표로 칸을 나눈 **표 형태 텍스트**(엑셀 호환) |
| **PDF** | 휴대용 문서 형식 | Portable Document Format | **인쇄·배포**에 쓰는 고정 레이아웃 문서 |
| **MD / Markdown** | 마크다운(경량 표기) | — | `# 제목`, 목록 등 **간단한 문법**으로 글을 쓰는 형식 |
| **UTF-8** | 유니코드 8비트 변환 형식 | 8-bit Unicode Transformation Format | 한글·기호를 포함한 **글자 인코딩**(저장 파일 기본) |
| **KPI** | 핵심 성과 지표 | Key Performance Indicator | **핵심 지표**(가동률·처리량 등) |
| **FIFO** | 선입선출 | First In, First Out | **먼저 들어온 것부터** 처리하는 대기열 규칙 |
| **CP-SAT** | 제약 프로그래밍·만족 문제 기반 솔버 | Constraint Programming + SAT | OR-Tools의 **제약 만족·최적화 솔버** 계열 |
| **SPA** | 단일 페이지 애플리케이션 | Single Page Application | 한 페이지에서 **부분만 갱신**하는 웹앱 스타일 |
| **CDN** | 콘텐츠 전송 네트워크 | Content Delivery Network | 지리적으로 가까운 서버에서 **정적 파일을 빨리** 주는 배포망 |

#### Streamlit·이 앱 코드에서 자주 보는 말

| 용어 | 한글 용어 | 설명 |
|------|-----------|------|
| **Streamlit** | 스트림릿 | Python만으로 **웹 대시보드**를 만드는 프레임워크 |
| **`st.`** | 스트림릿 모듈 접두사 | Streamlit 모듈 접두사. `st.button`, `st.tabs` 등 **위젯·출력** 호출 |
| **session_state** | 세션 상태(브라우저별 저장) | 같은 브라우저 세션 안에서 **입력값·편집 본문을 기억**하는 저장소 |
| **rerun** | 재실행(화면 갱신) | 위젯 이벤트 후 **스크립트를 위에서 다시 실행**해 화면을 갱신하는 동작 |
"""


def render() -> None:
    st.header("🔤 용어·약어")

    _from_doc = load_web_terminology_markdown()
    _md = _from_doc if _from_doc else _WEB_ABBREV_FALLBACK_MD
    st.markdown(sanitize_display_text(_md))
