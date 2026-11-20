"""대표 시나리오 검증 (명세 4.7) — 실행 중인 서버에 요청을 보내고 결과 · 실행 로그 요약을 문서로 남긴다.

    ./venv/Scripts/python -m uvicorn app.main:app --port 8000      (다른 터미널)
    ./venv/Scripts/python scripts/run_scenarios.py                  → docs/verification/scenarios.md
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("PLANNER_URL", "http://localhost:8000")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# (번호, 경우, [요청들 — 같은 세션에서 차례로], 기대 동작, 확인 함수)
# 요청은 글 또는 (요약 글, 패널 선택 {"held", "include"}). 보유 자격 패널이 뜨면 다음 요청이 선택이 아닐 때
# '보유 자격 없음' 으로 자동 응답한다 (기존 시나리오는 가진 자격이 없는 사용자)
SCENARIOS = [
    ("S1", "한 번에 충족 — 분야만 말함", ["전기 쪽으로 취업하고 싶어. 자격증 계획 짜줘"],
     "많이 따는 루트 → 같은 계열은 상위(전기기사)만 남기고 기능사 · 산업기사는 '상위에 포함', 다른 종목(전기공사기사)은 보완으로 유지",
     lambda rs: rs[-1]["draft_plan"][0]["name"] == "전기기사"
     and {"전기기능사", "전기산업기사"} <= {e["name"] for e in rs[-1]["excluded"] if e["reason_code"] == "SUPERSEDED"}),
    ("S2", "재계획 — 기한 안에 불가", ["전기기사 3월까지 따고 싶어"],
     "기한(3월) 안에 준비 기간을 채울 회차가 없어 재계획 1회 → 기한을 넘기는 가장 빠른 대안 제시",
     lambda rs: rs[-1]["replans"] and rs[-1]["draft_plan"]),
    ("S3", "재계획 상한 도달", ["전기 쪽 자격증 내년 2월까지, 자격마다 150주씩 공부할래"],
     "기한 안 불가 → 기한 완화(1회) → 그래도 150주를 채울 회차 없음 → 다음 후보(2회, 상한) → 멈추고 조건 조정을 되묻는다",
     lambda rs: rs[-1]["needs_replan"] == "LIMIT_REACHED" and len(rs[-1]["replans"]) == 2 and "재계획 상한" in rs[-1]["answer"]),
    ("S3b", "재계획으로 대안 제시 — 기한 완화", ["다음 달 안에 전기 쪽 자격증 하나 따고 싶어", "기한 없이 다시 짜줘"],
     "한 달 안에는 불가 → 기한을 넘기는 가장 빠른 대안. 후속 '기한 없이' 는 기한만 지운다",  # rs[0] = 보유 자격 패널, rs[1] = 자동 응답 후 계획
     lambda rs: rs[1]["replans"] and rs[1]["draft_plan"] and not rs[-1]["conditions"].get("deadline") and rs[-1]["draft_plan"]),
    ("S4", "Tool 일부 실패 · 출처 없음", ["금융권 가려고 하는데 투자자산운용사랑 사회복지사 1급 일정 알려줘"],
     "투자자산운용사는 출처 없음, 사회복지사 1급은 NO_EXAM_DATE — 날짜를 지어내지 않고 사유 표시",
     lambda rs: "투자자산운용사: 등록된 출처" in rs[-1]["answer"] and "NO_EXAM_DATE" in str(rs[-1]["failures"])),
    ("S5", "Tool 불필요", ["안녕, 이거 어떻게 써?"],
     "Tool 호출 없이 사용법 안내",
     lambda rs: not any(e["type"] == "tool_call" for e in rs[-1]["events"])),
    ("S6", "조건 부족 — 되묻기", ["자격증 따고 싶어"],
     "Tool 을 부르기 전에 분야 · 자격을 되묻는다",
     lambda rs: not any(e["type"] == "tool_call" for e in rs[-1]["events"]) and "알려 주세요" in rs[-1]["answer"]),
    ("S7", "후속 요청 — 바뀐 조건만 갱신", ["조리사로 일하고 싶어", "양식은 빼고 다시"],
     "분야(조리)는 유지하고 '양식' 이 들어간 자격만 빠진다",
     lambda rs: rs[-1]["conditions"].get("field") == "조리" and not any("양식" in p["name"] for p in rs[-1]["draft_plan"])),
    ("S8", "여러 분야 섞기 — 공무원 + 한국사", ["9급 공무원이랑 한국사 같이 준비할래"],
     "인사혁신처 공무원 일정과 국사편찬위원회 한국사 일정을 함께 배치",
     lambda rs: len(rs[-1]["draft_plan"]) >= 2),
    ("S9", "사실 조회", ["간호사 국가시험 언제야?"],
     "국시원 데이터로 회차 · 접수 · 시험일, 다음 해는 추정 표시",
     lambda rs: rs[-1]["intent"] == "fact_lookup" and "간호사" in rs[-1]["answer"]),
    ("S10", "RAG — 외부 API 로 확인할 수 없는 자격 정보", ["전기기사 시험과목이랑 합격기준 알려줘"],
     "자격 정보 문서 검색 Tool 을 골라 원문 조각과 출처를 그대로 제시",
     lambda rs: rs[-1]["intent"] == "qual_info" and rs[-1]["documents"] and "전기자기학" in rs[-1]["answer"] and "출처" in rs[-1]["answer"]),
    ("S11", "RAG — 큐넷 밖 자격의 시행기관", ["공인회계사 시험은 어디서 시행해?"],
     "일정 데이터는 없어도 국가전문자격정보 문서로 시행기관 · 홈페이지를 근거와 함께 안내",
     lambda rs: "금융감독원" in rs[-1]["answer"]),
    ("S12", "루트 전체 + 관계 분석 — 기간 없음", ["IT쪽 취업 하고싶어 뭘따는게 좋을까"],
     "기간이 없으면 루트 전체: 정보처리기사(인기 1위) + 같은 분야 보완 + 가까운 분야(데이터) 보완, 정보처리산업기사는 상위에 포함",
     lambda rs: rs[-1]["draft_plan"][0]["name"] == "정보처리기사" and len(rs[-1]["draft_plan"]) >= 5
     and any("SQL" in p["name"] for p in rs[-1]["draft_plan"])
     and "정보처리산업기사" not in [p["name"] for p in rs[-1]["draft_plan"]]),
    ("S13", "말한 분야 우선 — 데이터", ["데이터쪽으로 취업하고싶어 내년말까지"],
     "데이터 자격(SQLD · ADsP · 빅분기 …)이 가까운 분야(정보처리기사)보다 먼저",
     lambda rs: rs[-1]["draft_plan"] and rs[-1]["draft_plan"][0]["name"] in
     {"SQL 개발자(SQLD)", "데이터분석 준전문가(ADsP)", "빅데이터분석기사", "데이터아키텍처 준전문가(DAsP)"}),
    ("S14", "보유 자격 패널 — 고른 자격 반영", ["IT쪽 취업 하고싶어",
                                       ("보유: SQL 개발자(SQLD) · 같이 준비: 한국사능력검정시험",
                                        {"held": ["SQL 개발자(SQLD)"], "include": ["한국사능력검정시험"]})],
     "계획 전에 분야 자격 · 기본 자격 선택지를 먼저 보여 주고(일정 조회 없음), 고르면 SQLD 는 빼고 다음 단계 SQLP 를 루트에, 한국사는 루트 뒤에",
     lambda rs: rs[0]["view"].get("held_panel") and not rs[0]["draft_plan"]
     and "SQL 개발자(SQLD)" not in [p["name"] for p in rs[-1]["draft_plan"]]
     and "SQL 전문가(SQLP)" in [p["name"] for p in rs[-1]["draft_plan"]]
     and "한국사능력검정시험" in [p["name"] for p in rs[-1]["draft_plan"]]),
]


def summarize(r: dict) -> list[str]:
    ev = r["events"]
    steps = [e["node"] for e in ev if e["type"] == "node_enter"]
    tools = [(e["tool"], "성공" if e["ok"] else e["code"], e["duration_ms"]) for e in ev if e["type"] == "tool_result"]
    lines = [f"- 실행 단계: {' → '.join(steps)}",
             f"- Tool 호출 {len(tools)}회: " + ", ".join(f"{t}({o}, {ms}ms)" for t, o, ms in tools[:10])
             + (" …" if len(tools) > 10 else "")]
    for e in ev:
        if e["type"] == "llm_decision":
            lines.append(f"- LLM 판단({e['kind']}): {e['decision']} — {e.get('reason') or ''}")
        if e["type"] == "replan":
            lines.append(f"- 🔁 재계획 {e['count']}회차: {e['change']}")
    lines.append(f"- 추출 조건: { {k: v for k, v in (r.get('conditions') or {}).items() if v} }")
    return lines


def main() -> int:
    try:
        requests.get(BASE + "/api/health", timeout=5).raise_for_status()
    except requests.RequestException:
        print("서버가 실행 중이 아닙니다: ./venv/Scripts/python -m uvicorn app.main:app --port 8000")
        return 1
    out = [f"# 대표 시나리오 검증 ({datetime.now():%Y-%m-%d %H:%M})", "",
           "실행 중인 서버(`/api/chat`)에 실제로 요청해 얻은 결과다. 실행 로그 전체는 화면의 [더보기 › 신뢰성 정보] 또는 `GET /api/logs/{session_id}`.", "",
           "| # | 경우 | 기대 동작 | 결과 | 소요 |", "|---|---|---|---|---|"]
    details = []
    passed = 0
    for sid, case, messages, expect, check in SCENARIOS:
        session, results, took, sent = None, [], 0.0, []

        def post(text, selection=None):
            nonlocal session, took
            t0 = time.time()
            body = {"session_id": session, "message": text, **({"selection": selection} if selection else {})}
            r = requests.post(BASE + "/api/chat", json=body, timeout=300).json()
            took += time.time() - t0
            session = r["session_id"]
            results.append(r)
            sent.append(text)
            return r

        for i, m in enumerate(messages):
            r = post(*m) if isinstance(m, tuple) else post(m)
            nxt = messages[i + 1] if i + 1 < len(messages) else None
            if (r.get("view") or {}).get("held_panel") and not isinstance(nxt, tuple):
                post("보유 자격 없음 (자동 응답)", {"held": [], "include": []})
        ok = bool(check(results))
        passed += ok
        print(f"{'✅' if ok else '❌'} {sid} {case} ({took:.1f}s)")
        out.append(f"| {sid} | {case} | {expect} | {'✅ 기대와 같음' if ok else '❌ 차이 있음'} | {took:.1f}s |")
        details += [f"## {sid}. {case}", "", f"- 세션: `{session}`"]
        for m, r in zip(sent, results):
            details += ["", f"**요청**: {m}", "", *summarize(r), "", "<details><summary>최종 응답</summary>", "",
                        r["answer"], "", "</details>"]
        details.append("")
    out += ["", f"결과: {passed}/{len(SCENARIOS)} 기대와 같음", "", *details]
    path = ROOT / "docs" / "verification" / "scenarios.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"\n{passed}/{len(SCENARIOS)} — 저장: {path.relative_to(ROOT).as_posix()}")
    return 0 if passed == len(SCENARIOS) else 1


if __name__ == "__main__":
    sys.exit(main())
