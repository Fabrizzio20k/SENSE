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

En Experimentación, cada combinación de escenario, modo y repetición se bloquea
al completar los 30 minutos y resolver todas las observaciones, incluida la de
cierre. Las mediciones detenidas antes de tiempo, fallidas o interrumpidas no
bloquean la repetición. El bloqueo persiste al recargar o reiniciar el backend;
si ya había varios resultados completos con la misma etiqueta, se toma el
intento más reciente. Las advertencias de cobertura y datos no observados se
conservan: terminar el protocolo no certifica la calidad de las mediciones.

«Volver a medir» autoriza un nuevo intento para esa combinación. Solo cuando
también termine el protocolo sustituirá al resultado vigente; si se interrumpe,
el anterior sigue vigente. El historial distingue el resultado vigente de los
anteriores y conserva sus datos y exportaciones. No se borra ni migra la base.

Con la página abierta, al completar el cierre se solicita automáticamente el
ZIP, después de finalizar los workers pendientes. Se recuerda la solicitud en
ese navegador para evitar repetirla al recargar. El navegador puede bloquear
la descarga o pedir dónde guardar: «Descargar ZIP» permite reintentar. Con la
página cerrada no se pueden iniciar descargas; al volver a conectarse se revisa
la ejecución actual. Las ejecuciones anteriores siguen descargables desde el
historial. La UI `/offline` reproduce este recorrido con datos simulados.

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

El YAML conserva los valores originales salvo el límite de almacenamiento,
ampliado a **10 GiB (10240 MiB)** para la base y sus archivos auxiliares. Se mantiene
un mínimo de **256 MiB libres** en el disco. Reinicia el backend tras cambiar la
configuración; no requiere recompilar ni borrar datos. El hash identifica los
valores efectivos. SQLite usa el mismo esquema;
para consultar el historial Python existente, indica su directorio con
`SENSE_DATA_DIR` y detén antes cualquier backend que use esa misma base. Guarda
una copia de seguridad antes de utilizar datos históricos. Al abrir una base,
las ejecuciones que quedaron `RUNNING` se marcan `INTERRUPTED`, como antes.
No se trasladan ni se borran automáticamente los datos del backend Python.

En las cuatro pestañas, abre **Orientación de cámara**, pulsa **Tomar foto actual**,
elige 0°, 90°, 180° o 270° horarios y pulsa **Aplicar orientación**. La vista previa
no ejecuta modelos. El giro se aplica a los píxeles antes de YOLO; Gemma recibe
exactamente esa misma imagen. La orientación se mantiene mientras el servidor
esté abierto y queda registrada por ejecución. Se bloquea durante una ejecución
y mientras terminen sus workers; cambiarla invalida la foto anterior del sandbox.

En B–F, el control manual aporta el estado de presencia al mismo flujo de datos
que el radar y se muestrea una vez por segundo mientras la medición está activa.
Se guarda como `PresenceAgent`, sin etiquetas de origen manual ni eventos de
muestreo exclusivos; Auto/Manual solo identifica el control en la interfaz.
Cada muestra tiene su propio ID y hora. Mantener el estado no genera cambios de
presencia, nuevos disparos de YOLO ni solicitudes al observador. No se inventan
distancias ni energías. La edad y salud del radar físico siguen independientes.
Al volver a Auto se recupera la última lectura física con su antigüedad real
(puede estar vencida); al finalizar cesa el muestreo. Los registros anteriores
conservan su formato original.

Las fotografías experimentales se guardan en SQLite y se incluyen en el ZIP CSV
bajo `images/`, con la orientación ya aplicada. Replay muestra la última foto
analizada disponible hasta el instante seleccionado, sin girarla otra vez. Los
ZIP antiguos sin fotos u orientación siguen siendo compatibles. NDJSON conserva
el registro y las referencias, sin los archivos JPEG. El sandbox y la vista previa
permanecen en memoria; los temporales de cámara se eliminan. Guardar fotografías
aumenta el tamaño de la base y del ZIP; Replay conserva sus límites de 64 MB
comprimidos y 128 MB descomprimidos.

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

## Interpretaciones Q6 y Q7

Q6 recibe evidencia JSON compacta con lecturas vigentes, unidades y edades,
salud de componentes, diferencias calculadas respecto al inicio de sesión y el
último evento de cada tipo (hasta cuatro), con edad y estado actual evaluable.
El contexto y las tres preguntas se envían en español, con lecturas agrupadas
en `SHT40` y `ENS160` para identificar su origen. Cada grupo incluye salud,
valores actuales, estados y edades por campo y cambios desde el inicio con valor
inicial, delta, dirección y duración. Las unidades están en los nombres de campo;
no se repiten valores actuales ni fechas absolutas en cada cambio. Los estados
distintos de `HEALTHY` incluyen motivo y antigüedad del estado.
Tiempos desconocidos, futuros o inválidos se representan como `null`, no como cero.
Los valores inválidos o vencidos se envían como `null`
con su estado. Un delta de sesión no se presenta como tendencia continua y un
evento histórico no implica que siga activo. El conteo se identifica como
personas visibles en una captura; la presencia usa el mismo formato con entrada Auto o Manual.
Se explicita que no hay historial de conteos, datos de ventilación ni referencia
independiente de CO₂. No se adjuntan datos simulados ni diagnósticos prefabricados.

Gemma responde en tres puntos de hasta 100 palabras: cambio e interpretación,
límites de las lecturas de gases y acción ambiental razonable con seguimiento.
Puede sugerir observaciones o ajustes de bajo riesgo sin demostrar causalidad;
no debe recomendar reinicios ni manipular conexiones durante la medición.
`HEALTHY` describe el sensor, no garantiza un ambiente estable o saludable.
Q7 utiliza la misma
evidencia más la imagen autorizada de YOLO para interpretar contexto visual,
distribución u oclusiones pertinentes, en vez de limitarse a describir objetos.
No sustituye el conteo, identifica personas ni deduce ventilación suficiente o
causas físicas a partir de una foto. La salud `FAILED` puede reflejar un campo
inválido, no necesariamente todas las mediciones del componente.

Ambos usan temperatura **0**, **256 tokens** de salida en el piloto y no fuerzan
`response_format: json_object`. Se conservan políticas, presupuestos y límites
de imágenes existentes. `SLM_INPUT` registra el prompt y las opciones efectivas.
La respuesta se guarda como `summary` y también en `inferences` para conservar
compatibilidad con respuestas, exportaciones y lectores anteriores. El panel
muestra el texto sin interpretar HTML; los resultados históricos con las tres
listas antiguas siguen siendo legibles. No hay migración ni borrado de datos.

`VALIDATED` indica únicamente que hay texto admisible y evidencia atribuible,
no que las hipótesis sean correctas. Se rechazan respuestas vacías, degeneradas,
JSON de salida inesperado, texto de más de 2.000 caracteres, controles inválidos
y truncamiento declarado por el servidor (`finish_reason: length`). Si el servidor
declara `stop` al agotar tokens, no puede garantizarse que el texto esté completo.
Los ensayos de desarrollo mostraron errores de razonamiento del modelo: las
interpretaciones requieren evaluación y no son diagnósticos certificados.

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
Se conserva la comparación del hash de configuración original, restaurando en
la prueba su límite histórico de 512 MiB. `tests/fixtures/prompts.json` permanece
como referencia histórica de Python; los prompts Q6/Q7 actuales evolucionaron
al contrato textual descrito arriba y se prueban por sus invariantes de evidencia,
privacidad y generación, no por igualdad con aquella plantilla.

Las demás pruebas trasladan los escenarios de workers, interpretación, API,
observador, fallas, recuperación, trazabilidad y servidor offline. Incluyen
sesiones simuladas completas de 1.800 segundos, compatibilidad con una base
creada por Python y exportación con un snapshot WAL consistente mientras siguen
entrando eventos.

La migración fue compilada y comprobada con dobles de hardware en macOS. No se
arrancó la aplicación, no se hicieron inferencias reales ni se validó ARM64/Ubuntu.
