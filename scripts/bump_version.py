"""앱 버전 표기(`webapp.py`의 APP_VERSION_INFO)를 올리고 시각을 지금으로 맞춘다.

    python scripts/bump_version.py            # 패치 증가 (0.3.1 -> 0.3.2)
    python scripts/bump_version.py --minor    # 0.3.1 -> 0.4.0
    python scripts/bump_version.py --major    # 0.3.1 -> 1.0.0
    python scripts/bump_version.py --stage    # 커밋에 포함되도록 색인에도 반영

`--stage`는 **그 한 줄만** 색인(index)에 넣는다. `git add webapp.py`를 쓰면
사용자가 일부러 빼 둔 다른 수정까지 함께 딸려 들어가기 때문에, 색인에 있던
내용에 같은 치환만 적용해 blob을 새로 만들어 넣는다.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "webapp.py"
REL = "webapp.py"

# v0.3.1-generic (2026.08.18 22:26)
_PATTERN = re.compile(
    r'(APP_VERSION_INFO\s*=\s*")v(\d+)\.(\d+)\.(\d+)([^"(]*)\(([^)]*)\)(")'
)


def _bump(text: str, part: str, stamp: str) -> tuple[str, str] | None:
    """버전 문자열을 올린 새 텍스트와 새 버전 표기를 돌려준다. 못 찾으면 None."""
    m = _PATTERN.search(text)
    if not m:
        return None

    major, minor, patch = int(m.group(2)), int(m.group(3)), int(m.group(4))
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1

    suffix = m.group(5)          # "-generic " 같은 꼬리표 (공백 포함 그대로 유지)
    shown = f"v{major}.{minor}.{patch}{suffix}({stamp})"
    return text[: m.start()] + m.group(1) + shown + m.group(7) + text[m.end() :], shown


def _stage_only_this_change(part: str, stamp: str) -> None:
    """색인에 있는 webapp.py에도 같은 치환만 적용해 넣는다(다른 수정은 건드리지 않음)."""
    try:
        staged = subprocess.run(
            ["git", "show", f":{REL}"],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout.decode("utf-8")
    except (subprocess.CalledProcessError, FileNotFoundError, UnicodeDecodeError):
        return  # 추적되지 않는 파일이거나 git이 없으면 조용히 건너뛴다

    result = _bump(staged, part, stamp)
    if result is None:
        return

    sha = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=ROOT, input=result[0].encode("utf-8"),
        capture_output=True, check=True,
    ).stdout.decode().strip()
    subprocess.run(
        ["git", "update-index", "--cacheinfo", f"100644,{sha},{REL}"],
        cwd=ROOT, check=True, capture_output=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--major", action="store_true")
    ap.add_argument("--minor", action="store_true")
    ap.add_argument("--stage", action="store_true", help="색인에도 반영(커밋 훅용)")
    args = ap.parse_args()
    part = "major" if args.major else "minor" if args.minor else "patch"

    if not TARGET.is_file():
        print(f"[bump_version] {REL} 를 찾지 못했습니다.", file=sys.stderr)
        return 1

    text = TARGET.read_text(encoding="utf-8")
    stamp = datetime.now().strftime("%Y.%m.%d %H:%M")
    result = _bump(text, part, stamp)
    if result is None:
        print("[bump_version] APP_VERSION_INFO 표기를 찾지 못했습니다.", file=sys.stderr)
        return 1

    new_text, shown = result
    TARGET.write_text(new_text, encoding="utf-8")
    if args.stage:
        _stage_only_this_change(part, stamp)
    print(f"[bump_version] {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
