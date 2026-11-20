from app.domain.qualinfo import parse_acquisition, parse_subjects, summarize_pass_rates

REAL_TEXT = """정보처리기사 취득방법\r\n\r\n 시 행 처 : 한국산업인력공단 \r\n 관련학과 :모든 학과 응시가능\r\n 시험과목 \r
- 필기 1. 소프트웨어설계 2. 소프트웨어개발 3. 데이터베이스구축 4. 프로그래밍언어활용 5. 정보시스템구축관리\r
- 실기 : 정보처리 실무\r\n 검정방법\r\n- 필기 : 객관식 4지 택일형, 과목당 20문항(과목당 30분)\r
- 실기 : 필답형(2시간30분)\r\n합격기준\r\n- 필기 : 100점을 만점으로 하여 과목당 40점 이상, 전과목 평균 60점 이상.\r
- 실기 : 100점을 만점으로 하여 60점 이상."""


def test_취득방법_실제텍스트():
    d = parse_acquisition(REAL_TEXT)
    assert d["subjects"]["필기"] == ["소프트웨어설계", "소프트웨어개발", "데이터베이스구축", "프로그래밍언어활용", "정보시스템구축관리"]
    assert d["subjects"]["실기"] == ["정보처리 실무"]
    assert d["exam_method"]["실기"] == "필답형(2시간30분)"
    assert "과목당 40점" in d["pass_criteria"]["필기"]


def test_번호_붙여쓰기와_번호없는_과목():
    assert parse_subjects("1.정보시스템 기반 기술2.프로그래밍언어 활용3. 데이터베이스 활용") == [
        "정보시스템 기반 기술", "프로그래밍언어 활용", "데이터베이스 활용"]
    assert parse_subjects("정보처리 실무") == ["정보처리 실무"]


def test_읽을_수_없으면_None():
    assert parse_acquisition(None) is None
    assert parse_acquisition("안내문만 있고 구조가 없음") is None


def test_합격률은_회차별_평균이_아니라_합산():
    rows = [{"stage": "필기", "takers": 100, "passed": 90},   # 90%
            {"stage": "필기", "takers": 900, "passed": 90},   # 10%  → 단순평균 50%, 합산 18%
            {"stage": "실기", "takers": None, "passed": 5}]   # 응시자 수 없음 → 제외
    assert summarize_pass_rates(rows) == {"필기": {"rate": 18.0, "takers": 1000, "passed": 180, "rounds": 2}}
    assert summarize_pass_rates([]) is None
