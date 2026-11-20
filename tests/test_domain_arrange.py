"""F3008 배치 규칙 — 여러 분야 · 여러 시험 구조."""

from datetime import date

from app.domain.arrange import arrange, order_candidates, prep_weeks

TODAY = date(2026, 11, 18)


def rnd(reg_end, exam, practical=None, stage=None, time=None, estimated=False, name="회차"):
    return {"name": name, "stage": stage, "exam_time": time, "estimated": estimated, "basis": None,
            "written_reg_start": None, "written_reg_end": reg_end, "written_exam_start": exam,
            "practical_exam_start": practical}


def cand(name, grade, rounds, fee=None, rate=None, qid=None):
    return {"qual_id": qid or name, "name": name, "grade": grade, "source": "t", "rounds": rounds,
            "fee": fee, "pass_rate": {"by_stage": {"필기": {"rate": rate}}} if rate is not None else None}


# 분야가 다른 예시 후보
IT_ENG = cand("정보처리기사", "기사", [rnd("2027-01-15", "2027-01-30", "2027-04-18"),
                                    rnd("2027-04-23", "2027-05-09", "2027-07-18"),
                                    rnd("2027-07-23", "2027-08-07", "2027-10-24")], fee={"1차": 19400, "2차": 22600})
IT_IND = cand("정보처리산업기사", "산업기사", [rnd("2027-01-15", "2027-03-01", "2027-04-18"),
                                          rnd("2027-04-23", "2027-05-31", "2027-07-18")], fee={"1차": 19400, "2차": 20800})
COOK = cand("한식조리기능사", "기능사", [rnd(f"2027-0{m}-01", f"2027-0{m}-10") for m in range(1, 10)],  # 상시시험
            fee={"1차": 14500, "2차": 26900})
NURSE = cand("간호사", None, [rnd("2026-10-02", "2027-01-23", stage=None)])
CIVIL = cand("9급공개경쟁채용시험", None, [rnd("2027-02-13", "2027-04-04", "2027-06-20", stage="1차 → 2차")])


def test_순서_낮은등급_먼저_사용자_지정이_우선():
    assert [c["name"] for c in order_candidates([IT_ENG, IT_IND, COOK])] == ["한식조리기능사", "정보처리산업기사", "정보처리기사"]
    assert [c["name"] for c in order_candidates([IT_IND, IT_ENG], targets=["정보처리기사"])] == ["정보처리기사", "정보처리산업기사"]


def test_선수관계는_순서를_바꾼다():
    out = order_candidates([IT_IND, COOK], precedes={"한식조리기능사": {"정보처리산업기사"}})
    assert [c["name"] for c in out] == ["정보처리산업기사", "한식조리기능사"]


def test_준비기간_합격률이_낮으면_늘린다():
    assert prep_weeks(cand("전기기사", "기사", [], rate=29.9), None)[0] == 12
    assert prep_weeks(cand("전기기사", "기사", [], rate=29.9), 4) == (4, "사용자 입력")
    weeks, basis = prep_weeks(NURSE, None)
    assert weeks == 10 and "등급 미상" in basis  # 등급 체계가 없는 면허도 기본값 + 근거


def test_한번에_충족_순차배치와_역산():
    out = arrange([IT_IND, IT_ENG], {}, TODAY)
    names = [(p["name"], p["exam_date"], p["study_start_by"]) for p in out["placed"]]
    # 산업기사(8주) 실기 04-18 이 끝난 뒤 기사(10주) 공부 → 1 · 2회는 준비 기간 부족, 3회(08-07)
    assert names == [("정보처리산업기사", "2027-03-01", "2027-01-04"), ("정보처리기사", "2027-08-07", "2027-05-29")]
    assert out["fee_total"] == 19400 + 20800 + 19400 + 22600


def test_상시시험은_준비가_끝나는_가장_빠른_회차():
    out = arrange([COOK], {}, TODAY)
    assert out["placed"][0]["exam_date"] == "2027-01-10"  # 6주 준비 → 12-30 이후 첫 회차


def test_기한을_넘으면_DEADLINE_EXCEEDED():
    out = arrange([IT_ENG], {"deadline": "2027-03-31"}, TODAY)
    assert out["placed"] == [] and out["excluded"][0]["reason_code"] == "DEADLINE_EXCEEDED"


def test_기한을_무시한_대안():
    out = arrange([IT_ENG], {"deadline": "2027-03-31"}, TODAY, ignore_deadline=True)
    assert out["placed"][0]["exam_date"] == "2027-01-30" and out["deadline_ignored"]


def test_접수가_끝난_자격은_REGISTRATION_CLOSED():
    out = arrange([NURSE], {}, TODAY)
    assert out["excluded"][0]["reason_code"] == "REGISTRATION_CLOSED"


def test_날짜가_비면_UNJUDGEABLE_채우지_않는다():
    out = arrange([cand("x", None, [rnd(None, "2027-03-01")])], {}, TODAY)
    assert out["excluded"][0]["reason_code"] == "UNJUDGEABLE"


def test_같은날_시험은_충돌_시각이_다르면_허용():
    a = cand("A", "기능사", [rnd("2027-03-01", "2027-03-20", time="09:00")])
    b = cand("B", "기능사", [rnd("2027-03-01", "2027-03-20", time="09:00"), rnd("2027-05-01", "2027-05-20")])
    out = arrange([a, b], {"max_parallel": 2}, TODAY)
    assert [(p["name"], p["exam_date"]) for p in out["placed"]] == [("A", "2027-03-20"), ("B", "2027-05-20")]
    c = cand("C", "기능사", [rnd("2027-03-01", "2027-03-20", time="14:00")])
    out = arrange([a, c], {"max_parallel": 2}, TODAY)
    assert len(out["placed"]) == 2


def test_시험불가_날짜():
    out = arrange([cand("A", "기능사", [rnd("2027-03-01", "2027-03-20")])], {"blocked_dates": ["2027-03-20"]}, TODAY)
    assert out["excluded"][0]["reason_code"] == "BLOCKED_DATE"


def test_1차2차_구조의_최종일로_기한_판정():
    out = arrange([CIVIL], {"deadline": "2027-05-31"}, TODAY)
    assert out["excluded"][0]["reason_code"] == "DEADLINE_EXCEEDED"  # 1차는 4월이지만 2차가 6월
    out = arrange([CIVIL], {"deadline": "2027-06-30"}, TODAY)
    assert out["placed"][0]["practical_exam_date"] == "2027-06-20"


def test_예산을_넘으면_마지막부터_빼고_응시료_모르는_것은_따로():
    out = arrange([COOK, IT_IND, NURSE], {"budget": 50000, "max_parallel": 3}, TODAY)
    assert [p["name"] for p in out["placed"]] == ["한식조리기능사"]
    assert out["excluded"][-1]["reason_code"] == "BUDGET_EXCEEDED"
    out = arrange([cand("면허", None, [rnd("2027-03-01", "2027-03-20")])], {}, TODAY)
    assert out["fee_unknown"] == ["면허"] and out["fee_total"] == 0


def test_같은_계열_앞단계가_빠지면_뒷단계도_넣지_않는다():
    low = {**cand("양식조리기능사", "기능사", [rnd("2026-11-01", "2026-11-10")]), "chain": "양식조리"}  # 접수 끝남
    high = {**cand("양식조리산업기사", "산업기사", [rnd("2027-07-23", "2027-08-07")]), "chain": "양식조리"}
    out = arrange([low, high], {}, TODAY)
    assert out["placed"] == []
    assert [e["reason_code"] for e in out["excluded"]] == ["REGISTRATION_CLOSED", "PREREQ_NOT_PLACED"]


def test_계획_크기_제한은_제외가_아니라_다음_후보():
    out = arrange([COOK, IT_IND, IT_ENG], {"max_parallel": 3}, TODAY, max_items=2)
    assert len(out["placed"]) == 2 and out["deferred"] == ["정보처리기사"] and out["excluded"] == []


# 공부 부담 — 기본 자격은 병행, 큰 시험은 혼자, 나머지는 2개까지 병행 (동시 공부 수를 말하지 않았을 때)
MONTHLY = lambda n, g="기능사", day=15: cand(n, g, [rnd(f"2027-{m:02d}-01", f"2027-{m:02d}-{day}") for m in range(1, 13)])  # noqa: E731
ov = lambda a, b: a[0] <= b[1] and b[0] <= a[1]  # noqa: E731


def _windows(out):
    return {p["name"]: (p["study_start_by"], p["practical_exam_date"] or p["exam_date"]) for p in out["placed"]}


def test_큰_시험이_아니면_2개까지_병행():
    out = arrange([MONTHLY("A"), MONTHLY("B", day=20), MONTHLY("C", day=25)], {}, TODAY)
    w = _windows(out)
    assert w["A"][0] == "2026-12-04" and ov(w["A"], w["B"])   # 둘은 같은 기간에 함께 (가장 빠른 회차)
    assert not (ov(w["C"], w["A"]) and ov(w["C"], w["B"]))   # 세 번째는 셋이 한꺼번에 겹치지 않게
    assert {p["name"]: p["load"] for p in out["placed"]} == {"A": "light", "B": "light", "C": "light"}
    assert next(p for p in out["placed"] if p["name"] == "A")["parallel_with"] == ["B"]


def test_큰_시험은_그_기간에_그것만():
    out = arrange([MONTHLY("기사X", "기사"), MONTHLY("A")], {}, TODAY)
    w = _windows(out)
    big, small = w["기사X"], w["A"]
    assert small[1] < big[0] or small[0] > big[1]        # 겹치지 않는다
    assert next(p for p in out["placed"] if p["name"] == "기사X")["load"] == "heavy"


def test_기본_자격은_큰_시험과도_병행():
    hist = {**MONTHLY("한국사능력검정시험", None), "basic": True}
    out = arrange([MONTHLY("기사X", "기사"), hist], {}, TODAY)
    p = {x["name"]: x for x in out["placed"]}
    assert p["한국사능력검정시험"]["load"] == "basic" and "기사X" in p["한국사능력검정시험"]["parallel_with"]


def test_동시_공부_수를_말하면_그_수만_본다():
    seq = arrange([MONTHLY("A"), MONTHLY("B")], {"max_parallel": 1}, TODAY)
    w = _windows(seq)
    assert w["B"][0] > w["A"][1]
    both = arrange([MONTHLY("기사X", "기사"), MONTHLY("기사Y", "기사", day=20)], {"max_parallel": 2}, TODAY)
    assert ov(_windows(both)["기사X"], _windows(both)["기사Y"])  # 사용자가 2개라고 하면 큰 시험도 함께
