"""자격 소개 — 공식 시험과목 먼저, 없으면 서비스 안내, 그것도 없으면 데이터로 확인되는 사실만."""

from app.domain.intro import build_intro

INTROS = {"정보처리기사": {"good_for": "개발 직군 기본 자격"}, "SQL 개발자(SQLD)": {"study": "SQL 기본 · 활용", "good_for": "SQL 실력 증명"}}
EXAM = {"subjects": {"필기": ["소프트웨어설계", "소프트웨어개발", "데이터베이스구축", "프로그래밍언어활용", "정보시스템구축관리", "여섯째"],
                     "실기": ["정보처리 실무"]}}


def test_공식_시험과목이_있으면_그것을_쓰고_출처를_밝힌다():
    it = build_intro("정보처리기사", EXAM, INTROS)
    assert it["study"].startswith("필기: 소프트웨어설계") and "외 1과목" in it["study"] and "실기: 정보처리 실무" in it["study"]
    assert it["study_source"] == "큐넷 시험과목"
    assert (it["good_for"], it["good_for_source"]) == ("개발 직군 기본 자격", "서비스 안내")


def test_시험과목이_없으면_서비스_안내_문구():
    it = build_intro("SQL 개발자(SQLD)", None, INTROS)
    assert (it["study"], it["study_source"]) == ("SQL 기본 · 활용", "서비스 안내")


def test_안내_문구도_없으면_데이터로_확인되는_사실만():
    it = build_intro("전기공사기사", None, {}, track="전기 설비 · 공사", popularity="2025년 실기 합격자 5,000명")
    assert it["good_for"] == "전기 설비 · 공사 쪽으로 갈 때 이어지는 자격 · 2025년 실기 합격자 5,000명"
    assert it["good_for_source"] == "데이터" and it["study"] is None
    assert build_intro("모르는자격", None, {})["good_for"] is None          # 지어내지 않는다


def test_소개_문구에는_확인할_수_없는_표현을_쓰지_않는다():
    import json
    from pathlib import Path
    items = json.loads((Path(__file__).resolve().parents[1] / "data" / "qual_intros.json").read_text(encoding="utf-8"))["items"]
    for name, v in items.items():
        for bad in ("가점", "가장 많이", "많이 요구", "가장 흔히", "많이 땀", "유리하다", "대표"):
            assert bad not in (v.get("good_for") or "") + (v.get("study") or ""), (name, bad)



def test_9급은_한국사만_능력검정으로_대체한다고_적는다():
    import json
    from pathlib import Path
    v = json.loads((Path(__file__).resolve().parents[1] / "data" / "qual_intros.json").read_text(encoding="utf-8"))["items"]["9급공개경쟁채용시험"]
    assert "영어 · 한국사를 능력검정" not in v["study"] and "한국사를 한국사능력검정 성적으로 대체" in v["study"]
