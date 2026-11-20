# Tool 호출 선택 확인 (2026-11-18 17:27, 모델 gpt-4.1-mini)

| 경우 | 요청 | 기대 | LLM 선택 | 인자 | 판정 |
|---|---|---|---|---|---|
| Tool 필요 — 분야 추천 | 비전공자인데 IT 쪽 자격증 따고 싶어. 뭐가 있어? | search_qualifications | search_qualifications | `{"field": "정보통신", "limit": 10}` | ✅ |
| Tool 필요 — 일정 확인 | 정보처리기사(종목코드 1320) 다음 시험 언제야? | get_exam_schedule | get_exam_schedule | `{"qual_id": "1320"}` | ✅ |
| Tool 필요 — 교재 | SQLD 필기 교재 알려줘 | search_books | search_books | `{"qualification_name": "SQLD", "exam_type": "필기", "limit": 5}` | ✅ |
| RAG — 문서로만 있는 정보 | 전기기사 필기 시험과목이랑 합격기준이 어떻게 돼? | search_documents | search_documents | `{"query": "전기기사 필기 시험과목 합격기준", "qualification_name": "전기기사", "limit": 3}` | ✅ |
| RAG — 시행기관 | 공인회계사 시험은 어느 기관에서 시행해? | search_documents | search_documents | `{"query": "공인회계사 시험 시행기관", "qualification_name": "공인회계사", "limit": 1}` | ✅ |
| Tool 불필요 — 인사 | 안녕! 너는 뭐 하는 서비스야? | (없음) | (없음) | `{}` | ✅ |

결과: 6/6 기대와 일치
