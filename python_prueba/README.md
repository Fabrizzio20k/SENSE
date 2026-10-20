# SENSE · primera versión Python

Prototipo independiente de Rust para la Raspberry Pi. Consume los productores MQTT existentes; contiene FSM, reglas temporales, cámara/YOLO NCNN, interpretación LiteRT-LM, políticas A–D, ruta `E_visual`, API/SSE, controles de fallos y exportaciones experimentales.

**Estado:** implementación escrita, pendiente de verificar integralmente en la Raspberry. Después de la instrucción del autor de no ejecutar, no se iniciaron servicios, no se instalaron más paquetes ni se ejecutaron las pruebas de esta versión ampliada. Las verificaciones anteriores del núcleo no validan las incorporaciones de cámara/SLM ni sustituyen pruebas de hardware.

## Ver y trabajar la interfaz sin hardware

Desde `python_prueba/`, puedes servir solo la interfaz con Python estándar, sin instalar las dependencias del prototipo:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory static
```

Abre **http://127.0.0.1:8000/?preview=1**. También puedes abrir `static/index.html` directamente: las direcciones `file:` activan la misma vista previa. Edita ese archivo y recarga el navegador para ver los cambios. Los comandos son instrucciones para el autor; no se ejecutaron aquí.

La vista previa permite recorrer las cuatro etapas y editar los campos, **sin peticiones HTTP a la API, SSE ni temporizadores de sondeo**. No inicia verificaciones, modelos, MQTT, cámara ni sesiones; tampoco muestra mediciones ficticias. Inicio, intervenciones, guardado y exportación permanecen bloqueados. Usa el arranque normal de abajo para trabajar con datos reales. Abrir `?preview=1` en una API ya iniciada solo desconecta esa página: no detiene el backend ni su preparación.

## Recorrido del panel

1. **Preparar:** seis componentes, estado de comprobación y diagnóstico técnico desplegable. Puedes revisar el siguiente paso mientras termina; la API sigue controlando la admisión.
2. **Configurar:** explicación de cada variante, conteo A–D, escenario/guion, duración, bloque, espacio y fase. El escenario es una etiqueta, no un plan de acciones automático. El perfil solo admite desarrollo o piloto.
3. **Monitorear:** reloj, ambiente, radar, conteo, respuestas, cronología y recursos. Un aviso persistente muestra las W pendientes y la próxima lectura. **Preparar cierre** lleva a la lectura final; **Guardar W y detener** registra esa lectura y solicita la detención. **Detener sin lectura de cierre** siempre permite parar y deja la tarea pendiente. Cancelar también conserva los pendientes.
4. **Registro:** cola de lecturas, observaciones humanas, fallos desplegables y exportaciones. **Cerrar medición** solo se habilita tras confirmar la detención y resolver las tareas; la API aplica la misma guarda. El historial permite volver a revisar mediciones pendientes y descargar las últimas 20 ejecuciones. Una descarga con adquisición o revisión pendientes es provisional.

La guía recuerda historia ambiental mínima, cobertura, comparación por bloque y separación de `E_visual`. No automatiza el guion, la aleatorización, la calificación ciega ni el análisis estadístico. Las observaciones anteriores y su referencia completa están en las exportaciones; el panel resume la última entrada enviada desde la página. El diseño es claro, adaptable a móvil y sin fuentes, iconos ni librerías remotas. La nueva interfaz y sus pruebas siguen pendientes de ejecución y revisión visual autorizadas.

### Lecturas W obligatorias y cierre

Las nuevas sesiones vivas guardan el plan `manual-power-v1`: lectura inicial, cada 30 s y final. La cola se deriva del plan y de eventos SQLite; persiste al recargar, cerrar el navegador o reiniciar el backend. Este último caso sigue marcando la adquisición como interrumpida, con su último tiempo persistido. No se crean obligaciones retrospectivas para sesiones anteriores sin ese plan ni para replay.

- **Lectura actual:** pulsa Registrar, observa W y guarda. Dejar el instante vacío usa recepción como aproximación, identificada como tal.
- **Lectura atrasada:** solo introduce el valor si lo habías observado/anotado, indicando su instante real. La tarea periódica acepta tiempos en su intervalo `[instante previsto, siguiente instante previsto)`, limitados por la adquisición. No acepta W actuales para rellenar una tarea vieja.
- **Lectura olvidada:** pulsa **No la observé** y escribe un motivo. La tarea queda omitida, sin inventar una muestra ni eliminar el hueco. No se permiten omisiones masivas automáticas.
- **Final:** guarda W inmediatamente antes de solicitar detener. La tarea de cierre exige una lectura distinta de las periódicas, dentro de los últimos 30 s de adquisición. Una detención lenta puede dejar esa lectura fuera del intervalo y exigir revisión; si no hubo otra observación anotada, declara la omisión.
- **Cierre:** el vencimiento de duración y los comandos de detención no esperan al formulario. Después, resuelve pendientes y pulsa **Cerrar medición**. El registro queda `closed` o `closed_with_omissions`; desde entonces se bloquean modificaciones de potencia. Esto es cierre administrativo, no validación científica. Una adquisición fallida/interrumpida conserva ese estado aunque se cierre su registro.

Los intervalos son reglas administrativas candidatas del piloto, no precisión temporal certificada del vatímetro. Se conserva el tiempo observado y la incertidumbre; no se desplazan muestras al instante previsto. La estimación de energía sigue usando tiempos reales y hueco máximo de 60 s. Un contador Wh/kWh no cumple una tarea de W. La UI bloquea comenzar otra medición desde un registro pendiente; la API conserva su admisión independiente de adquisición y exige las tareas al cerrar cada registro.

`GET /v1/runs/{id}` incluye `measurement` con tareas, estados, pendientes, omisiones y `can_close`. `POST .../power-readings` admite `task_id` (`power-0`, `power-30`, … o `final`); si se omite, una W se asigna por su tiempo al intervalo periódico. Las correcciones conservan su tarea. Para resolver sin valor, `POST .../power-tasks/{task_id}/omit` recibe `{"reason":"No observé el vatímetro"}`; para cerrar, `POST .../measurement-close` recibe `{}` y devuelve 409 si faltan requisitos. Los comandos de cierre y la repetición de la misma omisión son idempotentes.

Se mantienen las doce tablas CSV: `runs.csv` añade `measurement_status`, `power_pending_count` y `power_omitted_count`; `power_readings.csv` añade `task_id`. `manifest.json` incluye plan y cola completa, y `events.jsonl` conserva motivos de omisión y cierre. `partial=true` también identifica revisiones pendientes. Descargar nunca se bloquea para evitar pérdida de acceso a datos. Las pruebas nuevas en `tests/test_measurement.py` y `tests/test_ui.cjs` están escritas, no ejecutadas.

## Preparación en la Raspberry

Los siguientes comandos son instrucciones para ejecutarlas allí; no fueron ejecutados en esta entrega. Usar Raspberry Pi OS de 64 bits y Python del sistema **3.11 o posterior** compatible con Picamera2/libcamera. No copiar `.venv` de macOS.

```bash
cd python_prueba
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade -r requirements.txt
```

`requirements.txt` es la lista única de dependencias, incluidas Ultralytics, NCNN y pnnx, sin versiones fijadas ni límites superiores. `--upgrade` solicita las versiones estables más recientes compatibles con el intérprete y entre sí; no garantiza compatibilidad de hardware. `pyproject.toml` lee esa misma lista para evitar restricciones contradictorias. No es necesario instalar el proyecto como paquete para arrancarlo desde esta carpeta.

Picamera2 y libcamera deben estar instalados para ese Python mediante los paquetes de Raspberry Pi OS. La API importa esos módulos únicamente dentro del worker visual. Ultralytics/NCNN y los paquetes resueltos deben funcionar en ARM64 y con la ABI de cámara instalada. El programa **no descarga modelos, no exporta pesos ni instala paquetes durante una sesión**. No actualizar dependencias entre repeticiones de un mismo piloto. El manifiesto registra versiones del backend, cliente, imagen, detector y librerías numéricas; una dependencia no instalada figura como `null`, no como verificada. Para archivar el entorno resuelto antes del piloto:

```bash
.venv/bin/python -m pip freeze > requirements-pi-resolved.txt
```

Ese inventario complementa la versión de Raspberry Pi OS y sus paquetes de cámara; no sustituye su instalación. No se generó aquí un inventario de la Pi ni se comprobó qué versiones publicadas serán compatibles allí.

En modo vivo, el arranque **prepara YOLO automáticamente antes de aceptar sesiones**. Busca `data/models/yolo26n_320_ncnn_model` (relativo a esta carpeta). Si existe, exige `.param`, `.bin` y `metadata.yaml` no vacíos, `imgsz=320` y clase 0 `person`; registra hashes y lo reutiliza. Si falta, ejecuta `prepare.py` en un subproceso con `YOLO("yolo26n.pt").export(format="ncnn", imgsz=320, quantize=16, device="cpu")` y publica la carpeta al terminar. `quantize=16` solicita FP16, no INT8. Una exportación existente inválida **se conserva y se rechaza**, sin sobrescribirla.

La primera preparación puede descargar los pesos oficiales si no existe `data/models/yolo26n.pt`; necesita internet para esa descarga. Para una Pi sin internet, llevar previamente ese `.pt` o una exportación compatible. Las dependencias se instalan antes con el comando anterior; el exportador no las instala automáticamente. `SENSE_VISION_MODEL` permite elegir la carpeta destino y `SENSE_VISION_WEIGHTS` los pesos locales. `SENSE_VISION_INPUT_SIZE=640` prepara una red 640 cuando falta el destino; una carpeta 320 no se reutiliza como red 640. `SENSE_DATA_DIR` cambia también la ubicación predeterminada de modelos.

LiteRT-LM y Mosquitto se administran por separado. Mantener Gemma residente con thinking desactivado en su configuración. El cliente envía siempre `reasoning_effort=none` y `max_completion_tokens`; aún hay que verificar que la versión instalada respete esos parámetros. `SENSE_SLM_IMAGE_SIDE` permite 320/480/640 para el ensayo visual separado; se registran dimensiones, bytes y hash del JPEG enviado, sin atribuirle un coste interno del encoder no medido.

## Configuración y arranque

Primera terminal, desde la raíz del repositorio:

```bash
sh run-litert.sh
```

Segunda terminal, desde la raíz del repositorio, después de que LiteRT-LM esté disponible:

```bash
cd python_prueba
# La primera vez: crea .env si todavía no existe; después edítalo si corresponde.
cp -n .env.example .env
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

No hace falta definir URL ni modelo de Gemma: los valores internos son `http://127.0.0.1:8080` y `gemma4-e2b`, iguales al script raíz. El cliente solo admite HTTP de loopback; no usa proxies del entorno. `SENSE_SLM_URL` y `SENSE_SLM_MODEL` quedan como ajustes opcionales. El backend no inicia ni reinicia LiteRT-LM.

Abrir `http://127.0.0.1:8000`; el contrato interactivo HTTP está en `/docs`. Una sola instancia, sin `--reload` durante mediciones. Para acceso desde otro equipo, usar un túnel SSH o un proxy autenticado y restringido; esta API local no implementa cuentas ni permisos separados de evaluador. No exponerla directamente a internet.

La pantalla puede abrirse mientras se comprueba el equipo. La navegación separa **Preparar, Configurar, Monitorear y Registro y datos**, según el recorrido anterior. El inicio de sesión se habilita solo al terminar correctamente la comprobación; el backend aplica la misma guarda. Si conservabas abierta una versión anterior, recarga la página después de copiar los cambios; no hace falta reiniciar la API por editar únicamente `static/index.html`, que se sirve sin caché. La clave de idempotencia del navegador tiene alternativas cuando `crypto.randomUUID` no existe (por ejemplo, HTTP sobre una IP); no requiere HTTPS para generarla ni se utiliza como credencial.

El backend **carga automáticamente `python_prueba/.env` al arrancar**, mediante `python-dotenv`, antes de validar su configuración. La ruta se resuelve desde el código, independientemente del directorio de trabajo; no busca otros `.env` en carpetas superiores. Las variables ya definidas en el sistema tienen prioridad sobre el archivo. Si no existe `.env`, usa el entorno y los valores predeterminados; `.env.example` es solo la plantilla. No hace falta ejecutar `source` ni `set -a`. Reiniciar el backend después de editar el archivo.

MQTT usa `rustio/rpi5-01/telemetry`, puerto 1883 por defecto y una suscripción QoS 0. Credenciales opcionales: `SENSE_MQTT_USERNAME` y `SENSE_MQTT_PASSWORD`; no entran en el manifiesto. `SENSE_DATA_DIR` cambia el directorio de SQLite y artefactos. `SENSE_SLM_PID` permite medir el proceso del servidor, además del backend, broker local y worker visual.

### Comprobaciones previas

`GET /health` muestra el diagnóstico `preflight`. El sondeo de Gemma usa `GET /v1/models` y coincidencia exacta del identificador; por sí solo verifica API y catálogo. **El arranque también realiza un calentamiento multimodal**, después de preparar YOLO: lee `static/image.png` y pide «Describe lo que ves en la imagen con una sola palabra en español. Responde solo esa palabra.», con thinking solicitado desactivado, temperatura 0, máximo 16 tokens y plazo total de 120 s. Acepta una palabra alfabética con puntuación final opcional, sin herramientas ni pensamiento devuelto, y exige respuesta terminada. Registra `gemma_warmup.status=ready`, `generation_verified=true` e `image_request_completed=true`.

Se usa la misma ruta HTTP y transformación visual que en las interpretaciones: conversión a RGB, lado mayor limitado por `SENSE_SLM_IMAGE_SIDE` (480 por defecto), JPEG calidad 85 y datos de imagen dentro de la petición local. El informe conserva ruta y hash del PNG original, dimensiones originales/enviadas, tamaño y hash del JPEG, prompt, respuesta y uso reportado. No se abre la cámara ni se pasa esa imagen por YOLO. Llevar **también `static/image.png`** al copiar el proyecto: si falta o no se puede decodificar, la preparación informa el error sin enviar una petición al modelo ni dejar una reserva falsa de cómputo.

El calentamiento se ejecuta una vez al arrancar y al solicitar explícitamente `POST /v1/runtime/prepare`; no se repite antes de cada sesión si ya terminó correctamente. **`/health` es pasivo:** presenta los últimos chequeos de modelos/cámara y el estado actual de recepción MQTT; no vuelve a sondear Gemma, generar ni capturar. Tras levantar o reiniciar LiteRT-LM por separado, repetir la comprobación: el catálogo con el mismo identificador no permite detectar ese reinicio ni garantiza residencia futura.

Para estudiar el arranque en frío de Gemma, definir `SENSE_SLM_WARMUP=0` antes de iniciar el backend y reiniciar el servidor del modelo sin consultas previas. El valor y el resultado quedan registrados en el manifiesto. Omitir el calentamiento por sí solo **no garantiza un modelo frío**. El envío de imagen y la respuesta breve ejercitan la ruta multimodal, pero no certifican por sí solos que la palabra sea correcta ni todas las operaciones internas del encoder (`visual_encoder_verified=false`). No se declara thinking efectivo verificado a partir de una sola respuesta breve. **YOLO sí ejecuta el conteo inicial de comprobación**, por lo que las sesiones posteriores normalmente encuentran su worker/modelo cargados; no presentarlas como primera inferencia en frío.

La comprobación en modo vivo conecta MQTT desde el principio y, antes de admitir **cualquier** variante, también exige:

- Una captura real de Picamera2 seguida de conteo NCNN, con plazo de 90 s. Se comprueba que el JPEG exista, pueda decodificarse, tenga las dimensiones/hash reportados y devuelva un conteo entero coherente con las cajas. **Cero personas es un resultado válido**. Se guardan hash, tiempo, dimensiones, referencia del modelo y conteo en `preflight.camera`; la foto temporal se elimina siempre después del intento.
- Al menos una publicación nueva válida de **SHT40, ENS160 y LD2410C**, recibida después de comenzar la comprobación y con antigüedad menor que 7 s al admitir. Se descartan retenidos y timestamps repetidos/fuera de orden. Los bloques se validan por separado. Tras los chequeos de modelos/cámara se esperan hasta **30 s** adicionales para completar sensores y conexión; es un plazo candidato de arranque, no un TTL físico.
- Catálogo/modelo de Gemma disponible y calentamiento correcto cuando está habilitado.

Las lecturas del diagnóstico se siguen mostrando aunque no haya sesión, pero **no rellenan la historia ni el conteo de la sesión**. Una publicación válida no certifica calibración ni tiempo físico de adquisición. Una captura y conteo exitosos comprueban ejecución, no exactitud del detector.

Los errores dejan la pantalla de diagnóstico disponible en `degraded`, `blocked` o `failed`, con inicio de sesiones bloqueado incluso para `rules-v1`. Esto sustituye la admisión anterior de reglas con dependencias incompletas, por petición del autor. Solo el replay omite hardware y admite `rules-v1`. Si únicamente faltaban sensores, nuevas publicaciones válidas pueden completar la condición; errores de cámara/modelo requieren repetir la comprobación. Cada nueva sesión pesada revalida sus dependencias aplicables antes de empezar su reloj. Preparación y admisión están serializadas. Repetir la misma clave idempotente recupera su sesión sin duplicarla; el panel conserva esa clave si se pierde una respuesta de creación.

Después de corregir el problema, usar **Repetir comprobación** o `POST /v1/runtime/prepare` con `{}`. Devuelve **202** sin esperar a los modelos/captura; consultar progreso y resultado en `/health` (`preparing`, `can_start_session`, `preflight`). Peticiones repetidas durante esa misma comprobación no crean otra. No se permite preparar durante una sesión ni liberar reservas mientras una comprobación está activa.

El informe queda en `data/preflight.json` y en el manifiesto de cada sesión; incluye sensores, prueba visual y calentamiento. Las conversiones nuevas conservan además su `preparation.json`. Conversión, calentamiento y captura de comprobación quedan fuera del reloj y de los recuentos/estimaciones de la sesión. Para exports anteriores sin procedencia solo se conocen hashes actuales; la validación de archivos sigue diferenciada de la inferencia efectivamente comprobada. Tras una prueba exitosa, `preflight.camera.inference_verified=true` identifica esa ejecución.

Si el calentamiento agota su plazo o se cancela, se conserva `slm_busy` porque cerrar HTTP no confirma que Gemma haya dejado de calcular. No hay reintento automático ni admisión pesada hasta verificar el servidor y confirmar su inactividad con el procedimiento documentado abajo. Una respuesta recibida completa pero rechazada libera la reserva y deja el calentamiento fallido; el operador puede repetir la preparación.

## Crear una sesión

Enviar JSON a `POST /v1/runs`, preferiblemente con cabecera `Idempotency-Key`. Ejemplo de monitoreo adaptativo con interpretación:

```json
{
  "variant": "D",
  "source_mode": "live",
  "duration_s": 1200,
  "profile_id": "rules-pilot-v1",
  "scenario_id": "S01",
  "block_id": "pilot-01",
  "space_id": "laboratorio",
  "phase": "pilot",
  "monitor_count": true,
  "retain_images": false,
  "overlap_verified": false,
  "fault_plan": [
    {"source_id": "ld2410c", "mode": "disabled", "start_elapsed_s": 300, "duration_s": 45}
  ]
}
```

| Variante | Política |
|---|---|
| `rules-v1` | MQTT y reglas durante la sesión; la preparación en modo vivo también comprueba cámara y modelos. |
| A | Visión periódica, inicialmente cada 30 s si `monitor_count=true`; reglas. |
| B | Visión al confirmar ausencia→presencia si se requiere conteo; reglas. El estado inicial presente no se convierte en entrada. |
| C | Renovación de conteo faltante/vencido si el objetivo lo requiere; reglas. |
| D | Misma adquisición que C, más interpretación condicional de cambios ambientales persistentes o conflictos comparables. |
| `E_visual` | Descripción directa de imagen solicitada explícitamente; experimento separado. |

`monitor_count=false` permite objetivos de sensores sin renovar conteo por defecto. Para comparar A–D en conteo, fijarlo en `true` en las cuatro, con el mismo guion y configuración. Un cambio ambiental por sí solo no dispara la cámara. Las preguntas directas de presencia/ambiente no invocan Gemma.

`GET /v1/runs/{id}` muestra estado y si hay cierre pendiente. `POST .../finish` finaliza normalmente; `POST .../cancel` solicita cancelación. Los eventos terminales confirman el cierre; desconectar SSE no cancela la sesión.

## Consultas y evidencia

`POST /v1/runs/{id}/questions` admite:

```json
{"type":"count_people"}
```

Otros tipos: `presence`, `environment`, `monitor`, `environment_trend`, `interpret_context`, `describe_image`. Las herramientas pesadas devuelven `job_id` y `episode_id`; su resultado se entrega y persiste por SSE. Cualquier texto generado es una interpretación que requiere evaluación humana, no una medición nueva.

Para contrastar interpretación con **exactamente el mismo snapshot**, recuperar su ID en los eventos de C y solicitarlo desde D:

```json
{"type":"interpret_context","source_run_id":"ID-DE-C","snapshot_id":"HASH-DEL-SNAPSHOT"}
```

Se recupera el snapshot persistido, sin reconstruirlo ni adquirir evidencia adicional. Se conserva su hash de evidencia y se etiqueta la respuesta histórica. El `acquisition_hash` del manifiesto permite contrastar configuraciones C–D; no demuestra que dos sesiones físicas distintas observaran la misma escena.

`POST /v1/artifacts` recibe bytes JPEG/PNG directamente, hasta 8 MiB y 16 megapíxeles. Devuelve `artifact_id`; puede acompañar una consulta `count_people` o `describe_image`. `GET /v1/artifacts/{id}` recupera bytes retenidos y `DELETE` elimina bytes manteniendo la referencia histórica. Una imagen subida no renueva el conteo de la cámara en vivo. Por defecto las capturas del programa se eliminan después de la acción; `retain_images=true` las conserva explícitamente. Las cargas del investigador se conservan hasta borrado explícito. El programa no crea una autorización para capturar participantes.

## Fallos y medición

`POST /v1/runs/{id}/faults` acepta `source_id` (`sht40`, `ens160`, `ld2410c`, `camera`, `slm`), `mode` (`disabled`, `drop`, `freeze`, `error`), `start_after_s`, `duration_s` y `reason`. Una duración `null` mantiene el fallo hasta retirarlo. `POST .../faults/{fault_id}/clear` retira el overlay; no rejuvenece evidencia antigua. Se admiten ventanas programadas sin solapamiento por fuente. La aplicación efectiva y cualquier ventana perdida quedan registradas. Intervenir manualmente fuera del plan se marca como desviación.

`POST .../power-readings` registra W, Wh o kWh con tiempos observado/registrado separados y correcciones por `supersedes_reading_id`. `POST .../annotations` conserva referencia humana fuera de la política. `POST .../evaluations` registra evaluación de una respuesta por `episode_id`, evaluador, versión de rúbrica, `correct`, `supported`, `score` y nota. No se calculan aciertos ni F1 sin referencia adecuada.

`GET .../metrics` devuelve recuentos descriptivos y energía estimada con cobertura. `GET .../exports/{table}.csv` y `GET .../export.zip` entregan las doce tablas, manifiesto, esquema y eventos originales en un corte consistente. Máximos de recursos son muestreados a 1 Hz. La estimación por W usa trapecios con hueco máximo de 60 s y sin extrapolar extremos; no representa picos ni energía de una inferencia breve.

## Tiempos, límites y cancelación

- Umbrales acordados: ±0.5 °C, ±3 pp RH, ±50 ppb TVOC y ±100 ppm eCO2; medianas 30/120 s, apertura 10 s y retorno a media banda durante 20 s. Radar: debounce 2 s; watchdog de recepción MQTT: 7 s.
- El backend usa recepción monotónica como **aproximación** temporal en vivo; la adquisición física sigue desconocida si el productor no la informa. Conserva timestamp de fuente y recepción por separado. Retenidos, repetidos y fuera de orden no se presentan como nuevas mediciones.
- Se empareja radar previo a captura, no radar recibido al terminar inferencia. Sin cobertura común y relojes verificados, el desacuerdo queda `not_comparable`. Declaraciones opcionales documentadas en `.env.example`; `crossmodal_max_skew_s` se fija en el run después de medirlo. No se inventa ese desfase.
- Candidatos operativos: conteo vigente 30 s, cooldown 5 s, cámara/YOLO hasta 90 s, SLM hasta 120 s, episodio hasta 240 s incluyendo cola, una acción pesada simultánea y cola máxima 8. Hasta dos seguimientos de conteo, separados 30 s, dentro de 180 s; al agotarse se suspende la renovación hasta nueva necesidad/restauración. No hay reintentos generativos automáticos.
- Guardas iniciales: reserva de 512 MiB y CPU menor que 80 °C cuando hay sensor disponible. Son elecciones de ingeniería pendientes de piloto, no garantías de que la inferencia quepa.
- El worker de cámara se termina y se comprueba su salida antes de reutilizarlo. Para Gemma, cancelar la espera HTTP no prueba que el servidor haya detenido CPU: un timeout/cierre no confirmado conserva una reserva persistente del slot pesado, incluso tras reinicio de la API. El investigador debe comprobar el runtime y, solo después, enviar `POST /v1/runtime/confirm-idle` con `confirmed_idle=true` y nota. Esta es una confirmación del operador, no un acuse automático del servidor.

## Replay y pruebas preparadas

Para diagnóstico sin hardware, en un momento posterior:

```bash
export SENSE_INPUT_MODE=replay
export SENSE_REPLAY_SPEED=10
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

Ese replay usa solo las 490 líneas completas de la captura conocida, con hash y cola excluida documentados. Solo admite `rules-v1`: sin imágenes pareadas no simula YOLO/Gemma ni comparaciones A–D. Sus tiempos son virtuales y sus recursos pertenecen al host de replay; no acepta W físicos.

Pruebas preparadas, **sin ejecutar después de la instrucción del autor**:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Incluyen ventanas/persistencia, debounce, validez parcial, stale sin mensajes, retenidos/duplicados, restauración, planes, idempotencia, SQLite tras reinicio, SSE recuperable, CSV/ZIP, potencia, fusión de cajas, IDs del modelo, cola y snapshots. `tests/test_prepare.py` añade preparación simulada, conservación de exports inválidos, parámetros de conversión, errores, sondeo HTTP sin generación, calentamiento con imagen, JPEG/hash/dimensiones, respuesta de una palabra, imagen ausente/corrupta, ausencia de repeticiones por sesión, opción de omisión y reserva ante timeout/cancelación, y exclusión entre preparación/admisión. Picamera2, el export NCNN y LiteRT-LM necesitan además verificación real en la Pi. El perfil sigue siendo `pilot_candidate`; no se admiten sesiones declaradas finales.

`tests/test_startup.py` añade foto/conteo cero simulados, eliminación de foto, sensores por fuente, exclusión de retenidos/duplicados, recepción vencida, diagnóstico durante preparación y bloqueo de admisión. `tests/test_ui.cjs` prepara una regresión aislada de la clave de idempotencia en navegadores con y sin `randomUUID`/`crypto`; puede ejecutarse posteriormente con Node y `node --test tests/test_ui.cjs`. Node no es necesario para ejecutar el backend ni la página. **Estas pruebas nuevas tampoco se ejecutaron aquí.**

Justificación para tesis y estado de implementación: [documentación](docs/README.md) y [entrega Python](docs/16-version-python.md).

Para retomar en otra sesión: [AGENTS.md de la raíz](../AGENTS.md), con acuerdos vigentes, avance, criterios y próximos pasos. La tesis está en [docs/main.pdf](docs/main.pdf).
