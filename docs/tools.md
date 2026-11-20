# Tool 정의서

> `scripts/export_docs.py` 가 `app/tools/__init__.py` 의 레지스트리에서 뽑은 문서다. 손으로 고치지 않는다.

## 공통 약속 (F3001)

- 모든 Tool 은 `{"ok": true, "data": ...}` 또는 `{"ok": false, "error": {"code", "message"}}` 로 답한다. 예외를 밖으로 던지지 않는다.
- 응답 원본을 넘기지 않고 판단에 쓸 값만 뽑는다. 비어 있는 값은 `null` 로 둔다 (`""` · `0` 으로 채우지 않는다).
- Agent 에는 이름 · 설명 · 입력 규격만 넘긴다 (`catalog()`). 설명에는 기능이 아니라 '언제 부르는지' 를 적는다.
- 같은 인자의 호출 결과는 요청 안에서 재사용하고(재계획 포함), 큐넷 응답은 1시간 캐시한다.

## 실패 코드

| 코드 | 구분 | 뜻 | Agent 처리 |
|---|---|---|---|
| `BAD_ARGUMENT` | 공통 | 입력이 규격과 다르다 (빈 값 · 형식 틀림 · 모르는 인자) | LLM 이 인자를 고쳐 다시 부를 수 있음 |
| `INVALID_KEY` | 공통 | 키가 없거나 틀렸다 | 치명적 — 재계획하지 않고 설정 안내 |
| `NOT_FOUND` | 공통 | 없는 식별자 | 후보에서 제외, 사유 표시 |
| `NO_DATA` | 공통 | 조회는 됐지만 결과가 비었다 | 후보에서 제외 · '출처에 없음' 안내 |
| `UPSTREAM_ERROR` | 공통 | 외부 API 가 응답하지 않음 (시간 초과 · 서버 오류) | 치명적 — 잠시 후 다시 시도 안내 |
| `NO_EXAM_DATE` | 도메인 | 일정은 있지만 모든 회차에서 접수 마감 · 시험일이 비어 있다 | 채우지 않고 '판단하지 않음' 으로 제외 |
| `QUOTA_EXCEEDED` | 도메인 | 외부 API 호출 한도 초과 | 치명적 — 잠시 후 다시 시도 안내 |

치명적 실패(`INVALID_KEY, QUOTA_EXCEEDED, UPSTREAM_ERROR`)는 다시 불러도 결과가 같으므로 재계획하지 않는다.

## 1. `search_qualifications` (외부 API 툴)

**언제 부르나**: 사용자가 분야(예: 정보통신, 전기, 경영)나 자격명 일부를 말했는데 어떤 자격증을 따야 할지 후보 목록이 필요할 때 부른다. 결과의 qual_id 를 get_exam_schedule 에 넘긴다. 등록된 출처(큐넷 국가자격 · 공공데이터 · 공고문 보충)에 있는 자격만 다룬다.

**입력**

| 인자 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `field` | string |  | 직무분야 또는 중직무분야 이름 일부 (예: 정보통신, 정보기술, 전기) |
| `keyword` | string |  | 자격명 일부 (예: 정보처리, 전기) |
| `grade` | string (기능사 · 산업기사 · 기사 · 기능장 · 기술사 · 전문자격) |  |  |
| `base_date` | string |  | 조회 기준 날짜 YYYY-MM-DD. 없으면 오늘 |
| `limit` | integer |  |  |

**출력 `data`**

```json
{
  "base_date": "str",
  "base_date_defaulted": "bool",
  "estimated": "bool",
  "basis": "str",
  "total": "int",
  "truncated": "bool",
  "items": [
    {
      "qual_id": "str",
      "name": "str",
      "grade": "str",
      "qual_type": "str|null",
      "field": "str|null",
      "sub_field": "str|null",
      "organization": "str|null",
      "source": "str",
      "popularity": {
        "year": "int",
        "acquired": "int",
        "basis": "str"
      }
    }
  ],
  "source_errors": [
    {
      "source": "str",
      "code": "str",
      "message": "str"
    }
  ]
}
```

## 2. `get_exam_schedule` (외부 API 툴)

**언제 부르나**: 후보 자격증의 접수 기간 · 필기/실기 시험일 · 합격 발표일 · 응시료 · 시험과목 · 최근 합격률을 확인해야 할 때 부른다. 날짜를 모르는 상태로 계획을 말하지 말고 반드시 이 Tool 로 확인한다. 다음 해 일정이 미공고면 estimated=true 와 근거(basis)가 붙는다.

**입력**

| 인자 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `qual_id` | string | ✅ | search_qualifications 결과의 qual_id |
| `from_date` | string |  | 이 날짜 이후 접수 가능한 회차만. 없으면 오늘 |

**출력 `data`**

```json
{
  "qual_id": "str",
  "name": "str",
  "grade": "str|null",
  "from_date": "str",
  "estimated": "bool (다음 시험이 추정인가)",
  "rounds": [
    {
      "name": "str",
      "stage": "필기|실기|필기+실기|null",
      "exam_time": "HH:MM|null",
      "estimated": "bool",
      "basis": "str|null",
      "written_reg_start": "date|null",
      "written_reg_end": "date",
      "written_exam_start": "date",
      "written_exam_end": "date|null",
      "written_pass": "date|null",
      "practical_reg_start": "date|null",
      "practical_reg_end": "date|null",
      "practical_exam_start": "date|null",
      "practical_exam_end": "date|null",
      "practical_pass": "date|null"
    }
  ],
  "more_rounds": "int",
  "unjudged": [
    {
      "name": "str",
      "missing": [
        "str"
      ]
    }
  ],
  "fee": "{label: int}|null",
  "fee_text": "str|null",
  "exam_info": {
    "subjects": "{단계: [과목]}|null",
    "exam_method": "{단계: str}|null",
    "pass_criteria": "{단계: str}|null",
    "source": "str"
  },
  "pass_rate": {
    "year": "int",
    "by_stage": "{단계: {rate, takers, passed, rounds}}",
    "basis": "str"
  },
  "source": "str"
}
```

## 3. `search_books` (외부 API 툴)

**언제 부르나**: 계획에 넣은 자격증의 교재를 함께 보여 줄 때 부른다. 제목에 자격명이 들어간 실제 책만 돌려주며 판매 순위가 아니다. 책을 직접 지어내지 말고 이 Tool 결과만 쓴다.

**입력**

| 인자 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `qualification_name` | string | ✅ | 자격명 (예: 정보처리기사) |
| `exam_type` | string (필기 · 실기) |  |  |
| `limit` | integer |  |  |

**출력 `data`**

```json
{
  "query": "str",
  "provider": "kakao",
  "basis": "str",
  "excluded_unmatched": "int",
  "items": [
    {
      "title": "str",
      "authors": "str|null",
      "publisher": "str|null",
      "pub_date": "str|null",
      "price": "int|null",
      "isbn": "str|null",
      "link": "str|null"
    }
  ]
}
```

## 4. `search_documents` (로컬 서버 API 툴)

**언제 부르나**: 시험 날짜가 아니라 시험과목 · 검정방법 · 합격기준 · 응시자격 안내 · 출제경향 · 시행기관 · 소관부처처럼 문서로만 있는 자격 정보를 물을 때 부른다. 원문 조각과 출처를 돌려준다. 내용을 지어내지 말고 이 결과만 근거로 쓴다.

**입력**

| 인자 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `query` | string | ✅ | 사용자 질문 |
| `qualification_name` | string |  | 자격명을 정확히 알면 (예: 정보처리기사) |
| `limit` | integer |  |  |

**출력 `data`**

```json
{
  "query": "str",
  "qualification_name": "str|null",
  "scoped_to_qualification": "bool",
  "basis": "str",
  "items": [
    {
      "text": "str",
      "qual_name": "str|null",
      "kind": "취득방법|출제경향|시행기관",
      "source": "str",
      "url": "str|null",
      "distance": "float"
    }
  ]
}
```

## 5. `list_schedule` (로컬 서버 API 툴)

**언제 부르나**: 계획을 짤 때 사용자 캘린더에 이미 잡힌 일정을 확인해야 할 때 부른다. 일정이 있는 날은 시험일로 잡지 않는다.

**입력**

| 인자 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `date_from` | string |  | YYYY-MM-DD. 없으면 오늘 |
| `date_to` | string |  | YYYY-MM-DD. 없으면 1년 뒤 |

**출력 `data`**

```json
{
  "backend": "local|google",
  "date_from": "str",
  "date_to": "str",
  "busy_dates": [
    "str"
  ],
  "events": [
    {
      "event_id": "str",
      "title": "str",
      "date": "str",
      "start_time": "HH:MM|null",
      "end_time": "HH:MM|null",
      "all_day": "bool",
      "link": "str|null"
    }
  ]
}
```

## 6. `register_plan` (로컬 서버 API 툴)

**언제 부르나**: 사용자가 저장한 계획을 캘린더에 등록해 달라고 할 때 부른다. 계획 번호만 넘긴다 — 제목 · 날짜 · 시각은 서버가 저장소에서 읽는다.

**입력**

| 인자 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `plan_id` | integer | ✅ |  |

**출력 `data`**

```json
{
  "backend": "local|google",
  "plan_id": "int",
  "title": "str",
  "date": "str",
  "start_time": "HH:MM|null",
  "event_id": "str",
  "link": "str|null"
}
```

## 출처와 이용 조건 (NF3007)

| Tool | 출처 | 이용 조건 · 한도 |
|---|---|---|
| search_qualifications · get_exam_schedule | 한국산업인력공단 큐넷 오픈 API (종목 목록 · 시험일정 · 응시료 · 취득방법 · 합격률) | 공공데이터포털 이용허락범위 제한 없음. 개발계정 일 10,000건 (일부 1,000건) |
| 〃 (보충 출처) | 공공데이터포털 자동변환 API — 데이터산업진흥원 · 국사편찬위원회 · 국시원 · 한국콘텐츠진흥원 · 한국해양수산연수원 · 한국산림복지진흥원 · 인사혁신처 · 국립축산과학원 | 각 데이터 상세 페이지의 이용허락범위. 개발계정 일 10,000건. `data/sources.json` 에 출처 URL 기록 |
| search_books | 카카오 책 검색 API | Kakao Developers 약관. 결과에 원문 링크를 표시, 책 정보는 저장하지 않음 |

## Tool 추가 · 확장

- 새 Tool: 함수를 만들고 `app/tools/__init__.py` 의 `TOOLS` 에 `Tool(name, description, parameters, func, returns)` 를 더한다.
- 새 시험일정 출처: 공공데이터포털 CSV · 자동변환 API 는 `data/sources.json` 에 설정 한 줄 (코드 수정 없음, 형식은 `app/tools/sources/table.py` 맨 위).
  모양이 다른 API 는 `app/tools/sources/` 에 어댑터(`owns` · `list_quals` · `get_schedule`)를 추가한다.
- API 가 없는 기관: `data/manual_schedules.json` 에 공고문을 옮겨 적는다 (출처 URL · 확인일 필수).
