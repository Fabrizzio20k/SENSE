#!/usr/bin/env python3
"""Publica las lecturas de SHT40, ENS160 y LD2410C en MQTT."""

from __future__ import annotations

import json
import logging
import os
import signal
from datetime import UTC, datetime
from threading import Event

import adafruit_ens160
import adafruit_sht4x
import board
import paho.mqtt.client as mqtt
from LD2410 import LD2410

from mqtt_settings import MqttSettings, get_settings

ESTADOS = {
    0: "Sin presencia",
    1: "Persona en movimiento",
    2: "Persona estática",
    3: "Movimiento y presencia estática",
}
STOP = Event()
CONNECTED = Event()


class Sensors:
    def __init__(self) -> None:
        i2c = board.I2C()
        self.sht40 = adafruit_sht4x.SHT4x(i2c)
        self.ens160 = adafruit_ens160.ENS160(i2c)
        self.radar = LD2410(port="/dev/ttyAMA0")
        self.radar.start()

    def close(self) -> None:
        self.radar.stop()

    def read(self, device_id: str) -> dict:
        temperature, humidity = self.sht40.measurements
        self.ens160.temperature_compensation = temperature
        self.ens160.humidity_compensation = humidity

        data, _, _ = self.radar.get_data()
        presence = None
        if data is not None:
            (
                kind,
                motion_distance,
                motion_energy,
                static_distance,
                static_energy,
                total_distance,
            ) = data
            presence = {
                "state_code": kind,
                "state": ESTADOS.get(kind, "Estado desconocido"),
                "motion_distance_cm": motion_distance,
                "motion_energy": motion_energy,
                "static_distance_cm": static_distance,
                "static_energy": static_energy,
                "total_distance_cm": total_distance,
            }

        return {
            "schema": "rustio.iot.telemetry.v1",
            "device_id": device_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "environment": {
                "sht40": {
                    "temperature_c": round(temperature, 2),
                    "humidity_percent": round(humidity, 2),
                },
                "ens160": {
                    "aqi": self.ens160.AQI,
                    "tvoc_ppb": self.ens160.TVOC,
                    "eco2_ppm": self.ens160.eCO2,
                },
            },
            "presence": presence,
        }


def make_client(settings: MqttSettings) -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=settings.client_id,
        protocol=mqtt.MQTTv311,
    )
    if settings.username:
        client.username_pw_set(settings.username, settings.password)
    if settings.tls:
        client.tls_set(ca_certs=settings.ca_cert)

    client.will_set(settings.availability_topic, "offline", qos=settings.qos, retain=True)

    def on_connect(client: mqtt.Client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            logging.error("El broker rechazó la conexión: %s", reason_code)
            return
        logging.info("Conectado a %s:%s", settings.host, settings.port)
        CONNECTED.set()
        client.publish(settings.availability_topic, "online", qos=settings.qos, retain=True)

    def on_disconnect(_client, _userdata, _disconnect_flags, reason_code, _properties) -> None:
        CONNECTED.clear()
        if reason_code:
            logging.warning("Desconectado del broker: %s", reason_code)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    return client


def publish_status(
    client: mqtt.Client,
    settings: MqttSettings,
    device_id: str,
    state: str,
    detail: str | None = None,
) -> None:
    body = {
        "device_id": device_id,
        "state": state,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if detail:
        body["detail"] = detail
    client.publish(settings.status_topic, json.dumps(body), qos=settings.qos, retain=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("LD2410").setLevel(logging.WARNING)
    settings = get_settings("sensor")
    device_id = os.getenv("DEVICE_ID", "rpi5-01")
    client = make_client(settings)
    sensors: Sensors | None = None

    def stop(_signal, _frame) -> None:
        STOP.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        sensors = Sensors()
        client.connect_async(settings.host, settings.port, keepalive=60)
        client.loop_start()
        if not CONNECTED.wait(timeout=15):
            raise RuntimeError("No fue posible conectar con el broker MQTT en 15 segundos")

        publish_status(client, settings, device_id, "running")
        while not STOP.is_set():
            try:
                assert sensors is not None
                payload = sensors.read(device_id)
                result = client.publish(
                    settings.telemetry_topic,
                    json.dumps(payload, separators=(",", ":")),
                    qos=settings.qos,
                )
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    logging.warning("No se pudo encolar telemetría: %s", result.rc)
                else:
                    logging.info("Publicado %s", settings.telemetry_topic)
            except Exception as error:
                logging.exception("Error leyendo sensores")
                publish_status(client, settings, device_id, "sensor_error", str(error))
            STOP.wait(settings.interval_seconds)
    finally:
        if CONNECTED.is_set():
            publish_status(client, settings, device_id, "stopped")
            client.publish(settings.availability_topic, "offline", qos=settings.qos, retain=True)
        client.loop_stop()
        client.disconnect()
        if sensors is not None:
            sensors.close()


if __name__ == "__main__":
    main()
