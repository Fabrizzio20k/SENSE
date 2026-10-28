# SENSE · Raspberry Pi 5

El panel conserva Preparación y su sandbox. Medición añade una FSM común, seis modos experimentales (F reutiliza la política de E) y un pipeline que muestra transiciones reales. No requiere dependencias nuevas sobre el entorno existente.

## Ejecutar

Mantén el servicio Rust que publica `rustio.iot.telemetry.v1` y el broker MQTT. En otra terminal inicia Gemma con el `run.sh` existente y después el panel:

```sh
sh run.sh
# Otra terminal, con el entorno Python existente activado:
python main.py
```

Abre `http://<raspberry>:5000`, espera a que termine la preparación y entra en Medición. Selecciona A–F y pulsa **Comenzar**. El botón cambia a **Finalizar**. La vista separa **Ejecución en vivo**, **Respuestas actuales**, **Interpretaciones de Gemma** e **Historial y registros guardados**. Las lecturas detalladas y el diagnóstico técnico quedan en desplegables. Un error de preparación permite monitoreo degradado; el sandbox mantiene sus requisitos originales. Durante una medición y mientras se vacían workers, las operaciones manuales del sandbox quedan bloqueadas para evitar competencia y contaminación experimental.

Las respuestas Q1–Q7 se actualizan automáticamente con una hora de evaluación visible; Q7 solo se muestra en E. **Reevaluar** es una consulta opcional que mantiene las políticas de adquisición e interpretación. La pantalla conserva las respuestas actuales y muestra hasta diez interpretaciones recientes, mientras SQLite guarda las respuestas de cada ciclo completado en `REPORT`, incluso si su contenido no cambió. Las transiciones de la FSM se registran por separado. Cada salida de Gemma conserva su snapshot e imagen originales, su tiempo y su validación; los rechazos, errores y resultados tardíos también quedan registrados. Avanzar un bloque del pipeline no implica generar otra interpretación de Gemma. El historial permite descargar el registro completo.

No reinstales el entorno que ya funciona. Se reutilizan Flask/SSE, MQTT, `requests`, `psutil`, PyYAML y YOLO/NCNN; SQLite, colas, contratos y coordinación `asyncio` usan la biblioteca estándar. Picamera2 continúa procediendo del sistema de la Pi, como antes. No se añaden frameworks multiagente, servicios de colas ni dependencias de frontend.

## Configuración de piloto

Edita [sense/pilot.yaml](sense/pilot.yaml) antes de experimentar. `SENSE_CONFIG` permite elegir otro archivo; `SENSE_DATA_DIR` cambia el directorio de registros. La configuración se vuelve a leer y validar al iniciar cada ejecución y queda congelada en su registro, junto con su versión y SHA-256. Un campo obligatorio ausente, `null`, no finito o fuera de rango bloquea el inicio.

Los valores pedidos de +1 °C, +5 puntos de humedad, +1 nivel AQI, cruce de 700 ppm eCO₂, ventana de 300 s, tres muestras, cooldown de 30 s y vigencia visual de 60 s están incluidos. **Todos son provisionales, no resultados científicos.** Los límites adicionales son propuestas iniciales para poder caracterizar el sistema: rearme eCO₂ a 650 ppm equivalentes, rearme térmico a +0.5 °C y de humedad a +2.5 puntos, máximo diez visiones/300 s, una inferencia Gemma activa y una en espera (se rechaza la nueva al saturarse), plazos de 20/90/180 s para visión/texto/multimodal y ejecución de hasta 1800 s. Hay presupuestos separados para cada modalidad generativa y límites globales de memoria, CPU y almacenamiento.

La versión suministrada requiere al menos 1024 MB disponibles y limita el RSS del proceso principal a 2048 MB y la CPU total al 95% para admitir nuevas inferencias. Estos valores pueden resultar restrictivos con el modelo real: ajustarlos exige medición en la Pi. No se asegura que `run.sh --mode full` o `--mode limit` sea óptimo; deben compararse durante el piloto y mantenerse constantes entre modos comparados.

En este montaje SENSE, radar y cámara comparten siempre la misma dirección y región física (`rasp_shared_view`), por lo que `radar_camera_comparable: true` es una invariante de `sense/pilot.yaml`. No lo cambies a `false` salvo que se altere el montaje. Una comparación todavía exige ambas lecturas vigentes y una proximidad temporal de hasta tres segundos. La ausencia del radar nunca representa automáticamente toda el aula: sólo la región compartida.

## Reglas y preguntas

- **A:** YOLO en calendario anclado al inicio, inicialmente cada 30 s. No recupera en ráfaga intervalos vencidos; registra períodos perdidos por ocupación del worker o restricciones de recursos. Reglas para interpretación.
- **B (sense-pilot-2-radar-proximity):** disparador de proximidad, separado de la presencia original del radar. Entra con distancia **menor de 30 cm** y sale desde **50 cm**, con tres lecturas válidas consecutivas y mínimo 30 s entre capturas. Estos umbrales de piloto son configurables en `modes.reactive_enter_below_cm` y `modes.reactive_exit_at_or_above_cm`; la salida debe superar a la entrada. Si comienza dentro de la zona, la primera confirmación próxima también autoriza una captura. Se usa la distancia estática para código 2, la de movimiento para código 1 y la menor de ambas para código 3, exigiendo ambas distancias válidas en este último caso. No se usa `total_distance_cm` como sustituto. Distancia ausente, cero, inválida o radar vencido no significan proximidad ni salida; rompen la confirmación. Código 0 permite confirmar salida sin inventar una distancia. Se conserva la histéresis entre 30 y 50 cm y se registra el evento que originó cada comando. Si varias entradas/salidas se acumulan durante cooldown o falta de recursos, queda pendiente el último cambio confirmado. Permanecer dentro o fuera no repite capturas: un conteo vencido puede seguir vencido hasta otro cambio. La tarjeta muestra la zona B y, por separado, la presencia original y distancia del blanco. A/C/D/E mantienen sus políticas. La distancia radial no garantiza que una persona esté dentro del encuadre de la cámara: hay que calibrar los umbrales y la orientación con hardware real. Si usas un YAML externo anterior, añade ambos umbrales y actualiza su versión antes de iniciar una nueva ejecución.
- **C/D/E/F:** adquisición visual por necesidad, no por calendario: un conteo vencido por sí solo no autoriza cámara. Solicitan YOLO cuando una pregunta requiere evidencia visual y el conteo falta, venció o entra en conflicto: episodio ambiental confirmado, cambio confirmado de presencia en la región compartida, conflicto radar/cámara o consulta explícita de Q2. Si el conteo vigente ya responde a la necesidad, no recapturan. E/F toman además una imagen inicial de referencia para Q7. Disponibilidad, cooldown y presupuesto siguen aplicando.
- **Q1–Q5:** reglas deterministas. Q4 informa episodios confirmados y distingue ventana incompleta/datos insuficientes de ausencia de cambios. Q5 conserva las limitaciones de fuente, región y tiempo.
- **Q6:** las reglas describen coincidencia temporal si existe un episodio y presencia/conteo próximos dentro de la ventana configurada. Dos o más tipos de cambio ambiental entre los últimos cuatro episodios, con evidencia de ocupación comparable, constituyen la necesidad inicial de síntesis adicional. C conserva su respuesta determinista parcial; D/E/F pueden solicitar texto a Gemma. No se infiere causalidad. Sin esa necesidad, las reglas bastan y no se invoca el modelo.
- **Q7:** disponible en E y F. Describe una imagen obtenida legítimamente por la política compartida. La necesidad inicial es una descripción de referencia; luego solo se considera una descripción adicional cuando cambia el conteo, aparece un nuevo episodio ambiental o existe una consulta explícita. No se llama al modelo para cada imagen ni se captura una foto únicamente para Q7. No identifica personas ni reemplaza conteos o sensores.

La deduplicación generativa usa pregunta, valores/estados/regiones relevantes, episodios, versión del modelo e imagen cuando corresponde; excluye timestamps e identificadores nuevos de observación. Una solicitud equivalente fallida o rechazada por validación no se repite indefinidamente sobre el mismo contexto. Las respuestas del modelo deben cumplir JSON y referenciar evidencia conocida; sus hechos observados deben copiar exactamente observaciones vigentes. Una validación estructural no demuestra la veracidad de las inferencias del modelo.

Temperatura, humedad y AQI comparan contra una muestra válida próxima al inicio de la ventana completa (tolerancia inicial 10 s). No se interpola. La referencia se congela desde la candidatura hasta la recuperación confirmada; después se vuelve a reunir una ventana de muestras posterior al rearme. La línea base de sesión no cambia. Lecturas inválidas y huecos superiores a seis segundos rompen la confirmación. eCO₂ requiere una lectura inferior a 700 antes del cruce inicial; tras un episodio requiere recuperar a 650 durante tres muestras. AQI repetido no produce episodios nuevos.

## Ejecución, memoria y fallos

### F: E con fallas por software

**Medición y pruebas** permite iniciar A–F sin el formulario del protocolo. **Experimentación** permite los mismos seis modos con S1–S3 y repetición 1–3: 54 combinaciones identificadas por ejecuciones independientes, sin sobrescribir anteriores. Se comparte el panel de medición; al terminar puedes regresar a Medición y pruebas. F conserva `mode: F` y `policy_mode: E` en metadatos, las preguntas Q1–Q7, la adquisición por necesidad y los mismos límites de E. No fuerza inferencias para producir un fallo.

Solo F activo permite suspender/restaurar por software SHT40, ENS160, radar y cámara, o armar un timeout para la siguiente tarea aceptada de visión/Gemma. La API también comprueba el modo; los controles se reinician en cada ejecución. El corte de sensores descarta sus entradas al dominio, conserva el último valor con edad y deja que venza por su TTL normal. El MQTT original sigue registrado. La cámara deshabilitada provoca un error en las nuevas tareas visuales sin invocar cámara ni detector; no altera una tarea que ya estaba ejecutándose ni rejuvenece imágenes anteriores. Estos controles no cortan la alimentación y no representan un ahorro eléctrico del sensor.

El timeout simulado ocupa lógicamente el worker hasta vencer el plazo, sin ejecutar modelo ni dejar un hilo dormido. Las tareas y muestras incluyen la marca de simulación; el CSV de tareas indica `model_executed: false`. Si la tarea vence en cola sin comenzar, la falla se registra como no ejecutada. Un timeout real de HTTP sigue dejando el runtime remoto en cuarentena: los controles de F no lo liberan. Los timeouts armados esperan una necesidad legítima de la política; puedes usar cambios de presencia o consultas con evidencia pertinente, conservando cooldown y presupuestos.

La salud observada se gestiona en el núcleo común, con estados por componente `UNKNOWN`, `HEALTHY`, `STALE`, `UNAVAILABLE`, `FAILED` y `RECOVERING`. No lee los interruptores del inyector para anunciar fallos: observa edad/calidad de datos y resultados de tareas. La FSM existente pasa por `DEGRADED → REPORT → WAIT` y sigue respondiendo con la evidencia restante, incluso durante una tarea visual. C mantiene sus reglas deterministas. La cámara puede volver a probarse cuando exista necesidad y termine el cooldown; Gemma puede comprobarse mediante una reevaluación explícita o un contexto nuevo. No se reutilizan respuestas tardías como actuales ni se ejecutan reintentos sin los límites existentes. Restablecer una entrada no confirma recuperación: hace falta evidencia nueva válida.

Cada falla conserva `fault_id`, componente, tipo, activación, tarea relacionada, inicio efectivo, detección y recuperación. El núcleo registra `COMPONENT_HEALTH_CHANGED`; el inyector registra por separado `FAULT_INJECTED`, `FAULT_APPLIED`, `FAULT_TASK_STARTED`, `FAULT_DETECTED`, `FAULT_RESTORED`, `FAULT_RECOVERED`, `FAULT_NOT_EXECUTED` y cierre sin recuperación cuando corresponda. `faults.csv` resume esos eventos. Para un timeout, la latencia de detección se cuenta desde el inicio de la tarea, no desde el instante en que se armó. Una falla ya presente al activar el control queda marcada y no recibe una latencia atribuida ficticia. Un corte breve puede recuperarse sin llegar a detectarse antes de vencer el TTL; ambas situaciones quedan distinguibles. El navegador no participa en la ejecución del fallo ni en su medición.

### Presencia Auto/Manual en B–F

El control está disponible tanto en pruebas como en ejecuciones guiadas. Manual fija una señal explícita del operador, con fuente `OperatorControl`; no se convierte en lecturas periódicas del radar ni en ground truth. El valor permanece fijado hasta cambiarlo o volver a Auto. Se conservan las observaciones reales del radar y su salud por separado; una presencia manual activa no oculta una pérdida del sensor. Al volver a Auto se recupera la observación original con su antigüedad, o se espera evidencia nueva si no existe.

**B automático sigue usando proximidad:** un conteo vencido por sí solo no dispara YOLO. En B manual, el botón representa dentro/fuera de zona y presencia coherente; la entrada/salida manual constituye un evento explícito, no tres muestras fabricadas ni una distancia inventada. La API permite distinguir `detected` y `near` en B (zona próxima exige presencia). Volver a Auto reinicia la confirmación de zona y exige lecturas reales. C–F utilizan la presencia manual como antes, manteniendo sus reglas de necesidad visual. Los cambios de fuente también invalidan la equivalencia de una interpretación anterior aunque el booleano sea igual. Cada intervención guiada solicita W/personas/acción por separado y puede filtrarse en el análisis.

API de controles:

```text
POST /api/experiments/faults    {"action":"availability","component":"sht40","enabled":false}
POST /api/experiments/faults    {"action":"timeout","lane":"gemma"}
POST /api/experiments/presence  {"mode":"manual","detected":true,"near":true}  (B)
POST /api/experiments/presence  {"mode":"auto"}
```

`sense/` separa adquisición MQTT, contratos, contexto/snapshots inmutables, políticas, agentes de inferencia, Task Manager, FSM, coordinación, recursos y almacenamiento. Los módulos no dependen de Flask ni del DOM. No se duplican drivers I2C/UART: se adaptan los agentes físicos del servicio Rust ya funcional. El orquestador es la única autoridad que emite comandos de inferencia durante un experimento.

Un hilo aloja el event loop de coordinación; la adquisición MQTT dispone de su propio hilo y una cola limitada de 32 mensajes. YOLO/cámara tiene un worker dedicado; Gemma usa otro worker para HTTP contra el proceso LiteRT-LM independiente. Las inferencias no se ejecutan en el event loop. Los ciclos tienen ID, plazo, historial, máximo de solicitudes y como máximo una solicitud visual. E registra la interpretación asíncrona y vuelve a WAIT sin esperar a Gemma. Datos recientes continúan entrando durante las inferencias.

Los timestamps de adquisición son UTC con zona horaria; el timestamp de cámara se toma justo antes de `capture_file`, después del calentamiento, y no representa una sincronización por hardware. Duraciones, plazos internos y vigencias usan reloj monotónico, incorporando la edad inicial de las observaciones MQTT. Se rechazan paquetes duplicados, fuera de orden o demasiado adelantados; sincroniza los relojes de los publicadores. Los resultados de Gemma siempre conservan la imagen y el snapshot originales, y nunca escriben observaciones.

Las imágenes experimentales no se guardan en el sandbox ni en SQLite. Se limita su tamaño a 2 MB; E conserva como máximo una imagen reciente durante 120 s para admitir solicitudes nuevas. Las solicitudes aceptadas pueden retener su propia referencia mientras sea necesaria para una inferencia activa. Una imagen en cola se descarta al expirar. Al finalizar se vacían pendientes y referencias; una inferencia activa conserva lo necesario hasta terminar. Los temporales de captura se eliminan incluso ante fallo. Los registros conservan identificadores, no fotografías.

Un timeout lógico no libera el worker hasta que termine físicamente. La API de LiteRT utilizada no aporta cancelación remota verificable: un timeout o una desconexión HTTP deja el estado remoto incierto y **bloquea nuevas llamadas a Gemma**, en vez de presumir que se liberó memoria. El monitoreo y las respuestas por reglas continúan. Para recuperar ese worker, comprueba/reinicia el runtime LiteRT y reinicia el panel; no basta con pulsar Finalizar. Los resultados tardíos se registran como históricos. Al reiniciar, las ejecuciones que quedaron abiertas se marcan `INTERRUPTED`.

## Registros y ground truth

### Experimentación guiada de 30 minutos

En **Experimentación**, selecciona escenario S1–S3, modo A–F y repetición 1–3. **Comenzar** solicita observador, identificación del vatímetro, equipos medidos, región, W y personas iniciales. El reloj empieza al guardar. El guion original permanece disponible y el mismo panel de Medición se muestra dentro de Experimentación, sin duplicar sensores, controles ni IDs. Las ejecuciones guiadas exigen `runtime.max_run_seconds: 1800`; las políticas de adquisición e interpretación mantienen su autoridad.

El backend detiene la ejecución al completar 1800 segundos aunque el navegador esté cerrado. No inicia tareas en cola al vencer el plazo. Los workers activos pueden terminar después; sus resultados tardíos quedan registrados y no actualizan las respuestas de la ejecución cerrada. Se mantiene la reserva hasta vaciar los workers; un estado remoto incierto sigue exigiendo recuperación del runtime. También puedes finalizar antes: se registra la duración real y el motivo, sin presentarla como una ejecución completa de 30 minutos.

Los diálogos solicitan W cada 60 segundos en todos los modos, en los cambios de etapa del guion, en eventos confirmados y al iniciar/finalizar/fallar/expirar las tareas. YOLO solicita además personas al iniciar su tarea; los cambios del guion y el cierre solicitan personas y acción real. **Registrar evento real** permite anotar cambios no previstos. El operador debe registrar lo observado o declarar cada campo **no observado**, con motivo. **Dejar pendiente** conserva la obligación y no pausa ni borra datos. Los pendientes sobreviven a recargas y reinicios; pueden completarse desde el historial incluso después de finalizar. Las estimaciones visuales se ocultan mientras falta una observación humana de personas; Auto/Manual de presencia está disponible en B–F también durante ejecuciones guiadas y cada cambio se registra como intervención explícita. No se usa ground truth para dirigir las inferencias.

Cada respuesta conserva solicitud, evento/tarea de origen, hora del evento observado, hora real de lectura W, hora de observación de personas y hora de registro. Si la observación de personas corresponde a la captura, indica esa hora; una observación posterior no se considera automáticamente verdad para la imagen anterior. Un aviso puede llegar cuando una inferencia breve ya terminó: registra la diferencia temporal o declara que no la observaste. El vatímetro mide el conjunto declarado de equipos, no exclusivamente Gemma. **W es potencia instantánea**: no se inventan W por segundo ni se calculan Wh a partir de estas lecturas.

`samples_1s` guarda como máximo una fila por segundo transcurrido (segundos 0–1799). Incluye observaciones con ID, timestamp original, edad y estado; FSM, tareas y necesidades; CPU/RAM del sistema y SENSE, swap, temperatura/throttling y procesos Gemma observables. Los recursos se consultan cada segundo con el YAML suministrado y conservan su propia fecha y edad. Un campo no observable queda `null`. Los saltos del muestreador producen `SAMPLE_GAP`; no se reconstruyen silenciosamente. El resumen distingue muestras perdidas, sensores incompletos, fallos/timeouts y observaciones pendientes/no observadas. Los inicios/finales reales de los workers se registran dentro del worker y no se confunden con el instante en que el coordinador los recoge.

**Descargar CSV · ZIP** está disponible durante y después de la ejecución. Entrega un snapshot consistente de SQLite, aunque sigan llegando datos: `metadata.json`, `samples_1s.csv`, `events.csv`, `observations.csv`, `inference_tasks.csv`, `question_results.csv`, `ground_truth.csv`, `power_readings.csv`, `observer_requests.csv`, `images.csv`, `faults.csv` y un LEEME. Los CSV usan UTF-8 con BOM; las celdas vacías representan datos desconocidos. Los campos anidados conservan JSON. Se relacionan por `run_id`, `task_id`, `request_id`, IDs de evidencia e imagen. `images.csv` contiene referencias, no fotografías. Una descarga durante una ejecución es parcial; vuelve a descargar tras resolver pendientes y terminar los workers para incorporar los resultados posteriores. El NDJSON original sigue disponible e incluye muestras y solicitudes.

La migración añade solo `samples_1s`, `observer_requests` e índices a la base existente. Observaciones, decisiones, tareas y respuestas se reutilizan desde los eventos originales; los CSV son proyecciones para análisis. No se borran ni se rellenan registros históricos que no tenían estas mediciones.

En `events.csv`, `timestamp_utc` usa la hora del evento original cuando existe y `recorded_at` indica su persistencia. El porcentaje CPU del proceso sigue la definición de `psutil` y puede superar 100% al sumar varios núcleos; la CPU total representa el conjunto del sistema. En una interrupción, el final real puede ser desconocido: los metadatos indican cuándo se detectó y marcan `end_time_uncertain`. También se corrigió el adaptador del radar para conservar la presencia según `state_code`, seleccionar la distancia del blanco activo y permitir confirmar ausencia sin inventar distancia; se conservan todas las distancias originales.

SQLite en `data/experiments.sqlite3` conserva configuración, versiones de dependencias/modelos, hash del detector NCNN, observaciones, snapshots, necesidades, razones positivas y negativas, comandos, transiciones, entradas/salidas/validación/tokens del SLM, duraciones y recursos. Las escrituras de cada ciclo se agrupan en una transacción para reducir escrituras en la SD. Las colas descartan solicitudes nuevas al saturarse y registran la pérdida. Se limita la base inicialmente a 512 MB y se exige espacio libre; no se borran experimentos automáticamente. Exporta/archiva los registros antes de alcanzar el límite.

La CPU/RSS del proceso principal incluye los threads de YOLO; se identifican por separado procesos LiteRT observables y la carga/swap total. Pico RSS y swap del proceso se leen de `/proc` en Linux; temperatura y `vcgencmd get_throttled` se registran cuando están disponibles. Los campos no observables quedan `null`. **No se deriva energía de CPU.**

API de consulta y descarga:

```text
GET  /api/experiments                         últimas 100 ejecuciones
GET  /api/experiments/<run_id>?after=<sequence> metadatos + hasta 200 eventos
GET  /api/experiments/<run_id>/export          NDJSON en streaming
POST /api/experiments/query                   {"question_id":"Q3"}
POST /api/experiments/<run_id>/human-records
```

El último endpoint registra en una tabla separada del sistema predictivo. Ejemplos de cuerpo JSON:

```json
{"kind":"GROUND_TRUTH","payload":{"observed_at":"2026-10-24T20:05:02+00:00","region":"camera_view","visible_people":3,"observer":"operador"}}
```

```json
{"kind":"EXTERNAL_ENERGY","payload":{"observed_at":"2026-10-24T20:35:02+00:00","scope":"whole_run","value":2.4,"unit":"Wh","instrument":"medidor externo"}}
```

Conserva las mismas preguntas, detector y configuración entre comparaciones. Controla también las condiciones de recursos al comparar C/D/E. D no recibe imágenes; E sí añade acceso visual original, diferencia que debe figurar en el análisis experimental.

## Verificación sin hardware

```sh
.venv/bin/python -m unittest discover -s tests -v
node --test tests/measurement.test.cjs tests/experiment.test.cjs
```

Las pruebas usan hardware/modelos simulados; no descargan modelos ni inician inferencias reales. Cubren contratos, episodios, frescura, políticas, colas, asincronía, resultados históricos, persistencia, API y comportamiento DOM. Hace falta ejecutar el piloto con los sensores, cámara y LiteRT reales para caracterizar latencia, memoria, disponibilidad y calidad de las salidas. No constituye validación científica ni revisión visual en navegador.
