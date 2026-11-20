"""Tool 레지스트리 (F3001). Agent 에는 catalog() — 이름 · 설명 · 입력 규격만 넘긴다.

새 Tool 추가: 함수를 만들고 아래 TOOLS 목록에 Tool(...) 하나를 더한다.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")  # 키는 환경변수로만 (NF3001)

from .base import FATAL_CODES, Tool, fail, ok  # noqa: E402
from .books import search_books  # noqa: E402
from .qualifications import get_exam_schedule, search_qualifications  # noqa: E402
from .rag import search_documents  # noqa: E402
from .calendar import list_schedule, register_plan  # noqa: E402

_DATE = {"type": "string", "description": "YYYY-MM-DD"}

TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool(
        name="search_qualifications",
        description=(
            "사용자가 분야(예: 정보통신, 전기, 경영)나 자격명 일부를 말했는데 어떤 자격증을 따야 할지 "
            "후보 목록이 필요할 때 부른다. 결과의 qual_id 를 get_exam_schedule 에 넘긴다. "
            "등록된 출처(큐넷 국가자격 · 공공데이터 · 공고문 보충)에 있는 자격만 다룬다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "field": {"type": "string", "description": "직무분야 또는 중직무분야 이름 일부 (예: 정보통신, 정보기술, 전기)"},
                "keyword": {"type": "string", "description": "자격명 일부 (예: 정보처리, 전기)"},
                "grade": {"type": "string", "enum": ["기능사", "산업기사", "기사", "기능장", "기술사", "전문자격"]},
                "base_date": {**_DATE, "description": "조회 기준 날짜 YYYY-MM-DD. 없으면 오늘"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
        func=search_qualifications,
        returns={"base_date": "str", "base_date_defaulted": "bool", "estimated": "bool", "basis": "str",
                 "total": "int", "truncated": "bool",
                 "items": [{"qual_id": "str", "name": "str", "grade": "str", "qual_type": "str|null",
                            "field": "str|null", "sub_field": "str|null", "organization": "str|null", "source": "str",
                            "popularity": {"year": "int", "acquired": "int", "basis": "str"}}],
                 "source_errors": [{"source": "str", "code": "str", "message": "str"}]},
    ),
    Tool(
        name="get_exam_schedule",
        description=(
            "후보 자격증의 접수 기간 · 필기/실기 시험일 · 합격 발표일 · 응시료 · 시험과목 · 최근 합격률을 확인해야 할 때 부른다. "
            "날짜를 모르는 상태로 계획을 말하지 말고 반드시 이 Tool 로 확인한다. "
            "다음 해 일정이 미공고면 estimated=true 와 근거(basis)가 붙는다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "qual_id": {"type": "string", "description": "search_qualifications 결과의 qual_id"},
                "from_date": {**_DATE, "description": "이 날짜 이후 접수 가능한 회차만. 없으면 오늘"},
            },
            "required": ["qual_id"],
        },
        func=get_exam_schedule,
        returns={"qual_id": "str", "name": "str", "grade": "str|null", "from_date": "str", "estimated": "bool (다음 시험이 추정인가)",
                 "rounds": [{"name": "str", "stage": "필기|실기|필기+실기|null", "exam_time": "HH:MM|null",
                             "estimated": "bool", "basis": "str|null",
                             "written_reg_start": "date|null", "written_reg_end": "date",
                             "written_exam_start": "date", "written_exam_end": "date|null",
                             "written_pass": "date|null", "practical_reg_start": "date|null",
                             "practical_reg_end": "date|null", "practical_exam_start": "date|null",
                             "practical_exam_end": "date|null", "practical_pass": "date|null"}],
                 "more_rounds": "int", "unjudged": [{"name": "str", "missing": ["str"]}],
                 "fee": "{label: int}|null", "fee_text": "str|null",
                 "exam_info": {"subjects": "{단계: [과목]}|null", "exam_method": "{단계: str}|null",
                               "pass_criteria": "{단계: str}|null", "source": "str"},
                 "pass_rate": {"year": "int", "by_stage": "{단계: {rate, takers, passed, rounds}}", "basis": "str"},
                 "source": "str"},
    ),
    Tool(
        name="search_books",
        description=(
            "계획에 넣은 자격증의 교재를 함께 보여 줄 때 부른다. 제목에 자격명이 들어간 실제 책만 돌려주며 "
            "판매 순위가 아니다. 책을 직접 지어내지 말고 이 Tool 결과만 쓴다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "qualification_name": {"type": "string", "description": "자격명 (예: 정보처리기사)"},
                "exam_type": {"type": "string", "enum": ["필기", "실기"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["qualification_name"],
        },
        func=search_books,
        returns={"query": "str", "provider": "naver|kakao", "basis": "str", "excluded_unmatched": "int",
                 "items": [{"title": "str", "authors": "str|null", "publisher": "str|null",
                            "pub_date": "str|null", "price": "int|null", "isbn": "str|null", "link": "str|null"}]},
    ),
    Tool(
        name="search_documents",
        kind="local",
        description=(
            "시험 날짜가 아니라 시험과목 · 검정방법 · 합격기준 · 응시자격 안내 · 출제경향 · 시행기관 · 소관부처처럼 "
            "문서로만 있는 자격 정보를 물을 때 부른다. 원문 조각과 출처를 돌려준다. 내용을 지어내지 말고 이 결과만 근거로 쓴다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "사용자 질문"},
                "qualification_name": {"type": "string", "description": "자격명을 정확히 알면 (예: 정보처리기사)"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
        func=search_documents,
        returns={"query": "str", "qualification_name": "str|null", "scoped_to_qualification": "bool", "basis": "str",
                 "items": [{"text": "str", "qual_name": "str|null", "kind": "취득방법|출제경향|시행기관",
                            "source": "str", "url": "str|null", "distance": "float"}]},
    ),
    Tool(
        name="list_schedule",
        kind="local",
        description="계획을 짤 때 사용자 캘린더에 이미 잡힌 일정을 확인해야 할 때 부른다. 일정이 있는 날은 시험일로 잡지 않는다.",
        parameters={"type": "object", "properties": {
            "date_from": {"type": "string", "description": "YYYY-MM-DD. 없으면 오늘"},
            "date_to": {"type": "string", "description": "YYYY-MM-DD. 없으면 1년 뒤"}}},
        func=list_schedule,
        returns={"backend": "local|google", "date_from": "str", "date_to": "str", "busy_dates": ["str"],
                 "events": [{"event_id": "str", "title": "str", "date": "str", "start_time": "HH:MM|null",
                             "end_time": "HH:MM|null", "all_day": "bool", "link": "str|null"}]},
    ),
    Tool(
        name="register_plan",
        kind="local",
        description="사용자가 저장한 계획을 캘린더에 등록해 달라고 할 때 부른다. 계획 번호만 넘긴다 — 제목 · 날짜 · 시각은 서버가 저장소에서 읽는다.",
        parameters={"type": "object", "properties": {"plan_id": {"type": "integer", "minimum": 1}}, "required": ["plan_id"]},
        func=register_plan,
        returns={"backend": "local|google", "plan_id": "int", "title": "str", "date": "str", "start_time": "HH:MM|null",
                 "event_id": "str", "link": "str|null"},
    ),
]}


def catalog() -> list[dict]:
    """Agent 에게 넘기는 것은 이름 · 설명 · 입력 규격뿐"""
    return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in TOOLS.values()]


def run_tool(name: str, **kwargs) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        return fail("BAD_ARGUMENT", f"등록되지 않은 Tool 입니다: {name}")
    return tool.run(**kwargs)


__all__ = ["TOOLS", "FATAL_CODES", "Tool", "catalog", "run_tool", "ok", "fail"]
