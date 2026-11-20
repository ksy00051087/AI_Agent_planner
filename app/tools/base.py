"""Tool 공통 약속 (F3001) — tools_start.py 의 ①② 를 그대로 옮겼다.

    · 성공도 실패도 ok() · fail() 로 돌려준다. 예외를 밖으로 던지지 않는다
    · 응답 원본을 통째로 넘기지 않는다. 판단에 쓸 값만 뽑는다
    · 비어 있는 값은 "" 나 0 으로 채우지 않는다
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


def ok(data):
    return {"ok": True, "data": data}


def fail(code, message):
    return {"ok": False, "error": {"code": code, "message": message}}


# 공통 실패 코드
BAD_ARGUMENT = "BAD_ARGUMENT"      # 입력이 규격과 다르다 (빈 값 · 형식 틀림 · 모르는 인자)
INVALID_KEY = "INVALID_KEY"        # 키가 없거나 틀렸다
NOT_FOUND = "NOT_FOUND"            # 찾는 대상이 없다 (없는 식별자)
NO_DATA = "NO_DATA"                # 조회는 됐지만 결과가 비었다
UPSTREAM_ERROR = "UPSTREAM_ERROR"  # 외부 API 가 응답하지 않았다 (시간 초과 · 서버 오류)
# 도메인 전용 실패 코드
NO_EXAM_DATE = "NO_EXAM_DATE"      # 일정은 있지만 판단에 필요한 날짜(접수 마감 · 시험일)가 모든 회차에서 비어 있다
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"  # 외부 API 호출 한도를 넘었다

# 다시 불러도 결과가 같은 실패 — Agent 는 재시도 · 재계획하지 않고 바로 안내한다 (명세 2.4)
FATAL_CODES = {INVALID_KEY, QUOTA_EXCEEDED, UPSTREAM_ERROR}


@dataclass
class Tool:
    name: str            # 이름표
    description: str     # 언제 쓰는지 (모델이 읽는다)
    parameters: dict     # 입력 규격 (JSON Schema)
    func: Callable       # 실제로 일하는 함수
    kind: str = "external"   # external: 외부 API 툴 / local: 로컬 서버 API 툴 (F3001 구분)
    returns: dict = field(default_factory=dict)  # 출력 구조 (Tool 정의서용, Agent 에는 넘기지 않는다)

    def run(self, **kwargs):
        allowed = set(self.parameters.get("properties", {}))
        unknown = set(kwargs) - allowed
        if unknown:
            return fail(BAD_ARGUMENT, f"모르는 인자입니다: {', '.join(sorted(unknown))}")
        try:
            return self.func(**kwargs)
        except TypeError:
            return fail(BAD_ARGUMENT, "입력값이 규약과 다릅니다.")
        except Exception:
            return fail(UPSTREAM_ERROR, "Tool 실행 중 오류입니다.")
