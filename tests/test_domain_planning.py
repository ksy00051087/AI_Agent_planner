from datetime import date

from app.domain.planning import find_overlaps, judge_round, latest_start, prep_weeks_for
from app.domain.schedule import normalize_round


class TestPrepWeeks:
    def test_사용자값이_우선(self):
        assert prep_weeks_for("기사", 4) == (4, "사용자 입력")

    def test_등급별_기준값_산업기사는_기사보다_먼저_매칭(self):
        assert prep_weeks_for("산업기사")[0] == 8
        assert prep_weeks_for("기사")[0] == 10
        assert "서비스 기준값" in prep_weeks_for("기사")[1]

    def test_모르는_등급은_기본값(self):
        weeks, basis = prep_weeks_for(None)
        assert weeks == 10 and "등급 미상" in basis


def test_latest_start_역산():
    assert latest_start(date(2027, 3, 7), 8) == date(2027, 1, 10)


class TestJudgeRound:
    r = normalize_round("2027 1회", {"written_reg_end": "20270115", "written_exam_start": "20270130"})

    def test_충분하면_통과_시작일_제시(self):
        out = judge_round(self.r, date(2026, 11, 1), 10)
        assert out["ok"] and out["latest_start"] == date(2026, 11, 21)

    def test_접수마감_지남(self):
        assert judge_round(self.r, date(2027, 1, 16), 2)["reason"] == "REGISTRATION_CLOSED"

    def test_준비기간_부족은_부족일수와_함께(self):
        out = judge_round(self.r, date(2026, 12, 20), 10)
        assert out["reason"] == "NOT_ENOUGH_TIME"
        assert "29일 부족" in out["detail"]

    def test_날짜가_비면_판단하지_않음(self):
        empty = normalize_round("x", {})
        assert judge_round(empty, date(2026, 11, 1), 10)["reason"] == "UNJUDGEABLE"


class TestFindOverlaps:
    d = date(2027, 3, 7)
    plans = [
        {"plan_id": 1, "plan_date": d, "start_time": "09:00", "end_time": "11:30"},
        {"plan_id": 2, "plan_date": d, "start_time": "13:00", "end_time": "15:00"},
        {"plan_id": 3, "plan_date": date(2027, 3, 8), "start_time": "09:00", "end_time": "11:00"},
        {"plan_id": 4, "plan_date": d, "start_time": None, "end_time": None},
    ]

    def ids(self, new):
        return [p["plan_id"] for p in find_overlaps(new, self.plans)]

    def test_시간이_겹치면_알림(self):
        assert self.ids({"plan_date": self.d, "start_time": "11:00", "end_time": "12:00"}) == [1, 4]

    def test_끝과_시작이_맞닿으면_안겹침(self):
        assert self.ids({"plan_date": self.d, "start_time": "11:30", "end_time": "13:00"}) == [4]

    def test_다른_날짜는_안겹침(self):
        assert self.ids({"plan_date": date(2027, 3, 9), "start_time": "09:00", "end_time": "18:00"}) == []

    def test_시각을_모르면_같은날_전부_겹침으로(self):
        assert self.ids({"plan_date": self.d, "start_time": None, "end_time": None}) == [1, 2, 4]

    def test_수정할때_자기자신은_제외(self):
        assert self.ids({"plan_id": 1, "plan_date": self.d, "start_time": "09:00", "end_time": "10:00"}) == [4]


def test_자격명_맞추기():
    from app.domain.names import name_matches, strip_suffix
    assert strip_suffix("간호사 국가시험") == "간호사" and strip_suffix("한국사능력검정시험") == "한국사능력검정"
    assert name_matches("간호사 국가시험", "간호사") and name_matches("전기기사", "전기기사")
    assert name_matches("SQLD", "SQL 개발자(SQLD)") and not name_matches("기", "전기기사")
    from app.domain.names import target_found
    assert target_found("9급 공무원", ["9급공개경쟁채용시험"], ["9급"])
    assert not target_found("투자자산운용사", ["전기기사"], ["금융"])
