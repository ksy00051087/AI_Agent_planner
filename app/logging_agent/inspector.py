"""이상 징후 판정 (F3020) — 규칙만. LLM 을 쓰지 않는다.

요청(run) 1건의 이벤트를 읽고 세 가지를 센다.
    REPEATED_CALL      같은 Tool 을 같은 인자로 두 번 이상 불렀다 (재사용 캐시가 깨졌다는 신호)
    EXCESSIVE_REPLAN   재계획이 상한에 닿았다
    UNPLANNED_CALL     plan 단계가 정한 Tool 목록에 없던 Tool 을 불렀다
근거 이벤트가 없으면 '이상 없음' 이 아니라 '판정 불가' 다.
"""

from __future__ import annotations

import json
from collections import defaultdict

NORMAL, ANOMALY, UNKNOWN = "정상", "이상", "판정 불가"


def _args_key(args) -> str:
    return json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)


def inspect_run(events: list[dict], replan_limit: int = 2) -> dict:
    """반환 {"run_id", "session_id", "verdict", "warnings": [{"type", "detail", "evidence": [seq]}], "counts"}"""
    if not events:
        return {"run_id": None, "session_id": None, "verdict": UNKNOWN, "warnings": [],
                "reason": "이벤트가 없음", "counts": {}}
    run_id, session_id = events[0].get("run_id"), events[0].get("session_id")
    calls = [e for e in events if e["type"] == "tool_call"]
    replans = [e for e in events if e["type"] == "replan"]
    plan_exit = next((e for e in events if e["type"] == "node_exit" and e.get("node") == "plan"), None)
    finished = any(e["type"] == "node_exit" and e.get("node") == "respond" for e in events)
    counts = {"tool_calls": len(calls), "replans": len(replans), "events": len(events)}

    if not finished:
        return {"run_id": run_id, "session_id": session_id, "verdict": UNKNOWN, "warnings": [],
                "reason": "응답 단계 종료 이벤트가 없어 실행이 끝났는지 알 수 없음", "counts": counts}
    if calls and plan_exit is None:
        return {"run_id": run_id, "session_id": session_id, "verdict": UNKNOWN, "warnings": [],
                "reason": "Tool 을 불렀는데 계획(plan) 이벤트가 없어 '계획에 없던 호출' 을 판정할 수 없음", "counts": counts}

    warnings = []
    same = defaultdict(list)
    for e in calls:
        same[(e["tool"], _args_key(e.get("args")))].append(e["seq"])
    for (tool, args), seqs in same.items():
        if len(seqs) > 1:
            warnings.append({"type": "REPEATED_CALL", "detail": f"{tool} 를 같은 인자 {args} 로 {len(seqs)}번 호출",
                             "evidence": seqs})

    if replan_limit and len(replans) >= replan_limit:
        warnings.append({"type": "EXCESSIVE_REPLAN", "detail": f"재계획 {len(replans)}회로 상한({replan_limit})에 닿음",
                         "evidence": [e["seq"] for e in replans]})

    if plan_exit is not None:
        planned = {s.get("tool") for s in ((plan_exit.get("summary") or {}).get("steps") or [])}
        extra = [e for e in calls if e["tool"] not in planned]
        if extra:
            warnings.append({"type": "UNPLANNED_CALL",
                             "detail": f"계획에 없던 Tool 호출: {sorted({e['tool'] for e in extra})}",
                             "evidence": [e["seq"] for e in extra]})

    return {"run_id": run_id, "session_id": session_id, "verdict": ANOMALY if warnings else NORMAL,
            "warnings": warnings, "reason": None, "counts": counts}


DIAGNOSE_PROMPT = """너는 자격증 플래너 Agent 의 실행 기록을 점검한다. 아래 규칙 판정에서 이상 징후가 나왔다.
원인이 어느 쪽(메인 Agent 의 요청 해석 · 계획 · Tool · 재계획 규칙 중 어디)에 있는지, 무엇을 고치면 되는지
한국어 세 문장 이내로 진단한다. 기록에 없는 사실을 지어내지 않는다.

판정: {warnings}

실행 기록(요약):
{events}
"""


def summarize_for_diagnosis(events: list[dict], limit: int = 60) -> str:
    """진단 LLM 에 넘길 요약 — 원본 응답 · 긴 필드는 뺀다."""
    lines = []
    for e in events[:limit]:
        keep = {k: e[k] for k in ("tool", "args", "ok", "code", "count", "kind", "decision", "reason",
                                  "reason_code", "change", "summary") if k in e and e[k] not in (None, "", [])}
        lines.append(f"{e['seq']}. {e['type']} {e.get('node') or ''} {json.dumps(keep, ensure_ascii=False, default=str)[:300]}")
    return "\n".join(lines)
