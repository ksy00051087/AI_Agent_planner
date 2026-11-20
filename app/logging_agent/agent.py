"""로깅 서브 Agent (F3013 · F3020).

- 이벤트를 구독해 받는 즉시 세션 단위로 순서대로 저장한다. 수집 · 저장에 LLM 을 쓰지 않고, 가공 · 요약하지 않는다.
- 요청 하나가 끝나면(respond 종료 이벤트) 규칙으로 이상 징후를 판정해 저장한다 (inspector.py, LLM 없음).
- '이상' 으로 판정한 실행에만 진단 함수(LLM)를 백그라운드에서 부른다. 진단은 판정과 따로 저장하고,
  진단이 실패해도 판정과 실행 로그는 그대로 남는다. 정상 · 판정 불가에는 진단을 부르지 않는다.
- 저장이 실패해도 메인 Agent 에 예외를 돌려주지 않는다. 메인 Agent 는 이 클래스를 모른다.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Callable

from app.events import EventBus

from .inspector import ANOMALY, inspect_run


class LoggingAgent:
    def __init__(self, store, on_error: Callable[[Exception], None] | None = None,
                 diagnose: Callable[[dict, list[dict]], str] | None = None, replan_limit: int = 2,
                 background: bool = True):
        self.store = store
        self.on_error = on_error
        self.diagnose = diagnose            # (판정, 이벤트) -> 진단 문장. None 이면 진단하지 않음
        self.replan_limit = replan_limit
        self.background = background        # 테스트에서는 False 로 동기 실행
        self.saved = 0
        self.dropped = 0
        self.diagnosed = 0
        self._runs: dict[str, list[dict]] = defaultdict(list)
        self._threads: list[threading.Thread] = []
        self._unsubscribe = None

    def handle(self, event: dict) -> None:
        try:
            self.store.append(event)
            self.saved += 1
        except Exception as e:  # 저장 실패가 대화를 멈추게 하지 않는다
            self.dropped += 1
            if self.on_error:
                self.on_error(e)
        run = event.get("run_id")
        if run:
            self._runs[run].append(event)
            if event.get("type") == "node_exit" and event.get("node") == "respond":
                self._inspect(self._runs.pop(run))

    def _inspect(self, events: list[dict]) -> None:
        try:
            result = inspect_run(events, self.replan_limit)
            self.store.save_inspection(result)
        except Exception as e:
            if self.on_error:
                self.on_error(e)
            return
        if result["verdict"] == ANOMALY and self.diagnose is not None:
            if self.background:
                t = threading.Thread(target=self._diagnose, args=(result, events), daemon=True)
                self._threads.append(t)
                t.start()
            else:
                self._diagnose(result, events)

    def _diagnose(self, result: dict, events: list[dict]) -> None:
        try:
            text = self.diagnose(result, events)
            self.store.save_diagnosis(result["run_id"], text, "ok")
            self.diagnosed += 1
        except Exception:
            try:
                self.store.save_diagnosis(result["run_id"], None, "failed")
            except Exception:
                pass

    def attach(self, bus: EventBus) -> "LoggingAgent":
        self._unsubscribe = bus.subscribe(self.handle)
        return self

    def detach(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
