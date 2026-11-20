# Agent 설계 — 자격증 장기 플래너

> 구현과 맞춘 문서 (2026-11-18). 1일차 초안과 달라진 점은 맨 아래 "변경 이력".

## 1. 원칙

- **확인하지 않은 값을 지어내지 않는다.** 날짜 · 응시료 · 합격률 · 교재는 Tool 결과에서만, 판정은 `app/domain/` 순수 함수가 한다.
- **LLM 은 요청 해석에만** 쓴다(의도 · 조건 추출). Tool 순서 · 판정 · 재계획 · 응답 문장은 규칙(코드)이다. 그래서 응답에 나오는 숫자는 모두 출처가 있다.
- 확인할 수 없는 값은 이름을 붙여 드러낸다: "추정"(미공고 일정), "서비스 기준값"(공부 기간), "확인 불가"(출처 없음).

## 2. 실행 그래프 (LangGraph)

```
START → analyze ─┬─ 오류 · 인사 · 저장 · 되묻기 ───────────────────────────────→ respond → END
                 └─ 계획 · 수정 · 사실조회 → plan → execute ─┬─ 치명적 실패 ──────→ respond
                                                  ↑           └→ judge ─┬─ 사실조회 · 배치 없음 → respond
                                                  │                     ├─ 재계획 필요 → replan ┐
                                                  └─────────────────────┼────────────────────────┘
                                                                        └─ 배치 있음 → enrich → respond
```

| 노드 | 하는 일 | LLM | 상태에 쓰는 값 |
|---|---|---|---|
| analyze (F3005 · F3010) | 의도 분류 · 조건 추출 → 코드 검증 → 이전 조건과 병합 → 되묻기 판단 | ✅ 구조화 출력 1회 | intent, conditions, missing, interpretations, warnings |
| plan (F3006) | 의도 · 조건으로 Tool 순서 결정 | ❌ | steps, batch_end |
| execute (F3007) | 후보 검색 → 순위(흐름) → 상위 후보 일정 병렬 조회 | ❌ | candidates, tool_results, failures, fatal |
| judge (F3008) | `domain.arrange` 로 배치, 재계획 필요 여부 | ❌ | arrangement, needs_replan |
| replan (F3009) | 다음 후보 추가 또는 기한 완화 | ❌ | replan_count, replan_log, batch_end · ignore_deadline |
| enrich (F3004) | 배치된 자격의 교재 | ❌ | books |
| respond (F3011) | 구조화된 결과 → 문장 | ❌ (템플릿) | answer, last_plan |

## 3. 조건 추출과 검증 (F3005)

LLM 이 `AnalyzeOutput`(의도 · 이유 · new_topic · 조건 · 해석)을 채우면 코드가 다시 검사한다.

| 조건 | 기본값 / 검증 |
|---|---|
| start_date · deadline | 말하지 않으면 비움(시작은 오늘로 계산하고 "(오늘)" 표시). 날짜가 아니면 버림. **지난 기한은 고쳐 쓰지 않고 되묻기** |
| field | 출처에 실제로 있는 분야 75개 중에서만. 밖이면 keywords 로 옮김 |
| targets · keywords · grades · exclude | 등급 낱말이 targets 에 있으면 grades 로. **사용자가 말하지 않은 등급은 버림**. "취업" · "자격증" 같은 낱말은 검색어에서 뺌 |
| budget · prep_weeks · max_parallel · blocked_dates | 0 이하 · 날짜 아님은 버림 |
| 해석 | "내년 6월까지" → 2027-06-30 같은 변환은 `interpretations` 와 `llm_decision` 이벤트로 남기고 응답에도 표시 |

되묻기: 계획 요청인데 분야 · 자격 · 검색어가 모두 없음 / 사실조회인데 자격명이 없음 / 기한이 오늘보다 이전.

## 4. 계획 수립과 Tool 순서 (F3006 · F3007)

| 의도 | 순서 |
|---|---|
| plan_create · plan_modify | `search_qualifications`(지정 자격 · 분야 · 검색어마다) → 상위 후보 6개 `get_exam_schedule`(병렬) → 배치된 자격 최대 4개 `search_books` |
| fact_lookup | `search_qualifications` → 상위 3개 `get_exam_schedule` |
| chat · plan_save · 되묻기 · LLM 오류 | Tool 없음 |

- 같은 인자의 Tool 결과는 요청 안에서 재사용(재계획 포함), 큐넷 응답은 1시간 캐시.
- 실패는 `failures` 에 사유를 남기고 다음 후보로. `INVALID_KEY` · `QUOTA_EXCEEDED` · `UPSTREAM_ERROR` 는 치명적 → 바로 안내.

## 5. 판정 규칙 (F3008) — `app/domain/arrange.py`

**① 루트 선정과 관계 분석 (가장 중요)** — `app/domain/relations.py::select_route`
1. **루트 (1순위)**: 말한 분야(세부 분야가 정확히 맞으면 그 안)에서 최근 연도 최종 합격자 수가 최다 종목의 10% 이상인 종목. 큐넷인데 통계가 없으면 거의 치르지 않는 종목으로 본다. 통계가 없는 다른 기관 자격(데이터진흥원 등)은 그 분야 자격으로 넣는다(최대 4).
2. **가까운 분야 보완**: `data/qual_relations.json` 의 분야 묶음(정보기술 ↔ 데이터)에서 보완 자격을 말한 분야 다음에 둔다(통계 있는 것 3개 + 통계 없는 것).
3. **관계 분석 (2순위)**
   - 상하위 · 학력만으로 상위 응시 가능(기능사 < 산업기사 < 기사): **상위만 남기고 하위는 `SUPERSEDED`** ("상위 자격 X 를 따면 따로 딸 필요 없음"). 응시자격이 안 될 때의 사다리는 참고로 안내.
   - 상하위 · 상위가 실무 경력 요구(2급 < 1급, 준전문가 < 전문가, 기능장 · 기술사): 자동 루트에는 하위만, 상위는 '다음 단계' 로 안내.
   - 같은 분야의 다른 종목: 보완 관계로 유지.
4. **기간을 말하지 않으면 루트 전체(최대 8개)**, 기한이 있으면 들어가는 만큼 배치하고 나머지는 "기한 안에 못 넣은 루트" 로 보여 준다.
5. 사용자가 이름을 댄 자격은 맨 앞, 상위로 대체하지 않는다. 인기 루트 밖 자격은 재계획(`NEXT_CANDIDATES`) 대안으로만 쓴다.

**② 배치** — 후보를 순서대로, 자격마다 가능한 가장 빠른 회차:

| 판정 | 실패 코드 |
|---|---|
| 접수 마감 · 시험일이 비어 있음 | `UNJUDGEABLE` |
| 필기 접수 마감이 지남 | `REGISTRATION_CLOSED` |
| 마지막 시험(실기 · 2차)이 기한을 넘음 | `DEADLINE_EXCEEDED` |
| 시험일 − 준비 기간 < 공부 가능 시작일 | `NOT_ENOUGH_TIME` |
| 시험 불가일 | `BLOCKED_DATE` |
| 앞서 배치한 자격과 같은 날 · 같은(또는 모르는) 시각 | `DATE_CONFLICT` |
| 같은 계열 앞 단계가 빠짐 | `PREREQ_NOT_PLACED` |
| 응시료 합계 > 예산 (마지막부터 뺌) | `BUDGET_EXCEEDED` |

- 준비 기간: 사용자 값 > 등급별 서비스 기준값(기능사 6 · 산업기사 8 · 기사 10 · 그 외 10주) + 필기 합격률 35% 미만이면 2주. 근거를 함께 남긴다.
- 공부 가능 시작일: 동시 공부 수(기본 1)만큼 앞 자격의 마지막 시험이 끝난 다음 날.
- "늦어도 공부 시작" = 필기 시험일 − 준비 기간 (역산).
- 계획 크기: 자격을 지정하지 않았으면 4개까지, 나머지는 "다음 계획 후보".

## 6. 재계획 (F3009 · NF3004)

| 조건 | 재계획 |
|---|---|
| 배치가 0개, 또는 지정한 자격이 판정으로 빠짐 — 남은 후보가 있고 자격 지정이 없음 | `NEXT_CANDIDATES`: 다음 후보 6개를 더 조회 (이미 받은 일정은 재사용) |
| 위와 같은데 기한이 있음 | `RELAX_DEADLINE`: 기한을 넘기는 가장 빠른 대안 계산, 응답에 ⚠️ 표시 |
| 재계획 횟수 ≥ `REPLAN_LIMIT`(2) | `LIMIT_REACHED`: 멈추고 기한 · 공부 기간 · 동시 공부 수 조정을 되묻는다 |
| 치명적 실패 · 되묻기 · 지정 자격이 출처에 없음 | 재계획하지 않음 |

## 7. 대화 맥락 (F3010)

LangGraph `MemorySaver` 체크포인터, `thread_id = session_id`.

| 남긴다 | 요청마다 지운다 (`PER_TURN_RESET`) |
|---|---|
| conditions(병합된 조건), intent, last_plan(자격 · 시험일 · 시작일 요약) | Tool 결과 · 후보 · 배치 · 교재 · 재계획 기록 · 경고 |

후속 요청은 `merge_conditions` 로 **바뀐 조건만** 갱신(exclude 는 누적), `new_topic=true` 면 이전 조건을 버린다.

## 8. 메인 Agent 와 로깅 Agent (F3012 · F3013)

```
PlannerAgent ──Emitter.emit()──▶ EventBus.publish() ──▶ LoggingAgent.handle() ──▶ LogStore(SQLite)
      │                              (구독자 실패는 삼킴)        (LLM 없음, 실패해도 예외 없음)
      └── 응답에 같은 이벤트 사본(events) → 화면 타임라인 (로깅 Agent 와 무관)
```

| 이벤트 | 필드 (공통: session_id · run_id · seq · ts · type · node) |
|---|---|
| node_enter / node_exit | summary (추출 조건, 배치 · 제외 목록, 재계획 필요 여부 …) |
| tool_call / tool_result | tool, args / ok, code, message, duration_ms, count (원본 응답은 싣지 않음) |
| llm_decision | kind(intent · interpretation), decision, reason |
| replan | count, reason_code, change |
| error | code, where |

- 메인 Agent 는 로깅 Agent 를 import 하지 않는다. `app/main.py` 가 버스에 구독시킨다.
- 검증: 구독자가 예외를 던지거나 저장소가 고장 나도 메인 Agent 는 정상 응답 (`test_구독자가_고장나도_메인_Agent는_정상응답`, `test_로깅Agent가_저장에_실패해도_메인은_정상`).

## 9. 심화 — 이상 징후 판단(F3020)과 RAG(F3022)

**이상 징후** — `app/logging_agent/inspector.py` · `agent.py`

| 규칙 | 근거 이벤트 |
|---|---|
| `REPEATED_CALL` 같은 Tool · 같은 인자 2회 이상 | tool_call 의 (tool, args) |
| `EXCESSIVE_REPLAN` 재계획 수 ≥ 상한 | replan |
| `UNPLANNED_CALL` plan 이 정한 Tool 목록 밖의 호출 | node_exit(plan).summary.steps · tool_call |
| 판정 불가 | 이벤트 없음 / respond 종료 없음 / Tool 호출은 있는데 plan 이벤트 없음 |

- LLM 호출 조건: 판정이 '이상' 일 때만, 로깅 Agent 가 백그라운드로 1회. 정상 · 판정 불가에는 부르지 않는다.
- 진단은 `inspections.diagnosis` 칸에 따로 저장(경고 수에 섞지 않음), 실패하면 `diagnosis_status=failed` 로 남고 판정 · 로그는 그대로.
- 메인 Agent 는 `AgentDeps.last_inspection(session_id)` 로 저장소의 직전 판정을 읽기만 한다 → `inspection_seen` 이벤트 + 응답 참고 문구.

**RAG** — `app/tools/rag.py` (로컬 서버 API 툴), `app/rag/store.py`, `scripts/build_index.py`
- 색인: 큐넷 종목별 취득방법 · 출제경향(613종목) + 국가전문자격정보(212건) → 900자 조각 1,157개, GMS `text-embedding-3-small`, Chroma(코사인).
- 의도 `qual_info`(시험과목 · 합격기준 · 응시자격 · 시행기관 질문) → plan: `search_documents`(자격명을 알면 그 자격 문서로 좁힘) → respond: 원문 조각과 출처 링크를 그대로. 거리 0.75 를 넘는 문서는 버리고, 없으면 `NO_DATA`, 색인이 없으면 `NO_INDEX`.

**캘린더(F3023)** — `app/calendar/backends.py` (LocalCalendar · GoogleCalendar), `app/tools/calendar.py`
- plan 이 `list_schedule` 단계를 넣고, execute 가 오늘부터 1년의 일정을 조회해 `busy_dates` 로 남긴다. judge 는 `arrange(busy_dates=...)` 로 그날 시험이 잡힌 회차를 `CALENDAR_BUSY` 로 건너뛴다. 캘린더가 연결되지 않았으면(`NOT_CONFIGURED`) 조용히 넘어간다.
- `register_plan(plan_id)` 은 계획 저장소에서 자격명 · 단계 · 시험일 · 시각 · 공부 시작일 · 추정 여부를 읽어 일정 제목과 설명을 만든다. 모델이 넘길 수 있는 값은 번호 하나뿐이다.
- 구현체 교체: `CALENDAR_BACKEND=local|google`. 두 구현체는 `list_events` · `create_event` 의 입출력이 같고, 테스트가 이를 확인한다.

## 10. 의존성 방향 (클린 아키텍처)

`domain` ← `agent`(deps 로 주입받음) ← `container` · `api` · `main`. `agent/` 는 tools · LLM SDK · FastAPI · SQL 을 import 하지 않는다 (`AgentDeps`: run_tool · tool_catalog · field_options · analyze_llm · precedes · replan_limit).

## 변경 이력

| 1일차 초안 | 구현 | 이유 |
|---|---|---|
| plan 노드가 `bind_tools` 로 첫 Tool 선택 | 의도 · 조건 기반 규칙 | Tool 선택은 의도로 결정되고, 규칙이 더 예측 가능 (LLM 의 Tool 선택 능력은 `check_tool_calling.py` 로 별도 확인) |
| 후보 순서: 낮은 등급 → 과목 겹침 → 시험일 | **합격자 수 기반 계열 흐름** | 실제 실행에서 사람들이 따는 흐름과 다른 결과 (요구사항 정의서 4장) |
| respond 에서 LLM 이 문장 작성 | 템플릿 | 값을 지어낼 여지를 없앰 |
| 교재는 execute 에서 | enrich 노드 분리 | 배치가 확정된 자격에만 부르기 위해 |
