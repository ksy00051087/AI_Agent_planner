"""기획 검증 2.7 '도구 연결 확인' — Tool 명세를 넘겼을 때 LLM 이 Tool 호출을 고르는지 본다.

    ./venv/Scripts/python scripts/check_tool_calling.py

요청마다 LLM 이 고른 Tool 과 인자를 출력한다. Tool 은 실행하지 않는다 (선택만 확인).
결과는 docs/verification/tool_calling.md 에 저장한다 (제출물 '기획 검증 결과' 근거).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.tools import catalog  # noqa: E402  (.env 도 여기서 읽힌다)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CASES = [
    ("Tool 필요 — 분야 추천", "비전공자인데 IT 쪽 자격증 따고 싶어. 뭐가 있어?", "search_qualifications"),
    ("Tool 필요 — 일정 확인", "정보처리기사(종목코드 1320) 다음 시험 언제야?", "get_exam_schedule"),
    ("Tool 필요 — 교재", "SQLD 필기 교재 알려줘", "search_books"),
    ("RAG — 문서로만 있는 정보", "전기기사 필기 시험과목이랑 합격기준이 어떻게 돼?", "search_documents"),
    ("RAG — 시행기관", "공인회계사 시험은 어느 기관에서 시행해?", "search_documents"),
    ("Tool 불필요 — 인사", "안녕! 너는 뭐 하는 서비스야?", None),
]
SYSTEM = ("너는 자격증 장기 학습 플래너다. 시험 일정 · 자격 종목 · 교재는 반드시 Tool 로 확인하고 지어내지 않는다. "
          "Tool 이 필요 없는 대화에는 Tool 을 부르지 않는다.")


def main() -> int:
    key = (os.getenv("GMS_API_KEY") or "").strip()
    if not key:
        print("GMS_API_KEY 가 .env 에 없습니다.")
        return 1
    base = (os.getenv("GMS_BASE_URL") or "https://gms.ssafy.io/gmsapi/api.openai.com/v1").rstrip("/")
    model = os.getenv("GMS_MODEL") or "gpt-4.1-mini"
    tools = [{"type": "function", "function": c} for c in catalog()]

    lines = [f"# Tool 호출 선택 확인 ({datetime.now():%Y-%m-%d %H:%M}, 모델 {model})", "",
             "| 경우 | 요청 | 기대 | LLM 선택 | 인자 | 판정 |", "|---|---|---|---|---|---|"]
    passed = 0
    for label, text, expected in CASES:
        try:
            res = requests.post(f"{base}/chat/completions", timeout=60,
                                headers={"Authorization": f"Bearer {key}"},
                                json={"model": model, "tools": tools, "tool_choice": "auto",
                                      "messages": [{"role": "system", "content": SYSTEM},
                                                   {"role": "user", "content": text}]})
        except requests.RequestException as e:
            print(f"[{label}] 호출 실패 ({type(e).__name__})")
            return 1
        if res.status_code != 200:
            print(f"[{label}] HTTP {res.status_code} {res.text[:150]}")
            return 1
        msg = res.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        chosen = calls[0]["function"]["name"] if calls else None
        args = json.loads(calls[0]["function"]["arguments"]) if calls else {}
        ok = chosen == expected
        passed += ok
        mark = "✅" if ok else "❌"
        print(f"{mark} {label}\n   요청: {text}\n   기대: {expected}  →  선택: {chosen}  인자: {args}"
              + ("" if calls else f"\n   답변: {(msg.get('content') or '')[:80]}"))
        lines.append(f"| {label} | {text} | {expected or '(없음)'} | {chosen or '(없음)'} | "
                     f"`{json.dumps(args, ensure_ascii=False)}` | {mark} |")

    lines += ["", f"결과: {passed}/{len(CASES)} 기대와 일치"]
    out = ROOT / "docs" / "verification" / "tool_calling.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(CASES)} 일치 — 저장: {out.relative_to(ROOT).as_posix()}")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
