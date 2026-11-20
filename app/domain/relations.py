"""루트 선정과 자격 관계 분석 (F3008) — 순수 함수.

1순위  루트: 사람들이 많이 따는 자격 — 같은 후보 묶음에서 최근 최종 합격자 수가 최다 종목의 ROUTE_SHARE 이상
2순위  관계 분석
       · 상하위(같은 계열, 상위가 학력만으로 응시 가능한 사다리: 기능사 < 산업기사 < 기사)
         → 상위만 남기고 하위는 SUPERSEDED (상위 자격을 따면 하위는 필요 없다)
       · 상위가 실무 경력을 요구하는 사다리(2급 < 1급, 준전문가 < 전문가, 기능장 · 기술사)
         → 자동 루트에는 하위만 (상위는 '다음 단계' 로만 안내)
       · 같은 분야의 다른 종목 → 보완 관계로 남긴다
"""

from __future__ import annotations

import re

from app.domain.names import name_matches

ROUTE_SHARE = 0.10          # 최다 종목 합격자 수의 10% 이상이면 '많이 따는' 루트
MAX_ROUTE = 8
MAX_NO_STAT = 4             # 취득자 통계가 없는 출처(데이터진흥원 · 국시원 …)에서 보완으로 넣을 수
DIRECT_LADDER = ("기능사", "산업기사", "기사")        # 상위가 학력만으로도 응시 가능 → 상위가 하위를 대체
EXPERT_GRADES = ("기능장", "기술사")
_KUP = re.compile(r"\s*([123])\s*급")


def _acq(q: dict) -> int:
    return ((q.get("popularity") or {}).get("acquired")) or 0


def chain_of(q: dict, ladders: list[list[str]] | None = None) -> tuple[str, int, str]:
    """(계열 이름, 계열 안 단계(클수록 상위), 사다리 종류 direct|experience|none)"""
    name, grade = q["name"], q.get("grade") or ""
    for lad in ladders or []:
        if name in lad:
            return "ladder:" + lad[0], lad.index(name), "experience"
    if grade in (*DIRECT_LADDER, *EXPERT_GRADES) and name.endswith(grade):
        stem = name[: -len(grade)]
        order = (*DIRECT_LADDER, *EXPERT_GRADES).index(grade)
        return stem, order, "direct" if grade in DIRECT_LADDER else "experience"
    m = _KUP.search(name)
    if m:   # 사회조사분석사2급 · 1급 언어재활사 — 숫자가 작을수록 상위, 상위는 경력 요구
        return _KUP.sub("", name).strip(), 3 - int(m.group(1)), "experience"
    return name, 0, "none"


def select_route(cands: list[dict], conditions: dict, *, ladders: list[list[str]] | None = None,
                 expert: set[str] | None = None, related_fields: set[str] | None = None) -> dict:
    """반환 {"route": [후보 + route_reason · chain · ladder], "superseded": [{"name", "by"}],
             "next_steps": [{"name", "after"}], "not_popular": [이름], "held": [{"name", "by"}]}

    conditions["held"]    이미 가진 자격 — 그 자격과 같은 계열의 그 단계 이하는 루트에서 뺀다.
                          경력 사다리(SQLD → SQLP)는 가진 단계의 바로 위 단계를 루트로 올린다.
    conditions["include"] 같이 준비하기로 고른 기본 자격 (토익 · 한국사 …) — 분야 루트 뒤에 붙인다."""
    targets = conditions.get("targets") or []
    held_names = conditions.get("held") or []
    include = conditions.get("include") or []
    keywords = [*(conditions.get("keywords") or []), *include]
    wanted_grades = set(conditions.get("grades") or [])
    expert = expert or set()
    related_fields = related_fields or set()

    def said(q):  # 사용자가 이름 · 낱말로 직접 말한 자격
        return any(t and (t in q["name"] or q["name"] in t) for t in targets) or any(k and k in q["name"] for k in keywords)

    # 계열 묶기 (같은 계열 전체 사다리는 안내용으로 남긴다)
    info = {q["qual_id"]: chain_of(q, ladders) for q in cands}
    chains: dict[str, list[dict]] = {}
    for q in cands:
        chains.setdefault(info[q["qual_id"]][0], []).append(q)
    for v in chains.values():
        v.sort(key=lambda x: info[x["qual_id"]][1])

    # ⓪ 이미 가진 자격 — 그 단계 이하는 뺀다. 경력 사다리는 바로 위 단계를 '다음 단계' 로 루트에 올린다
    held_ids = {q["qual_id"] for q in cands if any(name_matches(h, q["name"]) for h in held_names)}
    covered: dict[str, str] = {}          # 뺀 qual_id → 가진 자격 이름
    unlocked: dict[str, str] = {}         # 올린 qual_id → 바로 아래 가진 자격 이름
    for q in cands:
        if q["qual_id"] not in held_ids:
            continue
        stem, step, kind = info[q["qual_id"]]
        for x in chains[stem]:
            if info[x["qual_id"]][1] <= step and (x["qual_id"] not in covered or x["qual_id"] == q["qual_id"]):
                covered[x["qual_id"]] = q["name"]
        upper = [x for x in chains[stem] if info[x["qual_id"]][1] > step]
        if upper and kind == "experience" and upper[0].get("grade") not in EXPERT_GRADES:
            unlocked[upper[0]["qual_id"]] = q["name"]
    for qid in covered:
        unlocked.pop(qid, None)
    held = [{"name": q["name"], "qual_id": q["qual_id"], "by": covered[q["qual_id"]]}
            for q in cands if q["qual_id"] in covered]

    # ① 경력이 필요한 상위 단계는 자동 루트에서 뺀다 (원하면 넣는다)
    next_steps, pool = [], []
    for q in cands:
        if q["qual_id"] in covered:
            continue
        if "특례" in q["name"] and not said(q):   # 특례 시험은 정해진 대상자용 — 말했을 때만
            continue
        stem, step, kind = info[q["qual_id"]]
        lower = [x for x in chains[stem] if info[x["qual_id"]][1] < step]
        is_expert = (q.get("grade") in EXPERT_GRADES or q["name"] in expert
                     or (kind == "experience" and lower)) and q["qual_id"] not in unlocked
        if is_expert and not said(q) and q.get("grade") not in wanted_grades:
            if lower:
                next_steps.append({"name": q["name"], "after": lower[-1]["name"]})
            continue
        pool.append(q)

    # ② 루트 — 말한 분야(primary) → 가까운 분야(related, 보완) 순. 그 밖은 사용자가 말했을 때만
    field = conditions.get("field")

    def group(q) -> int:
        if not field:
            return 0
        if field in (q.get("field"), q.get("sub_field")):
            return 0
        if q.get("field") in related_fields or q.get("sub_field") in related_fields:
            return 1
        return 2

    # '9급 공무원' · '2급' 처럼 급수를 말했으면 그 급수인 종목만 (분야 검색으로 5급 · 7급까지 딸려 오지 않게)
    levels = [k for k in keywords if re.fullmatch(r"\d\s*급", k or "")]
    if levels and any(any(lv in q["name"] for lv in levels) for q in pool):
        pool = [q for q in pool if said(q) and any(lv in q["name"] for lv in levels)
                or any(name_matches(i, q["name"]) for i in include)]

    if field and not any(group(q) == 0 for q in pool):
        group = lambda q: 0  # noqa: E731  분야 이름이 정확히 맞는 종목이 없으면 검색된 전부를 그 분야로 본다

    route, not_popular = [], []
    for g in (0, 1):
        members = [q for q in pool if group(q) == g and not said(q) and q["qual_id"] not in unlocked]
        top = max((_acq(q) for q in members), default=0)
        popular = [q for q in members if _acq(q) and _acq(q) >= top * ROUTE_SHARE]
        # 큐넷 합격률 통계는 시행된 종목을 모두 담는다 → 큐넷인데 통계가 없으면 거의 치르지 않는 종목
        not_popular += [q for q in members if (_acq(q) and _acq(q) < top * ROUTE_SHARE)
                        or (not _acq(q) and q.get("source") == "qnet")]
        no_stat = [q for q in members if not _acq(q) and q.get("source") != "qnet"]
        if g == 1:
            popular = sorted(popular, key=lambda x: -_acq(x))[:3]   # 가까운 분야는 보완이라 3개까지
        # 진로를 골랐으면 후보가 이미 좁혀져 있어 통계 없는 자격을 더 넣는다
        route += popular + no_stat[:MAX_NO_STAT + (2 if conditions.get("tracks") else 0)]
    route += [q for q in pool if said(q) or q["qual_id"] in unlocked]
    extras = sorted(not_popular, key=lambda x: -_acq(x))   # 인기 루트로 안 될 때 재계획 대안
    not_popular = [q["name"] for q in not_popular]

    # ③ 상하위: 학력만으로 갈 수 있는 사다리(direct)는 상위가 있으면 하위를 뺀다
    superseded, kept = [], []
    by_chain: dict[str, list[dict]] = {}
    for q in route:
        by_chain.setdefault(info[q["qual_id"]][0], []).append(q)
    for stem, qs in by_chain.items():
        qs.sort(key=lambda x: info[x["qual_id"]][1])
        top_q = qs[-1]
        for q in qs[:-1]:
            if info[q["qual_id"]][2] == "direct" and not any(t and t in q["name"] for t in targets):
                superseded.append({"name": q["name"], "qual_id": q["qual_id"], "by": top_q["name"]})
            else:
                kept.append(q)
        kept.append(top_q)

    # ④ 순서: 지정 자격 → 말한 낱말 → 말한 분야(인기순 → 통계 없음) → 가까운 분야 보완, 같은 계열은 낮은 단계 먼저
    def picked(q):  # 같이 준비하기로 고른 기본 자격 (분야 루트 뒤에 둔다)
        return any(name_matches(i, q["name"]) for i in include) and not any(t and t in q["name"] for t in targets)

    def key(q):
        tpos = next((i for i, t in enumerate(targets) if t and (t in q["name"] or q["name"] in t)), len(targets))
        stem = info[q["qual_id"]][0]
        chain_pop = max(_acq(x) for x in by_chain.get(stem, [q]))
        return (1 if picked(q) else 0, tpos, 0 if said(q) else 1, group(q), 0 if chain_pop else 1, -chain_pop, stem, info[q["qual_id"]][1])

    kept.sort(key=key)
    rank_of_pop = {}
    for g in (0, 1, 2):
        for i, x in enumerate(sorted([x for x in kept if _acq(x) and group(x) == g], key=lambda x: -_acq(x))):
            rank_of_pop[x["qual_id"]] = i + 1
    out = []
    main = [q for q in kept if not picked(q)]
    chosen = main[:MAX_ROUTE] + [q for q in kept if picked(q)]
    for i, q in enumerate(chosen):
        stem = info[q["qual_id"]][0]
        lad = [x["name"] for x in chains[stem]]
        reasons = []
        if any(t and (t in q["name"] or q["name"] in t) for t in targets):
            reasons.append("직접 지정한 자격")
        elif picked(q):
            reasons.append("직접 골라 넣은 자격")
        elif q["qual_id"] in unlocked:
            reasons.append(f"보유한 {unlocked[q['qual_id']]} 의 다음 단계 (응시자격은 시행기관에서 확인)")
        elif said(q):
            reasons.append("말씀하신 자격")
        where = "이 분야" if group(q) == 0 else "가까운 분야"
        if q.get("popularity"):
            # 직접 골라 넣은 자격은 인기 순위를 붙이지 않는다 (응시자가 적어도 순위가 높아 보이지 않게)
            rank = "" if picked(q) else f" · {where} 인기 {rank_of_pop[q['qual_id']]}위"
            reasons.append(f"{q['popularity']['basis']}{rank}")
        elif not said(q) and q["qual_id"] not in unlocked:
            reasons.append(f"{where} 자격 (취득자 통계 없음 — 인기 순위 대신 분야로 넣음)")
        if group(q) == 1 and not picked(q):
            reasons.append("말씀하신 분야를 보완")
        sup = [s["name"] for s in superseded if s["by"] == q["name"]]
        if sup:
            reasons.append(f"상위 자격이라 {', '.join(sup)} 는 따로 딸 필요 없음")
        out.append({**q, "path_rank": i, "chain": stem if len(lad) > 1 else None,
                    "ladder": lad if len(lad) > 1 else None, "route_reason": " · ".join(reasons)})
    overflow = [q["name"] for q in main[MAX_ROUTE:]]
    extra_out = [{**q, "path_rank": len(out) + i, "chain": None, "ladder": None,
                  "route_reason": "인기 루트 밖 — 재계획 대안 (최근 합격자가 적거나 통계 없음)"}
                 for i, q in enumerate(extras) if q["qual_id"] not in {x["qual_id"] for x in out}]
    held_set = {h["name"] for h in held}
    return {"route": out, "extras": extra_out, "superseded": superseded,
            "next_steps": [n for n in next_steps if n["name"] not in held_set], "not_popular": not_popular,
            "overflow": overflow, "held": held}


def held_options(cands: list[dict], out: dict, ladders: list[list[str]] | None = None, limit: int = 18) -> list[dict]:
    """'지금 가진 자격' 고르기 패널의 분야 선택지 — 루트 · 상위에 포함 · 다음 단계에 나온 자격을 계열별로.
    반환 [{"chain": 계열 이름 | None, "items": [{"name", "grade"}] (낮은 단계 먼저)}]"""
    names = []
    for q in out["route"]:
        names += [*(q.get("ladder") or []), q["name"]]
    names += [x["name"] for x in out["superseded"]] + [x["name"] for x in out["next_steps"]]
    names += [x["name"] for x in out.get("held") or []]
    by_name = {q["name"]: q for q in cands}
    groups: dict[str, list[tuple[int, dict]]] = {}
    seen = set()
    for n in names:
        q = by_name.get(n)
        if not q or n in seen:
            continue
        seen.add(n)
        stem, step, _ = chain_of(q, ladders)
        groups.setdefault(stem, []).append((step, {"name": n, "grade": q.get("grade")}))
    result, count = [], 0
    for stem, items in groups.items():
        if count >= limit:
            break
        items.sort(key=lambda x: x[0])
        result.append({"chain": stem if len(items) > 1 else None, "items": [x[1] for x in items]})
        count += len(items)
    return result


# ── 진로 방향 (직업군) — 계획 전에 '어느 쪽으로 갈지' 묻고, 고른 쪽 자격만 루트로 ─────────
def track_group(groups: list[dict], field: str | None, cands: list[dict]) -> dict | None:
    """요청 분야에 맞는 직업군 묶음. 분야 이름이 없으면 후보들의 분야 · 세부분야로 가장 많이 걸리는 묶음."""
    if not groups:
        return None
    if field:
        hit = next((g for g in groups if field in g.get("fields", [])), None)
        if hit:
            return hit
    def score(g):
        fs = set(g.get("fields", []))
        return sum(1 for q in cands if q.get("field") in fs or q.get("sub_field") in fs)
    best = max(groups, key=score)
    return best if score(best) else None


def in_track(item: dict, name: str) -> bool:
    return any(m and m in name for m in item.get("match", []))


def track_options(group: dict | None, cands: list[dict], route_names: list[str], limit: int = 3) -> list[dict]:
    """[{"name", "examples": [대표 자격 이름], "note"?}] — 후보에 걸리는 자격이 없는 직업군은 뺀다.
    대표 자격은 루트에 든 것 먼저, 그다음 취득자 많은 순."""
    if not group:
        return []
    order = {n: i for i, n in enumerate(route_names)}
    out = []
    for item in group.get("items", []):
        hits = [q for q in cands if in_track(item, q["name"])]
        if not hits:
            continue
        hits.sort(key=lambda q: (order.get(q["name"], 10**6), -_acq(q), q["name"]))
        out.append({"name": item["name"], "examples": [q["name"] for q in hits[:limit]],
                    **({"note": item["note"]} if item.get("note") else {})})
    return out


def filter_by_tracks(cands: list[dict], group: dict | None, chosen: list[str]) -> tuple[list[dict], list[str]]:
    """(고른 직업군에 드는 후보, 실제로 적용한 직업군). 고른 것이 없거나 걸리는 후보가 없으면 그대로 돌려준다."""
    items = [i for i in (group or {}).get("items", []) if i["name"] in chosen]
    if not items:
        return cands, []
    kept = [q for q in cands if any(in_track(i, q["name"]) for i in items)]
    if not kept:
        return cands, []
    return kept, [i["name"] for i in items]


# ── 블로그 후기에서 함께 언급 (비공식 근거) — 루트를 정하는 데 쓰지 않고 보여 주기만 한다 ─────────
def co_mentions(names: list[str], co: dict, *, min_count: int = 3, min_ratio: float = 0.1) -> list[dict]:
    """계획에 든 자격 둘이 '{A} 다음 자격증' 블로그 후기에서 함께 나온 횟수.
    반환 [{"a", "b", "count", "posts"}] — count 가 min_count 이상이고 A 후기의 min_ratio 이상인 쌍만, 많은 순"""
    out, seen = [], set()
    for a in names:
        info = co.get(a) or {}
        posts = info.get("posts") or 0
        if not posts:
            continue
        for b, n in (info.get("with") or {}).items():
            if b == a or b not in names or frozenset((a, b)) in seen:
                continue
            if n >= min_count and n / posts >= min_ratio:
                seen.add(frozenset((a, b)))
                out.append({"a": a, "b": b, "count": n, "posts": posts})
    return sorted(out, key=lambda x: -x["count"])
