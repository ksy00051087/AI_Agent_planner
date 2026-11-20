# API 명세서

> `scripts/export_docs.py` 가 FastAPI OpenAPI 스키마에서 뽑은 문서다. 실행 중에는 `/docs` 에서도 볼 수 있다.

| 메서드 | 경로 | 설명 | 요청 | 응답 |
|---|---|---|---|---|
| POST | `/api/chat` | 사용자 발화 1건을 메인 Agent 로 처리한다. 응답 · 계획 초안 · 제외 사유 · 실행 이벤트를 돌려준다. | ChatIn | ChatOut |
| GET | `/api/plans` | 저장한 계획 목록 (시험일 순). | – | PlanOut[] |
| POST | `/api/plans` | 계획 1건 저장. 같은 날짜에 시간이 겹치는 계획이 있으면 저장하고 overlaps 로 알린다. | PlanIn | PlanSaved |
| POST | `/api/plans/batch` | 대화에서 만든 계획 여러 항목을 한 번에 저장한다. 항목마다 겹침을 알린다. | PlanBatchIn | PlanSaved[] |
| GET | `/api/plans/{plan_id}` | 계획 상세. | – | PlanOut |
| PUT | `/api/plans/{plan_id}` | 계획 핵심 값 수정. 수정 뒤 겹침을 다시 알린다. | PlanUpdate | PlanSaved |
| DELETE | `/api/plans/{plan_id}` | 계획 삭제. | – | 204 No Content |
| GET | `/api/logs` | 세션 단위 실행 로그 목록 (요청 수 · 이벤트 수 · 재계획 · Tool 실패 수). | – | LogSession[] |
| GET | `/api/logs/{session_id}` | 특정 세션의 실행 로그를 실행 순서대로. | – | LogEvent[] |
| DELETE | `/api/logs/{session_id}` | 특정 세션의 실행 로그 삭제. | – | 204 No Content |
| GET | `/api/logs/{session_id}/inspections` | 세션의 요청별 이상 징후 판정(F3020, 규칙) 과 진단(LLM, 이상일 때만). 판정과 진단은 칸이 따로다. | – | LogInspection[] |
| GET | `/api/calendar` | 캘린더 일정 조회 (list_schedule Tool). 기본: 오늘부터 1년. | – | – |
| POST | `/api/plans/{plan_id}/calendar` | 저장한 계획을 캘린더에 등록 (register_plan Tool). 계획 번호만 받고 제목 · 날짜 · 시각은 저장소에서 읽는다. | – | – |
| GET | `/api/health` | 서버 상태 · LLM 키 설정 여부 · 로깅 Agent 저장 수. | – | – |

실행 로그에는 수정(PUT · PATCH) 경로가 없다. 오류 응답의 `detail` 에는 내부 오류 원문을 싣지 않는다.

## 스키마

### ChatIn



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `session_id` | string 또는 null |  | 없으면 새 세션을 만든다 |
| `message` | string | ✅ |  |

### ChatOut



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `session_id` | string | ✅ |  |
| `run_id` | string | ✅ |  |
| `answer` | string | ✅ |  |
| `intent` | string 또는 null |  |  |
| `conditions` | object 또는 null |  |  |
| `draft_plan` | object[] |  |  |
| `excluded` | object[] |  |  |
| `books` | object |  |  |
| `documents` | object[] |  | 자격 정보 문서 검색 결과 (F3022, 근거 원문 · 출처) |
| `replans` | object[] |  |  |
| `needs_replan` | string 또는 null |  |  |
| `failures` | object[] |  |  |
| `events` | object[] |  | 실행 단계 · Tool 호출 이력 (실행 순서) |
| `prev_inspection` | object 또는 null |  | 직전 요청의 이상 징후 판정 (F3020) |

### LogEvent



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `session_id` | string | ✅ |  |
| `run_id` | string | ✅ |  |
| `seq` | integer | ✅ |  |
| `ts` | string | ✅ |  |
| `type` | string | ✅ |  |
| `node` | string 또는 null |  |  |

### LogInspection



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `run_id` | string | ✅ |  |
| `session_id` | string | ✅ |  |
| `verdict` | string | ✅ | 정상 · 이상 · 판정 불가 (규칙 판정, LLM 미사용) |
| `warnings` | LogWarning[] | ✅ |  |
| `reason` | string 또는 null |  | 판정 불가일 때 이유 |
| `counts` | object | ✅ |  |
| `diagnosis` | string 또는 null |  | 이상일 때만 LLM 이 쓴 원인 진단 (판정과 별도) |
| `diagnosis_status` | string 또는 null |  | null(대상 아님) · pending · ok · failed |
| `created_at` | string | ✅ |  |

### LogSession



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `session_id` | string | ✅ |  |
| `runs` | integer | ✅ |  |
| `events` | integer | ✅ |  |
| `started_at` | string | ✅ |  |
| `last_at` | string | ✅ |  |
| `replans` | integer | ✅ |  |
| `errors` | integer | ✅ |  |
| `tool_failures` | integer | ✅ |  |

### LogWarning



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `type` | string | ✅ | REPEATED_CALL · EXCESSIVE_REPLAN · UNPLANNED_CALL |
| `detail` | string | ✅ |  |
| `evidence` | integer[] | ✅ | 근거 이벤트 seq |

### PlanBatchIn



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `items` | PlanIn[] | ✅ |  |

### PlanIn



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `qual_name` | string | ✅ |  |
| `plan_date` | string | ✅ | 시험일 |
| `start_time` | string 또는 null |  |  |
| `end_time` | string 또는 null |  |  |
| `qual_id` | string 또는 null |  |  |
| `stage` | string 또는 null |  |  |
| `round_name` | string 또는 null |  |  |
| `practical_date` | string 또는 null |  |  |
| `registration_end` | string 또는 null |  |  |
| `study_start` | string 또는 null |  |  |
| `estimated` | boolean |  |  |
| `source` | string 또는 null |  |  |
| `memo` | string 또는 null |  |  |
| `group_id` | string 또는 null |  |  |

### PlanOut



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `qual_name` | string | ✅ |  |
| `plan_date` | string | ✅ | 시험일 |
| `start_time` | string 또는 null |  |  |
| `end_time` | string 또는 null |  |  |
| `qual_id` | string 또는 null |  |  |
| `stage` | string 또는 null |  |  |
| `round_name` | string 또는 null |  |  |
| `practical_date` | string 또는 null |  |  |
| `registration_end` | string 또는 null |  |  |
| `study_start` | string 또는 null |  |  |
| `estimated` | boolean |  |  |
| `source` | string 또는 null |  |  |
| `memo` | string 또는 null |  |  |
| `group_id` | string 또는 null |  |  |
| `plan_id` | integer | ✅ |  |
| `created_at` | string | ✅ |  |
| `updated_at` | string | ✅ |  |

### PlanSaved



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `plan` | PlanOut | ✅ |  |
| `overlaps` | PlanOut[] | ✅ | 같은 날짜에 시간이 겹치는 기존 계획 (저장은 막지 않는다) |
| `message` | string | ✅ |  |

### PlanUpdate



| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| `qual_name` | string 또는 null |  |  |
| `plan_date` | string 또는 null |  |  |
| `start_time` | string 또는 null |  |  |
| `end_time` | string 또는 null |  |  |
| `stage` | string 또는 null |  |  |
| `round_name` | string 또는 null |  |  |
| `practical_date` | string 또는 null |  |  |
| `registration_end` | string 또는 null |  |  |
| `study_start` | string 또는 null |  |  |
| `memo` | string 또는 null |  |  |

