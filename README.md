# SENSE en Rust

Backend del panel SENSE migrado desde `main.py`, `serve_offline.py` y `sense/`.
Sirve la misma UI en el puerto **5000** en Linux y **5001** en macOS, y conserva las rutas HTTP, SSE, telemetría
MQTT, modos A–F, políticas, controles manuales, fallas simuladas, coordinación,
observaciones externas, SQLite y exportaciones NDJSON/CSV/ZIP para Replay.

`public/` conserva la UI compartida, con cierre confirmado de la medición incluso
si hay fallos o workers pendientes, y CPU/RAM con dos decimales. Cerrar detiene
el registro; los workers pendientes siguen protegidos hasta terminar o confirmar
su estado. `run.sh` se conserva tal como fue copiado. El backend no ejecuta
Python. LiteRT-LM y el broker son servicios externos existentes; `run.sh` continúa
siendo exclusivamente el lanzador de LiteRT-LM.

## Compilar y ejecutar

Requiere Rust 1.92+, Cargo, herramientas de compilación C y acceso a Internet para
la primera descarga de dependencias/ONNX Runtime. En Ubuntu, `build-essential`,
`pkg-config` y certificados del sistema deben estar disponibles. La captura Linux
utiliza el ejecutable `rpicam-still`; en macOS utiliza `ffmpeg` con AVFoundation.

Desde esta carpeta:

```sh
cargo build --locked
```

Con tu broker y LiteRT-LM ya iniciados, cuando quieras ejecutar el panel:

```sh
cargo run --locked --release
```

Abre `http://localhost:5000` en Linux o `http://localhost:5001` en macOS. Puedes
elegir otro puerto con `SENSE_PORT=5050 cargo run --locked --release`. El puerto
se reserva antes de iniciar modelos o MQTT; si está ocupado, el proceso devuelve
un error sin comenzar la preparación. El arranque conecta MQTT y prepara secuencialmente
YOLO, Gemma de texto y Gemma multimodal, igual que el backend original. La
medición se crea al utilizar sus endpoints; una configuración inválida de medición
no impide servir Preparación ni la UI offline.

Ctrl+C inicia el apagado: cierra las conexiones de actualizaciones del panel
en el siguiente segundo y guarda el cierre de una medición activa con el motivo
`PROCESS_SHUTDOWN`. LiteRT-LM y el broker se detienen desde sus propias terminales.

Para servir únicamente la UI simulada, sin modelos, cámara, MQTT ni base de datos:

```sh
cargo run --locked --bin serve_offline -- --bind 127.0.0.1 --port 8000
```

## Configuración y archivos

Se conservan las variables originales:

| Variable | Valor predeterminado |
|---|---|
| `SENSE_PORT` | `5000` en Linux; `5001` en macOS para evitar el puerto de Control Center |
| `MQTT_HOST` | `127.0.0.1`, puerto 1883 |
| `MQTT_TOPIC` | `rustio/rpi5-01/telemetry` |
| `LITERT_URL` | `http://127.0.0.1:8080/v1/chat/completions` |
| `LITERT_MODEL` | `gemma4-e2b` |
| `SENSE_CONFIG` | `sense/pilot.yaml` de esta carpeta |
| `SENSE_DATA_DIR` | `data/` de esta carpeta |

El YAML conserva los valores originales y su hash. SQLite usa el mismo esquema;
para consultar el historial Python existente, indica su directorio con
`SENSE_DATA_DIR` y detén antes cualquier backend que use esa misma base. Guarda
una copia de seguridad antes de utilizar datos históricos. Al abrir una base,
las ejecuciones que quedaron `RUNNING` se marcan `INTERRUPTED`, como antes.
No se trasladan ni se borran automáticamente los datos del backend Python.

Las fotografías experimentales siguen sin guardarse en SQLite ni exportarse. La
captura del sandbox permanece en memoria; los temporales de cámara se eliminan.

## Adaptadores nativos

- **YOLO:** `ultralytics-inference` 0.0.51 y `yolo26n.onnx`, CPU, clase 0,
  confianza 0.15 y tamaño solicitado 640×640. El modelo conocido se descarga si
  falta. Se deshabilitaron las funciones de ventana/anotación/vídeo del crate:
  la UI es la web existente y la captura se realiza por separado.
- **Cámara Linux:** `rpicam-still`, JPEG 1280×960 y preparación de 2 segundos.
  El timestamp se obtiene de la escritura del archivo capturado; es una
  aproximación temporal, no sincronización por hardware.
- **Cámara macOS:** FFmpeg, cámara 0, espera de 2 segundos y un fotograma JPEG.
- **Recursos:** `sysinfo`, `/proc`, temperatura del sistema y `vcgencmd` cuando
  está disponible. Un dato no observable permanece `null`.

La lógica del experimento se conserva; la equivalencia numérica del detector
NCNN anterior frente al modelo ONNX y el soporte de la cámara en Ubuntu requieren
comprobación en la Pi. Esta implementación no permite afirmar igualdad de
predicciones sin esa comparación real.

## Pruebas sin hardware

```sh
cargo test --locked --offline --all-targets
cargo clippy --locked --offline --all-targets -- -D warnings
cargo fmt --check
```

Las pruebas de frontend necesitan Node.js. `cargo test` las ejecuta también;
genera ZIP con el exportador Rust y los entrega a los tests JS del panel.
No necesita Python, un broker, LiteRT-LM, cámara ni modelos. No abre un servidor.
`--offline` requiere haber descargado antes las dependencias.

`tests/domain_parity.rs` reproduce 3.133 operaciones de 37 casos originales de
adquisición, contexto y políticas contra resultados capturados de Python. Se
normalizan los UUID de eventos/snapshots y la hora de creación generados durante
la prueba; valores, estados, evidencia, decisiones y límites se comparan.
`tests/fixtures/provenance.json` conserva las huellas de los módulos de referencia.
También se comparan exactamente los prompts Q6/Q7 y el hash de configuración.

Las demás pruebas trasladan los escenarios de workers, interpretación, API,
observador, fallas, recuperación, trazabilidad y servidor offline. Incluyen
sesiones simuladas completas de 1.800 segundos, compatibilidad con una base
creada por Python y exportación con un snapshot WAL consistente mientras siguen
entrando eventos.

La migración fue compilada y comprobada con dobles de hardware en macOS. No se
arrancó la aplicación, no se hicieron inferencias reales ni se validó ARM64/Ubuntu.
