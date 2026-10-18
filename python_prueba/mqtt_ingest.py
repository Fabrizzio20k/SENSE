"""El hilo de Paho solo encola; jamás ejecuta la FSM, SQLite o modelos."""

import queue
import threading
import time

import paho.mqtt.client as mqtt

from store import utc_now


class MQTTInput:
    def __init__(self, host, port, username=None, password=None):
        self.host, self.port = host, port
        self.queue = queue.Queue(maxsize=256)
        self.connected = False
        self.started = False
        self._dropped = 0
        self._lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self.client.username_pw_set(username, password)
        self.client.reconnect_delay_set(1, 30)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if self.connected:
            client.subscribe("rustio/rpi5-01/telemetry", qos=0)

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False

    def on_message(self, client, userdata, message):
        if len(message.payload) > 16384:
            self.drop()
            return
        item = (message.payload, time.monotonic(), utc_now(), message.retain, message.qos)
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.drop()

    def drop(self):
        with self._lock:
            self._dropped += 1

    def take_dropped(self):
        with self._lock:
            dropped, self._dropped = self._dropped, 0
        return dropped

    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()
        self.started = True

    def stop(self):
        if not self.started:
            return
        self.client.disconnect()
        self.client.loop_stop()
        self.started = False
