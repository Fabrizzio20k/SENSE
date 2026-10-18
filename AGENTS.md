# Continuidad de RustIO / SENSE

Último estado documentado: **17 de octubre de 2026**. Este archivo permite continuar el trabajo sin depender del historial del chat. Actualizarlo cuando cambien decisiones, evidencia de pruebas o próximos pasos.

## Objetivo y acuerdos con el autor

- El trabajo activo es el prototipo independiente en **`python_prueba/`**, destinado a una Raspberry Pi 5 de 8 GB. Priorizar funcionalidad, trazabilidad experimental y documentación para la tesis; la UI solo necesita ser operativa.
- No migrar ni ampliar el código Rust por inferencia. La tesis todavía menciona Rust; el autor eligió Python para esta versión.
- **Instrucción vigente: no ejecutar aquí el programa, pruebas, modelos, conversiones ni instalaciones.** Leer y editar archivos está autorizado. Los comandos del README son instrucciones para que el autor los ejecute en la Pi. No interpretar «continuar» como revocación de esta restricción ni pedir permiso para cada edición rutinaria.
- Inferencia siempre local. MQTT, LiteRT-LM y cámara son dependencias de la Pi; no sustituirlos por servicios de nube. La descarga inicial de pesos es preparación, separada de la inferencia y las mediciones.
- Documentar cada decisión material con motivo, procedencia, límite de afirmación y verificación pendiente. Diferenciar requisito del PDF, instrucción posterior del autor, dato observado y elección de ingeniería.
- No afirmar que «ya funciona», está validado o produjo ahorro/precisión por haber escrito el código. Hasta este corte **no hay resultados comunicados de pruebas integradas en la Pi**.
- Último reporte del autor: `crypto.randomUUID is not a function` en la interfaz. Se corrigió por lectura con alternativas para HTTP sobre IP; el autor pidió además captura/conteo reales y lectura de cada sensor antes de admitir sesiones, y ordenar la pantalla. No se reprodujo ni verificó la corrección ejecutándola aquí.

## Dónde retomar

Leer en este orden, según el trabajo:

1. [README de Python](python_prueba/README.md): instalación, `.env`, arranque, API y recuperación.
2. [16 — Versión Python](python_prueba/docs/16-version-python.md): implementación efectiva, decisiones recientes, invariantes y pruebas pendientes.
3. [14 — Umbrales](python_prueba/docs/14-umbrales-y-activacion.md) y [15 — Línea base/desfases](python_prueba/docs/15-analisis-linea-base.md): números, procedencia y límites.
4. [01 — Requisitos del PDF](python_prueba/docs/01-requisitos-del-pdf.md), [09 — Fuentes](python_prueba/docs/09-fuentes.md) y el [índice de documentación](python_prueba/docs/README.md).
5. Para piloto/evaluación: documentos 07, 10, 11 y 13 del índice.

**Tesis actual:** [python_prueba/docs/main.pdf](python_prueba/docs/main.pdf). El autor la movió desde la raíz. Se comprobó por lectura de hash que conserva el SHA-256 registrado: `01d11cd74e23183d7a57f3d73c79ba06dfa91427d593498bfd69a756fe0a65be`. No es necesario repetir la extracción del PDF para cada cambio de código; usar las páginas ya referenciadas en 01/09 cuando corresponda.

Algunos documentos de diseño conservan texto histórico como «pendiente de implementar». Contrastar con 16 y el código actual; no reconstruir funcionalidades que ya existen. El antiguo `questions.md` no está disponible en el estado observado del repositorio; los pendientes que sí están documentados se resumen debajo, sin inventar el contenido de aquellas preguntas.

## Estado real del avance

| Área | Estado y evidencia |
|---|---|
| Requisitos y diseño | Matriz de trazabilidad del PDF, arquitectura/FSM, criterios A–D, controles y protocolo en docs 01–14. Son diseño y candidatos, no resultados finales. |
| Registro de telemetría | Original preservado, análisis descriptivo y derivados existentes en docs/data y docs/analysis; explicación en 15. No se recalculó durante este traspaso. |
| Núcleo anterior | Antes de la instrucción de no ejecutar, se instalaron dependencias en un `.venv` del Mac y se comprobó una versión anterior de sensores/reglas. Eso no verifica la entrega ampliada. |
| Prototipo ampliado | Código escrito y revisado por lectura: MQTT, FSM, políticas, visión, SLM, API/SSE, persistencia, controles y exportación. **Arranque integrado y hardware pendientes de prueba.** |
| Incorporaciones recientes | Preparación automática, calentamiento multimodal, requirements/`.env`, comprobación real de captura/conteo y sensores, diagnóstico en segundo plano y panel ordenado. No instaladas ni ejecutadas aquí. |
| Pruebas | Escritas en `python_prueba/tests/`: system, actions, prepare, settings y startup; `test_ui.cjs` para alternativas a randomUUID, Node opcional solo para esa prueba. No ejecutadas sobre esta versión ampliada por instrucción del autor. |

## Mapa de responsabilidades

Todas las rutas de esta tabla son relativas a `python_prueba/`.

| Archivo | Responsabilidad |
|---|---|
| `context.py` | Contrato MQTT, validación por fuente, ventanas, presencia, calidad y perfiles candidatos. |
| `orchestrator.py` | FSM por episodio, snapshots/hash, reglas, fallos y degradación. |
| `mqtt_ingest.py` | Una suscripción Paho; callbacks solo encolan, cola acotada. |
| `actions.py` | Políticas A–D/E_visual, cola pesada, guardas, presupuestos, seguimientos y cancelación. |
| `vision.py` | Worker de Picamera2/YOLO NCNN, captura/metadata del mismo request, validación de artefacto y fusión entre mosaicos. |
| `prepare.py` | Reutilización o exportación NCNN previa, bloqueo por destino, carpeta temporal y procedencia. |
| `slm.py` | Cliente LiteRT-LM local, sondeo, transformación visual compartida, calentamiento y respuestas estructuradas validadas. |
| `runtime.py` | Settings/`.env`, ciclo vivo/replay, exclusión preparación/admisión, preflight y manifiesto. |
| `store.py`, `experiment.py` | SQLite/WAL, eventos, reservas persistentes, doce tablas CSV/ZIP/JSONL, recursos y energía estimada. |
| `app.py`, `static/index.html` | API FastAPI, límites/validación HTTP, SSE y UI básica de experimentación. |
| `requirements.txt`, `pyproject.toml` | Una lista de dependencias sin fijar versiones; setuptools lee requirements. |
| `static/image.png` | Imagen aportada por el autor para el calentamiento de Gemma. Copiarla también a la Pi. |

## Criterios que no deben perderse

### Evidencia y tiempo

- Esquema `rustio.iot.telemetry.v1`, dispositivo `rpi5-01`, tópico `rustio/rpi5-01/telemetry`; MQTT local por defecto, puerto 1883, suscripción QoS 0.
- Distinguir estado físico, conocimiento disponible y estado de la FSM. Ausencia de datos no equivale a cero personas ni a cero ambiental.
- Validar por fuente: un bloque ENS160 inválido no borra SHT40/radar. Conservar timestamps, unidades, procedencia, recepción y limitaciones.
- El tiempo vivo usa recepción monotónica como **aproximación**. Adquisición física por sensor, calidad instrumental y desfase radar–cámara siguen sin verificar. No aplicar una compensación temporal fija inventada.
- Radar: `0` significa ausencia declarada; `1/2/3`, presencia declarada en su cobertura. Un código desconocido no es ausencia. No reconstruir presencia a partir de energías o distancias aisladas.
- Emparejar radar previo a captura; sin relojes/cobertura común comprobados, el contraste es `not_comparable`. Retenidos, duplicados, fuera de orden e imágenes subidas no rejuvenecen evidencia en vivo.
- eCO2 es estimado, no CO2 medido. TVOC/eCO2 del ENS160 no son dos corroboraciones independientes. No deducir gases, peligros certificados ni límites de seguridad de este piloto.

### Umbrales confirmados para empezar

Son **`pilot_candidate`**, no parámetros calibrados ni límites de seguridad. Valores centrales en `context.py`; justificación en docs 14–15.

| Magnitud | Apertura por cambio absoluto | Banda de retorno |
|---|---:|---:|
| Temperatura | 0.5 °C | 0.25 °C |
| Humedad relativa | 3 puntos porcentuales | 1.5 puntos porcentuales |
| TVOC | 50 ppb | 25 ppb |
| eCO2 | 100 ppm | 50 ppm |

- Comparar mediana reciente de 30 s con los 120 s anteriores, sin solapamiento; historia inicial de 150 s. Mínimos 12/48 muestras y cobertura temporal, sin rellenar huecos.
- Cambio sostenido 10 s; recuperación 20 s respecto de la referencia conservada. Detectar aumentos y descensos, conservar el signo y evitar reaperturas por cada publicación.
- Debounce radar 2 s; watchdog de recepción MQTT 7 s. El watchdog no demuestra cadencia física ni sensor interno congelado.
- Perfil operativo: visión periódica/TTL visual 30 s, cooldown 5 s, visión hasta 90 s, SLM hasta 120 s, episodio hasta 240 s incluyendo cola; concurrencia pesada 1, cola 8; máximo dos seguimientos cada 30 s dentro de 180 s; salida SLM principal hasta 384 tokens.
- Guardas candidatas: reserva 512 MiB y temperatura CPU menor que 80 °C cuando existe lectura. Verificar en piloto; no demuestran RAM suficiente ni plazos correctos.
- Arranque: esperar hasta 30 s adicionales, después de los chequeos pesados, para recibir datos válidos recientes de los tres sensores y conectar MQTT; `startup_sensor_timeout_s` en el perfil operativo. No es TTL físico ni tiempo de estabilización del ENS160.

### Comparación y límites del experimento

- `rules-v1`: sensores y reglas. A: visión periódica; B: entrada radar confirmada; C: renovación por necesidad/vigencia; D: misma adquisición que C más interpretación condicional. `monitor_count=true` para comparar conteo A–D.
- `E_visual`: descripción directa de imagen, experimento separado. D no recibe imágenes adicionales frente a C en el contraste interpretativo; usar el mismo snapshot persistido cuando se compare una interpretación.
- Una lectura o cambio ambiental no justifica por sí solo activar cámara. Preguntas deterministas se responden por reglas; el SLM no selecciona herramientas libres ni consigue evidencia adicional.
- Thinking solicitado siempre desactivado, cero reintentos generativos automáticos dentro de una acción. Una respuesta sin pensamiento visible no demuestra que el runtime haya desactivado internamente thinking.
- Snapshots/evidencias con hash; anotaciones y evaluaciones humanas fuera de la política/prompts. No reciclar interpretaciones como nuevas mediciones.
- Recursos nominales a 1 Hz; ausentes `null`. W por trapecios, hueco máximo 60 s y sin extrapolar extremos; contador Wh/kWh se trata aparte. No atribuir picos ni energía breve no observados.
- Replay: solo las 490 líneas válidas conocidas y `rules-v1`, tiempo virtual, sin imágenes ni W físicos. No usarlo para afirmar rendimiento A–D.
- Los perfiles solo admiten desarrollo/piloto; faltan referencia humana, calibración y congelación para evaluación final. No inventar F1, ahorro energético o superioridad del SLM.

## Decisiones recientes de instalación y arranque

- **`.env` automático:** `Settings.environment()` carga `python_prueba/.env` mediante `python-dotenv` antes de validar; ruta relativa al código y prioridad de variables ya presentes en el entorno. `.env.example` es plantilla, no se carga como configuración. No hace falta `source`; reiniciar tras editar.
- **Dependencias:** `pip install --upgrade -r requirements.txt` solicita versiones estables recientes compatibles, incluida Ultralytics. No se verificó esa resolución en ARM64. Picamera2/libcamera vienen de Raspberry Pi OS; usar Python compatible y venv con `--system-site-packages`, sin copiar el `.venv` del Mac. Archivar versiones y no actualizarlas entre repeticiones.
- **Gemma:** el script raíz `run-litert.sh` pertenece al flujo existente del autor. Python no lo inicia/reconfigura. Defaults coincidentes: `http://127.0.0.1:8080`, `gemma4-e2b`, CPU, thinking solicitado desactivado. Cliente restringido a HTTP loopback y sin proxies del entorno.
- **YOLO:** destino predeterminado `data/models/yolo26n_320_ncnn_model`, pesos `data/models/yolo26n.pt` bajo `python_prueba/` o `SENSE_DATA_DIR`. Rutas opcionales `SENSE_VISION_MODEL`/`SENSE_VISION_WEIGHTS`. Exporta solo si falta: NCNN, `imgsz=320`, `quantize=16` (FP16 solicitado, no INT8), CPU. El tamaño 640 necesita artefacto/configuración coincidentes.
- Reutilizar export válido; exigir archivos no vacíos `.param`, `.bin`, `metadata.yaml`, tamaño compatible y clase 0 `person`. Una carpeta existente inválida se conserva y rechaza. Validar archivos no demuestra inferencia real. El peso estándar ausente puede descargarse; el preparador no instala paquetes.
- **Calentamiento vigente:** `gemma-image-warmup-v1` reemplaza el antiguo «OK» de texto. Envía `static/image.png`, pide una palabra en español sobre lo visible, máximo 16 tokens, temperatura 0, `reasoning_effort=none`. Comparte transformación con consultas: RGB, JPEG calidad 85, lado mayor 480 por defecto (`SENSE_SLM_IMAGE_SIDE`). No abre cámara ni usa YOLO.
- Calentamiento una vez al arrancar o al pedir preparación explícita; no por cada sesión después de éxito. Si Gemma faltaba, corregir y repetir la comprobación antes de iniciar. `SENSE_SLM_WARMUP=0` permite omitirlo para ensayos de frío controlados de Gemma; no garantiza estado frío. Tras reiniciar LiteRT-LM aparte, repetir preparación: el catálogo no identifica su nueva instancia.
- Preflight/manifiesto registran resultado, duración, prompt, respuesta, hashes original/JPEG, dimensiones y versiones. El hash de adquisición incluye perfil e imagen de calentamiento. `image_request_completed=true` no certifica corrección semántica ni operaciones internas del encoder; `visual_encoder_verified=false` sigue explícito.
- **Comprobación funcional nueva:** conectar ingesta antes de preparar, capturar con Picamera2 y contar con YOLO (90 s), validar JPEG/hash/dimensiones/conteo/cajas; cero personas es válido. Eliminar la foto temporal y conservar resumen en `preflight.camera`, con `inference_verified=true` solo tras éxito. No alimenta el conteo ni las historias de una sesión.
- Exigir publicaciones válidas de SHT40/ENS160/radar posteriores al inicio de la comprobación y de menos de 7 s al admitir, excluyendo retenidos/repetidos/fuera de orden. La calidad física sigue sin verificar. El diagnóstico muestra recepción actual incluso sin sesión.
- Conversión, calentamiento y captura/conteo de prueba fuera del reloj experimental y serializados con admisión. El worker YOLO normalmente queda cargado: las sesiones posteriores no son primera inferencia fría. Fijar condición inicial/estabilización iguales entre comparadores.
- **Admisión viva estricta:** todas las variantes, incluido `rules-v1`, requieren broker, tres sensores, captura/conteo y Gemma listos, con calentamiento si está habilitado. Sustituye la admisión anterior de reglas con modelos incompletos. Replay mantiene su excepción sin hardware. Si fallan componentes, la página diagnóstica sigue disponible, sin admitir sesiones.
- `/health` es pasivo: último chequeo de modelos/cámara más recepción actual de sensores; no sondea ni infiere. Informa `preparing` y `can_start_session`. `POST /v1/runtime/prepare` con `{}` devuelve 202 e inicia/reutiliza la misma comprobación en segundo plano, solo fuera de sesión. El panel consulta el progreso; no hay bucle automático de reintentos pesados. Detalle en `data/preflight.json`, procedencia del export en `preparation.json`.
- Panel en tres etapas: comprobación, configuración de sesión y lecturas/decisiones. Inicio bloqueado tanto en navegador como en backend. Clave de idempotencia con alternativas sin `randomUUID`/`crypto`; conservarla al perder respuesta de creación. Actualizar archivos en la Pi, reiniciar API y recargar la página para retirar el script anterior.
- **Reservas:** timeout/cancelación HTTP no demuestra detención remota. `slm_busy`/`camera_busy` persisten incluso tras reinicio; no borrarlos automáticamente. Verificar detención antes de `POST /v1/runtime/confirm-idle` con confirmación y nota del operador. Un fallo local previo al envío o respuesta completa rechazada libera la reserva correspondiente. Un worker sin salida confirmada mantiene el bloqueo.

## Evidencia de telemetría que ya existe

- Original: `python_prueba/docs/data/2026-10-17-baseline-recibido.txt`; SHA-256 `2b47eda963f45490bedda4590f637f8cd6a700a47e6e0ee2f313c7eb920a3ce7`.
- 490 mensajes completos, última línea 491 truncada y excluida sin reparación; 489 intervalos, mediana 2.014112 s, duración 984.938503 s. Hay 42 cambios de modo radar y 4 de presencia binaria.
- Los 6.938503 s frente a una cuadrícula hipotética de 2 s **no son un desfase medido de relojes**. No hay recepción/acquisición por fuente ni imágenes pareadas para calcularlo.
- Script y resultados existentes en `docs/analysis/`; 15 documenta el método. No tratar 490 muestras como 490 réplicas independientes ni variabilidad de una sesión como error calibrado.

## Próximos pasos, en orden

1. Retomar el estado de la Pi con lo que comunique el autor; no asumir una ejecución exitosa ni repetir instalaciones por iniciativa propia.
2. El autor debe trasladar `python_prueba/` completo (incluidos `static/image.png` y el fixture de replay), preparar el entorno de la Pi y levantar Gemma/MQTT según el README. No trasladar el `.venv` del Mac.
3. Primera aceptación: página diagnóstica visible durante preparación; seis componentes listos, lectura válida por sensor, foto/conteo real (incluido cero) y calentamiento de una palabra. Verificar que el botón se habilite solo entonces y que no aparezca el error de randomUUID en el navegador de uso. Comprobar errores de cámara/modelo, imagen ausente y reserva pendiente sin bucles automáticos.
4. Probar primero `rules-v1`: sensores por fuente, ventanas, debounce, silencio/restauración y exportación. Después C con `monitor_count=true`: captura, colores, conteo y tiempos. Luego D: interpretación con evidencia; `E_visual` por separado.
5. Ejecutar las pruebas preparadas **en el entorno que el autor habilite para ello**, y verificar hardware real aparte. Hasta entonces no cambiar «escritas» por «pasadas». Ante fallos, pedir logs concretos, `/health`, versiones y petición usada, sin credenciales, y corregir en la capa responsable.
6. Validar continuidad de MQTT bajo carga, cola/cancelación, cierre de procesos, flags tras reinicio, exportación consistente e instrumentación. Archivar versión resuelta de dependencias y modalidad de calentamiento.
7. Medir los pendientes siguientes, calibrar el perfil con referencia humana y congelar protocolo/configuración antes de recoger datos finales. Adaptar la metodología de la tesis a Python, visión directa separada y método de potencia efectivamente usado.

## Pendientes de medición y metodología

- Semántica del timestamp global del productor, adquisición por sensor, secuencia/boot ID, calidad y calentamiento del ENS160; TTL físico aplicable a cada pregunta.
- Relojes e incertidumbre de radar/cámara, `SensorTimestamp`/BOOTTIME y cobertura común; decidir `crossmodal_max_skew_s` después de medir, no asignar un desfase por conveniencia.
- Latencias y consumo frío/caliente de captura, NCNN y Gemma multimodal, con ingesta e instrumentación; suficiencia de plazos, RAM, temperatura y cooldown.
- Escenas/ROI, sensibilidad de conteo y mosaicos, falsas detecciones, condiciones ambientales etiquetadas y omisiones/demoras de las ventanas candidatas.
- Compatibilidad real de LiteRT-LM con campos enviados, thinking desactivado, imagen y cancelación; validar efectos del calentamiento, no suponerlos por recibir una palabra.
- Objetivos/antigüedad aceptable, guion, referencia humana independiente, rúbrica, retención de imágenes y autorización aplicable. Las propuestas de bloques/escenarios de docs 07/11 aún no prueban potencia estadística.
- Actualizar las diferencias documentales del PDF antes de la evaluación final; no modificar la tesis ni presentar inferencias como resultados sin solicitud/evidencia.

## Al cerrar la próxima sesión

Registrar brevemente cambios, criterios, archivos afectados, pruebas realmente ejecutadas y sus resultados, limitaciones y próximo paso concreto. Actualizar 16 y este traspaso cuando cambie el estado; no copiar secretos, logs completos ni conclusiones no verificadas. Revisar `git status` antes de editar: al crear este documento `python_prueba/` figuraba sin seguimiento; no confundirlo con cambios propios ni eliminarlo.

<!-- CODEGRAPH_START -->
## CodeGraph

En repositorios indexados por CodeGraph (existe `.codegraph/` en la raíz), usarlo **antes de grep/find o leer código** para localizar o entender símbolos:

- MCP `codegraph_explore`, si está disponible: consultar símbolos/archivos para obtener código y rutas de llamadas; cargar por búsqueda de herramientas si está diferido.
- Shell: `codegraph explore "<símbolos o pregunta>"`.

Si no existe `.codegraph/`, omitir CodeGraph. No crear el índice por iniciativa propia; indexar es decisión del autor. No había `.codegraph/` en este corte.
<!-- CODEGRAPH_END -->
