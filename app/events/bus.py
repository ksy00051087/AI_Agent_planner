"""실행 이벤트 발행 · 구독 (F3012).

- 발행하는 쪽(메인 Agent)은 누가 구독하는지 모른다.
- 구독자가 실패해도 발행은 계속된다 — 로깅 Agent 가 멈춰도 메인 Agent 는 정상 응답해야 한다.
- 이벤트에는 원본 응답 · API 키 · 오류 원문을 싣지 않는다 (NF3002).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime

Event = dict
Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Handler] = []
        self._lock = threading.Lock()

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        with self._lock:
            self._subs.append(handler)

        def unsubscribe() -> None:
            with self._lock:
                if handler in self._subs:
                    self._subs.remove(handler)

        return unsubscribe

    def publish(self, event: Event) -> None:
        for handler in list(self._subs):
            try:
                handler(event)
            except Exception:  # 구독자 실패는 발행자에게 전파하지 않는다
                pass

    def subscriber_count(self) -> int:
        return len(self._subs)


class Emitter:
    """요청(run) 하나의 이벤트를 만든다. 공통 필드(session_id · run_id · seq · ts)를 채운다.

    events 에도 사본을 쌓는다 — 화면의 실행 과정 표시(F3019)는 로깅 Agent 와 무관하게 이것을 쓴다.
    """

    def __init__(self, bus: EventBus | None, session_id: str, run_id: str | None = None) -> None:
        self.bus = bus
        self.session_id = session_id
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.seq = 0
        self.events: list[Event] = []
        self._lock = threading.Lock()

    def emit(self, type_: str, node: str | None = None, **fields) -> Event:
        with self._lock:
            self.seq += 1
            seq = self.seq
        event = {"session_id": self.session_id, "run_id": self.run_id, "seq": seq,
                 "ts": datetime.now().isoformat(timespec="milliseconds"), "type": type_, "node": node, **fields}
        self.events.append(event)
        if self.bus is not None:
            self.bus.publish(event)
        return event

    # 자주 쓰는 모양
    def node_enter(self, node: str, **summary) -> Event:
        return self.emit("node_enter", node, summary=summary or None)

    def node_exit(self, node: str, **summary) -> Event:
        return self.emit("node_exit", node, summary=summary or None)

    def tool_call(self, node: str, tool: str, args: dict) -> Event:
        return self.emit("tool_call", node, tool=tool, args=args)

    def tool_result(self, node: str, tool: str, result: dict, duration_ms: int, count: int | None = None) -> Event:
        err = None if result.get("ok") else result.get("error", {})
        return self.emit("tool_result", node, tool=tool, ok=bool(result.get("ok")), code=err and err.get("code"),
                         message=err and err.get("message"), duration_ms=duration_ms, count=count)

    def llm_decision(self, node: str, kind: str, decision, reason: str | None = None) -> Event:
        return self.emit("llm_decision", node, kind=kind, decision=decision, reason=reason)

    def replan(self, node: str, count: int, reason_code: str, change: str) -> Event:
        return self.emit("replan", node, count=count, reason_code=reason_code, change=change)

    def error(self, node: str, code: str, where: str | None = None) -> Event:
        return self.emit("error", node, code=code, where=where)


# 앱 전체에서 쓰는 기본 버스. 로깅 Agent 는 여기에 구독한다.
default_bus = EventBus()
