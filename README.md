# SENSE · Raspberry Pi 5

El panel conserva Preparación y su sandbox. Medición añade una FSM común, cinco políticas experimentales y un pipeline que muestra transiciones reales. No requiere dependencias nuevas sobre el entorno existente.

## Ejecutar

Mantén el servicio Rust que publica `rustio.iot.telemetry.v1` y el broker MQTT. En otra terminal inicia Gemma con el `run.sh` existente y después el panel:

```sh
sh run.sh
# Otra terminal, con el entorno Python existente activado:
python main.py
```

Abre `http://<raspberry>:5000`, espera a que termine la preparación y entra en Medición. Selecciona A–E y pulsa **Comenzar**. El botón cambia a **Finalizar**. Los desplegables contienen Q1–Q7, consultas explícitas, interpretaciones históricas, decisiones, recursos y descargas. Un error de preparación permite monitoreo degradado; el sandbox mantiene sus requisitos originales. Durante una medición y mientras se vacían workers, las operaciones manuales quedan bloqueadas para evitar competencia y contaminación experimental.

No reinstales el entorno que ya funciona. Se reutilizan Flask/SSE, MQTT, `requests`, `psutil`, PyYAML y YOLO/NCNN; SQLite, colas, contratos y coordinación `asyncio` usan la biblioteca estándar. Picamera2 continúa procediendo del sistema de la Pi, como antes. No se añaden frameworks multiagente, servicios de colas ni dependencias de frontend.

## Configuración de piloto

Edita [sense/pilot.yaml](sense/pilot.yaml) antes de experimentar. `SENSE_CONFIG` permite elegir otro archivo; `SENSE_DATA_DIR` cambia el directorio de registros. La configuración se vuelve a leer y validar al iniciar cada ejecución y queda congelada en su registro, junto con su versión y SHA-256. Un campo obligatorio ausente, `null`, no finito o fuera de rango bloquea el inicio.

Los valores pedidos de +1 °C, +5 puntos de humedad, +1 nivel AQI, cruce de 700 ppm eCO₂, ventana de 300 s, tres muestras, cooldown de 30 s y vigencia visual de 60 s están incluidos. **Todos son provisionales, no resultados científicos.** Los límites adicionales son propuestas iniciales para poder caracterizar el sistema: rearme eCO₂ a 650 ppm equivalentes, rearme térmico a +0.5 °C y de humedad a +2.5 puntos, máximo diez visiones/300 s, una inferencia Gemma activa y una en espera (se rechaza la nueva al saturarse), plazos de 20/90/180 s para visión/texto/multimodal y ejecución de hasta 1800 s. Hay presupuestos separados para cada modalidad generativa y límites globales de memoria, CPU y almacenamiento.

La versión suministrada requiere al menos 1024 MB disponibles y limita el RSS del proceso principal a 2048 MB y la CPU total al 95% para admitir nuevas inferencias. Estos valores pueden resultar restrictivos con el modelo real: ajustarlos exige medición en la Pi. No se asegura que `run.sh --mode full` o `--mode limit` sea óptimo; deben compararse durante el piloto y mantenerse constantes entre modos comparados.

Las regiones iniciales están marcadas como **no verificadas**. Antes de un experimento final configura las coberturas reales; radar y cámara no se comparan por defecto. `radar_camera_comparable: true` solo corresponde si el alcance declarado hace comparables presencia y conteo; también se exige proximidad temporal. El perfil debe describir la ubicación y cobertura efectiva. La ausencia del radar nunca representa automáticamente toda el aula.

## Reglas y preguntas

- **A:** YOLO en calendario anclado al inicio, inicialmente cada 30 s. No recupera en ráfaga intervalos vencidos; registra períodos perdidos por ocupación del worker o restricciones de recursos. Reglas para interpretación.
- **B:** solo transiciones confirmadas presencia/ausencia del radar, con tres muestras consecutivas y mínimo 30 s entre capturas. La primera lectura establece referencia y no es una transición. Un disparador pendiente puede posponerse por presupuesto. Reglas para interpretación.
- **C/D/E:** exactamente la misma adquisición visual, basada en Q2, estado del conteo, conflictos comparables, disponibilidad, cooldown y presupuesto. Q2 se evalúa automáticamente, por lo que inicia una captura al desconocer el conteo y lo renueva al vencer. Un episodio ambiental aislado no genera otra captura si el conteo vigente es suficiente. Las preguntas que solo necesitan radar o ambiente no autorizan cámara adicional.
- **Q1–Q5:** reglas deterministas. Q4 informa episodios confirmados y distingue ventana incompleta/datos insuficientes de ausencia de cambios. Q5 conserva las limitaciones de fuente, región y tiempo.
- **Q6:** las reglas describen coincidencia temporal si existe un episodio y presencia/conteo próximos dentro de la ventana configurada. Dos o más tipos de cambio ambiental entre los últimos cuatro episodios, con evidencia de ocupación comparable, constituyen la necesidad inicial de síntesis adicional. C conserva su respuesta determinista parcial; D/E pueden solicitar texto a Gemma. No se infiere causalidad. Sin esa necesidad, las reglas bastan y no se invoca el modelo.
- **Q7:** exclusiva de E. Describe una imagen obtenida legítimamente por la política compartida. La necesidad inicial es una descripción de referencia; luego solo se considera una descripción adicional cuando cambia el conteo, aparece un nuevo episodio ambiental o existe una consulta explícita. No se llama al modelo para cada imagen ni se captura una foto únicamente para Q7. No identifica personas ni reemplaza conteos o sensores.

La deduplicación generativa usa pregunta, valores/estados/regiones relevantes, episodios, versión del modelo e imagen cuando corresponde; excluye timestamps e identificadores nuevos de observación. Una solicitud equivalente fallida o rechazada por validación no se repite indefinidamente sobre el mismo contexto. Las respuestas del modelo deben cumplir JSON y referenciar evidencia conocida; sus hechos observados deben copiar exactamente observaciones vigentes. Una validación estructural no demuestra la veracidad de las inferencias del modelo.

Temperatura, humedad y AQI comparan contra una muestra válida próxima al inicio de la ventana completa (tolerancia inicial 10 s). No se interpola. La referencia se congela desde la candidatura hasta la recuperación confirmada; después se vuelve a reunir una ventana de muestras posterior al rearme. La línea base de sesión no cambia. Lecturas inválidas y huecos superiores a seis segundos rompen la confirmación. eCO₂ requiere una lectura inferior a 700 antes del cruce inicial; tras un episodio requiere recuperar a 650 durante tres muestras. AQI repetido no produce episodios nuevos.

## Ejecución, memoria y fallos

`sense/` separa adquisición MQTT, contratos, contexto/snapshots inmutables, políticas, agentes de inferencia, Task Manager, FSM, coordinación, recursos y almacenamiento. Los módulos no dependen de Flask ni del DOM. No se duplican drivers I2C/UART: se adaptan los agentes físicos del servicio Rust ya funcional. El orquestador es la única autoridad que emite comandos de inferencia durante un experimento.

Un hilo aloja el event loop de coordinación; la adquisición MQTT dispone de su propio hilo y una cola limitada de 32 mensajes. YOLO/cámara tiene un worker dedicado; Gemma usa otro worker para HTTP contra el proceso LiteRT-LM independiente. Las inferencias no se ejecutan en el event loop. Los ciclos tienen ID, plazo, historial, máximo de solicitudes y como máximo una solicitud visual. E registra la interpretación asíncrona y vuelve a WAIT sin esperar a Gemma. Datos recientes continúan entrando durante las inferencias.

Los timestamps de adquisición son UTC con zona horaria; el timestamp de cámara se toma justo antes de `capture_file`, después del calentamiento, y no representa una sincronización por hardware. Duraciones, plazos internos y vigencias usan reloj monotónico, incorporando la edad inicial de las observaciones MQTT. Se rechazan paquetes duplicados, fuera de orden o demasiado adelantados; sincroniza los relojes de los publicadores. Los resultados de Gemma siempre conservan la imagen y el snapshot originales, y nunca escriben observaciones.

Las imágenes experimentales no se guardan en el sandbox ni en SQLite. Se limita su tamaño a 2 MB; E conserva como máximo una imagen reciente durante 120 s para admitir solicitudes nuevas. Las solicitudes aceptadas pueden retener su propia referencia mientras sea necesaria para una inferencia activa. Una imagen en cola se descarta al expirar. Al finalizar se vacían pendientes y referencias; una inferencia activa conserva lo necesario hasta terminar. Los temporales de captura se eliminan incluso ante fallo. Los registros conservan identificadores, no fotografías.

Un timeout lógico no libera el worker hasta que termine físicamente. La API de LiteRT utilizada no aporta cancelación remota verificable: un timeout o una desconexión HTTP deja el estado remoto incierto y **bloquea nuevas llamadas a Gemma**, en vez de presumir que se liberó memoria. El monitoreo y las respuestas por reglas continúan. Para recuperar ese worker, comprueba/reinicia el runtime LiteRT y reinicia el panel; no basta con pulsar Finalizar. Los resultados tardíos se registran como históricos. Al reiniciar, las ejecuciones que quedaron abiertas se marcan `INTERRUPTED`.

## Registros y ground truth

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
node --test tests/measurement.test.cjs
```

Las pruebas usan hardware/modelos simulados; no descargan modelos ni inician inferencias reales. Cubren contratos, episodios, frescura, políticas, colas, asincronía, resultados históricos, persistencia, API y comportamiento DOM. Hace falta ejecutar el piloto con los sensores, cámara y LiteRT reales para caracterizar latencia, memoria, disponibilidad y calidad de las salidas. No constituye validación científica ni revisión visual en navegador.
