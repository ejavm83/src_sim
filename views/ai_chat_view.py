"""💬 AI 어시스턴트 — 대화 내용을 기존 공정 JSON·MD에 보완 반영한다.

대화에서 확인·정리된 내용을 현재 JSON·MD 위에 덧붙이거나 수정한다.
LLM 응답은 두 가지 JSON 수정 채널을 가진다.
  json_updates : 스칼라 리프 값 수정 (경로 + 새 값)
  json_patch   : 구조적 수정 (remove / add / replace_object)
                 배열 요소 삭제·추가, 객체 전체 교체에 사용한다.
변경은 즉시 std_schema_result 세션에 적용 → 📋·📐 탭에 반영된다.
MD는 기존 문서 전체에 대화 내용을 반영한 텍스트를 디스크에 저장 → 📄 공정 설명 탭.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import streamlit as st

_CHAT_KEY = "ai_chat_history"
_CHAT_INPUT_KEY = "ai_chat_input"


# ─── 현재 컨텍스트 ────────────────────────────────────────────────────────────────

def _current_md() -> str:
    try:
        from views.process_description import _EDIT_MODE_KEY, _SESSION_DRAFT_KEY, _load_text
        if st.session_state.get(_EDIT_MODE_KEY):
            return str(st.session_state.get(_SESSION_DRAFT_KEY, ""))
        return _load_text()
    except Exception:
        return ""


def _current_json() -> dict[str, Any]:
    result = st.session_state.get("std_schema_result")
    if isinstance(result, dict) and "updated" in result:
        return result["updated"]
    try:
        from schema_extract import load_base_schema
        return load_base_schema()
    except Exception:
        return {}


# ─── LLM 응답 스키마 ──────────────────────────────────────────────────────────────

def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "json_updates": {
                "type": "array",
                "description": "스칼라 리프 값 변경. path는 반드시 스칼라 리프여야 함.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path":     {"type": "string"},
                        "value":    {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["path", "value"],
                    "additionalProperties": False,
                },
            },
            "json_patch": {
                "type": "array",
                "description": (
                    "구조적 변경. op: remove(배열 요소·키 삭제), "
                    "add(배열에 객체 추가), replace_object(객체/배열 전체 교체). "
                    "value는 JSON 직렬화 문자열."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "op":    {"type": "string", "enum": ["remove", "add", "replace_object"]},
                        "path":  {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["op", "path"],
                    "additionalProperties": False,
                },
            },
            "md_updated": {"type": "string"},
        },
        "required": ["reply", "json_updates", "json_patch", "md_updated"],
        "additionalProperties": False,
    }


# ─── 시스템 프롬프트 ──────────────────────────────────────────────────────────────

def _system_prompt(cur_json: dict, cur_md: str, history: list[dict]) -> str:
    history_text = ""
    if history:
        lines = []
        for m in history[-6:]:
            role = "사용자" if m["role"] == "user" else "어시스턴트"
            lines.append(f"[{role}] {m['content'][:300]}")
        history_text = "\n\n이전 대화:\n" + "\n".join(lines)

    json_text = json.dumps(cur_json, ensure_ascii=False, indent=2)
    md_preview = cur_md[:3000] + ("\n...(이하 생략)" if len(cur_md) > 3000 else "")

    return (
        "당신은 케이블 제조 공정 관리 AI 어시스턴트입니다.\n"
        "대화에서 확인된 내용을 **기존** 공정 JSON·MD에 보완·반영합니다. "
        "요청과 이전 대화 맥락을 바탕으로, 현재 데이터·문서를 유지한 채 필요한 부분만 추가·수정하세요.\n"
        + history_text
        + "\n\n현재 공정 JSON:\n```json\n" + json_text + "\n```\n\n"
        "현재 공정 설명(MD):\n```\n" + md_preview + "\n```\n\n"
        "━━━ 출력 규칙 ━━━\n\n"
        "【json_updates】 — 스칼라 리프 값 수정\n"
        "  - path: 현재 JSON에 실제 존재하는 스칼라(숫자·문자열·불리언) 경로만 허용\n"
        "    예) process_routing.steps[0].std_speed\n"
        "  - value: 항상 문자열 (숫자 \"350\", 불리언 \"true\")\n"
        "  - 객체나 배열 자체를 path 대상으로 하면 자동으로 거부됨\n\n"
        "【json_patch】 — 구조적 수정 (배열 요소 삭제·추가, 객체 교체)\n"
        "  op: \"remove\"  — 배열 요소 또는 키 삭제\n"
        "    path 예) process_routing.steps[1]  (인덱스는 0-based)\n"
        "    value: 빈 문자열 \"\"\n"
        "  op: \"add\"  — 배열에 새 객체 추가 (배열 경로 지정, 항목은 끝에 추가됨)\n"
        "    path 예) process_routing.steps\n"
        "    value: 추가할 객체를 JSON 직렬화 문자열로\n"
        "      예) \"{\\\"step_no\\\": 3, \\\"process_name\\\": \\\"장입/용해\\\", ...}\"\n"
        "  op: \"replace_object\"  — 경로의 객체/배열 전체를 교체\n"
        "    path 예) process_routing.steps\n"
        "    value: 교체할 전체 값을 JSON 직렬화 문자열로\n\n"
        "【md_updated】 — 기존 MD 전체에 대화 내용을 반영한 텍스트(미수정 구간은 그대로 유지). "
        "수정 없으면 빈 문자열.\n\n"
        "【reply】 — 사용자에게 전달할 한국어 설명 (변경 항목·이유 요약).\n\n"
        "주의: json_patch.value에서 객체는 반드시 올바른 JSON 문자열이어야 합니다."
    )


# ─── LLM 호출 ────────────────────────────────────────────────────────────────────

def _call_llm(user_msg: str, cur_json: dict, cur_md: str, history: list[dict]) -> dict:
    from llm_config import generate_structured_json

    raw = generate_structured_json(
        _system_prompt(cur_json, cur_md, history),
        _response_schema(),
        user_msg,
    )
    data = json.loads(raw)
    return {
        "reply":        str(data.get("reply", "")),
        "json_updates": data.get("json_updates") or [],
        "json_patch":   data.get("json_patch") or [],
        "md_updated":   str(data.get("md_updated", "")),
    }


# ─── JSON 변경 적용 ───────────────────────────────────────────────────────────────

def _apply_scalar_updates(
    updates: list[dict], obj: dict
) -> tuple[list[dict], list[dict]]:
    """스칼라 값 변경 적용. (diffs, skipped) 반환."""
    from schema_extract import apply_updates
    _, diffs, skipped = apply_updates(obj, updates)
    return diffs, skipped


def _apply_patch(patches: list[dict], obj: dict) -> tuple[list[str], list[str]]:
    """구조적 패치(remove/add/replace_object) 적용. (applied_msgs, failed_msgs) 반환."""
    from schema_extract import _navigate, _parse_path  # noqa: PLC0415

    applied: list[str] = []
    failed:  list[str] = []

    for p in patches:
        op    = str(p.get("op", "")).strip().lower()
        path  = str(p.get("path", "")).strip()
        val_s = str(p.get("value", "")).strip()

        if op not in ("remove", "add", "replace_object") or not path:
            failed.append(f"`{path}` — 알 수 없는 연산 `{op}`")
            continue

        toks = _parse_path(path)
        if not toks:
            failed.append(f"`{path}` — 경로 파싱 실패")
            continue

        # 상위 노드 탐색
        if len(toks) > 1:
            ok, parent = _navigate(obj, toks[:-1])
        else:
            ok, parent = True, obj
        last = toks[-1]

        if not ok:
            failed.append(f"`{path}` — 상위 경로 없음")
            continue

        try:
            if op == "remove":
                if isinstance(last, int) and isinstance(parent, list):
                    if 0 <= last < len(parent):
                        del parent[last]
                        applied.append(f"제거: `{path}`")
                    else:
                        failed.append(f"`{path}` — 인덱스 범위 초과 (길이 {len(parent)})")
                elif isinstance(parent, dict) and last in parent:
                    del parent[last]
                    applied.append(f"제거: `{path}`")
                else:
                    failed.append(f"`{path}` — 키/인덱스 없음")

            elif op == "add":
                # 대상이 배열이면 요소 추가
                ok2, target = _navigate(obj, toks)
                if ok2 and isinstance(target, list):
                    try:
                        item = json.loads(val_s) if val_s else {}
                    except json.JSONDecodeError:
                        item = val_s
                    if isinstance(item, list):
                        target.extend(item)
                    else:
                        target.append(item)
                    applied.append(f"추가: `{path}` (1개 항목)")
                else:
                    failed.append(f"`{path}` — 배열이 아니어서 add 불가")

            elif op == "replace_object":
                try:
                    new_val = json.loads(val_s) if val_s else None
                except json.JSONDecodeError:
                    new_val = val_s
                parent[last] = new_val  # type: ignore[index]
                applied.append(f"교체: `{path}`")

        except Exception as exc:  # noqa: BLE001
            failed.append(f"`{path}` — 오류: {exc}")

    return applied, failed


def _commit_json(
    updated: dict,
    extra_diffs: list[dict],
    extra_skipped: list[dict],
    patch_applied: list[str],
) -> None:
    """변경된 JSON을 std_schema_result 세션에 저장하고 테이블 캐시를 무효화한다."""
    prev = st.session_state.get("std_schema_result") or {}
    st.session_state["std_schema_result"] = {
        "updated":   updated,
        "diffs":     (prev.get("diffs") or []) + extra_diffs,
        "skipped":   (prev.get("skipped") or []) + extra_skipped,
        "missing":   prev.get("missing") or [],
        "ambiguous": prev.get("ambiguous") or [],
    }
    # 변경된 경로 세트 저장 → 📋 공정 데이터 탭에서 강조 표시
    changed_paths: set[str] = st.session_state.get("_ai_changed_paths") or set()
    for d in extra_diffs:
        changed_paths.add(d["경로"])
    for msg in patch_applied:
        # "제거: `path`" / "추가: `path`" / "교체: `path`" 형태에서 경로 추출
        if "`" in msg:
            p = msg.split("`")[1]
            changed_paths.add(p)
    st.session_state["_ai_changed_paths"] = changed_paths
    st.session_state.pop("_tbl_src_hash", None)   # 📋 공정 데이터 탭 캐시 무효화


def _apply_md_update(md_updated: str) -> None:
    from views.process_description import (
        PROCESS_DOC_PATH,
        _EDIT_MODE_KEY,
        _SESSION_DRAFT_KEY,
    )
    if not md_updated.strip():
        return
    try:
        PROCESS_DOC_PATH.write_text(md_updated, encoding="utf-8")
        st.session_state[_SESSION_DRAFT_KEY] = md_updated
        st.session_state[_EDIT_MODE_KEY] = False
    except Exception as exc:
        st.warning(f"MD 저장 실패: {exc}")


# ─── 메시지 처리 ──────────────────────────────────────────────────────────────────

def _handle_message(user_msg: str) -> None:
    history: list[dict] = st.session_state.setdefault(_CHAT_KEY, [])
    history.append({"role": "user", "content": user_msg, "meta": None})

    cur_json = _current_json()
    cur_md   = _current_md()

    with st.spinner("AI가 응답을 생성하는 중..."):
        try:
            result = _call_llm(user_msg, cur_json, cur_md, history[:-1])
        except Exception as exc:  # noqa: BLE001
            history.append({"role": "assistant", "content": f"⚠️ 오류: {exc}", "meta": None})
            st.rerun()
            return

    # 변경 적용 (deep copy 위에서 진행 후 한 번에 커밋)
    meta: dict[str, Any] = {}
    has_change = bool(result["json_updates"] or result["json_patch"])

    if has_change:
        working = copy.deepcopy(cur_json)

        # ① 스칼라 업데이트
        diffs: list[dict] = []
        skipped: list[dict] = []
        if result["json_updates"]:
            from schema_extract import apply_updates
            working, diffs, skipped = apply_updates(working, result["json_updates"])

        # ② 구조적 패치
        patch_applied: list[str] = []
        patch_failed:  list[str] = []
        if result["json_patch"]:
            patch_applied, patch_failed = _apply_patch(result["json_patch"], working)

        # 세션에 커밋
        _commit_json(working, diffs, skipped, patch_applied)

        meta["json_scalar_applied"] = len(diffs)
        meta["json_scalar_skipped"] = skipped
        meta["json_patch_applied"]  = patch_applied
        meta["json_patch_failed"]   = patch_failed
        meta["json_diffs"]          = diffs

    if result["md_updated"].strip():
        _apply_md_update(result["md_updated"])
        meta["md_changed"] = True
        st.session_state["_ai_md_changed"] = True

    # toast 메시지 준비 (rerun 후 표시)
    parts = []
    if meta.get("json_scalar_applied"):
        parts.append(f"값 수정 {meta['json_scalar_applied']}건")
    if meta.get("json_patch_applied"):
        parts.append(f"구조 변경 {len(meta['json_patch_applied'])}건")
    if meta.get("md_changed"):
        parts.append("MD 수정")
    if parts:
        st.session_state["_ai_toast"] = "✅ JSON 수정 완료 — " + " · ".join(parts)

    history.append({"role": "assistant", "content": result["reply"], "meta": meta or None})
    st.rerun()


# ─── UI ───────────────────────────────────────────────────────────────────────────

def _badge(text: str, color: str) -> str:
    palette = {
        "green":  ("#22c55e22", "#22c55e66", "#15803d"),
        "yellow": ("#fef9c322", "#fde04766", "#92400e"),
        "blue":   ("#3b82f622", "#3b82f666", "#1e3a8a"),
        "red":    ("#fee2e222", "#fca5a566", "#991b1b"),
    }
    bg, bd, fg = palette.get(color, palette["green"])
    return (
        f'<span style="background:{bg};border:1px solid {bd};border-radius:4px;'
        f'padding:2px 8px;font-size:0.8rem;color:{fg};">{text}</span>'
    )


def _render_meta_badge(meta: dict) -> None:
    badges = []

    sa = meta.get("json_scalar_applied", 0)
    pa = meta.get("json_patch_applied") or []
    sf = meta.get("json_scalar_skipped") or []
    pf = meta.get("json_patch_failed") or []

    if sa:
        badges.append(_badge(f"✓ 값 수정 {sa}건", "green"))
    if pa:
        badges.append(_badge(f"✓ 구조 변경 {len(pa)}건", "green"))
    if meta.get("md_changed"):
        badges.append(_badge("✓ MD 수정", "blue"))
    if sf or pf:
        badges.append(_badge(f"⚠️ 실패 {len(sf) + len(pf)}건", "yellow"))

    if not badges:
        return

    st.markdown(" &nbsp; ".join(badges), unsafe_allow_html=True)

    # 상세 펼치기
    if meta.get("json_diffs"):
        with st.expander(f"값 변경 상세 ({sa}건)", expanded=False):
            for d in meta["json_diffs"]:
                st.markdown(f"- `{d['경로']}` : **{d['표준값']}** → **{d['추출값']}**")

    if pa:
        with st.expander(f"구조 변경 상세 ({len(pa)}건)", expanded=False):
            for msg in pa:
                st.markdown(f"- {msg}")

    if sf or pf:
        with st.expander(f"실패 상세 ({len(sf) + len(pf)}건)", expanded=True):
            for s in sf:
                st.markdown(f"- `{s.get('path','?')}` — {s.get('reason','')}")
            for f in pf:
                st.markdown(f"- {f}")


def render_page() -> None:
    # 수정 완료 toast
    if st.session_state.get("_ai_toast"):
        st.toast(st.session_state.pop("_ai_toast"), icon="✅")

    st.header("💬 AI 어시스턴트")
    st.caption(
        "대화로 정리한 내용을 **기존** 공정 데이터(JSON)와 공정 설명(MD)에 보완·반영하세요. "
        "JSON 변경은 **📋 공정 데이터** · **📐 표준 JSON** 탭에, "
        "MD 변경은 **📄 공정 설명** 탭에 즉시 반영됩니다. "
        "(API 키 필요 — **⚙️ 설정** 탭)"
    )

    from llm_config import api_key_configured, resolve_api_key_info
    if not api_key_configured():
        st.warning("LLM API 키가 설정되지 않았습니다. **⚙️ 설정** 탭에서 등록하세요.")
        return

    info = resolve_api_key_info()
    provider_label = "Gemini" if info.provider == "gemini" else "OpenAI"
    st.caption(f"현재 제공자: **{provider_label}** · 키: `{info.masked}`")

    history: list[dict] = st.session_state.get(_CHAT_KEY, [])

    if not history:
        st.markdown(
            """
**예시 — 대화 내용을 기존 JSON에 보완 반영:**
- `방금 말한 신선 표준 속도 350 m/min을 기존 JSON에 반영해줘`
- `대화에서 정한 절연 재질 XLPE를 공정 데이터에 보완해줘`
- `논의한 대로 연선 공정 단계는 삭제하고, JSON 구조도 맞춰줘`

**예시 — 대화 내용을 기존 MD에 보완 반영:**
- `지금까지 말한 야간 교대 운영 내용을 공정 설명에 추가해줘`
- `앞에서 확인한 용해 2시간 세팅을 해당 단계 설명에 보완해줘`
- `대화로 정리한 신선 속도 350m/min을 MD 해당 문단에도 맞춰줘`
            """.strip()
        )

    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("meta"):
                _render_meta_badge(msg["meta"])

    if prompt := st.chat_input("대화 내용을 JSON·MD에 보완 반영해 달라고 요청하세요...", key=_CHAT_INPUT_KEY):
        _handle_message(prompt)

    # ── 변경 내용 확인 패널 ──
    ai_paths: set[str] = st.session_state.get("_ai_changed_paths") or set()
    result = st.session_state.get("std_schema_result")
    cur_md  = _current_md()
    md_changed = st.session_state.get("_ai_md_changed", False)

    has_json_change = bool(ai_paths and isinstance(result, dict))
    has_md_change   = bool(md_changed and cur_md.strip())

    if has_json_change or has_md_change:
        st.divider()
        st.markdown("#### 🔍 변경 내용 확인")

        if has_json_change and has_md_change:
            tab_j, tab_m = st.tabs(["📊 변경된 JSON", "📝 변경된 MD"])
        elif has_json_change:
            tab_j = st.container()
            tab_m = None
        else:
            tab_j = None
            tab_m = st.container()

        if has_json_change and tab_j is not None:
            with tab_j:
                diffs = result.get("diffs") or []
                ai_diffs = [d for d in diffs if d.get("경로") in ai_paths]
                patch_paths = [p for p in ai_paths if not any(d.get("경로") == p for d in diffs)]

                if ai_diffs:
                    st.markdown("**값 변경 항목**")
                    rows_data = [
                        {"경로": d["경로"], "이전 값": str(d["표준값"]), "변경 후": str(d["추출값"])}
                        for d in ai_diffs
                    ]
                    import pandas as pd
                    st.dataframe(
                        pd.DataFrame(rows_data),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "경로":   st.column_config.TextColumn("경로", width="large"),
                            "이전 값": st.column_config.TextColumn("이전 값", width="small"),
                            "변경 후": st.column_config.TextColumn("변경 후", width="small"),
                        },
                    )
                if patch_paths:
                    st.markdown("**구조 변경 경로**")
                    for p in patch_paths:
                        st.markdown(f"- `{p}`")

                with st.expander("전체 JSON 보기", expanded=False):
                    st.json(result.get("updated", {}), expanded=1)

        if has_md_change and tab_m is not None:
            with tab_m:
                st.text_area(
                    "현재 공정 설명(MD) 전체",
                    value=cur_md,
                    height=400,
                    disabled=True,
                    label_visibility="collapsed",
                )
                st.caption("수정 내용이 **📄 공정 설명** 탭에도 반영되어 있습니다.")

    if history:
        if st.button("🗑️ 대화 초기화", key="ai_chat_clear"):
            st.session_state[_CHAT_KEY] = []
            st.rerun()
