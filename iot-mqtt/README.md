# Integración MQTT para los sensores IoT

Esta carpeta conecta los sensores de `tesis/prueba/sensores.py` con el agente
RustIO mediante MQTT. No modifica los scripts originales de la tesis.

## Diseño elegido

Usa **un broker MQTT** para todos los sensores y dispositivos. Un broker puede
atender muchos clientes; instalar uno por sensor complicaría la operación sin
aportar ventajas en esta instalación.

Cada Raspberry Pi debe tener un identificador único y su propio prefijo de
tópicos:

| Elemento | Ejemplo |
| --- | --- |
| Broker | `192.168.1.50:1883` |
| Dispositivo | `rpi5-01` |
| Telemetría | `rustio/rpi5-01/telemetry` |
| Disponibilidad | `rustio/rpi5-01/availability` |
| Estado | `rustio/rpi5-01/status` |

El publicador envía una sola lectura JSON cada dos segundos. Esta agrupa las
mediciones del mismo instante de SHT40, ENS160 y LD2410C. El receptor
puede escuchar todos los dispositivos con `rustio/+/telemetry`.

El archivo `camera.py` solo captura una fotografía y no genera telemetría. Por
eso no se envían imágenes por este flujo: cuando se necesiten, publique un
evento en `rustio/rpi5-01/camera/event` con la ruta o identificador de la
imagen almacenada, en lugar de cargar la imagen completa al broker.

## Archivos

- `sensor_publisher.py`: se ejecuta en la Raspberry Pi 5 conectada a los
  sensores. Parte de las bibliotecas necesarias de `tesis/prueba/sensores.py`.
- `telemetry_receiver.py`: se ejecuta donde se quiera consumir o almacenar los
  mensajes del broker.
- `.env.example`: configuración sin secretos que debe copiarse a `.env`.
- `rustio-sensor-publisher.service`: servicio opcional de systemd para la Pi.

## Preparación

En la Raspberry, copie esta carpeta y cree su archivo de configuración:

```bash
cd iot-mqtt
cp .env.example .env
```

Edite al menos `MQTT_HOST`. Si Mosquitto está en esa misma Raspberry, use
`MQTT_HOST=127.0.0.1`. Si está en otro equipo, use su IP LAN. Defina usuario y
contraseña si el broker los exige. No suba `.env` al repositorio.

Instale solamente el cliente MQTT en el mismo entorno Python donde ya funcionan
los sensores:

```bash
python -m pip install -r requirements.txt
```

El publicador conserva las dependencias de hardware necesarias: `board`,
`adafruit_sht4x`, `adafruit_ens160` y el controlador `LD2410`.

## Ejecución inicial

Primero arranque el publicador en la Raspberry:

```bash
python sensor_publisher.py
```

En el equipo que ejecuta RustIO u otro consumidor, copie `.env.example`, use
la misma configuración MQTT y ejecute:

```bash
python telemetry_receiver.py
```

El receptor escucha `MQTT_TOPIC_FILTER=rustio/+/telemetry` por defecto y
escribe cada mensaje válido en pantalla. Para guardarlos además en un archivo
NDJSON, asigne una ruta en `MQTT_OUTPUT_FILE`, por ejemplo
`data/telemetry.ndjson`.

## Formato de la telemetría

```json
{
  "schema": "rustio.iot.telemetry.v1",
  "device_id": "rpi5-01",
  "timestamp": "2026-10-17T16:00:00+00:00",
  "environment": {
    "sht40": {"temperature_c": 24.18, "humidity_percent": 56.42},
    "ens160": {"aqi": 1, "tvoc_ppb": 25, "eco2_ppm": 486}
  },
  "presence": {
    "state_code": 1,
    "state": "Persona en movimiento",
    "total_distance_cm": 117
  }
}
```

Los campos completos del radar incluyen distancias y energías de movimiento y
presencia estática. Si el radar aún no entrega datos, `presence` vale `null`.

## Seguridad y operación

- Mantenga el broker accesible solo desde la red privada. Para acceso fuera de
  ella, active TLS (`MQTT_TLS=true`) y configure `MQTT_CA_CERT`.
- Cada Raspberry necesita un `MQTT_CLIENT_ID` y `DEVICE_ID` distintos.
- El publicador usa QoS 1 para telemetría y publica `online`/`offline` de forma
  retenida en `availability`; un receptor puede saber si la Pi se desconectó.
- El mensaje `status` retenido contiene el último error de lectura. La
  telemetría continua cuando falla una lectura aislada y vuelve a intentarla en
  el siguiente ciclo.

## Servicio de inicio automático

Cuando la prueba manual funcione, ajuste las rutas y el usuario en
`rustio-sensor-publisher.service`, cópielo a `/etc/systemd/system/` y ejecute:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rustio-sensor-publisher
sudo systemctl status rustio-sensor-publisher
```
