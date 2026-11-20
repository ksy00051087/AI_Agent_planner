"""F3012 — 발행은 구독자에 의존하지 않는다."""

from app.events import Emitter, EventBus


def test_구독자가_없어도_발행된다():
    em = Emitter(EventBus(), "s1")
    em.node_enter("analyze")
    em.node_exit("analyze", intent="chat")
    assert [e["type"] for e in em.events] == ["node_enter", "node_exit"]
    assert [e["seq"] for e in em.events] == [1, 2]
    assert all(e["session_id"] == "s1" and e["run_id"] == em.run_id for e in em.events)


def test_구독자가_예외를_던져도_발행자는_계속():
    bus = EventBus()
    got = []

    def broken(e):
        raise RuntimeError("로깅 Agent 고장")

    bus.subscribe(broken)
    bus.subscribe(got.append)
    em = Emitter(bus, "s1")
    em.tool_call("execute", "search_books", {"qualification_name": "x"})
    assert len(got) == 1 and got[0]["tool"] == "search_books"


def test_구독_해제():
    bus = EventBus()
    got = []
    off = bus.subscribe(got.append)
    Emitter(bus, "s1").node_enter("a")
    off()
    Emitter(bus, "s1").node_enter("a")
    assert len(got) == 1 and bus.subscriber_count() == 0


def test_tool_result_는_원본_응답을_싣지_않는다():
    em = Emitter(None, "s1")
    e = em.tool_result("execute", "get_exam_schedule",
                       {"ok": False, "error": {"code": "NO_DATA", "message": "없음"}}, duration_ms=12)
    assert e["ok"] is False and e["code"] == "NO_DATA" and e["duration_ms"] == 12
    assert "data" not in e and "result" not in e
