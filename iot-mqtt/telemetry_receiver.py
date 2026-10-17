#!/usr/bin/env python3
"""Suscribe RustIO a la telemetría MQTT de todos los dispositivos IoT."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import paho.mqtt.client as mqtt

from mqtt_settings import get_settings


def append_message(path: Path, topic: str, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "received_at": datetime.now(UTC).isoformat(),
        "topic": topic,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, separators=(",", ":")) + "\n")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings("receiver")
    topic_filter = os.getenv("MQTT_TOPIC_FILTER", "rustio/+/telemetry")
    output_file = os.getenv("MQTT_OUTPUT_FILE")
    output_path = Path(output_file) if output_file else None

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=settings.client_id,
        protocol=mqtt.MQTTv311,
    )
    if settings.username:
        client.username_pw_set(settings.username, settings.password)
    if settings.tls:
        client.tls_set(ca_certs=settings.ca_cert)

    def on_connect(client: mqtt.Client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            logging.error("El broker rechazó la conexión: %s", reason_code)
            return
        client.subscribe(topic_filter, qos=settings.qos)
        logging.info("Suscrito a %s", topic_filter)

    def on_message(_client, _userdata, message: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logging.warning("Mensaje inválido en %s", message.topic)
            return

        if payload.get("schema") != "rustio.iot.telemetry.v1":
            logging.warning("Esquema desconocido en %s", message.topic)
            return

        logging.info(
            "telemetría de %s: %s",
            payload.get("device_id", "desconocido"),
            json.dumps(payload, ensure_ascii=False),
        )
        if output_path:
            append_message(output_path, message.topic, payload)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(settings.host, settings.port, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logging.info("Receptor detenido")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
