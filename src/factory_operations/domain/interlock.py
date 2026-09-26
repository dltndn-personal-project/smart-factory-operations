"""Interlock STOP 규칙 (docs/spec/03-control.md 3.1·3.2절, DECISIONS D-18·D-19).

상태와 판단만 한다. 발행·DB 작업·로그는 워커(`Processor`)가 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..mqtt.payloads import PdmResult

STOP_LINE_STATES = ("RUNNING", "UNKNOWN")  # 알 수 없는 라인에도 보낸다(D-19)


@dataclass(frozen=True)
class Pending:
    command_id: str
    issued_mono: float


@dataclass(frozen=True)
class InterlockView:
    judged: PdmResult | None
    pending: Pending | None
    last_trigger_ts: datetime | None


class Interlock:
    def __init__(self, pending_timeout_s: float = 5.0):
        self.pending_timeout_s = pending_timeout_s
        self.judged: PdmResult | None = None  # 판정 대상 결과 중 timestamp 최대
        self.pending: Pending | None = None
        self.last_trigger_ts: datetime | None = None

    def observe(self, r: PdmResult) -> None:
        """판정 대상 PdM Result(03 2절)를 받는다."""
        if self.judged is None or r.timestamp > self.judged.timestamp:
            self.judged = r

    def on_reference_changed(self, reference_time: datetime | None) -> None:
        """재가동 기준 시각이 바뀌면 조건에 맞지 않는 `judged`를 뺀다."""
        if self.judged is not None and reference_time is not None and self.judged.timestamp <= reference_time:
            self.judged = None

    def expire(self, now_mono: float) -> Pending | None:
        """3.2절 1번. 시간 초과로 끝낸 대기를 돌려준다."""
        p = self.pending
        if p is not None and now_mono - p.issued_mono >= self.pending_timeout_s:
            self.pending = None
            return p
        return None

    def should_stop(self, line_state: str) -> bool:
        """3.2절 2번의 네 조건."""
        j = self.judged
        return (
            j is not None
            and j.state == "CRITICAL"
            and line_state in STOP_LINE_STATES
            and self.pending is None
            and (self.last_trigger_ts is None or j.timestamp > self.last_trigger_ts)
        )

    def issued(self, command_id: str, now_mono: float) -> PdmResult:
        """3.2절 4번. 발행 성공 뒤 부른다. 원인 결과를 돌려준다."""
        assert self.judged is not None
        self.pending = Pending(command_id, now_mono)
        self.last_trigger_ts = self.judged.timestamp
        return self.judged

    def on_result(self, command_id: str, result: str) -> bool:
        """결과에 따른 대기 종료. `APPLIED`·`NO_CHANGE`면 끝내고 True. `REJECTED`는 시간 초과까지 유지."""
        if self.pending is not None and self.pending.command_id == command_id and result in ("APPLIED", "NO_CHANGE"):
            self.pending = None
            return True
        return False

    def view(self) -> InterlockView:
        return InterlockView(self.judged, self.pending, self.last_trigger_ts)
