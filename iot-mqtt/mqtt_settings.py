"""Configuración MQTT compartida por el publicador y el receptor."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path = Path(".env")) -> None:
    """Carga un archivo .env simple sin añadir otra dependencia."""
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int
    username: str | None
    password: str | None
    client_id: str
    topic_prefix: str
    qos: int
    interval_seconds: float
    tls: bool
    ca_cert: str | None

    @property
    def telemetry_topic(self) -> str:
        return f"{self.topic_prefix}/telemetry"

    @property
    def availability_topic(self) -> str:
        return f"{self.topic_prefix}/availability"

    @property
    def status_topic(self) -> str:
        return f"{self.topic_prefix}/status"


def get_settings(role: str) -> MqttSettings:
    load_dotenv()
    device_id = os.getenv("DEVICE_ID", "rpi5-01")
    topic_prefix = os.getenv("MQTT_TOPIC_PREFIX", f"rustio/{device_id}").strip("/")
    client_id_variable = "MQTT_CLIENT_ID" if role == "sensor" else "MQTT_RECEIVER_CLIENT_ID"
    client_id = os.getenv(client_id_variable, f"rustio-{role}-{device_id}")
    return MqttSettings(
        host=os.getenv("MQTT_HOST", "127.0.0.1"),
        port=int(os.getenv("MQTT_PORT", "1883")),
        username=os.getenv("MQTT_USERNAME") or None,
        password=os.getenv("MQTT_PASSWORD") or None,
        client_id=client_id,
        topic_prefix=topic_prefix,
        qos=int(os.getenv("MQTT_QOS", "1")),
        interval_seconds=float(os.getenv("MQTT_INTERVAL_SECONDS", "2")),
        tls=env_bool("MQTT_TLS"),
        ca_cert=os.getenv("MQTT_CA_CERT") or None,
    )
