from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

SCHEMA_VERSION = "sense.v1"
STATES = ("WAIT", "ACQUIRE", "ASSESS", "VISION", "INTERPRET", "REPORT", "DEGRADED")


def identifier() -> str:
    return uuid4().hex


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Command:
    command_id: str
    correlation_id: str
    experiment_run_id: str
    target_agent: str
    action: str
    created_at: str
    deadline: str
    parameters: dict
    reason: str
    schema: str = SCHEMA_VERSION


@dataclass(frozen=True)
class Observation:
    observation_id: str
    source_agent: str
    captured_at: str
    received_at: str
    region: str
    value: float | int | None
    unit: str
    quality: str
    status: str
    metadata: tuple = ()
    schema: str = SCHEMA_VERSION

    def document(self) -> dict:
        result = asdict(self)
        result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    created_at: str
    document_json: str

    def document(self) -> dict:
        import json

        return json.loads(self.document_json)


@dataclass(frozen=True)
class AgentEvent:
    correlation_id: str
    source_agent: str
    event_type: str
    payload: dict
    error: str | None = None
    event_id: str = field(default_factory=identifier)
    timestamp: str = field(default_factory=utc_now)
    schema: str = SCHEMA_VERSION
