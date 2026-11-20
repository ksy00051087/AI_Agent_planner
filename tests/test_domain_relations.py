"""루트 선정과 관계 분석 — 많이 따는 루트 먼저, 그다음 상하위 · 보완 관계."""

from app.domain.relations import chain_of, filter_by_tracks, held_options, select_route, track_group, track_options


def q(name, grade=None, acq=None, field=None, sub=None, source="qnet", qid=None):
    return {"qual_id": qid or name, "name": name, "grade": grade, "field": field, "sub_field": sub, "source": source,
            "popularity": {"year": 2025, "acquired": acq, "basis": f"합격자 {acq}명"} if acq else None}


IT = [q("정보처리기사", "기사", 16326, sub="정보기술"), q("정보처리산업기사", "산업기사", 2521, sub="정보기술"),
      q("사무자동화산업기사", "산업기사", 5546, sub="정보기술"), q("프로그래밍기능사", "기능사", 4918, sub="정보기술"),
      q("정보관리기술사", "기술사", 41, sub="정보기술"), q("컴퓨터시스템응용기술사", "기술사", 7, sub="정보기술"),
      q("SQL 개발자(SQLD)", field="정보통신", sub="데이터", source="kdata"),
      q("SQL 전문가(SQLP)", field="정보통신", sub="데이터", source="kdata"),
      q("데이터분석 준전문가(ADsP)", field="정보통신", sub="데이터", source="kdata")]
LADDERS = [["SQL 개발자(SQLD)", "SQL 전문가(SQLP)"]]


def names(out):
    return [x["name"] for x in out["route"]]


def test_계열_판별():
    assert chain_of(q("전기기능사", "기능사"))[::2] == ("전기", "direct")
    assert chain_of(q("사회조사분석사1급", "기사"))[0] == "사회조사분석사"
    assert chain_of(q("1급 응급구조사"))[0] == chain_of(q("2급 응급구조사"))[0] == "응급구조사"
    assert chain_of(q("SQL 전문가(SQLP)"), LADDERS)[2] == "experience"


def test_IT_상위는_하위를_대체_보완은_유지_전문가급은_다음단계():
    out = select_route(IT, {"field": "정보기술"}, ladders=LADDERS, expert={"SQL 전문가(SQLP)"},
                       related_fields={"정보기술", "데이터"})
    r = names(out)
    assert r[0] == "정보처리기사"                                     # 인기 1위
    assert "정보처리산업기사" not in r                                  # 상위(정보처리기사)에 포함
    assert {"사무자동화산업기사", "프로그래밍기능사"} <= set(r)          # 같은 분야 다른 종목 = 보완
    assert {"SQL 개발자(SQLD)", "데이터분석 준전문가(ADsP)"} <= set(r)   # 가까운 분야 보완 (통계 없는 출처)
    assert "SQL 전문가(SQLP)" not in r and "정보관리기술사" not in r    # 경력 · 전문가급은 자동 루트 밖
    assert out["superseded"] == [{"name": "정보처리산업기사", "qual_id": "정보처리산업기사", "by": "정보처리기사"}]
    assert {"name": "SQL 전문가(SQLP)", "after": "SQL 개발자(SQLD)"} in out["next_steps"]


def test_조리처럼_상위가_드물면_기능사들이_루트():
    cook = [q("한식조리기능사", "기능사", 14251), q("양식조리기능사", "기능사", 6250), q("조주기능사", "기능사", 3518),
            q("한식조리산업기사", "산업기사", 146), q("복어조리기능사", "기능사", 344)]
    out = select_route(cook, {"field": "조리"})
    assert names(out) == ["한식조리기능사", "양식조리기능사", "조주기능사"]   # 많이 따는 순
    assert set(out["not_popular"]) == {"한식조리산업기사", "복어조리기능사"}   # 10% 미만
    assert out["superseded"] == []                                          # 산업기사가 루트에 없으니 기능사 유지


def test_1급은_경력이_필요해_2급만_루트():
    out = select_route([q("임상심리사2급", "기사", 3739), q("임상심리사1급", "기사", 1102)], {"field": "보건.의료"})
    assert names(out) == ["임상심리사2급"] and out["next_steps"][0]["name"] == "임상심리사1급"


def test_직접_지정하면_인기가_낮아도_넣고_상위로_대체하지_않는다():
    out = select_route([q("정보처리기사", "기사", 16326), q("정보처리산업기사", "산업기사", 2521)],
                       {"targets": ["정보처리산업기사", "정보처리기사"]})
    assert set(names(out)) == {"정보처리산업기사", "정보처리기사"} and out["superseded"] == []
    out = select_route([q("정보관리기술사", "기술사", 41)], {"grades": ["기술사"], "field": "정보기술"})
    assert names(out) == ["정보관리기술사"]


def test_말한_분야가_가까운_분야보다_먼저_세부분야가_맞으면_그_안에서만():
    data = select_route(IT, {"field": "데이터"}, ladders=LADDERS, expert={"SQL 전문가(SQLP)"},
                        related_fields={"데이터", "정보기술"})
    r = names(data)
    assert r[:2] == ["SQL 개발자(SQLD)", "데이터분석 준전문가(ADsP)"]   # 말한 분야(데이터)가 먼저
    assert r[2] == "정보처리기사" and len([x for x in r if x in {"정보처리기사", "사무자동화산업기사", "프로그래밍기능사"}]) <= 3
    elec = [q("전기기사", "기사", 13918, "전기.전자", "전기"), q("전기공사기사", "기사", 4663, "전기.전자", "전기"),
            q("3D프린터운용기능사", "기능사", 3192, "전기.전자", "전자")]
    assert names(select_route(elec, {"field": "전기"})) == ["전기기사", "전기공사기사"]   # 전자는 다른 세부 분야


def test_보유한_경력사다리_아래단계는_빼고_바로_위_단계를_루트로():
    out = select_route(IT, {"field": "정보기술", "held": ["SQLD"]}, ladders=LADDERS, expert={"SQL 전문가(SQLP)"},
                       related_fields={"정보기술", "데이터"})
    r = names(out)
    assert "SQL 개발자(SQLD)" not in r and "SQL 전문가(SQLP)" in r
    sqlp = next(x for x in out["route"] if x["name"] == "SQL 전문가(SQLP)")
    assert "보유한 SQL 개발자(SQLD) 의 다음 단계" in sqlp["route_reason"]
    assert not any(n["name"] == "SQL 전문가(SQLP)" for n in out["next_steps"])


def test_보유한_direct_상위는_같은_계열_전부를_덮고_기술사는_올리지_않는다():
    out = select_route(IT, {"field": "정보기술", "held": ["정보처리기사"]}, ladders=LADDERS,
                       related_fields={"정보기술", "데이터"})
    r = names(out)
    assert "정보처리기사" not in r and "정보처리산업기사" not in r
    assert {h["name"] for h in out["held"]} == {"정보처리기사", "정보처리산업기사"}


def test_보유_패널_선택지는_계열별로_낮은_단계부터():
    out = select_route(IT, {"field": "정보기술"}, ladders=LADDERS, expert={"SQL 전문가(SQLP)"},
                       related_fields={"정보기술", "데이터"})
    opts = held_options(IT, out, LADDERS)
    chains = {g["chain"]: [i["name"] for i in g["items"]] for g in opts if g["chain"]}
    assert chains["정보처리"] == ["정보처리산업기사", "정보처리기사"]
    assert chains["ladder:SQL 개발자(SQLD)"] == ["SQL 개발자(SQLD)", "SQL 전문가(SQLP)"]


def test_급수를_말하면_그_급수_종목만():
    civil = [q("9급공개경쟁채용시험", sub="공무원", source="gosi"), q("지역인재선발시험9급", sub="공무원", source="gosi"),
             q("7급공개경쟁채용시험", sub="공무원", source="gosi"), q("5급(행정)공개경쟁채용시험", sub="공무원", source="gosi")]
    r = names(select_route(civil, {"field": "공무원", "keywords": ["9급"]}))
    assert set(r) == {"9급공개경쟁채용시험", "지역인재선발시험9급"}
    assert len(names(select_route(civil, {"field": "공무원"}))) == 4     # 급수를 말하지 않으면 그대로


IT_TRACKS = [{"fields": ["정보통신", "정보기술", "데이터"], "items": [
    {"name": "개발", "match": ["정보처리", "프로그래밍"]},
    {"name": "데이터", "match": ["SQL", "데이터"]},
    {"name": "보안", "match": ["정보보안"]}]},
    {"fields": ["조리"], "items": [{"name": "한식", "match": ["한식"]}]}]


def test_진로_묶음은_분야로_고르고_없으면_후보의_세부분야로():
    assert track_group(IT_TRACKS, "정보기술", IT)["fields"][0] == "정보통신"
    assert track_group(IT_TRACKS, None, IT)["items"][0]["name"] == "개발"      # 후보 세부분야(정보기술 · 데이터)로
    assert track_group(IT_TRACKS, "조리", IT)["items"][0]["name"] == "한식"
    assert track_group([], "정보기술", IT) is None


def test_진로_선택지는_걸리는_자격이_있는_것만_대표_자격과_함께():
    opts = track_options(IT_TRACKS[0], IT, ["정보처리기사", "SQL 개발자(SQLD)"])
    assert [o["name"] for o in opts] == ["개발", "데이터"]                    # 정보보안 자격이 없어 '보안' 은 뺌
    assert opts[0]["examples"][0] == "정보처리기사" and opts[1]["examples"][0] == "SQL 개발자(SQLD)"


def test_고른_진로의_자격만_남기고_못_찾으면_그대로():
    kept, used = filter_by_tracks(IT, IT_TRACKS[0], ["데이터"])
    assert used == ["데이터"] and {q["name"] for q in kept} == {"SQL 개발자(SQLD)", "SQL 전문가(SQLP)", "데이터분석 준전문가(ADsP)"}
    assert filter_by_tracks(IT, IT_TRACKS[0], []) == (IT, [])
    assert filter_by_tracks(IT, IT_TRACKS[0], ["보안"]) == (IT, [])


def test_특례_시험은_말했을_때만():
    health = [q("물리치료사", sub="보건.의료", source="kuksiwon"), q("2급 언어재활사 특례", sub="보건.의료", source="kuksiwon")]
    assert names(select_route(health, {"field": "보건.의료"})) == ["물리치료사"]
    assert "2급 언어재활사 특례" in names(select_route(health, {"field": "보건.의료", "keywords": ["특례"]}))



def test_직접_골라_넣은_자격에는_인기_순위를_붙이지_않는다():
    robot = [q("3D프린터운용기능사", "기능사", 3192, sub="전기"), q("로봇소프트웨어개발기사", "기사", 11, sub="전기")]
    out = select_route(robot, {"field": "전기"})
    assert names(out) == ["3D프린터운용기능사"] and out["extras"][0]["name"] == "로봇소프트웨어개발기사"   # 응시자 적음 → 기본 계획 밖
    added = select_route(robot, {"field": "전기", "include": ["로봇소프트웨어개발기사"]})
    r = next(x for x in added["route"] if x["name"] == "로봇소프트웨어개발기사")["route_reason"]
    assert "합격자 11명" in r and "인기" not in r


def test_후기_함께_언급은_계획에_든_자격끼리_기준을_넘는_것만():
    from app.domain.relations import co_mentions
    co = {"전기기사": {"posts": 30, "with": {"전기공사기사": 12, "소방설비기사(전기분야)": 9, "전기기능사": 2}},
          "전기공사기사": {"posts": 20, "with": {"전기기사": 15}}}
    out = co_mentions(["전기기사", "전기공사기사", "전기기능사"], co)
    assert out == [{"a": "전기기사", "b": "전기공사기사", "count": 12, "posts": 30}]   # 계획 밖(소방) · 2건은 뺌, 같은 쌍은 한 번
    assert co_mentions(["전기기사"], {}) == []
