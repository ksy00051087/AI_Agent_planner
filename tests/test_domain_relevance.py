"""목표와 자격의 관련성 — LLM 판정은 공식 시험과목으로 검증될 때만 받아들인다."""

from app.domain.qualinfo import parse_acquisition
from app.domain.relevance import apply_relevance, grounded

SUBJ = {"포장기사": "필기: 포장일반, 물류관리 및 유통시험, 포장재료 및 시험, 포장기법 / 실기: 포장실무",
        "사회조사분석사2급": "필기: 조사방법과 설계, 조사관리와 자료처리, 통계분석과 활용 / 실기: 사회조사실무"}
CANDS = [{"qual_id": "1", "name": "포장기사"}, {"qual_id": "2", "name": "사회조사분석사2급"}, {"qual_id": "3", "name": "SQLD"}]


def test_근거가_시험과목에_있을때만_뺀다():
    v = [{"name": "포장기사", "relevant": False, "basis": "포장일반", "reason": "제조 · 물류 과목"},
         {"name": "사회조사분석사2급", "relevant": True, "basis": "통계분석과 활용", "reason": "조사 · 분석"}]
    keep, dropped = apply_relevance(CANDS, SUBJ, v)
    assert [q["name"] for q in keep] == ["사회조사분석사2급", "SQLD"]
    assert dropped[0]["name"] == "포장기사" and dropped[0]["basis"] == "포장일반"


def test_지어낸_과목이면_판정을_버리고_남긴다():
    v = [{"name": "포장기사", "relevant": False, "basis": "회계원리", "reason": "?"}]
    keep, dropped = apply_relevance(CANDS, SUBJ, v)
    assert dropped == [] and len(keep) == 3


def test_시험과목이_없는_자격과_이름이_다른_판정은_건드리지_않는다():
    v = [{"name": "SQLD", "relevant": False, "basis": "SQLD", "reason": "?"},
         {"name": "포장일반", "relevant": False, "basis": "포장일반", "reason": "과목명으로 온 판정"}]
    keep, dropped = apply_relevance(CANDS, SUBJ, v)
    assert dropped == [] and len(keep) == 3


def test_grounded():
    assert grounded("포장 일반", "포장기사", SUBJ["포장기사"])     # 띄어쓰기 차이는 같은 과목
    assert not grounded("", "포장기사", SUBJ["포장기사"])
    assert not grounded("회계", "포장기사", SUBJ["포장기사"])


def test_취득방법_섹션이_줄끝에_붙어도_시험과목에_검정방법이_섞이지_않는다():
    text = ("컨벤션기획사2급 취득방법\n시험과목('22년부터 적용)\n- 필기 1. 컨벤션 기획(30문제) 2. 컨벤션 운영(30문제)\n"
            "- 실기 : 컨벤션 실무(실무제안서 작성) 검정방법\n- 필기 : 객관식 4지 택일형\n- 실기 : 작업형(6시간 정도, 100점)\n"
            "합격기준\n- 필기 : 과목당 40점 이상")
    info = parse_acquisition(text)
    assert info["subjects"]["필기"] == ["컨벤션 기획(30문제)", "컨벤션 운영(30문제)"]
    assert "객관식" not in " ".join(info["subjects"]["실기"])
    assert info["exam_method"]["필기"].startswith("객관식")
