from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from queue import SimpleQueue
import time

from requests.exceptions import ConnectionError, Timeout

from .contracts import AgentEvent, Command, utc_now


@dataclass
class Task:
    command: Command
    action: object
    key: str
    enqueued: float
    deadline: float
    future: object = None
    started: float | None = None
    expired: bool = False
    cancelled: bool = False
    enqueued_monotonic: float = field(default_factory=time.monotonic)
    started_monotonic: float | None = None
    completed_monotonic: float | None = None
    started_at: str | None = None
    completed_at: str | None = None
    simulation: dict | None = None


class TaskManager:
    """Una plaza física por lane; el timeout no libera un worker ocupado."""

    def __init__(self, queue_capacity: int):
        self.executors = {lane: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"sense-{lane}") for lane in ("vision", "gemma")}
        self.active = {"vision": None, "gemma": None}
        self.pending = deque()
        self.quarantined = {}
        self.capacity = queue_capacity
        self.counters = dict(accepted=0, rejected=0, cancelled=0, completed=0, failed=0, timed_out=0, late=0)
        self.lifecycle = SimpleQueue()

    @property
    def busy(self) -> bool:
        return any(self.active.values()) or bool(self.pending) or bool(self.quarantined)

    def submit(self, lane: str, command: Command, action, key: str, now: float, timeout: float, simulation: dict | None = None) -> str | None:
        if lane in self.quarantined:
            self.counters["rejected"] += 1
            return "REMOTE_EXECUTION_UNCERTAIN"
        if any(task and task.key == key for task in self.active.values()) or any(task.key == key for task in self.pending):
            self.counters["rejected"] += 1
            return "DUPLICATE_REQUEST"
        task = Task(command, action, key, now, now + timeout, simulation=simulation)
        if self.active[lane] is None:
            self._start(lane, task, now)
        elif lane == "gemma" and len(self.pending) < self.capacity:
            self.pending.append(task)
        else:
            self.counters["rejected"] += 1
            return "QUEUE_SATURATED"
        self.counters["accepted"] += 1
        return None

    def _start(self, lane: str, task: Task, now: float):
        task.started = now
        if task.simulation:
            task.started_monotonic, task.started_at = time.monotonic(), utc_now()
            task.future = Future()
            task.action = None
            self.active[lane] = task
            self.lifecycle.put(AgentEvent(task.command.command_id, task.command.target_agent, "TASK_STARTED",
                              {"command": asdict(task.command), "started_at": task.started_at,
                               "queue_seconds": now - task.enqueued, "semantic_key": task.key,
                               "simulated": True, "model_executed": False}))
            if task.simulation["kind"] == "CAMERA_UNAVAILABLE":
                task.completed_monotonic, task.completed_at = time.monotonic(), utc_now()
                task.future.set_exception(RuntimeError("CAMERA_UNAVAILABLE"))
            return
        action = task.action
        def execute():
            task.started_monotonic, task.started_at = time.monotonic(), utc_now()
            self.lifecycle.put(AgentEvent(task.command.command_id, task.command.target_agent, "TASK_STARTED",
                              {"command": asdict(task.command), "started_at": task.started_at,
                               "queue_seconds": task.started_monotonic - task.enqueued_monotonic,
                               "semantic_key": task.key}))
            try:
                return action()
            finally:
                task.completed_monotonic, task.completed_at = time.monotonic(), utc_now()
        task.future = self.executors[lane].submit(execute)
        task.action = None
        self.active[lane] = task

    def poll(self, now: float, allow_start: bool = True) -> list[AgentEvent]:
        events = []
        for lane, task in list(self.active.items()):
            if task is None:
                continue
            payload = {"command": asdict(task.command), "queue_seconds": task.started - task.enqueued,
                       "duration_seconds": now - task.started, "semantic_key": task.key}
            if task.started_monotonic is not None:
                payload.update(started_at=task.started_at, completed_at=task.completed_at,
                               queue_seconds=task.started_monotonic - task.enqueued_monotonic,
                               duration_seconds=(task.completed_monotonic or time.monotonic()) - task.started_monotonic)
            if task.simulation:
                payload.update(simulated=True, model_executed=False, duration_seconds=now - task.started,
                               queue_seconds=task.started - task.enqueued)
            completed_in_time = (task.completed_monotonic is not None and
                                 task.completed_monotonic - task.enqueued_monotonic < task.deadline - task.enqueued)
            if not task.expired and not task.cancelled and now >= task.deadline and not completed_in_time:
                task.expired = True
                self.counters["timed_out"] += 1
                events.append(AgentEvent(task.command.command_id, task.command.target_agent, "TASK_TIMEOUT", dict(payload)))
                if task.simulation and not task.future.done():
                    task.completed_monotonic, task.completed_at = time.monotonic(), utc_now()
                    payload["completed_at"] = task.completed_at
                    task.future.set_exception(RuntimeError("DEADLINE_EXCEEDED"))
            if task.future.done():
                late = task.expired or task.cancelled
                try:
                    payload["result"] = task.future.result()
                    payload["late"] = late
                    kind, error = "TASK_COMPLETED", None
                    self.counters["completed"] += 1
                except Exception as failure:
                    kind, error = "TASK_FAILED", str(failure)
                    self.counters["failed"] += 1
                    if lane == "gemma" and isinstance(failure, (Timeout, ConnectionError)):
                        self.quarantined[lane] = task
                        payload["remote_execution_uncertain"] = True
                        task.future = None
                if late:
                    self.counters["late"] += 1
                    payload["late"] = True
                events.append(AgentEvent(task.command.command_id, task.command.target_agent, kind, payload, error))
                self.active[lane] = None
        for task in list(self.pending):
            image_expiry = task.command.parameters.get("image_expires_monotonic")
            if now >= task.deadline or image_expiry is not None and now >= image_expiry:
                self.pending.remove(task)
                self.counters["timed_out"] += 1
                events.append(AgentEvent(task.command.command_id, task.command.target_agent, "TASK_TIMEOUT",
                                         {"command": asdict(task.command), "queue_seconds": now - task.enqueued, "semantic_key": task.key,
                                          "reason": "IMAGE_EXPIRED_IN_QUEUE" if image_expiry is not None and now >= image_expiry else "QUEUE_DEADLINE"}))
        if allow_start and self.pending and self.active["gemma"] is None and "gemma" not in self.quarantined:
            self._start("gemma", self.pending.popleft(), now)
        starts = []
        while not self.lifecycle.empty():
            starts.append(self.lifecycle.get_nowait())
        return starts + events

    def cancel(self, run_id: str) -> list[Command]:
        cancelled = []
        for task in self.active.values():
            if task and task.command.experiment_run_id == run_id and not task.cancelled:
                task.cancelled = True
                if task.simulation and not task.future.done():
                    task.completed_monotonic, task.completed_at = time.monotonic(), utc_now()
                    task.future.cancel()
                cancelled.append(task.command)
        for task in list(self.pending):
            if task.command.experiment_run_id == run_id:
                self.pending.remove(task)
                cancelled.append(task.command)
        self.counters["cancelled"] += len(cancelled)
        return cancelled

    def view(self, now: float) -> dict:
        active = [{"command_id": t.command.command_id, "agent": t.command.target_agent,
                            "simulated": bool(t.simulation),
                            "question_id": t.command.parameters["question_id"], "elapsed_seconds": round(now - t.started, 1),
                            "status": "DRAINING" if t.cancelled or t.expired else "RUNNING"}
                           for t in self.active.values() if t]
        active.extend({"command_id": t.command.command_id, "agent": t.command.target_agent,
                       "question_id": t.command.parameters["question_id"], "elapsed_seconds": round(now - t.started, 1),
                       "status": "REMOTE_EXECUTION_UNCERTAIN"} for t in self.quarantined.values())
        return {"active": active, "queued": len(self.pending), "queue_capacity": self.capacity,
                "counters": dict(self.counters)}
