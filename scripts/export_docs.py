"""Tool 정의서 · API 명세서를 코드에서 뽑아 문서로 만든다 — 코드와 문서가 어긋나지 않게.

    ./venv/Scripts/python scripts/export_docs.py   → docs/tools.md · docs/api.md
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PLANNER_NO_AUTOAPP", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.tools import TOOLS  # noqa: E402
from app.tools.base import FATAL_CODES  # noqa: E402

FAIL_CODES = [
    ("BAD_ARGUMENT", "공통", "입력이 규격과 다르다 (빈 값 · 형식 틀림 · 모르는 인자)", "LLM 이 인자를 고쳐 다시 부를 수 있음"),
    ("INVALID_KEY", "공통", "키가 없거나 틀렸다", "치명적 — 재계획하지 않고 설정 안내"),
    ("NOT_FOUND", "공통", "없는 식별자", "후보에서 제외, 사유 표시"),
    ("NO_DATA", "공통", "조회는 됐지만 결과가 비었다", "후보에서 제외 · '출처에 없음' 안내"),
    ("UPSTREAM_ERROR", "공통", "외부 API 가 응답하지 않음 (시간 초과 · 서버 오류)", "치명적 — 잠시 후 다시 시도 안내"),
    ("NO_EXAM_DATE", "도메인", "일정은 있지만 모든 회차에서 접수 마감 · 시험일이 비어 있다", "채우지 않고 '판단하지 않음' 으로 제외"),
    ("QUOTA_EXCEEDED", "도메인", "외부 API 호출 한도 초과", "치명적 — 잠시 후 다시 시도 안내"),
]


def tools_md() -> str:
    out = ["# Tool 정의서", "",
           "> `scripts/export_docs.py` 가 `app/tools/__init__.py` 의 레지스트리에서 뽑은 문서다. 손으로 고치지 않는다.", "",
           "## 공통 약속 (F3001)", "",
           "- 모든 Tool 은 `{\"ok\": true, \"data\": ...}` 또는 `{\"ok\": false, \"error\": {\"code\", \"message\"}}` 로 답한다. 예외를 밖으로 던지지 않는다.",
           "- 응답 원본을 넘기지 않고 판단에 쓸 값만 뽑는다. 비어 있는 값은 `null` 로 둔다 (`\"\"` · `0` 으로 채우지 않는다).",
           "- Agent 에는 이름 · 설명 · 입력 규격만 넘긴다 (`catalog()`). 설명에는 기능이 아니라 '언제 부르는지' 를 적는다.",
           "- 같은 인자의 호출 결과는 요청 안에서 재사용하고(재계획 포함), 큐넷 응답은 1시간 캐시한다.", "",
           "## 실패 코드", "", "| 코드 | 구분 | 뜻 | Agent 처리 |", "|---|---|---|---|"]
    out += [f"| `{c}` | {k} | {d} | {h} |" for c, k, d, h in FAIL_CODES]
    out += ["", f"치명적 실패(`{', '.join(sorted(FATAL_CODES))}`)는 다시 불러도 결과가 같으므로 재계획하지 않는다.", ""]
    for i, t in enumerate(TOOLS.values(), 1):
        req = set(t.parameters.get("required", []))
        out += [f"## {i}. `{t.name}` ({'외부 API 툴' if t.kind == 'external' else '로컬 서버 API 툴'})", "",
                f"**언제 부르나**: {t.description}", "", "**입력**", "", "| 인자 | 형식 | 필수 | 설명 |", "|---|---|---|---|"]
        for name, spec in t.parameters["properties"].items():
            typ = spec.get("type", "")
            if spec.get("enum"):
                typ += " (" + " · ".join(spec["enum"]) + ")"
            out.append(f"| `{name}` | {typ} | {'✅' if name in req else ''} | {spec.get('description', '')} |")
        out += ["", "**출력 `data`**", "", "```json", json.dumps(t.returns, ensure_ascii=False, indent=2), "```", ""]
    out += ["## 출처와 이용 조건 (NF3007)", "",
            "| Tool | 출처 | 이용 조건 · 한도 |", "|---|---|---|",
            "| search_qualifications · get_exam_schedule | 한국산업인력공단 큐넷 오픈 API (종목 목록 · 시험일정 · 응시료 · 취득방법 · 합격률) | 공공데이터포털 이용허락범위 제한 없음. 개발계정 일 10,000건 (일부 1,000건) |",
            "| 〃 (보충 출처) | 공공데이터포털 자동변환 API — 데이터산업진흥원 · 국사편찬위원회 · 국시원 · 한국콘텐츠진흥원 · 한국해양수산연수원 · 한국산림복지진흥원 · 인사혁신처 · 국립축산과학원 | 각 데이터 상세 페이지의 이용허락범위. 개발계정 일 10,000건. `data/sources.json` 에 출처 URL 기록 |",
            "| search_books | 카카오 책 검색 API (네이버 책 검색도 지원) | Kakao Developers 약관. 결과에 원문 링크를 표시, 책 정보는 저장하지 않음 |",
            "", "## Tool 추가 · 확장", "",
            "- 새 Tool: 함수를 만들고 `app/tools/__init__.py` 의 `TOOLS` 에 `Tool(name, description, parameters, func, returns)` 를 더한다.",
            "- 새 시험일정 출처: 공공데이터포털 CSV · 자동변환 API 는 `data/sources.json` 에 설정 한 줄 (코드 수정 없음, 형식은 `app/tools/sources/table.py` 맨 위).",
            "  모양이 다른 API 는 `app/tools/sources/` 에 어댑터(`owns` · `list_quals` · `get_schedule`)를 추가한다.",
            "- API 가 없는 기관: `data/manual_schedules.json` 에 공고문을 옮겨 적는다 (출처 URL · 확인일 필수)."]
    return "\n".join(out) + "\n"


def api_md() -> str:
    from app.main import create_app

    class _NoAgent:
        def run(self, *a, **k):
            raise RuntimeError

    spec = create_app(db_path=":memory:", agent=_NoAgent()).openapi()
    schemas = spec["components"]["schemas"]

    def ref(s):
        if not s:
            return ""
        if "$ref" in s:
            return s["$ref"].split("/")[-1]
        if s.get("type") == "array":
            return f"{ref(s['items'])}[]"
        if "anyOf" in s:
            return " 또는 ".join(ref(x) for x in s["anyOf"])
        return s.get("type", "")

    out = ["# API 명세서", "", "> `scripts/export_docs.py` 가 FastAPI OpenAPI 스키마에서 뽑은 문서다. 실행 중에는 `/docs` 에서도 볼 수 있다.", "",
           "| 메서드 | 경로 | 설명 | 요청 | 응답 |", "|---|---|---|---|---|"]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            ok = next((v for k, v in op["responses"].items() if k.startswith("2")), {})
            res = ok.get("content", {}).get("application/json", {}).get("schema")
            summary = (op.get("description") or op.get("summary") or "").split("\n")[0]
            out.append(f"| {method.upper()} | `{path}` | {summary} | {ref(body) or '–'} | {ref(res) or ('204 No Content' if '204' in op['responses'] else '–')} |")
    out += ["", "실행 로그에는 수정(PUT · PATCH) 경로가 없다. 오류 응답의 `detail` 에는 내부 오류 원문을 싣지 않는다.", "", "## 스키마", ""]
    for name, s in schemas.items():
        if name.startswith(("HTTPValidationError", "ValidationError")):
            continue
        out += [f"### {name}", "", s.get("description", ""), "", "| 필드 | 형식 | 필수 | 설명 |", "|---|---|---|---|"]
        req = set(s.get("required", []))
        for f, fs in (s.get("properties") or {}).items():
            out.append(f"| `{f}` | {ref(fs) or fs.get('type', '')} | {'✅' if f in req else ''} | {fs.get('description', '')} |")
        out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    (ROOT / "docs" / "tools.md").write_text(tools_md(), encoding="utf-8")
    (ROOT / "docs" / "api.md").write_text(api_md(), encoding="utf-8")
    print("docs/tools.md · docs/api.md 생성")
