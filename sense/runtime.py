from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from requests.exceptions import ConnectionError, Timeout

from .contracts import AgentEvent, Command


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


class TaskManager:
    """Una plaza física por lane; el timeout no libera un worker ocupado."""

    def __init__(self, queue_capacity: int):
        self.executors = {lane: ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"sense-{lane}") for lane in ("vision", "gemma")}
        self.active = {"vision": None, "gemma": None}
        self.pending = deque()
        self.quarantined = {}
        self.capacity = queue_capacity
        self.counters = dict(accepted=0, rejected=0, cancelled=0, completed=0, failed=0, timed_out=0, late=0)

    @property
    def busy(self) -> bool:
        return any(self.active.values()) or bool(self.pending) or bool(self.quarantined)

    def submit(self, lane: str, command: Command, action, key: str, now: float, timeout: float) -> str | None:
        if lane in self.quarantined:
            self.counters["rejected"] += 1
            return "REMOTE_EXECUTION_UNCERTAIN"
        if any(task and task.key == key for task in self.active.values()) or any(task.key == key for task in self.pending):
            self.counters["rejected"] += 1
            return "DUPLICATE_REQUEST"
        task = Task(command, action, key, now, now + timeout)
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
        task.future = self.executors[lane].submit(task.action)
        task.action = None
        self.active[lane] = task

    def poll(self, now: float, allow_start: bool = True) -> list[AgentEvent]:
        events = []
        for lane, task in list(self.active.items()):
            if task is None:
                continue
            payload = {"command": asdict(task.command), "queue_seconds": task.started - task.enqueued,
                       "duration_seconds": now - task.started, "semantic_key": task.key}
            if not task.expired and not task.cancelled and now >= task.deadline:
                task.expired = True
                self.counters["timed_out"] += 1
                events.append(AgentEvent(task.command.command_id, task.command.target_agent, "TASK_TIMEOUT", dict(payload)))
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
        return events

    def cancel(self, run_id: str) -> list[Command]:
        cancelled = []
        for task in self.active.values():
            if task and task.command.experiment_run_id == run_id and not task.cancelled:
                task.cancelled = True
                cancelled.append(task.command)
        for task in list(self.pending):
            if task.command.experiment_run_id == run_id:
                self.pending.remove(task)
                cancelled.append(task.command)
        self.counters["cancelled"] += len(cancelled)
        return cancelled

    def view(self, now: float) -> dict:
        active = [{"command_id": t.command.command_id, "agent": t.command.target_agent,
                            "question_id": t.command.parameters["question_id"], "elapsed_seconds": round(now - t.started, 1),
                            "status": "DRAINING" if t.cancelled or t.expired else "RUNNING"}
                           for t in self.active.values() if t]
        active.extend({"command_id": t.command.command_id, "agent": t.command.target_agent,
                       "question_id": t.command.parameters["question_id"], "elapsed_seconds": round(now - t.started, 1),
                       "status": "REMOTE_EXECUTION_UNCERTAIN"} for t in self.quarantined.values())
        return {"active": active, "queued": len(self.pending), "queue_capacity": self.capacity,
                "counters": dict(self.counters)}
