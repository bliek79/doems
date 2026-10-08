"""Worker-owned compact R5 measurements; no forecast or policy decisions."""
from __future__ import annotations

import time
from typing import Any


class PlannerDiagnostics:
    """Keep partial timings when cooperative cancellation interrupts a phase."""

    def __init__(self, stage: str, generation: int) -> None:
        self.stage = stage
        self.generation = generation
        self.started: float | None = None
        self.cpu_started: float | None = None
        self.phase: str | None = None
        self.phase_started: float | None = None
        self.phase_seconds: dict[str, float] = {}
        self.counts: dict[str, int] = {}
        self.context: dict[str, Any] = {}
        self.result = "pending"
        self.ended: float | None = None
        self.cpu_ended: float | None = None

    def start(self) -> None:
        self.started = time.monotonic()
        self.cpu_started = time.thread_time()
        self.result = "running"

    def enter(self, phase: str) -> None:
        now = time.monotonic()
        if self.phase is not None and self.phase_started is not None:
            self.phase_seconds[self.phase] = self.phase_seconds.get(self.phase, 0.0) + now - self.phase_started
        self.phase = phase
        self.phase_started = now

    def count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def finish(self, result: str) -> None:
        self.ended = time.monotonic()
        self.cpu_ended = time.thread_time()
        self.result = result
        if self.phase is not None and self.phase_started is not None:
            self.phase_seconds[self.phase] = self.phase_seconds.get(self.phase, 0.0) + self.ended - self.phase_started
            self.phase_started = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "stage": self.stage, "generation": self.generation,
            "result": self.result, "last_phase": self.phase,
            "worker_seconds": round(self.ended - self.started, 6) if self.ended is not None and self.started is not None else None,
            "worker_cpu_seconds": round(self.cpu_ended - self.cpu_started, 6) if self.cpu_ended is not None and self.cpu_started is not None else None,
            "phase_seconds": {key: round(value, 6) for key, value in self.phase_seconds.items()},
            "counts": dict(self.counts), "context": dict(self.context),
        }
