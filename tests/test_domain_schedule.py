from datetime import date

from app.domain.schedule import normalize_round, parse_fee, parse_ymd, shift_year, upcoming_rounds


def rnd(name, reg_end, exam, **more):
    return normalize_round(name, {"written_reg_end": reg_end, "written_exam_start": exam, **more})


class TestParseYmd:
    def test_정상(self):
        assert parse_ymd("20260130") == date(2026, 1, 30)

    def test_빈값_마스킹_잘못된날짜는_None(self):
        for v in (None, "", "XXXXXXXX", "2026013", "20261340", "abcdefgh"):
            assert parse_ymd(v) is None


def test_shift_year_윤일은_28일로():
    assert shift_year(date(2028, 2, 29), 1) == date(2029, 2, 28)
    assert shift_year(date(2026, 3, 7), 1) == date(2027, 3, 7)


class TestNormalizeRound:
    def test_필수값이_있으면_판단가능(self):
        r = rnd("1회", "20260115", "20260130")
        assert r["judgeable"] and r["missing"] == []
        assert r["dates"]["written_exam_start"] == date(2026, 1, 30)

    def test_시험일이_비면_채우지_않고_판단불가(self):
        r = rnd("2027 사회복지사", "20270101", None)
        assert not r["judgeable"]
        assert r["missing"] == ["written_exam_start"]
        assert r["dates"]["written_exam_start"] is None  # 0 이나 추측값으로 채우지 않는다


class TestUpcomingRounds:
    rounds = [rnd("2026 1회", "20260115", "20260130"),
              rnd("2026 2회", "20260423", "20260509"),
              rnd("2026 3회", "20260723", "20260807")]

    def test_공고된_회차가_먼저_그_뒤에_다음해_추정이_이어진다(self):
        out = upcoming_rounds(self.rounds, date(2026, 4, 1))
        assert [r["name"] for r in out[:2]] == ["2026 2회", "2026 3회"]
        assert not any(r["estimated"] for r in out[:2])
        assert all(r["estimated"] for r in out[2:]) and out[2]["dates"]["written_exam_start"] == date(2027, 1, 30)

    def test_다음해_미공고면_1년_더해_추정_2년까지(self):
        out = upcoming_rounds(self.rounds, date(2026, 11, 18))
        assert all(r["estimated"] for r in out)
        assert [r["dates"]["written_exam_start"].year for r in out] == [2027] * 3 + [2028] * 3
        assert "2027년 일정 미공고" in out[0]["basis"]

    def test_추정해도_이미_지난_회차는_빼고(self):
        out = upcoming_rounds(self.rounds, date(2027, 3, 1))
        assert [r["dates"]["written_exam_start"] for r in out][:2] == [date(2027, 5, 9), date(2027, 8, 7)]

    def test_상시시험_올해_남은_회차_뒤로_내년이_이어진다(self):
        rounds = [rnd(f"2026 {m}월", f"2026{m:02d}01", f"2026{m:02d}10") for m in range(1, 13)]
        out = upcoming_rounds(rounds, date(2026, 11, 18))
        # 11월 회차는 접수 마감(11-01)이 지났고, 12월 실제 회차 다음에 2027년 1월 추정 회차
        assert out[0]["dates"]["written_exam_start"] == date(2026, 12, 10) and not out[0]["estimated"]
        assert out[1]["dates"]["written_exam_start"] == date(2027, 1, 10) and out[1]["estimated"]

    def test_판단불가_회차는_추정에_쓰지_않는다(self):
        assert upcoming_rounds([rnd("x", None, None)], date(2026, 11, 18)) == []


class TestParseFee:
    def test_큐넷_형식(self):
        assert parse_fee("1차 : 19400, 2차 : 22600") == {"1차": 19400, "2차": 22600}

    def test_필기실기_쉼표금액(self):
        assert parse_fee("필기: 19,400원 / 실기: 22,600원") == {"필기": 19400, "실기": 22600}

    def test_못읽으면_None(self):
        assert parse_fee(None) is None
        assert parse_fee("수수료 안내 참조") is None
