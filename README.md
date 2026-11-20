# 자격증 장기 플래너 — Agent 기반 도메인 플래너 서비스

> SSAFY AI 코어 프로젝트 3회차 · 개인 프로젝트

**되고 싶은 직업을 말하면, 그 직업에 이어지는 자격을 사람들이 실제로 많이 따는 흐름대로 시험 일정으로 확인해 "무엇을 · 어떤 순서로 · 늦어도 언제부터 공부할지" 준비 계획을 짜 주는 서비스입니다.** 분야 · 자격 이름으로도 요청할 수 있습니다.

```
나: 전기 엔지니어가 되고 싶어. 준비 계획 짜줘

| 순서 | 자격         | 시험일      | 실기       | 늦어도 공부 시작 | 응시료    |
| 1   | 전기기능사    | 2027-01-20 | 2027-03-14 | 2026-12-09 (6주)  | 120,700원 |
| 2   | 전기산업기사  | 2027-08-07 | 2027-10-24 | 2027-05-29 (10주) | 40,200원  |
| 3   | 전기기사      | 2028-01-30 | 2028-04-18 | 2027-11-07 (12주) | 42,000원  |

이 순서인 이유: 2025년 실기 합격자 27,015명 · '전기' 계열 1/3단계 (전기기능사 → 전기산업기사 → 전기기사) …
* 2027년 일정 미공고 — 2026년 같은 회차 날짜에 1년을 더한 추정치
```

가장 중요한 원칙은 **확인하지 않은 값을 지어내지 않는다** 입니다. 날짜 · 응시료 · 합격률 · 교재는 모두 외부 API(Tool) 결과에서 나오고, 순서 · 회차 · 공부 시작일은 코드(`app/domain/`)가 계산합니다. LLM 은 요청 해석(의도 · 조건)에만 씁니다. 확인할 수 없는 값은 "추정" · "확인 불가" 로 밝힙니다.

---

## 1. 실행 방법

```bash
# 1) 가상환경과 라이브러리 (Python 3.11 확인)
python -m venv venv
./venv/Scripts/python -m pip install -r requirements.txt      # Windows (Git Bash)
# source venv/bin/activate && pip install -r requirements.txt  # macOS · Linux

# 2) API 키 설정 — 아래 2장
cp .env.example .env        # .env 에 키를 채운다

# 3) (선택) 공공데이터 파일 예비본 내려받기 — 자동변환 API 가 실패할 때 대신 읽는다
./venv/Scripts/python scripts/download_datasets.py           # 또는 scripts\download_datasets.bat

# 4) (심화 F3022) 자격 정보 문서 색인 — 큐넷 613종목 취득방법 · 출제경향 + 국가전문자격정보, GMS 임베딩
./venv/Scripts/python -m pip install -r requirements-extra.txt
./venv/Scripts/python scripts/build_index.py              # 약 2분. 없으면 RAG 질문에 NO_INDEX 로 답한다

# 5) 서버 실행 → 화면 http://localhost:8000  · API 문서 http://localhost:8000/docs
./venv/Scripts/python scripts/dev_server.py 8000            # 윈도우는 start_app.bat 더블클릭과 같음. app/ 코드가 바뀌면 저절로 다시 켠다
# ./venv/Scripts/python -m uvicorn app.main:app --port 8000  # 자동 재시작 없이 실행
```

확인용 스크립트

| 명령 | 하는 일 |
|---|---|
| `python scripts/check_apis.py` | 외부 API 3종 + LLM 을 한 번씩 실제 호출 (1일차 기획 검증) |
| `python scripts/check_tool_calling.py` | Tool 명세를 줬을 때 LLM 이 Tool 을 고르는지 확인 |
| `python scripts/run_scenarios.py` | 대표 시나리오 15개를 실행 중인 서버에 보내고 결과를 `docs/verification/scenarios.md` 로 |
| `python -m pytest` | 오프라인 테스트 239개 — 외부 API 는 가짜 응답으로 격리, 테스트마다 60초 넘으면 멈춘 위치와 함께 실패 (`pytest-timeout`) |
| `python -m pytest -m live` | **배포 · 제출 전 스모크 점검** 5개 (약 30초) — 큐넷 · GMS LLM · RAG 색인 검색 · Agent 전체 흐름(전기)을 실제로 불러 응답 형식 · 인증 · 지연 변화를 잡는다 (키 필요). 외부 API 전체 점검은 `scripts/check_apis.py` |
| `python scripts/export_docs.py` | 코드에서 Tool 정의서 · API 명세서를 다시 만든다 |

## 2. API 키 발급 · 설정

키는 `.env` 에만 넣습니다 (`.gitignore` 대상, 코드에 적지 않음 — NF3001). `.env.example` 은 키 이름만 있는 안내서입니다.

| 환경변수 | 발급 | 필수 |
|---|---|---|
| `GMS_API_KEY` | SSAFY GMS (https://gms.ssafy.io) | ✅ 요청 해석 · 이상 징후 진단 · 문서 임베딩 |
| `KAKAO_REST_API_KEY` | developers.kakao.com → 내 애플리케이션 → 앱 키 → **REST API 키** | ✅ 교재 검색 |
| `DATA_GO_KR_KEY` | data.go.kr → 마이페이지 → 일반 인증키. 쓰는 데이터마다 **활용신청** 필요 (목록: `docs/research/data_sources.md`) | 보충 출처 (보건의료 · 공무원 · 한국사 등) |
| `CALENDAR_BACKEND` | `local`(기본) 또는 `google`. Google 은 Cloud 콘솔에서 Calendar API 사용 → OAuth 동의 화면(외부 · 테스트, 테스트 사용자에 본인 Gmail) → **데스크톱 앱** OAuth 클라이언트 JSON 을 `data/google/credentials.json` 으로 → `python scripts/google_login.py` 로 첫 로그인 (`data/google/` 은 git 제외, 테스트 모드 토큰은 7일마다 다시 로그인) | 선택 (심화 F3023) |
| `CAREERNET_API_KEY` | career.go.kr → Open API 센터 → 신청 · 승인 후 인증키 | 직업 정보 (하는 일 · 관련 자격 · 학과 · 훈련). 없으면 LLM 풀이 · 네이버 근거(비공식)로만 |
| `NAVER_HUB_CLIENT_ID/SECRET` | console.ncloud.com → NAVER API HUB → 검색(백과사전 · 블로그) | 선택 — RAG 수집 · 직무 근거 |
| `QNET_SERVICE_KEY` | data.go.kr 한국산업인력공단 서비스 활용신청 | 선택 — 큐넷은 키 없이 응답하고, **HTTPS 주소일 때만 보낸다** (아래 보안) |

키가 없으면: 화면 상단에 설정 안내가 뜨고(`/api/health`), 해당 Tool 은 `INVALID_KEY` 로 실패를 알립니다. 서비스는 멈추지 않습니다.

## 3. 기능

### 필수 (F3001 ~ F3019)

| 영역 | 번호 | 구현 | 위치 |
|---|---|---|---|
| Tool | F3001 | 레지스트리(이름 · 설명 · 입력 규격 · 출력 구조), 공통 `ok/fail`, 실패 코드 7종, 예외를 밖으로 던지지 않음 | `app/tools/base.py` · `__init__.py` |
| | F3002 | `search_qualifications` — 큐넷 613종목 + 공공데이터 12개 출처, 분야 · 자격명 · 등급 검색, **최근 합격자 수(인기)순**, 기준 날짜 기본값 = 오늘, 다른 해 기준이면 "추정" | `app/tools/qualifications.py` |
| | F3003 | `get_exam_schedule` — 접수 · 시험 · 발표일, 응시료, 시험과목, 합격률. **다음 해 미공고면 +1년 "추정"**, 날짜가 비면 `NO_EXAM_DATE` (채우지 않음) | 〃, `app/domain/schedule.py` |
| | F3004 | `search_books` — 카카오 책 검색. 제목에 자격명이 있는 책만, 후보와 임의로 짝짓지 않음, 결과 없음 = `NO_DATA` | `app/tools/books.py` |
| Agent | F3005 | 의도 5종 분류 + 조건 추출(LLM 구조화 출력) → 코드 검증: 출처 밖 분야 · 지어낸 등급 · 지난 기한 걸러내기 | `app/agent/analyze.py` |
| | F3006 | 의도 · 조건으로 Tool 순서 구성, 인사 · 되묻기는 Tool 없음 | `app/agent/nodes.py` (plan) |
| | F3007 | Tool 호출 · 결과 통합 · 실패해도 진행, 일정 조회 병렬 | 〃 (execute) |
| | F3008 | **많이 따는 계열 흐름 순서** → 회차 선택 · 공부 시작일 역산 · 기한 · 시험일 충돌 · 예산 · 계획 크기 | `app/domain/arrange.py` |
| | F3009 | 다음 후보 추가 · 기한 완화, 같은 Tool 결과 재사용, 상한 2회(`REPLAN_LIMIT`) | `app/agent/nodes.py` (judge · replan) |
| | F3010 | 세션별 체크포인터, 후속 요청은 바뀐 조건만 갱신 | `app/agent/graph.py`, `analyze.merge_conditions` |
| | F3011 | 계획표 · 순서 근거 · 판단 기준 · 출처 · 추정 표시 · 교재 · 제외 사유 · 재계획 이력 | `app/agent/respond.py` |
| 로깅 | F3012 | 단계 진입 · 종료, Tool 호출 · 결과 · 소요 시간, LLM 판단과 이유, 재계획 이벤트. 발행자는 구독자를 모름 | `app/events/bus.py` |
| | F3013 | 로깅 서브 Agent — 구독 즉시 세션 단위로 SQLite 에 순서대로 저장, LLM 미사용 | `app/logging_agent/` |
| | F3014 | 실행 로그 목록 · 상세 · 삭제 (수정 API 없음) | `app/api/logs.py` |
| 계획 | F3015 | 저장 · 목록 · 상세, 날짜 · 생성 일시 포함, **같은 날짜 시간 겹침은 저장하고 알림** | `app/storage/sqlite.py`, `app/api/plans.py` |
| | F3016 | 수정 · 삭제, 화면 즉시 반영 | 〃, `web/index.html` |
| 서버 · 화면 | F3017 | FastAPI `/api/chat` · `/api/plans` · `/api/logs`, Pydantic 형식 | `app/main.py`, `app/schemas.py` |
| | F3018 | 대화 · 계획 관리 · 실행 로그 화면 (HTML · JS) | `web/index.html` |
| | F3019 | 실행 단계 · Tool 호출 이력 타임라인, 재계획 강조, 처리 중 표시, Tool 실패 · 키 누락 안내 | 〃 |

### 계획을 짜는 규칙 (이 서비스의 핵심)

1. **루트 (1순위)**: 말한 분야에서 **최근 합격자 수가 많은 종목**(최다의 10% 이상)을 고른다. 통계가 없는 다른 기관 자격은 그 분야 자격으로, 가까운 분야(정보기술 ↔ 데이터)는 보완으로 넣는다.
   **관계 분석 (2순위)**: 같은 계열에서 학력만으로 상위에 응시할 수 있으면(기능사 < 산업기사 < 기사) **상위만 남기고 하위는 "상위에 포함"** 으로 뺀다. 상위가 경력을 요구하면(2급 < 1급, SQLD < SQLP) 하위만 넣고 상위는 다음 단계로 안내. 다른 종목은 보완으로 유지. **기간을 말하지 않으면 루트 전체(최대 8개)** 를 제안한다.
2. 자격을 직접 지정하면 그 자격만 계획하고, 응시자격이 안 될 때의 앞 단계 사다리를 참고로 보여 줍니다.
3. 공부 기간은 외부 데이터로 확인할 수 없어 **서비스 기준값**(등급별, 필기 합격률 35% 미만이면 +2주)을 쓰고 그렇게 표시합니다. 시험일에서 역산한 "늦어도 이 날 시작" 을 제시합니다.
4. 상시시험(기능사 등)은 공고된 회차 뒤로 다음 해 추정 회차를 이어 붙이고, 준비가 끝나는 가장 빠른 달에 배치합니다.

### 심화 (F3020 ~ F3023)

| 번호 | 구현 | 위치 |
|---|---|---|
| F3020 이상 징후 판단 | 로깅 Agent 가 요청이 끝날 때 **규칙으로** 판정: 같은 Tool · 같은 인자 반복(`REPEATED_CALL`), 재계획 상한 도달(`EXCESSIVE_REPLAN`), 계획에 없던 Tool(`UNPLANNED_CALL`). 근거 이벤트가 없으면 '판정 불가'. **'이상' 에만** LLM 이 원인을 3문장 이내로 진단(백그라운드), 진단은 판정과 칸을 나눠 저장하고 실패해도 판정 유지. 메인 Agent 는 저장된 직전 판정을 주입받아 참조(`inspection_seen` 이벤트, 응답 참고 문구). 진단이 짚은 문제(후보만 늘리는 재계획)를 실제로 고쳐 기한 완화를 먼저 하도록 바꿈 | `app/logging_agent/`, `GET /api/logs/{id}/inspections` |
| F3022 RAG 검색 Tool | **로컬 서버 API 툴** `search_documents` — 큐넷 613종목 취득방법 · 출제경향과 국가전문자격정보(시행기관 · 소관부처) 1,157개 문서 (+ 선택: 네이버 지식백과 674개, `scripts/collect_naver.py`) 를 GMS 임베딩으로 Chroma 에 색인. 시험과목 · 합격기준 · 응시자격 안내 · 시행기관 질문이면 Agent 가 이 Tool 을 고르고(`qual_info` 의도), **원문 조각과 출처 링크를 그대로** 보여 준다. 색인이 없으면 `NO_INDEX` | `app/tools/rag.py`, `app/rag/`, `scripts/build_index.py` |
| F3023 캘린더 연동 | **로컬 서버 API 툴** `list_schedule` · `register_plan`. 로컬(SQLite) 구현체로 먼저 동작하고, `CALENDAR_BACKEND=google` 이면 Google Calendar 로 바뀐다 — Tool 입출력은 같다. 등록은 **계획 번호만** 받고 제목 · 날짜 · 시각은 저장소에서 읽는다. 계획을 짤 때 캘린더에 일정이 있는 날은 시험일로 잡지 않는다(`CALENDAR_BUSY`). 실제 Google Calendar 등록 · 조회 · 판정 반영 확인 | `app/calendar/`, `app/tools/calendar.py`, `scripts/google_login.py` |
| F3021 Planner · Worker | 미구현 | – |

## 4. 외부 API 출처와 이용 조건 (NF3007)

| 출처 | 주는 정보 | 이용 조건 · 한도 |
|---|---|---|
| 한국산업인력공단 큐넷 오픈 API (종목 목록 · 시험일정 · 응시료 · 종목별 취득방법 · 합격률 통계) | 613종목, 회차별 접수 · 시험 · 발표일, 응시료, 시험과목 · 합격기준, 등급별 합격자 수 | 공공데이터포털 이용허락범위 제한 없음. 개발계정 일 10,000건 |
| 공공데이터포털 자동변환 API — 한국데이터산업진흥원(SQLD · ADsP · 빅분기), 국사편찬위원회(한국사), 국시원(간호사 등 44종), 한국콘텐츠진흥원(게임), 한국해양수산연수원(해기사 · 선박조리사 등), 한국산림복지진흥원, 인사혁신처(국가공무원), 국립축산과학원(가축인공수정사) | 분야별 시험 회차 · 접수 · 시험일 | 각 데이터 상세 페이지의 이용허락범위. 개발계정 일 10,000건. 출처 URL 은 `data/sources.json` |
| 카카오 책 검색 API | 교재 제목 · 저자 · 출판사 · 출간일 · 링크 | Kakao Developers 이용약관. 결과에 원문 링크 표시, 저장하지 않음 |
| SSAFY GMS (OpenAI 호환) | 요청 해석(의도 · 조건), 이상 실행 진단, 문서 · 질의 임베딩(text-embedding-3-small) | SSAFY 교육용 |

공식 데이터가 없는 분야(금융 · 상공회의소 · 어학 등)는 지어내지 않고 "등록된 출처에 없어 확인할 수 없음" 으로 답합니다. 공고문을 옮겨 적는 보충 데이터(`data/manual_schedules.json`)로 넓힐 수 있습니다.

## 5. 보안 · 한계

| 항목 | 현재 | 이유 · 확장 방향 |
|---|---|---|
| 큐넷 API 가 HTTP | 큐넷 원본 API 는 HTTPS 를 받지 않고(2026-11-19 확인: https 연결 시간 초과), 공공데이터포털 HTTPS 게이트웨이에는 이 서비스가 없다. 그래서 **서비스키를 HTTP 로 보내지 않는다** — 키 없이도 5개 API 가 모두 응답한다 | 평문 전송으로 키가 노출되지 않게. HTTPS 주소가 생기면 `QNET_BASE` 만 바꾸면 그때부터 키를 보낸다 (`app/tools/sources/qnet.py`) |
| 키 관리 | `.env` 에만, 화면 · 로그 · 오류 메시지에 원문을 내보내지 않음 (NF3001 · NF3002) | – |
| 사용자 구분 없음 | 로컬 단일 사용자 서비스. 계획 · 실행 로그 조회 · 삭제에 인증이 없다 | 외부 공개 시 계정 · 소유권(계획 · 세션에 user_id) · 데이터 격리 · 인증 필요 |
| 테스트 범위 | 오프라인 테스트는 외부 API 를 가짜 응답으로 격리해 계약 변경 · 지연 · 인증 정책 변화는 잡지 못한다 | `pytest -m live` 스모크 점검을 배포 · 제출 전에 따로 돌린다 |

## 6. 구조

```
app/
├─ domain/          Entities — 순수 파이썬: 일정 정규화 · 추정, 배치(흐름 · 역산 · 충돌), 겹침 판정
├─ agent/           Use Cases — LangGraph: analyze → (screen) → plan → execute → judge → (replan)* → enrich → (external) → respond
├─ events/          이벤트 버스 (메인 Agent 는 구독자를 모름)
├─ logging_agent/   로깅 서브 Agent (구독 · 저장 · 이상 징후 규칙 판정, 진단만 LLM)
├─ tools/           Adapter — 외부 API 툴 3종 + 로컬 RAG 툴, sources/ (큐넷 · 표 데이터 · 공고문)
├─ rag/             Vector DB (Chroma + GMS 임베딩)
├─ llm/             Adapter — GMS
├─ storage/         SQLite (계획 · 실행 로그)
├─ calendar/        캘린더 구현체 (로컬 · Google)
├─ api/             FastAPI 라우터
└─ container.py     조립 (agent 는 tools · LLM 을 주입받음)
web/index.html      화면
data/sources.json   표 형태 출처 설정 (코드 수정 없이 출처 추가)
```

## 7. 제출 산출물

| 산출물 | 위치 |
|---|---|
| 요구사항 정의서 (도메인 조건 근거 · 기획 검증 결과 포함) | [docs/requirements.md](docs/requirements.md) |
| Agent 설계 문서 | [docs/design/agent_design.md](docs/design/agent_design.md) |
| Tool 정의서 | [docs/tools.md](docs/tools.md) |
| API 명세서 | [docs/api.md](docs/api.md) (실행 중 `/docs`) |
| 검증 결과 — 대표 시나리오 | [docs/verification/scenarios.md](docs/verification/scenarios.md) |
| 실행 로그 샘플 (전체 · 재계획 · 상한 도달) · 이상 징후 판정 샘플 | [docs/verification/](docs/verification/) `log_sample_*.json` · `inspection_sample_S3.json` |
| 기획 검증 — Tool 선택 확인 · API 응답 원본 | [docs/verification/tool_calling.md](docs/verification/tool_calling.md), [docs/api_samples/](docs/api_samples/) |
| 데이터 출처 조사 | [docs/research/data_sources.md](docs/research/data_sources.md) |

### 직업 → 준비 계획 (커리어넷 직업정보)

1. 사용자가 말한 직업 이름으로 커리어넷 552개 직업 중 후보를 추린다 (`app/tools/sources/careernet.py` — 꼬리말 '엔지니어 · 관리자 …' 을 뗀 핵심 낱말 우선, 목록은 30일 캐시).
2. LLM 이 **후보 목록 안에서만** 같은 직업을 고른다 (하는 일이 다르면 고르지 않음 — 조리사 ≠ 영양사). 목록 밖 번호는 버린다.
3. 고른 직업의 상세(하는 일 · 관련 자격 · 학과 · 교육 · 훈련 · 채용)를 **원문 그대로** 출처 링크와 함께 보여 준다. 관련 자격 원문이 다른 직업 이야기면 쓰지 않고 그 사실을 알린다.
4. 관련 자격 원문에 나온 자격명 중 큐넷 · 공공데이터에 등록된 것만 후보로 → 시험과목 관련성 판정 → 일정 계산.
5. 커리어넷에 없는 직업이거나 관련 자격이 비어 있으면 LLM 풀이 · 네이버 글 근거로 찾고 화면에 'AI 풀이 · 비공식' 으로 표시한다.

주의: 상세 API(`job.json?seq=`)의 번호는 목록의 `job_cd` 다. 목록의 `seq` 를 넣으면 다른 직업이 온다 (`tests/test_careernet.py`).

### 목표 점검 Agent (`app/agent/screen.py`)

analyze 다음에, 직업 · 낱말로만 목표를 말한 새 계획 요청이면 LLM 이 **문장 전체 맥락**으로 판정한다.
`ok`(준비 가능한 직업 — 회사명 · 꾸밈말을 떼어 실제 직무로 고침) · `position`(스페이스X 대표 같은 직위) · `vague`(모호) · `not_job`(부자 되기).
걸러지면 Tool 을 부르지 않고 이유와 맥락에 맞는 실제 직업 2~4개를 화면 선택지로 보여 준다. 누르면 일반 흐름(커리어넷 · 큐넷 확인)을 다시 거친다.
자격을 직접 말했거나 화면 선택 후속이면 점검하지 않는다. 점검 LLM 이 실패하면 막지 않고 원래 흐름으로 간다.

### 외부 자격 탐색 Agent (`app/agent/external.py`)

목표 직업의 관련 자격 중 큐넷 · 공공데이터에 없는 것(금융 · 협회 · 민간 — 신용분석사, 투자자산운용사, CFA …)을 네이버 웹문서 검색(API HUB `webkr`, 3일 캐시)으로 찾는다.
- 자격 이름: 커리어넷 '관련 자격' 원문에 글자 그대로 있는 이름. 원문이 없으면 '{직업} 자격증' 웹 조각에 글자 그대로 있고, 그 이름으로 다시 검색해 웹문서 2건 이상에 나오는 이름만. 직업 이름 · 다른 이름의 일부는 뺀다.
- 시험일: '{자격} 시험일정' 조각에서 LLM 이 뽑되 **날짜 글자가 그 조각에 실제로 있어야** 하고, 연도는 코드가 정한다(조각에 연도가 없으면 오늘 이후 같은 월 · 일 — '추정' 표시). 1년 안의 날짜만.
- 공식 일정 계획과 섞지 않고 '큐넷 밖 관련 자격 — 웹 검색 · 비공식' 칸에 원문 표현 · 출처 링크와 함께. 준비 기간은 8주로 가정하고 그렇게 밝힌다.

