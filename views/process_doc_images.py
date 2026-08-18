"""공정 설명 마크다운의 상대경로 이미지를 미리보기에서 실제로 보이게 한다.

Streamlit의 `st.markdown`은 로컬 파일 경로(`images/fig_x.png`)를 못 읽는다.
그래서 표시 직전에 `![alt](상대경로)`를 base64 data URI `<img>` 태그로 바꾼다.
디스크의 .md 원문은 건드리지 않는다 — 다른 도구에서도 그대로 열리도록.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path

import streamlit as st

# ![alt](경로) — 경로가 http(s)/data URI가 아닌 경우만 대상
_IMG_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>(?!https?://|data:)[^)\s]+)\)")

_MAX_BYTES = 8 * 1024 * 1024  # 한 문서에 끼워 넣을 이미지 총량 상한


@st.cache_data(show_spinner=False)
def _data_uri(path_str: str, mtime: float) -> str | None:
    """파일을 data URI로. `mtime`은 캐시 무효화용 키."""
    path = Path(path_str)
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def embed_local_images(md: str, base_dir: Path) -> str:
    """`base_dir` 기준 상대경로 이미지를 인라인 `<img>`로 바꾼 마크다운을 돌려준다.

    파일이 없으면 원래 구문을 두지 않고, 어떤 경로가 비었는지 알려 주는 문구로 바꾼다.
    """
    budget = _MAX_BYTES

    def repl(m: re.Match[str]) -> str:
        nonlocal budget
        alt, src = m.group("alt"), m.group("src")
        path = (base_dir / src).resolve()

        try:
            path.relative_to(base_dir.resolve())
        except ValueError:
            return f"*(이미지 경로가 문서 폴더 밖입니다: `{src}`)*"

        if not path.is_file():
            return f"*(이미지 파일이 없습니다: `{src}`)*"

        uri = _data_uri(str(path), path.stat().st_mtime)
        if uri is None:
            return f"*(이미지를 읽지 못했습니다: `{src}`)*"

        if len(uri) > budget:
            return f"*(이미지가 너무 커서 생략했습니다: `{src}`)*"
        budget -= len(uri)

        # 강조 단계가 alt 안에 넣어 둔 <span>을 걷어낸다
        safe_alt = re.sub(r"<[^>]+>", "", alt).replace('"', "&quot;")
        return (
            f'<img src="{uri}" alt="{safe_alt}" '
            'style="max-width:100%;height:auto;display:block;margin:0.5rem auto;'
            'border:1px solid rgba(128,128,128,0.25);border-radius:6px;background:#fff" />'
        )

    return _IMG_RE.sub(repl, md)


def missing_images(md: str, base_dir: Path) -> list[str]:
    """문서가 참조하지만 실제로는 없는 이미지 경로 목록."""
    out = []
    for m in _IMG_RE.finditer(md):
        src = m.group("src")
        if not (base_dir / src).is_file():
            out.append(src)
    return out
