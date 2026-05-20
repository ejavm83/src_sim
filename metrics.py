"""이벤트 로깅과 KPI 집계용 자료구조."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    time_min: float
    kind: str
    resource: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Metrics:
    events: list[Event] = field(default_factory=list)
    buffer_samples: dict[str, list[tuple[float, int]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    resource_busy_time: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    resource_capacity: dict[str, int] = field(default_factory=dict)

    inbound_truck_durations: list[float] = field(default_factory=list)
    outbound_truck_durations: list[float] = field(default_factory=list)
    batch_durations: list[float] = field(default_factory=list)

    flake_produced_ton: float = 0.0
    scr_produced_ton: float = 0.0
    inbound_truck_count: int = 0
    outbound_truck_count: int = 0
    batches_completed: int = 0
    aborted_outbound: int = 0

    daily_production: dict[int, dict[str, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    _next_batch_id: int = field(default=0, repr=False)

    def next_batch_id(self) -> int:
        bid = self._next_batch_id
        self._next_batch_id += 1
        return bid

    def log(self, time: float, kind: str, resource: str = "", **detail: Any) -> None:
        self.events.append(Event(time, kind, resource, detail))

    def sample_buffer(self, time: float, name: str, level: int) -> None:
        self.buffer_samples[name].append((time, level))

    def add_busy(self, name: str, dur: float) -> None:
        self.resource_busy_time[name] += dur
